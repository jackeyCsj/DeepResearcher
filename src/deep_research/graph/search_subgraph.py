"""Inner Search Agent subgraph A^1.

Implements Section 2.2.2: Recursive two-level execution.
Each Search Agent is a complete Foundry Agent with its own Router-Planner-Execution cycle,
limited to direct tool calls (no further nesting). Max 10 retrieval rounds.

The inner Search Agent:
- Formulates and reformulates queries (progressive specificity)
- Invokes retrieval tools directly
- Consolidates returned evidence
- Returns evidence bundles and summaries to the outer Research Agent
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from deep_research.models.evidence import EvidenceBase, EvidenceBundle, EvidenceRecord
from deep_research.models.rubric import Rubric
from deep_research.tools.registry import ToolRegistry
from deep_research.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)


class SearchAgentState(BaseModel):
    """Local state for an inner Search Agent A^1."""

    query: str
    sub_queries: List[str] = Field(default_factory=list)
    current_round: int = 0
    max_rounds: int = 10
    queries_per_round: int = 3
    accumulated_evidence: EvidenceBase = Field(default_factory=EvidenceBase)
    rubric: Optional[Rubric] = None
    stop_flag: bool = False


class SimpleSearchAgent:
    """A simplified inner Search Agent for open-ended retrieval sub-tasks.

    Implements the multi-turn retrieval loop with:
    - Progressive specificity (broad → specific → OEM/supplier → standards)
    - Multi-formulation query expansion
    - Tool diversification (search + crawler)
    """

    def __init__(self, tools: ToolRegistry, llm_client: LLMClient) -> None:
        self.tools = tools
        self.llm = llm_client
        self.search_tool = tools.get("web_search")

    async def run(self, state: SearchAgentState) -> EvidenceBundle:
        """Execute the full search agent loop.

        Args:
            state: The SearchAgentState with query and configuration.

        Returns:
            EvidenceBundle containing all collected evidence.
        """
        logger.info(f"Search Agent starting: '{state.query[:80]}...'")

        # Round 1: Broad initial queries
        state.sub_queries = [state.query]
        await self._search_round(state)

        # Rounds 2+: Progressive refinement
        while state.current_round < state.max_rounds and not state.stop_flag:
            state.current_round += 1
            new_queries = await self._formulate_next_queries(state)

            if not new_queries:
                break

            state.sub_queries = new_queries
            await self._search_round(state)

            # Check stopping
            if await self._check_sufficient(state):
                state.stop_flag = True

        # Final consolidation
        summary = await self._consolidate(state)

        return EvidenceBundle(
            subtask_id=state.query[:50],
            records=state.accumulated_evidence.all_records,
            summary=summary,
        )

    async def _search_round(self, state: SearchAgentState) -> None:
        """Execute one round of parallel searches."""
        all_records: List[EvidenceRecord] = []

        for query in state.sub_queries[: state.queries_per_round]:
            try:
                result = await self.search_tool.arun(query=query, max_results=3)
                for i, url in enumerate(result.source_urls[:3]):
                    all_records.append(
                        EvidenceRecord(
                            id=f"sa-r{state.current_round}-q{i}",
                            source_url=url,
                            snippet=(result.content[:300] if i == 0 else ""),
                            subtask_id=state.query[:50],
                        )
                    )
            except Exception as e:
                logger.warning(f"Search round {state.current_round} query failed: {e}")

        bundle = EvidenceBundle(
            subtask_id=f"round-{state.current_round}",
            records=all_records,
            summary=f"Round {state.current_round}: {len(all_records)} results",
        )
        state.accumulated_evidence.incorporate(bundle)

    async def _formulate_next_queries(self, state: SearchAgentState) -> List[str]:
        """Formulate more specific queries based on current findings."""
        evidence_summary = "\n".join(
            f"- {r.snippet[:200]}" for r in state.accumulated_evidence.all_records[:10]
        )
        prompt = f"""Research query: {state.query}
Current round: {state.current_round + 1}/{state.max_rounds}
Evidence gathered so far:
{evidence_summary or "No evidence yet."}

Formulate up to {state.queries_per_round} more specific search queries to fill remaining gaps.
If sufficient evidence has been gathered, return an empty list.

Strategies:
- Progressively narrow from broad concepts to specific details
- Target specific OEMs, suppliers, standards, or case studies
- Cross-reference contradictory or missing information
"""
        response = await self.llm.generate(prompt)
        try:
            if isinstance(response, dict) and "queries" in response:
                return response["queries"]
            if isinstance(response, list):
                return response
        except Exception:
            pass
        return []

    async def _check_sufficient(self, state: SearchAgentState) -> bool:
        """Check whether current evidence is sufficient to stop."""
        if state.current_round >= state.max_rounds - 1:
            return True
        if len(state.accumulated_evidence.all_records) > 30:
            return True
        return False

    async def _consolidate(self, state: SearchAgentState) -> str:
        """Produce a consolidated summary of findings."""
        n_records = len(state.accumulated_evidence.all_records)
        urls = list(
            set(
                r.source_url
                for r in state.accumulated_evidence.all_records
                if r.source_url
            )
        )
        return (
            f"Search Agent completed for query: '{state.query[:80]}...'\n"
            f"Rounds: {state.current_round}, Results: {n_records}, Sources: {len(urls)}"
        )

"""Execution Module: schedules and executes actions issued by the Planner.

Routes to one of four targets:
1. Direct tool call (Tool Ecosystem)
2. Search Agent (inner Foundry Agent A^1)
3. Writer (outline or report generation)
4. Internal LLM reasoning (dedup, merge, cross-validate)

Supports parallel fan-out for independent frontier nodes.
"""

from __future__ import annotations
import asyncio
import logging
from typing import List

from deep_research.models.actions import (
    BaseAction,
    ActionType,
    ToolCallAction,
    SearchAgentAction,
    LLMReasoningAction,
    ActionRecord,
)
from deep_research.models.evidence import EvidenceBundle, EvidenceRecord
from deep_research.tools.registry import ToolRegistry
from deep_research.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)


class ExecutionModule:
    """Schedules and executes actions. Sets no research strategy of its own."""

    def __init__(self, tools: ToolRegistry, llm_client: LLMClient) -> None:
        self.tools = tools
        self.llm = llm_client

    async def execute_parallel(
        self,
        actions: List[BaseAction],
    ) -> List[EvidenceBundle]:
        """Execute all actions in parallel (fan-out over independent frontier nodes).

        Args:
            actions: List of actions from the Planner.

        Returns:
            List of EvidenceBundle, one per action.
        """
        if not actions:
            return []

        tasks = [self._execute_single(action) for action in actions]
        bundles = await asyncio.gather(*tasks, return_exceptions=True)

        results: List[EvidenceBundle] = []
        for action, result in zip(actions, bundles):
            if isinstance(result, Exception):
                logger.error(f"Action {action.id} failed: {result}")
                results.append(
                    EvidenceBundle(
                        subtask_id=action.subtask_id,
                        records=[],
                        summary=f"Execution failed: {result}",
                        completed=False,
                    )
                )
            else:
                results.append(result)

        return results

    async def _execute_single(self, action: BaseAction) -> EvidenceBundle:
        """Route a single action to the appropriate execution target."""
        if action.type == ActionType.TOOL_CALL:
            return await self._execute_tool(action)
        elif action.type == ActionType.SEARCH_AGENT:
            return await self._dispatch_search_agent(action)
        elif action.type == ActionType.LLM_REASONING:
            return await self._execute_llm_reasoning(action)
        else:
            raise ValueError(f"Unknown action type: {action.type}")

    async def _execute_tool(self, action: ToolCallAction) -> EvidenceBundle:
        """Execute a direct tool call."""
        try:
            tool = self.tools.get(action.tool_name)
            result = await tool.arun(
                query=action.tool_input,
                **action.tool_params,
            )
            records = [
                EvidenceRecord(
                    id=f"{action.subtask_id}-{i}",
                    source_url=url,
                    snippet=result.content[:300] if i == 0 else "",
                    subtask_id=action.subtask_id,
                )
                for i, url in enumerate(result.source_urls[:10])
            ]
            return EvidenceBundle(
                subtask_id=action.subtask_id,
                records=records,
                summary=result.summary,
            )
        except Exception as e:
            logger.exception(f"Tool execution failed: {e}")
            return EvidenceBundle(
                subtask_id=action.subtask_id,
                summary=f"Tool error: {e}",
                completed=False,
            )

    async def _dispatch_search_agent(self, action: SearchAgentAction) -> EvidenceBundle:
        """Dispatch an inner Search Agent for open-ended retrieval.

        In a full implementation, this would create and run a SearchAgent subgraph.
        For now, we simulate by doing a simple search.
        """
        logger.info(f"Dispatching Search Agent for: {action.sub_query}")
        try:
            tool = self.tools.get("web_search")
            result = await tool.arun(query=action.sub_query, max_results=5)
            records = [
                EvidenceRecord(
                    id=f"{action.subtask_id}-sa-{i}",
                    source_url=url,
                    snippet="",
                    subtask_id=action.subtask_id,
                )
                for i, url in enumerate(result.source_urls[:10])
            ]
            return EvidenceBundle(
                subtask_id=action.subtask_id,
                records=records,
                summary=f"Search Agent results for: {action.sub_query}\n{result.summary}",
            )
        except Exception as e:
            logger.exception(f"Search Agent failed: {e}")
            return EvidenceBundle(
                subtask_id=action.subtask_id,
                summary=f"Search Agent error: {e}",
                completed=False,
            )

    async def _execute_llm_reasoning(self, action: LLMReasoningAction) -> EvidenceBundle:
        """Execute an internal LLM reasoning action."""
        response = await self.llm.generate(action.instruction)
        return EvidenceBundle(
            subtask_id=action.subtask_id,
            summary=response[:1000] if isinstance(response, str) else str(response),
        )

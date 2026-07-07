"""内层 Search Agent 子图 A^1。

对应论文 2.2.2 的“递归两层执行”思想。
每个 Search Agent 都是一个局部研究循环：它接收外层派发的子任务，自己改写查询、
调用检索工具、汇总证据，再把 EvidenceBundle 返回给外层 Research Agent。

当前实现是简化版：不再继续嵌套新的 Search Agent，只做多轮直接检索。
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
    """内层 Search Agent 的局部状态。"""

    query: str
    sub_queries: List[str] = Field(default_factory=list)
    current_round: int = 0
    max_rounds: int = 10
    queries_per_round: int = 3
    accumulated_evidence: EvidenceBase = Field(default_factory=EvidenceBase)
    rubric: Optional[Rubric] = None
    stop_flag: bool = False


class SimpleSearchAgent:
    """用于开放式检索子任务的简化 Search Agent。

    实现一个多轮检索循环：
    - 先宽后窄：从泛化查询逐步收敛到具体实体、案例或标准。
    - 多查询扩展：每轮最多生成多个子查询并分别检索。
    - 证据汇总：把每轮结果折叠进局部 EvidenceBase。
    """

    def __init__(self, tools: ToolRegistry, llm_client: LLMClient) -> None:
        self.tools = tools
        self.llm = llm_client
        self.search_tool = tools.get("web_search")

    async def run(self, state: SearchAgentState) -> EvidenceBundle:
        """执行完整的内层检索循环。

        Args:
            state: 包含查询、轮次上限和局部证据库的 SearchAgentState。

        Returns:
            包含本子任务全部证据和摘要的 EvidenceBundle。
        """
        logger.info(f"Search Agent starting: '{state.query[:80]}...'")

        # 第 1 轮使用原始子任务 query，先获得宽泛背景。
        state.sub_queries = [state.query]
        await self._search_round(state)

        # 第 2 轮起由 LLM 根据已有证据生成更具体的查询。
        while state.current_round < state.max_rounds and not state.stop_flag:
            state.current_round += 1
            new_queries = await self._formulate_next_queries(state)

            if not new_queries:
                break

            state.sub_queries = new_queries
            await self._search_round(state)

            # 局部停止条件用于限制搜索成本，避免单个子任务无限扩张。
            if await self._check_sufficient(state):
                state.stop_flag = True

        # 将局部证据库压缩成一个摘要，返回给外层编排图。
        summary = await self._consolidate(state)

        return EvidenceBundle(
            subtask_id=state.query[:50],
            records=state.accumulated_evidence.all_records,
            summary=summary,
        )

    async def _search_round(self, state: SearchAgentState) -> None:
        """执行一轮检索，并把结果写入局部 EvidenceBase。"""
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
        """根据当前发现生成下一轮更具体的查询。"""
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
        """判断当前局部证据是否足够，足够则停止内层搜索。"""
        if state.current_round >= state.max_rounds - 1:
            return True
        if len(state.accumulated_evidence.all_records) > 30:
            return True
        return False

    async def _consolidate(self, state: SearchAgentState) -> str:
        """把多轮检索结果压缩成外层可消费的简短摘要。"""
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

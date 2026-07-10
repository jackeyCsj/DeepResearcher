"""Execution Module：调度并执行 Planner 发出的动作。

动作会被路由到以下目标之一：
1. 直接工具调用（Tool Ecosystem）
2. 内层 Search Agent（论文中的 A^1）
3. Writer（大纲或报告生成）
4. 内部 LLM 推理（去重、合并、交叉验证等）

该模块不决定研究策略，只负责把已批准的动作并行执行并转成 EvidenceBundle。
"""

from __future__ import annotations
import asyncio
import logging
from typing import List, Optional

from deep_research.config import config
from deep_research.models.actions import (
    BaseAction,
    ActionType,
    ToolCallAction,
    SearchAgentAction,
    LLMReasoningAction,
    ActionRecord,
)
from deep_research.models.evidence import EvidenceBundle, EvidenceRecord
from deep_research.tools.base import ToolResult
from deep_research.tools.registry import ToolRegistry
from deep_research.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)


class ExecutionModule:
    """动作执行器：只负责调度和执行，不内置研究策略。"""

    def __init__(
        self,
        tools: ToolRegistry,
        llm_client: LLMClient,
        max_parallel_tools: Optional[int] = None,
    ) -> None:
        self.tools = tools
        self.llm = llm_client
        self.max_parallel_tools = max(
            1,
            max_parallel_tools or config.max_parallel_tools,
        )
        self._semaphore = asyncio.Semaphore(self.max_parallel_tools)

    async def execute_parallel(
        self,
        actions: List[BaseAction],
    ) -> List[EvidenceBundle]:
        """并行执行一批动作，适配 DAG 中互不依赖的前沿节点。

        Args:
            actions: Planner 本轮选出的动作列表。

        Returns:
            每个动作对应一个 EvidenceBundle。
        """
        if not actions:
            return []

        # asyncio.gather 让同一批 frontier 节点并行执行
        tasks = [self._execute_with_limit(action) for action in actions]
        # bundles: List[EvidenceBundle | Exception] —— 每个 action 对应一个结果
        # return_exceptions=True 确保单个 action 失败不会中断整批并行任务
        bundles = await asyncio.gather(*tasks, return_exceptions=True)

        # 将并行的 gather 结果与原始 action 逐一配对，统一转换为 EvidenceBundle
        # 无论成功还是失败，上游拿到的都是干净的 List[EvidenceBundle]
        results: List[EvidenceBundle] = []
        for action, result in zip(actions, bundles):
            if isinstance(result, Exception):
                # 该 action 执行时抛出了异常 → 构造一个 marked-as-failed 的空证据包
                # 不中断整体流程，异常信息附在 summary 中供 reflection 节点检查
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
                # 正常返回的 EvidenceBundle，直接透传
                results.append(result)

        return results

    async def _execute_with_limit(self, action: BaseAction) -> EvidenceBundle:
        """限制同一 frontier 的工具并发，避免触发服务端限流。"""
        async with self._semaphore:
            return await self._execute_single(action)

    async def _execute_single(self, action: BaseAction) -> EvidenceBundle:
        """根据 ActionType 将单个动作路由到对应执行目标。"""
        if action.type == ActionType.TOOL_CALL:
            return await self._execute_tool(action)
        elif action.type == ActionType.SEARCH_AGENT:
            return await self._dispatch_search_agent(action)
        elif action.type == ActionType.LLM_REASONING:
            return await self._execute_llm_reasoning(action)
        else:
            raise ValueError(f"Unknown action type: {action.type}")

    async def _execute_tool(self, action: ToolCallAction) -> EvidenceBundle:
        """执行一次直接工具调用，并把工具返回包装成 EvidenceBundle。"""
        try:
            tool = self.tools.get(action.tool_name)
            result = await tool.arun(
                query=action.tool_input,
                **action.tool_params,
            )
            records = self._records_from_tool_result(
                action.subtask_id,
                result,
                id_prefix=action.subtask_id,
            )
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
        """派发一个内层 Search Agent 执行开放式检索。

        完整实现应创建并运行 search_subgraph 中的内层循环。
        当前版本先用一次 web_search 模拟，保留接口以便后续替换为真正子图。
        """
        logger.info(f"Dispatching Search Agent for: {action.sub_query}")
        try:
            tool = self.tools.get("web_search")
            result = await tool.arun(query=action.sub_query, max_results=5)
            records = self._records_from_tool_result(
                action.subtask_id,
                result,
                id_prefix=f"{action.subtask_id}-sa",
            )
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

    def _records_from_tool_result(
        self,
        subtask_id: str,
        result: ToolResult,
        id_prefix: str,
    ) -> List[EvidenceRecord]:
        """把每条搜索结果的标题和正文摘要写入原子证据。"""
        records: List[EvidenceRecord] = []
        structured = result.structured_data[:10]
        if structured:
            for index, item in enumerate(structured):
                content = str(item.get("content") or "")
                score = item.get("score")
                records.append(
                    EvidenceRecord(
                        id=f"{id_prefix}-{index}",
                        source_url=item.get("url") or None,
                        title=str(item.get("title") or "") or None,
                        snippet=content[:500],
                        content=content[:2000] or None,
                        subtask_id=subtask_id,
                        relevance_score=score if isinstance(score, (int, float)) else None,
                        metadata={
                            key: value
                            for key, value in item.items()
                            if key not in {"url", "title", "content"}
                        },
                    )
                )
            return records

        for index, url in enumerate(result.source_urls[:10]):
            records.append(
                EvidenceRecord(
                    id=f"{id_prefix}-{index}",
                    source_url=url,
                    snippet=result.content[:500] if index == 0 else "",
                    content=result.content[:2000] if index == 0 else None,
                    subtask_id=subtask_id,
                )
            )
        return records

    async def _execute_llm_reasoning(self, action: LLMReasoningAction) -> EvidenceBundle:
        """执行内部 LLM 推理动作，并将推理结果作为摘要型证据返回。"""
        response = await self.llm.generate(action.instruction)
        return EvidenceBundle(
            subtask_id=action.subtask_id,
            summary=response[:1000] if isinstance(response, str) else str(response),
        )

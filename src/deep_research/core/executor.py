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
from typing import Any, List, Optional

from deep_research.config import config
from deep_research.models.actions import (
    BaseAction,
    ActionType,
    ToolCallAction,
    SearchAgentAction,
    LLMReasoningAction,
    ActionRecord,
)
from deep_research.models.evidence import (
    EvidenceBundle,
    EvidenceClaim,
    EvidenceExtraction,
    EvidenceRecord,
    SearchHit,
)
from deep_research.tools.registry import ToolRegistry
from deep_research.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)

MAX_EVIDENCE_RECORDS_PER_ACTION = 5
MAX_CRAWLED_SOURCES_PER_ACTION = 3
MAX_CRAWL_CHARS = 8000
MAX_EXTRACTION_CHARS = 6000
CRAWL_TIMEOUT_SECONDS = 8.0

EVIDENCE_EXTRACTION_SYSTEM_PROMPT = """You extract structured, report-ready evidence from retrieved sources.
Only extract claims supported by the provided source text. Do not invent facts. Prefer concrete
facts, metrics, dates, methods, limitations, and trend statements over vague summaries."""


class ExecutionModule:
    """动作执行器：只负责调度和执行，不内置研究策略。"""

    def __init__(self, tools: ToolRegistry, llm_client: LLMClient) -> None:
        self.tools = tools
        self.llm = llm_client

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
        tasks = [self._execute_single(action) for action in actions]
        # bundles: List[EvidenceBundle | Exception] —— 每个 action 对应一个结果
        # return_exceptions=True 确保单个 action 失败不会中断整批并行任务
        bundles = await asyncio.gather(*tasks, return_exceptions=True)

        # 将并行的 gather 结果与原始 action 逐一配对，统一转换为 EvidenceBundle
        # 无论成功还是失败，上游拿到的都是干净的 List[EvidenceBundle]
        results: List[EvidenceBundle] = []
        for action, result in zip(actions, bundles):
            if isinstance(result, Exception):
                # 该 action 执行时抛出了异常 → 构造一个 marked-as-failed 的空证据包
                # 不中断整体流程，异常信息附在 summary 中供后续证据审查/重规划使用。
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
            records = await self._build_evidence_records(
                action=action,
                result=result,
                query=action.tool_input,
            )
            return EvidenceBundle(
                subtask_id=action.subtask_id,
                records=records,
                summary=self._summarize_records(action.tool_input, records, result.summary),
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
            records = await self._build_evidence_records(
                action=action,
                result=result,
                query=action.sub_query,
                record_id_suffix="sa",
            )
            return EvidenceBundle(
                subtask_id=action.subtask_id,
                records=records,
                summary=self._summarize_records(action.sub_query, records, result.summary),
            )
        except Exception as e:
            logger.exception(f"Search Agent failed: {e}")
            return EvidenceBundle(
                subtask_id=action.subtask_id,
                summary=f"Search Agent error: {e}",
                completed=False,
            )

    async def _execute_llm_reasoning(self, action: LLMReasoningAction) -> EvidenceBundle:
        """执行内部 LLM 推理动作，并将推理结果作为摘要型证据返回。"""
        response = await self.llm.generate(action.instruction)
        return EvidenceBundle(
            subtask_id=action.subtask_id,
            summary=response[:1000] if isinstance(response, str) else str(response),
        )

    async def _build_evidence_records(
        self,
        action: BaseAction,
        result: Any,
        query: str,
        record_id_suffix: str = "",
    ) -> List[EvidenceRecord]:
        """把搜索命中蒸馏为来源级 EvidenceRecord 和 claim 列表。"""
        hits = self._search_hits_from_result(result)
        if not hits:
            return []

        crawler = self._get_optional_tool("crawler")
        tasks = [
            self._build_record_from_hit(
                action=action,
                hit=hit,
                index=index,
                query=query,
                crawler=crawler,
                record_id_suffix=record_id_suffix,
            )
            for index, hit in enumerate(hits[:MAX_EVIDENCE_RECORDS_PER_ACTION])
        ]
        records_or_errors = await asyncio.gather(*tasks, return_exceptions=True)
        records: List[EvidenceRecord] = []
        for index, result_or_error in enumerate(records_or_errors):
            if isinstance(result_or_error, Exception):
                logger.warning(
                    "Evidence record build failed for action=%s hit=%s: %s",
                    action.id,
                    index,
                    result_or_error,
                )
                continue
            records.append(result_or_error)
        return records

    async def _build_record_from_hit(
        self,
        action: BaseAction,
        hit: SearchHit,
        index: int,
        query: str,
        crawler: Optional[Any],
        record_id_suffix: str = "",
    ) -> EvidenceRecord:
        """并发处理单条搜索命中：可选抓取正文，再抽取结构化证据。"""
        content = hit.snippet
        crawl_summary = ""
        if crawler is not None and hit.url and index < MAX_CRAWLED_SOURCES_PER_ACTION:
            try:
                crawled = await asyncio.wait_for(
                    crawler.arun(url=hit.url, max_chars=MAX_CRAWL_CHARS),
                    timeout=CRAWL_TIMEOUT_SECONDS,
                )
                if crawled.content and not crawled.content.startswith("Error:"):
                    content = crawled.content
                    crawl_summary = crawled.summary
            except asyncio.TimeoutError:
                logger.info("Crawler timed out for %s; falling back to search snippet.", hit.url)
            except Exception as exc:
                logger.debug("Crawler failed for %s: %s", hit.url, exc)

        record_id = (
            f"{action.subtask_id}-{record_id_suffix}-{index}"
            if record_id_suffix
            else f"{action.subtask_id}-{index}"
        )
        if self._should_use_llm_evidence_extraction():
            extraction = await self._extract_evidence_with_timeout(
                query=query,
                action_description=action.description,
                hit=hit,
                content=content,
            )
            extraction_mode = "llm"
        else:
            extraction = self._fallback_extraction(hit, content)
            extraction_mode = "fallback"
        claims = self._finalize_claims(
            extraction.claims,
            evidence_id=record_id,
            hit=hit,
        )
        summary = extraction.summary or hit.snippet[:500]
        return EvidenceRecord(
            id=record_id,
            source_url=hit.url,
            title=hit.title,
            snippet=(hit.snippet or summary)[:500],
            content=content[:MAX_CRAWL_CHARS] if content else None,
            summary=summary,
            key_claims=claims,
            search_hit=hit,
            verification_status=self._record_verification_status(claims),
            source_type="web",
            metadata={
                "query": query,
                "rank": hit.rank,
                "source": hit.source,
                "score": hit.score,
                "crawl_summary": crawl_summary,
                "claim_count": len(claims),
                "extraction_mode": extraction_mode,
            },
            subtask_id=action.subtask_id,
            relevance_score=hit.score,
        )

    def _search_hits_from_result(self, result: Any) -> List[SearchHit]:
        """从 ToolResult 中分离搜索命中，避免把搜索结果直接当 evidence。"""
        hits: List[SearchHit] = []
        seen_urls = set()
        for rank, item in enumerate(getattr(result, "structured_data", []) or []):
            url = str(item.get("url", "") or "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            hits.append(
                SearchHit(
                    url=url,
                    title=str(item.get("title", "") or ""),
                    snippet=str(item.get("content", item.get("snippet", "")) or ""),
                    rank=rank,
                    source=str(item.get("source", "web_search") or "web_search"),
                    score=self._coerce_float(item.get("score")),
                    metadata={k: v for k, v in item.items() if k not in {"url", "title", "content", "snippet", "score"}},
                )
            )

        for rank, url in enumerate(getattr(result, "source_urls", []) or []):
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            hits.append(SearchHit(url=url, rank=len(hits) + rank, source="web_search"))
        return hits

    async def _extract_evidence(
        self,
        query: str,
        action_description: str,
        hit: SearchHit,
        content: str,
    ) -> EvidenceExtraction:
        """从一个来源正文中抽取面向当前子任务的 report-ready claims。"""
        if not content.strip():
            return EvidenceExtraction(summary=hit.snippet[:500], claims=[])

        prompt = f"""Research query / subtask:
{query}

Action description:
{action_description}

Source:
Title: {hit.title}
URL: {hit.url}

Source text:
{content[:MAX_EXTRACTION_CHARS]}

Extract a concise source summary and 0-5 atomic claims relevant to the research task.
For every claim:
- Keep it faithful to the source text.
- Include a short supporting_quote copied from the source text.
- Capture conditions such as time, dataset, geography, metric, scenario, or method when present.
- Use verification_status="extracted_unverified"; later gates will verify or flag conflicts.
If the source text is irrelevant or too thin, return an empty claims list.
"""
        try:
            extraction = await self.llm.generate(
                prompt,
                response_model=EvidenceExtraction,
                system_prompt=EVIDENCE_EXTRACTION_SYSTEM_PROMPT,
                temperature=0,
                max_tokens=2048,
            )
            return extraction
        except Exception as exc:
            logger.info(
                "Evidence extraction failed for %s; using fallback snippet extraction: %s",
                hit.url,
                exc,
            )
            return self._fallback_extraction(hit, content)

    async def _extract_evidence_with_timeout(
        self,
        query: str,
        action_description: str,
        hit: SearchHit,
        content: str,
    ) -> EvidenceExtraction:
        """给单来源证据抽取加超时，避免慢模型拖死整轮搜索。"""
        try:
            return await asyncio.wait_for(
                self._extract_evidence(
                    query=query,
                    action_description=action_description,
                    hit=hit,
                    content=content,
                ),
                timeout=config.evidence_extraction_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.info(
                "Evidence extraction timed out for %s after %.0fs; using fallback snippet extraction.",
                hit.url,
                config.evidence_extraction_timeout_seconds,
            )
            return self._fallback_extraction(hit, content)

    def _should_use_llm_evidence_extraction(self) -> bool:
        mode = (config.evidence_extraction_mode or "auto").lower()
        if mode == "llm":
            return True
        if mode == "fallback":
            return False
        return not self.llm._is_dashscope_provider()

    def _fallback_extraction(self, hit: SearchHit, content: str) -> EvidenceExtraction:
        summary = self._clean_fallback_text(hit.snippet or content[:500])
        if not summary:
            return EvidenceExtraction()
        return EvidenceExtraction(
            summary=summary[:500],
            claims=[
                EvidenceClaim(
                    text=summary[:300],
                    claim_type="fact",
                    supporting_quote=summary[:300],
                    source_url=hit.url,
                    source_title=hit.title,
                    confidence=0.35,
                    verification_status="extracted_unverified",
                )
            ],
        )

    def _finalize_claims(
        self,
        claims: List[EvidenceClaim],
        evidence_id: str,
        hit: SearchHit,
    ) -> List[EvidenceClaim]:
        finalized: List[EvidenceClaim] = []
        for claim in claims[:5]:
            claim.evidence_id = evidence_id
            claim.source_url = claim.source_url or hit.url
            claim.source_title = claim.source_title or hit.title
            claim.verification_status = claim.verification_status or "extracted_unverified"
            finalized.append(claim)
        return finalized

    def _record_verification_status(self, claims: List[EvidenceClaim]) -> str:
        if not claims:
            return "no_claims_extracted"
        statuses = {c.verification_status for c in claims}
        if "verified" in statuses:
            return "partially_verified"
        if "conflicted" in statuses:
            return "has_conflicts"
        return "extracted_unverified"

    def _summarize_records(
        self,
        query: str,
        records: List[EvidenceRecord],
        fallback_summary: str,
    ) -> str:
        claim_lines: List[str] = []
        for record in records:
            for claim in record.key_claims[:2]:
                claim_lines.append(f"- {claim.text} ({record.source_url or 'N/A'})")
                if len(claim_lines) >= 8:
                    break
            if len(claim_lines) >= 8:
                break
        if claim_lines:
            return "Evidence distilled for query: " + query + "\n" + "\n".join(claim_lines)
        return fallback_summary

    def _clean_fallback_text(self, text: str) -> str:
        text = text or ""
        text = text.replace("\r", "\n")
        lines = []
        navigation_markers = (
            "latest commit",
            "repository files navigation",
            "license:",
            "history",
        )
        for raw_line in text.splitlines():
            line = " ".join(raw_line.strip().split())
            if not line:
                continue
            lowered = line.lower()
            if any(marker in lowered for marker in navigation_markers):
                continue
            if line.startswith(("#", "-", "*")):
                line = line.lstrip("#-* ").strip()
            if len(line) < 8:
                continue
            lines.append(line)
            if len(" ".join(lines)) >= 500:
                break
        cleaned = " ".join(lines) if lines else " ".join(text.split())
        return cleaned[:800].strip()

    def _get_optional_tool(self, name: str) -> Optional[Any]:
        try:
            return self.tools.get(name)
        except KeyError:
            return None

    def _coerce_float(self, value: Any) -> Optional[float]:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

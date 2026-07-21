"""Writer 模块：两阶段报告生成。

阶段 1：根据粗粒度探索证据生成报告大纲 O。
阶段 2：根据累积证据和持久 Rubric 合成最终长报告。

论文 2.1.2 中先生成统一的“pivot report”保证逻辑一致性，再由渲染器转成
Markdown、HTML、PPT 等格式。本项目当前实现聚焦 Markdown 文本报告。
"""

from __future__ import annotations
import logging
import re
from typing import Optional
from urllib.parse import urlsplit

from deep_research.models.topic import TopicSpec, Outline, TaskContext
from deep_research.models.evidence import EvidenceBase, EvidenceStatus
from deep_research.models.rubric import Rubric
from deep_research.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)


OUTLINE_SYSTEM_PROMPT = """You are a research outline generator. Create a detailed, structured
report outline based on initial research findings. Each chapter must include actionable rubric
guidance for evidence gathering."""


REPORT_SYSTEM_PROMPT = """You are a research report writer. Synthesize a comprehensive,
evidence-grounded report. Requirements:
1. Every factual claim must cite specific evidence using inline Markdown links.
2. Cross-validate sources - distinguish vendor claims from independent research.
3. Include conditional conclusions bounded by scenario applicability.
4. Use quantitative data and analytical frameworks where applicable.
5. Use Mermaid diagrams for structural visualization where helpful.
6. Never expose internal audit identifiers such as iteration IDs, bundle IDs, action IDs,
   subtask IDs, or node IDs. References like [Iter-1, node9] are forbidden."""


INTERNAL_AUDIT_CITATION = re.compile(
    r"\[(?=[^\]\n]*(?:iter(?:ation)?[-_ ]?\d+|node[-_ ]?[\w.-]+|"
    r"bundle[-_ ]?[\w:.-]+|action[-_ ]?[\w.-]+|subtask[-_ ]?[\w.-]+))"
    r"[^\]\n]+\]",
    flags=re.IGNORECASE,
)


class Writer:
    """带 Rubric 条件约束的两阶段报告生成器。"""

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm = llm_client

    async def generate_outline(
        self,
        topic: TopicSpec,
        evidence: EvidenceBase,
    ) -> Outline:
        """根据粗搜证据生成结构化报告大纲 O。

        Args:
            topic: Router 生成的结构化主题规格 x。
            evidence: 粗粒度探索阶段获得的初始证据。

        Returns:
            带章节和章节级 rubric_guidance 的 Outline。
        """
        evidence_summaries = "\n".join(
            f"Finding {index}: {bundle.summary[:300]}"
            for index, bundle in enumerate(evidence.bundles.values(), start=1)
        ) or "No preliminary evidence available."

        prompt = f"""Research topic: {topic.core_topic}
            Sub-questions: {topic.sub_questions}
            Scope: {topic.scope}

            Initial research findings:
            {evidence_summaries}

            Generate a multi-chapter research outline. Follow these principles:
            1. Start with background/context, end with conclusion/future work
            2. Each chapter should have a clear analytical purpose
            3. Include rubric_guidance for each chapter (actionable instruction for evidence gathering)
            4. Cover: historical background, current state, future trends, stakeholder perspectives,
            quantitative/qualitative evidence, comparisons, risks/limitations
        """
        response = await self.llm.generate(prompt, response_model=Outline, system_prompt=OUTLINE_SYSTEM_PROMPT)
        # 如果模型没有返回标题，则用核心主题兜底。
        if not response.title:
            response.title = topic.core_topic
        return response

    async def synthesize_report(
        self,
        context: TaskContext,
        evidence: EvidenceBase,
        persistent_rubric: Optional[Rubric] = None,
    ) -> str:
        """带指导信号的报告合成：y = W(x, O, e_t, ρ_p)。

        按论文 2.2.3 的设计，最终写作只消费持久 Rubric ρ_p，
        不直接使用瞬时 Rubric ρ^e_t。

        Args:
            context: 固定任务上下文 z = (x, O)。
            evidence: 累积证据库 e_t。
            persistent_rubric: 用于约束最终写作质量的持久 Rubric ρ_p。

        Returns:
            合成后的长篇研究报告字符串。
        """
        rubric_text = ""
        if persistent_rubric and persistent_rubric.criteria:
            rubric_text = "\n".join(
                f"[{c.name}] {c.description}: {c.guidance}"
                for c in persistent_rubric.criteria
            )

        evidence_sections = []
        unresolved_sections = []
        source_catalog: dict[str, tuple[str, str, str]] = {}
        for group_index, bundle in enumerate(evidence.bundles.values(), start=1):
            verified_records = [
                record
                for record in bundle.records
                if record.validation_status == EvidenceStatus.VERIFIED
            ]
            record_lines = []
            for record in verified_records[:5]:
                citation = self._register_source(source_catalog, record)
                if citation is None:
                    continue
                source_key, title, url = citation
                record_lines.append(
                    f"- source_key={source_key} | citation=[{title}]({url}) | "
                    f"evidence={(record.content or record.snippet)[:300]}"
                )
            records_text = "\n".join(record_lines)
            if records_text:
                evidence_sections.append(
                    f"### Evidence group {group_index}\n"
                    f"Context summary: {bundle.summary}\n"
                    f"Verified evidence:\n{records_text}"
                )

            unresolved_records = [
                record
                for record in bundle.records
                if record.validation_status
                in {
                    EvidenceStatus.UNVERIFIED,
                    EvidenceStatus.NEEDS_VERIFICATION,
                    EvidenceStatus.DISPUTED,
                }
            ]
            for record in unresolved_records[:5]:
                notes = "; ".join(record.validation_notes) or "No validation notes."
                source = self._markdown_source(record.title, record.source_url)
                unresolved_sections.append(
                    f"- [{record.validation_status.value}] "
                    f"{source} | {notes}"
                )

        chapter_outline = "\n".join(
            f"## {ch.title}\n{ch.description}\nRubric: {ch.rubric_guidance}"
            for ch in context.outline.chapters
        )

        evidence_text = "\n".join(evidence_sections) or "No verified evidence available."
        unresolved_text = (
            "\n".join(unresolved_sections)
            or "No unresolved evidence was retained."
        )
        prompt = f"""Topic: {context.topic.core_topic}

Report Outline:
{chapter_outline}

Quality Criteria:
{rubric_text}

Accumulated Evidence:
{evidence_text}

Unresolved Evidence and Limitations:
{unresolved_text}

Synthesize a comprehensive, well-structured research report. Follow the outline closely.
Use only the Verified evidence section to support analytical claims. Treat unresolved evidence
as limitations or open questions, never as established fact.

Citation rules:
1. Copy the supplied citation Markdown links directly after the claim they support, for example
   [S1: Source title](https://example.com/report).
2. Use only URLs supplied in Verified evidence. Never invent a URL.
3. Do not cite source_key as plain text such as [S1]; it must be a clickable Markdown link.
4. Never output internal identifiers including Iter, iteration, node, bundle, action, or subtask.
5. Do not use internal references such as [Iter-1, node9], even when they appear in context.
"""
        report = await self.llm.generate_long(
            prompt,
            system_prompt=REPORT_SYSTEM_PROMPT,
            max_tokens=16000,
        )
        report = INTERNAL_AUDIT_CITATION.sub("", report)
        report = re.sub(r"[ \t]+([，。,.；;])", r"\1", report)
        return self._append_verified_sources(report, source_catalog)

    def _register_source(
        self,
        source_catalog: dict[str, tuple[str, str, str]],
        record,
    ) -> Optional[tuple[str, str, str]]:
        """注册去重后的来源，并生成稳定的 Markdown 引用标签。"""
        url = record.canonical_source or record.source_url
        if not url:
            return None
        if url in source_catalog:
            return source_catalog[url]

        source_key = f"S{len(source_catalog) + 1}"
        fallback_title = urlsplit(url).netloc or "Source"
        title = self._clean_link_text(record.title or fallback_title)
        citation_title = f"{source_key}: {title}"
        entry = (source_key, citation_title, url)
        source_catalog[url] = entry
        return entry

    def _markdown_source(
        self,
        title: Optional[str],
        url: Optional[str],
    ) -> str:
        """把来源渲染为 Markdown 链接，缺少 URL 时返回说明文本。"""
        if not url:
            return "Source URL unavailable"
        fallback_title = urlsplit(url).netloc or "Source"
        return f"[{self._clean_link_text(title or fallback_title)}]({url})"

    def _clean_link_text(self, text: str) -> str:
        """清理会破坏 Markdown 链接标签的字符。"""
        return re.sub(r"[\[\]\r\n]+", " ", text).strip() or "Source"

    def _append_verified_sources(
        self,
        report: str,
        source_catalog: dict[str, tuple[str, str, str]],
    ) -> str:
        """在报告末尾追加确定性的已验证来源目录。"""
        if not source_catalog:
            return report
        source_lines = [
            f"- [{citation_title}]({url})"
            for _, citation_title, url in source_catalog.values()
        ]
        return report.rstrip() + "\n\n## 参考来源\n\n" + "\n".join(source_lines) + "\n"

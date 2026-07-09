"""Writer 模块：两阶段报告生成。

阶段 1：根据粗粒度探索证据生成报告大纲 O。
阶段 2：根据累积证据和持久 Rubric 合成最终长报告。

论文 2.1.2 中先生成统一的“pivot report”保证逻辑一致性，再由渲染器转成
Markdown、HTML、PPT 等格式。本项目当前实现聚焦 Markdown 文本报告。
"""

from __future__ import annotations
import asyncio
import logging
import re
from typing import Optional

from deep_research.models.topic import TopicSpec, Outline, Chapter, TaskContext
from deep_research.models.evidence import EvidenceBase, EvidenceClaim, EvidenceRecord
from deep_research.models.rubric import Rubric
from deep_research.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)

REPORT_GENERATION_TIMEOUT_SECONDS = 60.0


OUTLINE_SYSTEM_PROMPT = """You are a research outline generator. Create a detailed, structured
report outline based on initial research findings. Each chapter must include actionable rubric
guidance for evidence gathering."""


REPORT_SYSTEM_PROMPT = """You are a research report writer. Synthesize a comprehensive,
evidence-grounded report. Requirements:
1. Every claim must cite specific evidence sources (URLs).
2. Cross-validate sources - distinguish vendor claims from independent research.
3. Include conditional conclusions bounded by scenario applicability.
4. Use quantitative data and analytical frameworks where applicable.
5. Use Mermaid diagrams for structural visualization where helpful."""


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
            f"[{bid}] {b.summary[:300]}"
            for bid, b in evidence.bundles.items()
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
        try:
            response = await self.llm.generate(
                prompt,
                response_model=Outline,
                system_prompt=OUTLINE_SYSTEM_PROMPT,
                max_tokens=2048,
                temperature=0,
            )
        except Exception as exc:
            logger.info("Outline generation unavailable; using fallback outline: %s", exc)
            return self._fallback_outline(topic)
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

        evidence_text = self._build_verified_evidence_pack(evidence)

        chapter_outline = "\n".join(
            f"## {ch.title}\n{ch.description}\nRubric: {ch.rubric_guidance}"
            for ch in context.outline.chapters
        )

        prompt = f"""Topic: {context.topic.core_topic}

            Report Outline:
            {chapter_outline}

            Quality Criteria:
            {rubric_text}

            Accumulated Evidence:
            {evidence_text}

            Synthesize a comprehensive, well-structured research report. Follow the outline closely.
            Use the structured claims as the primary evidence pack. Cite source URLs for claims.
            Do not overstate extracted_unverified, single_source_primary, or single_source_risky claims as broad consensus.
            Do not use unsupported or conflicted claims as final facts; mention them only as unresolved evidence-quality issues.
            Preserve caveats, conditions, datasets, dates, and source-specific limitations.
        """
        try:
            report = await asyncio.wait_for(
                self.llm.generate_long(
                    prompt,
                    system_prompt=REPORT_SYSTEM_PROMPT,
                    max_tokens=6000,
                ),
                timeout=REPORT_GENERATION_TIMEOUT_SECONDS,
            )
            return report
        except asyncio.TimeoutError:
            logger.info(
                "Final report generation timed out after %.0fs; using fallback report.",
                REPORT_GENERATION_TIMEOUT_SECONDS,
            )
            return self._fallback_report(context, evidence)
        except Exception as exc:
            logger.warning("Final report generation failed; using fallback report: %s", exc)
            return self._fallback_report(context, evidence)

    def _build_verified_evidence_pack(self, evidence: EvidenceBase) -> str:
        """把 EvidenceBase 拼成给 Writer 使用的紧凑证据包。

        这里刻意不暴露 Bundle summary / Claims 等内部调试格式，避免模型在最终
        报告里照抄搜索结果目录或 evidence dump。
        """
        sections = []
        for subtask_id, bundle in evidence.bundles.items():
            record_blocks = [
                self._format_record_for_writer(record)
                for record in bundle.records[:5]
            ]
            records_text = "\n".join(block for block in record_blocks if block)
            if records_text:
                sections.append(f"Subtask {subtask_id}:\n{records_text}")
        return "\n\n".join(sections) or "No accumulated evidence available."

    def _format_record_for_writer(self, record: EvidenceRecord) -> str:
        source = record.source_url or "N/A"
        title = record.title or "Untitled source"
        summary = self._clean_evidence_text(record.summary or record.snippet, max_chars=360)
        lines = [f"- {title} ({source})"]
        if summary:
            lines.append(f"  Summary: {summary}")

        claims = self._usable_claims(record)
        if claims:
            claim_lines = [
                f"[{claim.verification_status}] {self._clean_evidence_text(claim.text, max_chars=260)}"
                for claim in claims[:3]
            ]
            lines.append("  Key points: " + " | ".join(claim_lines))
        elif record.verification_status:
            lines.append(f"  Evidence status: {record.verification_status}")
        return "\n".join(lines)

    def _fallback_outline(self, topic: TopicSpec) -> Outline:
        core_topic = topic.core_topic or topic.query or "研究主题"
        return Outline(
            title=core_topic,
            chapters=[
                Chapter(
                    id="1",
                    title="概念定义与背景",
                    description=f"解释{core_topic}的基本含义、问题背景和相关概念。",
                    rubric_guidance="收集能直接支持定义和背景说明的权威来源。",
                ),
                Chapter(
                    id="2",
                    title="核心组成与工作方式",
                    description=f"梳理{core_topic}的关键组成、流程和典型实现方式。",
                    rubric_guidance="优先查找技术文档、论文、工程文章或一手资料。",
                ),
                Chapter(
                    id="3",
                    title="应用场景、价值与局限",
                    description=f"分析{core_topic}的实际应用、收益、风险和适用边界。",
                    rubric_guidance="区分事实证据、厂商观点和第三方评价，并保留来源限制。",
                ),
            ],
        )

    def _fallback_report(self, context: TaskContext, evidence: EvidenceBase) -> str:
        title = context.outline.title or context.topic.core_topic or context.topic.query
        findings = self._fallback_findings(evidence, limit=10)
        sources = self._fallback_sources(evidence, limit=12)
        chapters = context.outline.chapters or self._fallback_outline(context.topic).chapters
        chapter_lines = "\n".join(
            f"- **{chapter.title}**：{chapter.description}"
            for chapter in chapters[:5]
        )
        finding_lines = "\n".join(f"- {finding}" for finding in findings) or "- 暂无可用证据摘要。"
        source_lines = "\n".join(f"- {source}" for source in sources) or "- 暂无来源。"
        return (
            f"# {title}\n\n"
            "> 最终 LLM 写作调用失败或超时，以下为规则兜底摘要。该版本只整理已检索证据，"
            "不展开内部调试字段；建议在模型响应稳定后重新运行最终写作。\n\n"
            "## 核心结论\n\n"
            f"{finding_lines}\n\n"
            "## 建议报告结构\n\n"
            f"{chapter_lines}\n\n"
            "## 主要来源\n\n"
            f"{source_lines}\n\n"
            "## 后续建议\n\n"
            "- 重新运行最终写作步骤，或适当提高 `LLM_REQUEST_TIMEOUT_SECONDS` / 最终报告超时时间。\n"
            "- 对 `single_source_risky`、`unsupported`、`conflicted` 状态的证据做人工复核或补充检索。\n"
        )

    def _fallback_findings(self, evidence: EvidenceBase, limit: int = 10) -> list[str]:
        findings: list[str] = []
        seen: set[str] = set()
        for record in evidence.all_records:
            claim_texts = [
                self._clean_evidence_text(claim.text, max_chars=260)
                for claim in self._usable_claims(record)
            ]
            candidates = claim_texts or [
                self._clean_evidence_text(record.summary or record.snippet, max_chars=260)
            ]
            for text in candidates:
                if not text or self._looks_like_navigation(text):
                    continue
                key = text.lower()
                if key in seen:
                    continue
                seen.add(key)
                source = record.source_url or "N/A"
                status = record.verification_status or "unverified"
                findings.append(f"{text}（证据状态：{status}；来源：{source}）")
                if len(findings) >= limit:
                    return findings
        return findings

    def _fallback_sources(self, evidence: EvidenceBase, limit: int = 12) -> list[str]:
        sources: list[str] = []
        seen_urls: set[str] = set()
        for record in evidence.all_records:
            url = record.source_url or ""
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            title = self._clean_evidence_text(record.title or "Untitled source", max_chars=100)
            status = record.verification_status or "unverified"
            sources.append(f"{title} — {url}（{status}）")
            if len(sources) >= limit:
                break
        return sources

    def _usable_claims(self, record: EvidenceRecord) -> list[EvidenceClaim]:
        blocked = {"unsupported", "conflicted"}
        return [
            claim
            for claim in record.key_claims
            if claim.text and claim.verification_status not in blocked
        ]

    def _clean_evidence_text(self, text: str, max_chars: int = 300) -> str:
        text = re.sub(r"https?://\S+", "", text or "")
        text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
        text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
        text = re.sub(r"[`*_>\[\]]+", "", text)
        text = re.sub(r"\s+", " ", text).strip(" -:：|")
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1].rstrip() + "…"

    def _looks_like_navigation(self, text: str) -> bool:
        lowered = text.lower()
        nav_terms = (
            "latest commit",
            "repository files navigation",
            "license",
            "history",
            "目录",
            "导航",
            "登录",
            "注册",
        )
        if any(term in lowered for term in nav_terms):
            return True
        words = re.findall(r"[\w\u4e00-\u9fff]+", text)
        if len(words) >= 4:
            return False
        return len(text.strip()) < 24

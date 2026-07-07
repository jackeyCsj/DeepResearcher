"""Writer 模块：两阶段报告生成。

阶段 1：根据粗粒度探索证据生成报告大纲 O。
阶段 2：根据累积证据和持久 Rubric 合成最终长报告。

论文 2.1.2 中先生成统一的“pivot report”保证逻辑一致性，再由渲染器转成
Markdown、HTML、PPT 等格式。本项目当前实现聚焦 Markdown 文本报告。
"""

from __future__ import annotations
import logging
from typing import Optional

from deep_research.models.topic import TopicSpec, Outline, Chapter, TaskContext
from deep_research.models.evidence import EvidenceBase
from deep_research.models.rubric import Rubric
from deep_research.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)


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
        for subtask_id, bundle in evidence.bundles.items():
            records_text = "\n".join(
                f"- Source: {r.source_url or 'N/A'} | {r.snippet[:200]}"
                for r in bundle.records[:5]
            )
            evidence_sections.append(f"### {subtask_id}: {bundle.summary}\n{records_text}")

        chapter_outline = "\n".join(
            f"## {ch.title}\n{ch.description}\nRubric: {ch.rubric_guidance}"
            for ch in context.outline.chapters
        )

        evidence_text = "\n".join(evidence_sections)
        prompt = f"""Topic: {context.topic.core_topic}

Report Outline:
{chapter_outline}

Quality Criteria:
{rubric_text}

Accumulated Evidence:
{evidence_text}

Synthesize a comprehensive, well-structured research report. Follow the outline closely.
Ensure every analytical claim is grounded in specific, cited evidence.
"""
        report = await self.llm.generate_long(
            prompt,
            system_prompt=REPORT_SYSTEM_PROMPT,
            max_tokens=16000,
        )
        return report

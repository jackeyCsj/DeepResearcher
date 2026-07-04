"""Writer module: Two-stage report generation.

Stage 1: Generate report outline O from coarse exploration evidence.
Stage 2: Synthesize final long-form report from accumulated evidence + persistent rubric.

From the paper (Section 2.1.2):
- First generates a unified "pivot report" ensuring logical coherence.
- Then specialized renderers translate to multiple formats (Markdown, HTML, PPT).
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
    """Two-stage report generation with rubric-conditioned synthesis."""

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm = llm_client

    async def generate_outline(
        self,
        topic: TopicSpec,
        evidence: EvidenceBase,
    ) -> Outline:
        """Generate structured report outline O from coarse exploration evidence.

        Args:
            topic: The structured topic specification x.
            evidence: Initial coarse exploration evidence e_tc.

        Returns:
            Outline with chapters, each containing rubric_guidance.
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
        # Set title if empty
        if not response.title:
            response.title = topic.core_topic
        return response

    async def synthesize_report(
        self,
        context: TaskContext,
        evidence: EvidenceBase,
        persistent_rubric: Optional[Rubric] = None,
    ) -> str:
        """Guidance-conditioned synthesis: y = W(x, O, e_t, ρ_p).

        Consumes ONLY the persistent rubric ρ_p (not ephemeral),
        per the paper's design (Section 2.2.3).

        Args:
            context: The task context z = (x, O).
            evidence: The accumulated evidence base e_t.
            persistent_rubric: The persistent rubric ρ_p for quality conditioning.

        Returns:
            The synthesized long-form report as a string.
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

"""Dynamic rubric generation for test-time optimization.

Implements Section 2.2.3 from the paper.

Two types of rubrics:
- Persistent Rubrics ρ_p: Stable, topic-level quality dimensions for the entire session.
  Generated once from (x, O). Fed to Writer for final synthesis.
- Ephemeral Rubrics ρ^e_t: Transient criteria based on latest evidence gaps.
  Refreshed each cycle: ρ^e_{t+1} = G_e(O, e_{t+1}).

Both contain criteria with actionable guidance instructions (not numeric scores).
"""

from __future__ import annotations
import logging
from typing import List

from deep_research.models.topic import TaskContext, Outline
from deep_research.models.evidence import EvidenceBase
from deep_research.models.rubric import Rubric, Criterion
from deep_research.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)

RUBRIC_SYSTEM_PROMPT = """You are a research quality criteria generator. Generate structured,
actionable rubrics for evaluating and guiding deep research. All guidance must be phrased as
executable reasoning instructions, NOT numeric scores."""


class RubricGenerator:
    """Generates and updates rubrics for test-time optimization.

    Implements INITGUIDANCE and UPDATEGUIDANCE from the paper.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm = llm_client

    async def init_persistent(self, context: TaskContext) -> Rubric:
        """Generate persistent rubric ρ_p from (x, O).

        From the paper (Equation 6):
        ρ_p = G_p(x, O)

        Extracts rubric guidance from each outline chapter and adds cross-cutting criteria.

        Args:
            context: The task context z = (x, O).

        Returns:
            Persistent Rubric with chapter-level and cross-cutting criteria.
        """
        criteria: List[Criterion] = []

        # Extract chapter-level criteria from outline
        for chapter in context.outline.chapters:
            if chapter.rubric_guidance:
                criteria.append(
                    Criterion(
                        name=f"chapter_{chapter.id}_quality",
                        description=chapter.description,
                        guidance=chapter.rubric_guidance,
                    )
                )

        # Add cross-cutting quality criteria
        cross_cutting = await self._generate_cross_cutting(context)
        criteria.extend(cross_cutting)

        return Rubric(criteria=criteria)

    async def update_ephemeral(
        self,
        outline: Outline,
        evidence: EvidenceBase,
    ) -> Rubric:
        """Generate ephemeral rubric ρ^e_{t+1} = G_e(O, e_{t+1}).

        Conditioned on accumulated evidence to target the most decision-relevant gaps.

        Args:
            outline: The report outline O.
            evidence: The accumulated evidence e_{t+1}.

        Returns:
            Ephemeral Rubric with 2-5 gap-focused criteria.
        """
        chapter_summaries = "\n".join(
            f"Chapter {ch.id}: {ch.title} — {ch.description[:200]}"
            for ch in outline.chapters
        )
        evidence_summaries = "\n".join(
            f"[{bid}] {b.summary[:300]}"
            for bid, b in evidence.bundles.items()
        ) or "No evidence collected yet."

        prompt = f"""Based on the report outline and accumulated evidence, identify critical evidence gaps.

Outline chapters:
{chapter_summaries}

Accumulated evidence:
{evidence_summaries}

Generate 2-5 ephemeral quality criteria that capture the most important evidence gaps.
Each criterion must have actionable guidance (not a numeric score).

Types of gaps to identify:
1. Coverage blanks — chapters with no corresponding evidence
2. Depth imbalance — chapters with only shallow/surface information
3. Conflicts — contradictory information across sources needing verification

If no outstanding gaps exist, set each criterion's guidance to "sufficient".
"""
        response = await self.llm.generate(prompt, response_model=Rubric, system_prompt=RUBRIC_SYSTEM_PROMPT)
        return response

    async def _generate_cross_cutting(self, context: TaskContext) -> List[Criterion]:
        """Generate cross-chapter quality criteria (multi-source, credibility, quantitative)."""
        prompt = f"""For the research topic "{context.topic.core_topic}", generate 2-3 cross-cutting quality criteria:

Focus on:
1. Multi-source cross-validation — evidence should come from multiple independent sources
2. Source credibility — assess authority, timeliness, and potential bias of sources
3. Quantitative evidence — claims should be backed by concrete data where possible

Each criterion needs: name, description, and actionable guidance (not a score).
"""
        response = await self.llm.generate(prompt, response_model=List[Criterion], system_prompt=RUBRIC_SYSTEM_PROMPT)
        return response if isinstance(response, list) else response

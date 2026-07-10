"""测试时优化使用的动态 Rubric 生成器。

对应论文 2.2.3。

两类 Rubric：
- 持久 Rubric ρ_p：稳定的话题级质量标准，由 (x, O) 生成一次，并传给最终 Writer。
- 瞬时 Rubric ρ^e_t：基于最新证据缺口生成的临时标准，每轮刷新。

二者都保存可执行的推理指导，而不是数字评分。
"""

from __future__ import annotations
import logging
from typing import List

from pydantic import BaseModel, Field

from deep_research.models.topic import TaskContext, Outline
from deep_research.models.evidence import EvidenceBase, EvidenceStatus
from deep_research.models.rubric import (
    Criterion,
    CriterionKind,
    CriterionStatus,
    Rubric,
)
from deep_research.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)

RUBRIC_SYSTEM_PROMPT = """You are a research quality criteria generator. Generate structured,
actionable rubrics for evaluating and guiding deep research. All guidance must be phrased as
executable reasoning instructions, NOT numeric scores."""


class CriterionList(BaseModel):
    """用对象包装列表，兼容只接受 json_object 的模型服务。"""

    criteria: List[Criterion] = Field(default_factory=list)


class RubricGenerator:
    """生成并更新测试时优化所需的 Rubric。

    对应论文中的 INITGUIDANCE 和 UPDATEGUIDANCE。
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm = llm_client

    async def init_persistent(self, context: TaskContext) -> Rubric:
        """根据 (x, O) 生成持久 Rubric ρ_p。

        论文公式：ρ_p = G_p(x, O)。

        该方法先读取章节级 rubric_guidance，再补充跨章节质量标准。

        Args:
            context: 固定任务上下文 z = (x, O)。

        Returns:
            同时包含章节级和跨章节标准的持久 Rubric。
        """
        criteria: List[Criterion] = []

        # 从大纲章节中抽取章节级质量标准。
        for chapter in context.outline.chapters:
            if chapter.rubric_guidance:
                criteria.append(
                    Criterion(
                        name=f"chapter_{chapter.id}_quality",
                        description=chapter.description,
                        guidance=chapter.rubric_guidance,
                    )
                )

        # 补充跨章节标准，例如多源交叉验证、来源可信度和定量证据。
        cross_cutting = await self._generate_cross_cutting(context)
        criteria.extend(cross_cutting)

        return Rubric(criteria=criteria)

    async def update_ephemeral(
        self,
        outline: Outline,
        evidence: EvidenceBase,
    ) -> Rubric:
        """生成瞬时 Rubric：ρ^e_{t+1} = G_e(O, e_{t+1})。

        它基于当前证据状态识别最值得补齐的信息缺口。

        这个函数被"每轮迭代"调用，evidence.bundles 包含从第 1 轮到现在
        累积的全部证据。随着轮次增长 bundles 数量会膨胀（如 5 轮 × 3 个 action
        = 15 个 bundle），如果不截断，prompt 长度会失控。

        Args:
            outline: 报告大纲 O。
            evidence: 当前累计证据 e_{t+1}，是所有历史轮次的并集。
                evidence.bundles 是 Dict[str, EvidenceBundle]，key 为 subtask_id。

        Returns:
            包含 2-5 条缺口导向标准的瞬时 Rubric。
        """
        # 大纲每个章节描述只取前 200 字符：章节描述由 LLM 生成，可能很冗长，
        # 但缺口分析只需知道每章主题，200 字足够判断"这章讲的什么"
        chapter_summaries = "\n".join(
            f"Chapter {ch.id}: {ch.title} — {ch.description[:200]}"
            for ch in outline.chapters
        )

        # 证据摘要每条只取前 300 字符：bundles 是全部轮次的累积结果，
        # 随迭代增长（如 10 轮 × 3 action = 30 条 bundle）。
        # 300 字摘要已经足够让 LLM 判断"这个话题有没有覆盖"，无需全文。
        # 用 [:300] 而非完整 summary 是为了把 prompt 控制在合理长度内。
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
            Each criterion must have actionable guidance (not a numeric score), a structured kind,
            and a structured status.

            Types of gaps to identify:
            1. Coverage blanks — chapters with no corresponding evidence
            2. Depth imbalance — chapters with only shallow/surface information
            3. Conflicts — contradictory information across sources needing verification

            Allowed kind values: coverage, depth, conflict, source_credibility, quantitative, other.
            Allowed status values: outstanding, sufficient, unknown.
            Use status="outstanding" for an unresolved gap and status="sufficient" when covered.
            If no outstanding gaps exist, set every criterion's status to "sufficient" and guidance
            to "sufficient".
        """
        try:
            response = await self.llm.generate(
                prompt,
                response_model=Rubric,
                system_prompt=RUBRIC_SYSTEM_PROMPT,
            )
            return response
        except Exception as exc:
            logger.warning(
                "Ephemeral rubric generation failed; using deterministic fallback: %s",
                exc,
            )
            return self._fallback_ephemeral(evidence)

    async def _generate_cross_cutting(self, context: TaskContext) -> List[Criterion]:
        """生成跨章节质量标准，如多源验证、来源可信度和定量证据要求。"""
        prompt = f"""For the research topic "{context.topic.core_topic}", generate 2-3 cross-cutting quality criteria:

            Focus on:
            1. Multi-source cross-validation — evidence should come from multiple independent sources
            2. Source credibility — assess authority, timeliness, and potential bias of sources
            3. Quantitative evidence — claims should be backed by concrete data where possible

            Each criterion needs: name, description, actionable guidance (not a score),
            kind, and status="unknown".
        """
        try:
            response = await self.llm.generate(
                prompt,
                response_model=CriterionList,
                system_prompt=RUBRIC_SYSTEM_PROMPT,
            )
            return response.criteria
        except Exception as exc:
            logger.warning(
                "Persistent rubric generation failed; using deterministic fallback: %s",
                exc,
            )
            return self._fallback_cross_cutting()

    def _fallback_cross_cutting(self) -> List[Criterion]:
        """返回稳定的跨章节质量标准，避免初始化阶段因 JSON 错误中断。"""
        return [
            Criterion(
                name="multi_source_validation",
                description="Cross-check important claims across independent sources.",
                guidance=(
                    "Verify each important conclusion with at least two independent "
                    "sources from different source categories."
                ),
                kind=CriterionKind.SOURCE_CREDIBILITY,
                status=CriterionStatus.UNKNOWN,
            ),
            Criterion(
                name="source_credibility",
                description="Assess authority, recency, and potential source bias.",
                guidance=(
                    "Prefer authoritative and recent primary sources; identify possible "
                    "commercial, editorial, or methodological bias."
                ),
                kind=CriterionKind.SOURCE_CREDIBILITY,
                status=CriterionStatus.UNKNOWN,
            ),
            Criterion(
                name="quantitative_support",
                description="Support causal claims with measurable evidence.",
                guidance=(
                    "For each causal claim, collect relevant prices, growth rates, "
                    "shipment data, capacity data, or other quantitative indicators."
                ),
                kind=CriterionKind.QUANTITATIVE,
                status=CriterionStatus.UNKNOWN,
            ),
        ]

    def _fallback_ephemeral(self, evidence: EvidenceBase) -> Rubric:
        """根据当前证据状态生成保守的瞬时 Rubric。"""
        records = evidence.all_records
        unresolved = [
            record
            for record in records
            if record.validation_status
            in {
                EvidenceStatus.UNVERIFIED,
                EvidenceStatus.NEEDS_VERIFICATION,
                EvidenceStatus.DISPUTED,
            }
        ]
        if not records:
            return Rubric(
                criteria=[
                    Criterion(
                        name="evidence_coverage",
                        description="No usable evidence has been collected.",
                        guidance="Collect traceable evidence for the report outline.",
                        kind=CriterionKind.COVERAGE,
                        status=CriterionStatus.OUTSTANDING,
                    )
                ]
            )
        if unresolved:
            return Rubric(
                criteria=[
                    Criterion(
                        name="evidence_verification",
                        description="Some collected evidence is not yet verified.",
                        guidance=(
                            "Cross-check unresolved records against independent sources "
                            "before treating them as established facts."
                        ),
                        kind=CriterionKind.SOURCE_CREDIBILITY,
                        status=CriterionStatus.OUTSTANDING,
                    )
                ]
            )
        return Rubric(
            criteria=[
                Criterion(
                    name="evidence_quality",
                    description="Collected evidence passed the available checks.",
                    guidance="sufficient",
                    kind=CriterionKind.OTHER,
                    status=CriterionStatus.SUFFICIENT,
                )
            ]
        )

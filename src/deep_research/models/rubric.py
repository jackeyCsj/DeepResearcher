"""用于测试时优化的 Rubric 模型。

对应论文 2.2.3：ρ_t = (ρ_p, ρ^e_t)。
- 持久 Rubric ρ_p：稳定的话题级质量维度。
- 瞬时 Rubric ρ^e_t：随证据状态刷新的缺口导向标准。
"""

from __future__ import annotations
from enum import Enum
from typing import List
from pydantic import BaseModel, Field


class CriterionKind(str, Enum):
    """Rubric 标准对应的质量问题类别。"""

    COVERAGE = "coverage"
    DEPTH = "depth"
    CONFLICT = "conflict"
    SOURCE_CREDIBILITY = "source_credibility"
    QUANTITATIVE = "quantitative"
    OTHER = "other"


class CriterionStatus(str, Enum):
    """Rubric 标准当前是否仍未满足。"""

    OUTSTANDING = "outstanding"
    SUFFICIENT = "sufficient"
    UNKNOWN = "unknown"


class Criterion(BaseModel):
    """单条标准 c = (name, description, guidance)。

    guidance 字段是可执行的推理指令，而不是数字评分。
    """

    name: str = ""
    description: str = ""
    guidance: str = Field(
        default="",
        description="Actionable reasoning instruction (NOT a numeric score)",
    )
    kind: CriterionKind = CriterionKind.OTHER
    status: CriterionStatus = CriterionStatus.UNKNOWN


class Rubric(BaseModel):
    """多条 Criterion 构成的 Rubric：ρ = {c₁, ..., cₖ}。"""

    criteria: List[Criterion] = Field(default_factory=list)

    def has_outstanding_gap(self) -> bool:
        """只要任一标准暗示仍有证据缺口，就返回 True。

        瞬时 Rubric 通过该方法向自适应停止机制传递“是否还要继续研究”。
        """
        if any(
            criterion.status == CriterionStatus.OUTSTANDING
            for criterion in self.criteria
        ):
            return True

        if self.criteria and all(
            criterion.status == CriterionStatus.SUFFICIENT
            for criterion in self.criteria
        ):
            return False

        gap_indicators = [
            "insufficient",
            "missing",
            "gap",
            "needs more",
            "not yet",
            "incomplete",
            "lacking",
            "uncovered",
            "not addressed",
            "conflict",
            "contradict",
            "verify",
            "single source",
        ]
        return any(
            any(indicator in c.guidance.lower() for indicator in gap_indicators)
            for c in self.criteria
        )


class RubricSignal(BaseModel):
    """完整指导信号 ρ_t = (ρ_p, ρ^e_t)。"""

    persistent: Rubric = Field(default_factory=Rubric, description="Stable topic-level rubrics ρ_p")
    ephemeral: Rubric = Field(default_factory=Rubric, description="Transient evidence-gap rubrics ρ^e_t")

    def active(self) -> Rubric:
        """合并持久与瞬时 Rubric，供 Planner、Reflection 和 Search Agent 消费。"""
        return Rubric(criteria=self.persistent.criteria + self.ephemeral.criteria)

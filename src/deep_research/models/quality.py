"""证据质量审查模型：Evidence Grounding 与 Cross-source Verify 的结构化输出。"""

from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field


class GroundingCheck(BaseModel):
    """检查单个 claim 是否被其 supporting quote 支撑。"""

    claim_text: str = ""
    evidence_id: Optional[str] = None
    source_url: Optional[str] = None
    passed: bool = True
    status: str = "supported"
    reason: str = ""
    suggested_revision: str = ""


class CrossSourceCheck(BaseModel):
    """检查 claim 在来源之间的支持、单源状态或冲突。"""

    claim_text: str = ""
    status: str = "single_source_primary"
    supporting_evidence_ids: List[str] = Field(default_factory=list)
    conflicting_evidence_ids: List[str] = Field(default_factory=list)
    independent_source_count: int = 0
    reason: str = ""
    recommended_followup: str = ""


class QualityFeedback(BaseModel):
    """反馈给 Planner 的质量问题和补查建议。"""

    passed: bool = True
    failed_checks: List[str] = Field(default_factory=list)
    failure_reasons: List[str] = Field(default_factory=list)
    affected_claims: List[str] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)
    summary: str = ""


class EvidenceQualityReport(BaseModel):
    """证据质量门控的本轮审查报告。"""

    passed: bool = True
    grounding_checks: List[GroundingCheck] = Field(default_factory=list)
    cross_source_checks: List[CrossSourceCheck] = Field(default_factory=list)
    feedback: QualityFeedback = Field(default_factory=QualityFeedback)
    summary: str = ""

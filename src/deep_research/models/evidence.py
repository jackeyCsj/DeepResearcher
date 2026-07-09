"""证据模型：用于累计每轮研究发现。"""

from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SearchHit(BaseModel):
    """搜索工具返回的轻量命中结果，尚未等同于可引用证据。"""

    url: str = ""
    title: str = ""
    snippet: str = ""
    rank: int = 0
    source: str = "web_search"
    score: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EvidenceClaim(BaseModel):
    """从来源正文中抽取出的原子事实/主张，是后续审查和写作的基本单位。
        claim 文本 = 说了什么
        supporting quote = 原文哪句话支持它
        source URL = 来自哪里
        conditions = 在什么条件下成立
        confidence = 抽取得有多可靠
        verification_status = 审核到哪一步了
    """

    text: str = ""
    claim_type: str = Field(default="fact", description="fact, metric, date, method, trend, limitation, forecast, opinion")
    supporting_quote: str = ""
    source_url: Optional[str] = None
    source_title: Optional[str] = None
    entities: List[str] = Field(default_factory=list)
    conditions: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    verification_status: str = Field(
        default="extracted_unverified",
        description="extracted_unverified, single_source_primary, single_source_risky, verified, conflicted, unsupported",
    )
    evidence_id: Optional[str] = None




class EvidenceExtraction(BaseModel):
    """单个来源面向当前子任务的证据蒸馏结果。"""

    summary: str = ""
    claims: List[EvidenceClaim] = Field(default_factory=list)


class EvidenceRecord(BaseModel):
    """来自工具调用或 Search Agent 返回的一条来源级证据。"""

    id: str = ""
    source_url: Optional[str] = None
    title: Optional[str] = None
    snippet: str = Field(default="", description="Short excerpt")
    content: Optional[str] = Field(default=None, description="Full extracted text")
    summary: str = Field(default="", description="Task-focused source summary")
    key_claims: List[EvidenceClaim] = Field(default_factory=list)
    search_hit: Optional[SearchHit] = None
    verification_status: str = "extracted_unverified"
    source_type: str = Field(default="web", description="web, pdf, code, api")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    retrieved_at: datetime = Field(default_factory=datetime.now)
    subtask_id: Optional[str] = Field(default=None, description="Which subtask produced this")
    relevance_score: Optional[float] = None


class EvidenceBundle(BaseModel):
    """单个动作执行后返回的一组证据，对应 Algorithm 2 中的 Δe_t。"""

    subtask_id: str
    records: List[EvidenceRecord] = Field(default_factory=list)
    summary: str = Field(default="", description="Consolidated findings for this subtask")
    completed: bool = True


class EvidenceBase(BaseModel):
    """全局累计证据库 e_t = ⋃_{i=1..t} Δe_i。"""

    bundles: Dict[str, EvidenceBundle] = Field(default_factory=dict)
    all_records: List[EvidenceRecord] = Field(default_factory=list)

    def incorporate(self, bundle: EvidenceBundle) -> None:
        """将新的 EvidenceBundle 合并进全局证据库。"""
        self.bundles[bundle.subtask_id] = bundle
        self.all_records.extend(bundle.records)

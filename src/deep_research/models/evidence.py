"""证据模型：用于累计每轮研究发现。"""

from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EvidenceRecord(BaseModel):
    """来自工具调用或 Search Agent 返回的一条原子证据。"""

    id: str = ""
    source_url: Optional[str] = None
    title: Optional[str] = None
    snippet: str = Field(default="", description="Short excerpt")
    content: Optional[str] = Field(default=None, description="Full extracted text")
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

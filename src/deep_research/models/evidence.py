"""Evidence models for accumulating research findings."""

from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EvidenceRecord(BaseModel):
    """A single piece of evidence from a tool call or Search Agent return."""

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
    """Evidence returned by a single action execution (Δe_t in Algorithm 2)."""

    subtask_id: str
    records: List[EvidenceRecord] = Field(default_factory=list)
    summary: str = Field(default="", description="Consolidated findings for this subtask")
    completed: bool = True


class EvidenceBase(BaseModel):
    """Accumulated global evidence e_t = ⋃_{i=1..t} Δe_i."""

    bundles: Dict[str, EvidenceBundle] = Field(default_factory=dict)
    all_records: List[EvidenceRecord] = Field(default_factory=list)

    def incorporate(self, bundle: EvidenceBundle) -> None:
        self.bundles[bundle.subtask_id] = bundle
        self.all_records.extend(bundle.records)

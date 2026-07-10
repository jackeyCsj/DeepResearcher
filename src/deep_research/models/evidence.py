"""证据模型：用于累计、验证和审计每轮研究发现。"""

from __future__ import annotations
import hashlib
import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, Field


TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
}


def normalize_source_url(source_url: Optional[str]) -> Optional[str]:
    """规范化来源 URL，移除锚点和常见追踪参数。"""
    if not source_url:
        return None

    raw = source_url.strip()
    if not raw:
        return None

    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw

    if not parsed.scheme or not parsed.netloc:
        return raw

    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in TRACKING_QUERY_KEYS
    ]
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")

    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            urlencode(sorted(query)),
            "",
        )
    )


class EvidenceStatus(str, Enum):
    """证据在质量循环中的审核状态。"""

    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    NEEDS_VERIFICATION = "needs_verification"
    DISPUTED = "disputed"
    REJECTED = "rejected"


class ValidationSeverity(str, Enum):
    """证据问题的严重程度。"""

    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


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
    validation_status: EvidenceStatus = EvidenceStatus.UNVERIFIED
    validation_notes: List[str] = Field(default_factory=list)
    canonical_source: Optional[str] = None
    corroborated_by: List[str] = Field(default_factory=list)

    def content_fingerprint(self) -> str:
        """生成用于去重的稳定内容指纹。"""
        material = self.content or self.snippet or self.title or ""
        normalized = re.sub(r"\s+", " ", material).strip().lower()
        if not normalized:
            return ""
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class EvidenceBundle(BaseModel):
    """单个动作执行后返回的一组证据，对应 Algorithm 2 中的 Δe_t。"""

    subtask_id: str
    records: List[EvidenceRecord] = Field(default_factory=list)
    summary: str = Field(default="", description="Consolidated findings for this subtask")
    completed: bool = True
    bundle_id: str = ""
    action_id: Optional[str] = None
    iteration: int = 0
    validation_summary: str = ""
    quality_flags: List[str] = Field(default_factory=list)


class EvidenceValidationIssue(BaseModel):
    """一次质量审核发现的具体证据问题。"""

    issue_type: str = ""
    description: str = ""
    severity: ValidationSeverity = ValidationSeverity.WARNING
    record_ids: List[str] = Field(default_factory=list)
    recommended_action: str = ""


class EvidenceRecordValidation(BaseModel):
    """语义交叉验证对单条证据给出的判定。"""

    record_id: str = ""
    status: EvidenceStatus = EvidenceStatus.NEEDS_VERIFICATION
    notes: str = ""
    corroborated_by: List[str] = Field(default_factory=list)


class EvidenceValidationResult(BaseModel):
    """一个 frontier 证据批次的最终质量审核结果。"""

    batch_id: str = ""
    passed: bool = True
    requires_follow_up: bool = False
    llm_validation_used: bool = False
    validator_error: Optional[str] = None
    action_ids: List[str] = Field(default_factory=list)
    bundle_ids: List[str] = Field(default_factory=list)
    quality_decision: str = ""
    issues: List[EvidenceValidationIssue] = Field(default_factory=list)
    record_validations: List[EvidenceRecordValidation] = Field(default_factory=list)
    follow_up_guidance: List[str] = Field(default_factory=list)


class EvidenceBase(BaseModel):
    """全局累计证据库 e_t = ⋃_{i=1..t} Δe_i。"""

    bundles: Dict[str, EvidenceBundle] = Field(default_factory=dict)
    all_records: List[EvidenceRecord] = Field(default_factory=list)

    def incorporate(self, bundle: EvidenceBundle) -> None:
        """合并证据包，同时保留历史并消除重复记录。"""
        base_id = bundle.bundle_id or f"{bundle.subtask_id}:{len(self.bundles) + 1}"
        bundle_id = base_id
        suffix = 2
        while bundle_id in self.bundles:
            bundle_id = f"{base_id}:{suffix}"
            suffix += 1
        bundle.bundle_id = bundle_id

        records_by_source = {
            record.canonical_source: record
            for record in self.all_records
            if record.canonical_source
        }
        records_by_content = {
            fingerprint: record
            for record in self.all_records
            if (fingerprint := record.content_fingerprint())
        }

        unique_records: List[EvidenceRecord] = []
        for record in bundle.records:
            record.canonical_source = (
                record.canonical_source or normalize_source_url(record.source_url)
            )
            fingerprint = record.content_fingerprint()
            duplicate = None
            if record.canonical_source:
                duplicate = records_by_source.get(record.canonical_source)
            if duplicate is None and fingerprint:
                duplicate = records_by_content.get(fingerprint)

            if duplicate is not None:
                if (
                    record.canonical_source
                    and record.canonical_source != duplicate.canonical_source
                    and record.canonical_source not in duplicate.corroborated_by
                ):
                    duplicate.corroborated_by.append(record.canonical_source)
                continue

            unique_records.append(record)
            self.all_records.append(record)
            if record.canonical_source:
                records_by_source[record.canonical_source] = record
            if fingerprint:
                records_by_content[fingerprint] = record

        bundle.records = unique_records
        self.bundles[bundle_id] = bundle

    def records_with_status(
        self,
        *statuses: EvidenceStatus,
    ) -> List[EvidenceRecord]:
        """按审核状态筛选全局证据。"""
        allowed = set(statuses)
        return [
            record
            for record in self.all_records
            if record.validation_status in allowed
        ]

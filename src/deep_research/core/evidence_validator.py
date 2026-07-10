"""Frontier 证据批次的整理、交叉验证与状态更新。"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlsplit

from deep_research.models.actions import BaseAction
from deep_research.models.evidence import (
    EvidenceBase,
    EvidenceBundle,
    EvidenceRecord,
    EvidenceRecordValidation,
    EvidenceStatus,
    EvidenceValidationIssue,
    EvidenceValidationResult,
    ValidationSeverity,
    normalize_source_url,
)
from deep_research.models.rubric import (
    CriterionKind,
    CriterionStatus,
    Rubric,
)
from deep_research.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)


VALIDATION_SYSTEM_PROMPT = """You are an evidence quality validator for a deep research system.
Evaluate only the supplied evidence records. Identify unsupported claims, source-quality risks,
cross-source contradictions, and missing independent corroboration. Return structured decisions;
do not invent facts or create research-plan nodes."""


class EvidenceQualityGate:
    """对每轮 frontier 证据执行确定性检查和按需语义交叉验证。"""

    def __init__(
        self,
        llm_client: LLMClient,
        min_independent_sources: int = 2,
        max_validation_records: int = 30,
    ) -> None:
        self.llm = llm_client
        self.min_independent_sources = min_independent_sources
        self.max_validation_records = max_validation_records

    def consolidate(
        self,
        bundles: List[EvidenceBundle],
        actions: List[BaseAction],
        iteration: int,
    ) -> List[EvidenceBundle]:
        """标准化一个 frontier 的结果并消除批次内重复证据。"""
        action_ids: Dict[str, str] = {
            action.subtask_id: action.id for action in actions
        }
        seen_sources: Dict[str, EvidenceRecord] = {}
        seen_content: Dict[str, EvidenceRecord] = {}
        normalized_bundles: List[EvidenceBundle] = []

        for bundle_index, original in enumerate(bundles, start=1):
            bundle = original.model_copy(deep=True)
            bundle.action_id = bundle.action_id or action_ids.get(bundle.subtask_id)
            bundle.iteration = iteration
            bundle.bundle_id = bundle.bundle_id or (
                f"iter-{iteration}:{bundle.action_id or bundle.subtask_id}:{bundle_index}"
            )

            unique_records: List[EvidenceRecord] = []
            duplicate_count = 0
            for record_index, record in enumerate(bundle.records, start=1):
                record.canonical_source = normalize_source_url(record.source_url)
                original_id = record.id or f"record-{record_index}"
                record.id = f"{bundle.bundle_id}:{original_id}"
                record.validation_status = EvidenceStatus.UNVERIFIED

                fingerprint = record.content_fingerprint()
                duplicate = None
                if record.canonical_source:
                    duplicate = seen_sources.get(record.canonical_source)
                if duplicate is None and fingerprint:
                    duplicate = seen_content.get(fingerprint)

                if duplicate is not None:
                    duplicate_count += 1
                    if (
                        record.canonical_source
                        and record.canonical_source != duplicate.canonical_source
                        and record.canonical_source not in duplicate.corroborated_by
                    ):
                        duplicate.corroborated_by.append(record.canonical_source)
                    continue

                unique_records.append(record)
                if record.canonical_source:
                    seen_sources[record.canonical_source] = record
                if fingerprint:
                    seen_content[fingerprint] = record

            bundle.records = unique_records
            flags: List[str] = []
            if not bundle.completed:
                flags.append("execution_failure")
            if not bundle.records and not bundle.summary.strip():
                flags.append("empty_evidence")
            if duplicate_count:
                flags.append("duplicates_removed")

            bundle.quality_flags = flags
            normalized_bundles.append(bundle)

        domains_by_subtask: Dict[str, set[str]] = {}
        for bundle in normalized_bundles:
            domains_by_subtask.setdefault(bundle.subtask_id, set()).update(
                self._source_domains(bundle.records)
            )

        for bundle in normalized_bundles:
            domains = domains_by_subtask.get(bundle.subtask_id, set())
            if bundle.records and not domains:
                bundle.quality_flags.append("missing_source")
            elif bundle.records and len(domains) < self.min_independent_sources:
                bundle.quality_flags.append("single_source")
            duplicate_count = int("duplicates_removed" in bundle.quality_flags)
            bundle.validation_summary = (
                f"records={len(bundle.records)}, sources={len(domains)}, "
                f"duplicates_removed={duplicate_count}, "
                f"flags={','.join(bundle.quality_flags) or 'none'}"
            )

        return normalized_bundles

    async def validate(
        self,
        batch: List[EvidenceBundle],
        evidence_base: EvidenceBase,
        ephemeral_rubric: Rubric,
        persistent_rubric: Optional[Rubric] = None,
    ) -> EvidenceValidationResult:
        """执行混合质量审核，并把判定同步到证据对象。"""
        batch_id = self._batch_id(batch)
        deterministic_issues = self._deterministic_issues(batch)
        use_llm = bool(deterministic_issues) or self._rubric_requires_validation(
            ephemeral_rubric
        )

        if not use_llm:
            result = EvidenceValidationResult(
                batch_id=batch_id,
                passed=True,
                requires_follow_up=False,
                action_ids=self._action_ids(batch),
                bundle_ids=[bundle.bundle_id for bundle in batch],
                record_validations=[
                    EvidenceRecordValidation(
                        record_id=record.id,
                        status=EvidenceStatus.VERIFIED,
                        notes="Passed deterministic evidence checks.",
                    )
                    for record in self._records(batch)
                ],
            )
            self.apply_result(batch, evidence_base, result)
            return result

        try:
            semantic = await self.llm.generate(
                self._validation_prompt(
                    batch,
                    evidence_base,
                    ephemeral_rubric,
                    persistent_rubric or Rubric(),
                ),
                response_model=EvidenceValidationResult,
                system_prompt=VALIDATION_SYSTEM_PROMPT,
            )
            semantic.batch_id = batch_id
            semantic.llm_validation_used = True
            semantic.action_ids = self._action_ids(batch)
            semantic.bundle_ids = [bundle.bundle_id for bundle in batch]
            semantic.issues = deterministic_issues + semantic.issues
            if any(
                issue.severity == ValidationSeverity.BLOCKING
                for issue in deterministic_issues
            ):
                semantic.passed = False
                semantic.requires_follow_up = True
            self._complete_record_decisions(batch, semantic)
            self.apply_result(batch, evidence_base, semantic)
            return semantic
        except Exception as exc:
            logger.exception("Evidence semantic validation failed: %s", exc)
            result = EvidenceValidationResult(
                batch_id=batch_id,
                passed=False,
                requires_follow_up=True,
                llm_validation_used=True,
                validator_error=str(exc),
                action_ids=self._action_ids(batch),
                bundle_ids=[bundle.bundle_id for bundle in batch],
                issues=deterministic_issues
                + [
                    EvidenceValidationIssue(
                        issue_type="validator_error",
                        description=f"Semantic evidence validation failed: {exc}",
                        severity=ValidationSeverity.BLOCKING,
                        record_ids=[record.id for record in self._records(batch)],
                        recommended_action=(
                            "Re-run validation or collect independent evidence before stopping."
                        ),
                    )
                ],
                record_validations=[
                    EvidenceRecordValidation(
                        record_id=record.id,
                        status=EvidenceStatus.NEEDS_VERIFICATION,
                        notes="Validator failed; evidence remains unresolved.",
                    )
                    for record in self._records(batch)
                ],
                follow_up_guidance=[
                    "Revalidate the latest evidence batch and obtain independent corroboration."
                ],
            )
            self.apply_result(batch, evidence_base, result)
            return result

    def apply_result(
        self,
        batch: List[EvidenceBundle],
        evidence_base: EvidenceBase,
        result: EvidenceValidationResult,
    ) -> None:
        """把结构化验证结果写回批次和全局证据库。"""
        decisions = {
            decision.record_id: decision for decision in result.record_validations
        }
        records = {
            record.id: record
            for record in [*self._records(batch), *evidence_base.all_records]
        }

        for record_id, decision in decisions.items():
            record = records.get(record_id)
            if record is None:
                continue
            record.validation_status = (
                EvidenceStatus.NEEDS_VERIFICATION
                if decision.status == EvidenceStatus.UNVERIFIED
                else decision.status
            )
            if decision.notes and decision.notes not in record.validation_notes:
                record.validation_notes.append(decision.notes)
            for source in decision.corroborated_by:
                normalized = normalize_source_url(source) or source
                if normalized not in record.corroborated_by:
                    record.corroborated_by.append(normalized)

        for bundle in batch:
            status_counts = Counter(
                record.validation_status.value for record in bundle.records
            )
            bundle.validation_summary = (
                f"{bundle.validation_summary}; validation="
                + ",".join(
                    f"{status}={count}" for status, count in sorted(status_counts.items())
                )
            )

    def _complete_record_decisions(
        self,
        batch: List[EvidenceBundle],
        result: EvidenceValidationResult,
    ) -> None:
        decided_ids = {
            decision.record_id for decision in result.record_validations
        }
        default_status = (
            EvidenceStatus.VERIFIED
            if result.passed and not result.requires_follow_up
            else EvidenceStatus.NEEDS_VERIFICATION
        )
        for record in self._records(batch):
            if record.id in decided_ids:
                continue
            result.record_validations.append(
                EvidenceRecordValidation(
                    record_id=record.id,
                    status=default_status,
                    notes="Defaulted from batch-level validation result.",
                )
            )

    def _deterministic_issues(
        self,
        batch: List[EvidenceBundle],
    ) -> List[EvidenceValidationIssue]:
        issues: List[EvidenceValidationIssue] = []
        for bundle in batch:
            record_ids = [record.id for record in bundle.records]
            if not bundle.completed or "execution_failure" in bundle.quality_flags:
                issues.append(
                    EvidenceValidationIssue(
                        issue_type="execution_failure",
                        description=f"Subtask {bundle.subtask_id} did not complete successfully.",
                        severity=ValidationSeverity.BLOCKING,
                        record_ids=record_ids,
                        recommended_action="Retry the failed subtask or replace its source path.",
                    )
                )
            if "empty_evidence" in bundle.quality_flags:
                issues.append(
                    EvidenceValidationIssue(
                        issue_type="empty_evidence",
                        description=f"Subtask {bundle.subtask_id} returned no usable evidence.",
                        severity=ValidationSeverity.BLOCKING,
                        recommended_action="Run a more specific retrieval action.",
                    )
                )
            if "missing_source" in bundle.quality_flags:
                issues.append(
                    EvidenceValidationIssue(
                        issue_type="missing_source",
                        description=f"Subtask {bundle.subtask_id} contains uncited evidence.",
                        severity=ValidationSeverity.BLOCKING,
                        record_ids=record_ids,
                        recommended_action="Retrieve traceable source URLs for these claims.",
                    )
                )
            if "single_source" in bundle.quality_flags:
                issues.append(
                    EvidenceValidationIssue(
                        issue_type="source_diversity",
                        description=(
                            f"Subtask {bundle.subtask_id} is supported by fewer than "
                            f"{self.min_independent_sources} independent sources."
                        ),
                        severity=ValidationSeverity.BLOCKING,
                        record_ids=record_ids,
                        recommended_action="Collect an independent corroborating source.",
                    )
                )
        return issues

    def _rubric_requires_validation(self, rubric: Rubric) -> bool:
        keywords = (
            "conflict",
            "contradict",
            "cross-source",
            "cross source",
            "verify",
            "credibility",
            "source",
            "coverage",
            "missing",
        )
        for criterion in rubric.criteria:
            if criterion.status == CriterionStatus.SUFFICIENT:
                continue
            if (
                criterion.status == CriterionStatus.OUTSTANDING
                and criterion.kind
                in {
                    CriterionKind.CONFLICT,
                    CriterionKind.SOURCE_CREDIBILITY,
                    CriterionKind.COVERAGE,
                }
            ):
                return True
            text = f"{criterion.name} {criterion.description} {criterion.guidance}".lower()
            if any(keyword in text for keyword in keywords):
                return True
        return False

    def _validation_prompt(
        self,
        batch: List[EvidenceBundle],
        evidence_base: EvidenceBase,
        ephemeral_rubric: Rubric,
        persistent_rubric: Rubric,
    ) -> str:
        current_records = self._records(batch)[: self.max_validation_records]
        current_ids = {record.id for record in current_records}
        historical = [
            record
            for record in evidence_base.all_records
            if record.id not in current_ids
            and record.validation_status == EvidenceStatus.VERIFIED
        ][-20:]

        current_text = "\n".join(
            f"- id={record.id} | source={record.canonical_source or 'N/A'} | "
            f"text={(record.content or record.snippet or record.title or '')[:500]}"
            for record in current_records
        ) or "No atomic evidence records in this batch."
        historical_text = "\n".join(
            f"- id={record.id} | source={record.canonical_source or 'N/A'} | "
            f"text={(record.content or record.snippet or record.title or '')[:300]}"
            for record in historical
        ) or "No previously verified evidence."
        rubric_text = "\n".join(
            f"- [{criterion.kind.value}/{criterion.status.value}] "
            f"{criterion.name}: {criterion.guidance}"
            for criterion in [
                *persistent_rubric.criteria,
                *ephemeral_rubric.criteria,
            ]
        ) or "No active rubric criteria."

        return f"""Validate the latest frontier evidence batch.

Active rubric:
{rubric_text}

Latest evidence:
{current_text}

Previously verified evidence:
{historical_text}

For every latest evidence record, return a record_validations entry using one status:
verified, needs_verification, disputed, or rejected.
Set passed=false and requires_follow_up=true when any important claim lacks traceable support,
has unresolved contradiction, or needs an independent source. Add concise follow_up_guidance
that the Planner can convert into retrieval or verification tasks.
"""

    def _source_domains(self, records: Iterable[EvidenceRecord]) -> set[str]:
        domains: set[str] = set()
        for record in records:
            source = record.canonical_source or normalize_source_url(record.source_url)
            if not source:
                continue
            parsed = urlsplit(source)
            if parsed.netloc:
                domains.add(parsed.netloc.lower())
            for corroborating_source in record.corroborated_by:
                corroborating = urlsplit(corroborating_source)
                if corroborating.netloc:
                    domains.add(corroborating.netloc.lower())
        return domains

    def _records(self, batch: List[EvidenceBundle]) -> List[EvidenceRecord]:
        return [record for bundle in batch for record in bundle.records]

    def _batch_id(self, batch: List[EvidenceBundle]) -> str:
        if not batch:
            return "empty-batch"
        return f"iteration-{batch[0].iteration}"

    def _action_ids(self, batch: List[EvidenceBundle]) -> List[str]:
        return [
            action_id
            for action_id in dict.fromkeys(
                bundle.action_id for bundle in batch if bundle.action_id
            )
            if action_id
        ]

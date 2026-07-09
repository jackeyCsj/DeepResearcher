"""Evidence Quality Gate：证据级 Grounding 与 Cross-source Verify。"""

from __future__ import annotations
from collections import defaultdict
import logging
import re
from typing import Dict, Iterable, List, Tuple
from urllib.parse import urlparse

from deep_research.models.evidence import EvidenceBase, EvidenceClaim, EvidenceRecord
from deep_research.models.quality import (
    CrossSourceCheck,
    EvidenceQualityReport,
    GroundingCheck,
    QualityFeedback,
)
from deep_research.models.rubric import RubricSignal
from deep_research.models.topic import TaskContext

logger = logging.getLogger(__name__)


class EvidenceQualityGate:
    """对已抽取的 EvidenceClaim 做轻量质量门控。

    该 MVP 先用确定性规则完成两件事：
    1. Evidence Grounding：claim 必须有 supporting_quote，且文本重叠不能过低。
    2. Cross-source Verify：区分 verified、single_source_primary、single_source_risky、
       conflicted、unsupported，避免把单篇创新论文误杀。
    """

    def __init__(
        self,
        grounding_overlap_threshold: float = 0.18,
        quote_source_overlap_threshold: float = 0.75,
    ) -> None:
        self.grounding_overlap_threshold = grounding_overlap_threshold
        self.quote_source_overlap_threshold = quote_source_overlap_threshold

    async def review(
        self,
        context: TaskContext,
        evidence: EvidenceBase,
        rubric: RubricSignal,
    ) -> EvidenceQualityReport:
        """审查当前 EvidenceBase，并原地更新 claim / record 的 verification_status。"""
        del context, rubric  # 当前规则版暂不需要；保留接口供后续 LLM/章节覆盖扩展。
        claim_items = list(self._iter_claims(evidence))
        grounding_checks = [
            self._check_grounding(record, claim)
            for record, claim in claim_items
        ]
        grounding_by_evidence = {
            (check.evidence_id, check.claim_text): check
            for check in grounding_checks
        }
        cross_checks = self._cross_source_checks(claim_items, grounding_by_evidence)
        feedback = self._build_feedback(grounding_checks, cross_checks)
        self._apply_statuses(evidence)
        report = EvidenceQualityReport(
            passed=feedback.passed,
            grounding_checks=grounding_checks,
            cross_source_checks=cross_checks,
            feedback=feedback,
            summary=feedback.summary,
        )
        logger.info(
            "Evidence quality: %s (%s grounding checks, %s cross-source checks)",
            "passed" if report.passed else "failed",
            len(grounding_checks),
            len(cross_checks),
        )
        return report

    def _iter_claims(
        self,
        evidence: EvidenceBase,
    ) -> Iterable[Tuple[EvidenceRecord, EvidenceClaim]]:
        for record in evidence.all_records:
            for claim in record.key_claims:
                yield record, claim

    def _check_grounding(
        self,
        record: EvidenceRecord,
        claim: EvidenceClaim,
    ) -> GroundingCheck:
        if not claim.text.strip():
            claim.verification_status = "unsupported"
            return GroundingCheck(
                claim_text=claim.text,
                evidence_id=record.id,
                source_url=record.source_url,
                passed=False,
                status="empty_claim",
                reason="Claim text is empty.",
            )
        if not claim.supporting_quote.strip():
            claim.verification_status = "unsupported"
            return GroundingCheck(
                claim_text=claim.text,
                evidence_id=record.id,
                source_url=record.source_url,
                passed=False,
                status="missing_quote",
                reason="Claim has no supporting quote from the source.",
                suggested_revision="Re-read the source and extract a direct quote before using this claim.",
            )

        quote_source_overlap = self._quote_source_overlap(record, claim.supporting_quote)
        if quote_source_overlap < self.quote_source_overlap_threshold:
            claim.verification_status = "unsupported"
            return GroundingCheck(
                claim_text=claim.text,
                evidence_id=record.id,
                source_url=record.source_url,
                passed=False,
                status="quote_not_in_source",
                reason=f"Supporting quote is not sufficiently grounded in the retrieved source text ({quote_source_overlap:.2f}).",
                suggested_revision="Re-read the source or crawl the full page before using this claim.",
            )

        claim_quote_overlap = self._text_overlap(claim.text, claim.supporting_quote)
        if claim_quote_overlap < self.grounding_overlap_threshold:
            claim.verification_status = "unsupported"
            return GroundingCheck(
                claim_text=claim.text,
                evidence_id=record.id,
                source_url=record.source_url,
                passed=False,
                status="weak_quote_support",
                reason=f"Claim and quote have low textual overlap ({claim_quote_overlap:.2f}); the claim may be overstated.",
                suggested_revision="Use a narrower claim that is directly supported by the quote.",
            )

        return GroundingCheck(
            claim_text=claim.text,
            evidence_id=record.id,
            source_url=record.source_url,
            passed=True,
            status="supported",
            reason="Claim has a supporting quote with sufficient textual overlap.",
        )

    def _cross_source_checks(
        self,
        claim_items: List[Tuple[EvidenceRecord, EvidenceClaim]],
        grounding_by_evidence: Dict[Tuple[str | None, str], GroundingCheck],
    ) -> List[CrossSourceCheck]:
        groups: Dict[str, List[Tuple[EvidenceRecord, EvidenceClaim]]] = defaultdict(list)
        for record, claim in claim_items:
            groups[self._claim_group_key(claim)].append((record, claim))

        checks: List[CrossSourceCheck] = []
        for _, items in groups.items():
            representative = items[0][1]
            grounded_items = [
                (record, claim)
                for record, claim in items
                if grounding_by_evidence.get((record.id, claim.text), GroundingCheck()).passed
            ]
            if not grounded_items:
                checks.append(
                    CrossSourceCheck(
                        claim_text=representative.text,
                        status="unsupported",
                        supporting_evidence_ids=[],
                        independent_source_count=0,
                        reason="No grounded source supports this claim.",
                        recommended_followup="Find a source with direct textual support for this claim.",
                    )
                )
                continue

            conflict_ids = self._conflicting_evidence_ids(grounded_items)
            domains = {
                self._domain(record.source_url)
                for record, _ in grounded_items
                if record.source_url
            }
            evidence_ids = [record.id for record, _ in grounded_items if record.id]

            if conflict_ids:
                status = "conflicted"
                reason = "Potential numeric/date conflict across sources with similar claim context."
                followup = "Run a targeted verification search for this claim and compare source definitions, dates, and measurement scope."
            elif len(domains) >= 2:
                status = "verified"
                reason = "Claim is supported by multiple independent source domains."
                followup = ""
            elif any(self._is_primary_source(record) for record, _ in grounded_items):
                status = "single_source_primary"
                reason = "Claim is grounded in one primary/original source; cite as that source's own finding, not as broad consensus."
                followup = ""
            else:
                status = "single_source_risky"
                reason = "Claim is grounded, but only one non-primary source supports it."
                followup = "Find an independent source before using this as a core conclusion."

            for _, claim in grounded_items:
                claim.verification_status = status
            checks.append(
                CrossSourceCheck(
                    claim_text=representative.text,
                    status=status,
                    supporting_evidence_ids=evidence_ids,
                    conflicting_evidence_ids=conflict_ids,
                    independent_source_count=len(domains),
                    reason=reason,
                    recommended_followup=followup,
                )
            )
        return checks

    def _build_feedback(
        self,
        grounding_checks: List[GroundingCheck],
        cross_checks: List[CrossSourceCheck],
    ) -> QualityFeedback:
        failed_checks: List[str] = []
        failure_reasons: List[str] = []
        affected_claims: List[str] = []
        recommended_actions: List[str] = []

        for check in grounding_checks:
            if not check.passed:
                failed_checks.append(f"grounding:{check.status}")
                failure_reasons.append(check.reason)
                affected_claims.append(check.claim_text)
                if check.suggested_revision:
                    recommended_actions.append(check.suggested_revision)

        for check in cross_checks:
            if check.status in {"conflicted", "unsupported"}:
                failed_checks.append(f"cross_source:{check.status}")
                failure_reasons.append(check.reason)
                affected_claims.append(check.claim_text)
                if check.recommended_followup:
                    recommended_actions.append(check.recommended_followup)
            elif check.status == "single_source_risky":
                recommended_actions.append(check.recommended_followup)

        passed = not any(
            check.startswith("grounding:") or check in {"cross_source:conflicted", "cross_source:unsupported"}
            for check in failed_checks
        )
        if passed:
            summary = "Evidence quality gate passed. Grounded claims can be used with their verification-status caveats."
        else:
            summary = "Evidence quality gate failed. Replan should prioritize direct support and conflict-resolution searches."
        return QualityFeedback(
            passed=passed,
            failed_checks=failed_checks,
            failure_reasons=failure_reasons,
            affected_claims=affected_claims[:10],
            recommended_actions=list(dict.fromkeys(recommended_actions))[:10],
            summary=summary,
        )

    def _apply_statuses(self, evidence: EvidenceBase) -> None:
        for record in evidence.all_records:
            statuses = {claim.verification_status for claim in record.key_claims}
            if not statuses:
                record.verification_status = "no_claims_extracted"
            elif "conflicted" in statuses:
                record.verification_status = "has_conflicts"
            elif "unsupported" in statuses:
                record.verification_status = "has_unsupported_claims"
            elif "verified" in statuses:
                record.verification_status = "partially_verified"
            elif "single_source_risky" in statuses:
                record.verification_status = "single_source_risky"
            elif "single_source_primary" in statuses:
                record.verification_status = "single_source_primary"
            else:
                record.verification_status = "extracted_unverified"

    def _claim_group_key(self, claim: EvidenceClaim) -> str:
        topic_key = self._claim_topic_key(claim)
        if claim.entities:
            entity_key = "|".join(sorted(e.lower().strip() for e in claim.entities if e.strip()))
            return f"{claim.claim_type}:{entity_key}:{topic_key}"
        text = self._normalize_text(claim.text)
        return f"{claim.claim_type}:{topic_key or text[:120]}"

    def _conflicting_evidence_ids(
        self,
        items: List[Tuple[EvidenceRecord, EvidenceClaim]],
    ) -> List[str]:
        signatures: Dict[Tuple[str, ...], List[str]] = defaultdict(list)
        for record, claim in items:
            values = tuple(self._numbers(claim.text + " " + claim.supporting_quote))
            if values:
                signatures[values].append(record.id)
        if len(signatures) <= 1:
            return []
        ids = []
        for record_ids in signatures.values():
            ids.extend(record_ids)
        return list(dict.fromkeys(i for i in ids if i))

    def _is_primary_source(self, record: EvidenceRecord) -> bool:
        url = record.source_url or ""
        domain = self._domain(url)
        if any(marker in domain for marker in ("arxiv.org", "doi.org", "acm.org", "ieee.org", "nature.com", "springer.com", "openreview.net")):
            return True
        if domain.endswith(".gov") or domain.endswith(".edu"):
            return True
        source_type = (record.source_type or "").lower()
        return source_type in {"paper", "pdf", "api"}

    def _domain(self, url: str | None) -> str:
        if not url:
            return ""
        netloc = urlparse(url).netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else netloc

    def _quote_source_overlap(self, record: EvidenceRecord, quote: str) -> float:
        source_text = " ".join(
            part
            for part in (record.content, record.summary, record.snippet)
            if part
        )
        if not source_text.strip():
            return 0.0

        normalized_quote = self._normalize_text(quote)
        normalized_source = self._normalize_text(source_text)
        if normalized_quote and normalized_quote in normalized_source:
            return 1.0
        quote_numbers = set(self._numbers(quote))
        source_numbers = set(self._numbers(source_text))
        if quote_numbers and not quote_numbers.issubset(source_numbers):
            return 0.0
        return self._text_overlap(quote, source_text)

    def _text_overlap(self, claim_text: str, quote: str) -> float:
        claim_tokens = self._tokens(claim_text)
        quote_tokens = self._tokens(quote)
        if not claim_tokens or not quote_tokens:
            return 0.0
        return len(claim_tokens & quote_tokens) / max(1, len(claim_tokens))

    def _tokens(self, text: str) -> set[str]:
        normalized = self._normalize_text(text)
        word_tokens = set(re.findall(r"[a-z0-9]+", normalized))
        cjk_chars = re.findall(r"[\u4e00-\u9fff]", normalized)
        cjk_bigrams = {
            "".join(cjk_chars[i : i + 2])
            for i in range(max(0, len(cjk_chars) - 1))
        }
        return word_tokens | cjk_bigrams

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.lower()).strip()

    def _numbers(self, text: str) -> List[str]:
        return re.findall(r"[-+]?\d+(?:\.\d+)?\s*%?", text)

    def _claim_topic_key(self, claim: EvidenceClaim) -> str:
        entity_tokens = {
            token
            for entity in claim.entities
            for token in re.findall(r"[a-z0-9]+", entity.lower())
        }
        stopwords = {
            "a",
            "an",
            "and",
            "are",
            "as",
            "at",
            "be",
            "by",
            "for",
            "from",
            "has",
            "in",
            "is",
            "of",
            "on",
            "or",
            "that",
            "the",
            "this",
            "to",
            "was",
            "were",
            "with",
        }
        words = [
            word
            for word in re.findall(r"[a-z0-9]+", claim.text.lower())
            if word not in stopwords
            and word not in entity_tokens
            and not re.fullmatch(r"\d+(?:\.\d+)?", word)
        ]
        if words:
            return "|".join(words[:8])

        cjk_chars = re.findall(r"[\u4e00-\u9fff]", claim.text)
        return "".join(cjk_chars[:24])

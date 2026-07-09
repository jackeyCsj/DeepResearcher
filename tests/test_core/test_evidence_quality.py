import pytest

pytest.importorskip("pydantic_settings")

from deep_research.core.evidence_quality import EvidenceQualityGate
from deep_research.models.evidence import EvidenceBase, EvidenceBundle, EvidenceClaim, EvidenceRecord
from deep_research.models.rubric import RubricSignal
from deep_research.models.topic import TaskContext


def _record(
    *,
    record_id: str = "r1",
    url: str = "https://example.com/source",
    content: str,
    claim_text: str,
    quote: str,
    entities: list[str] | None = None,
    source_type: str = "web",
) -> EvidenceRecord:
    return EvidenceRecord(
        id=record_id,
        source_url=url,
        title="Source",
        content=content,
        summary=content[:200],
        source_type=source_type,
        key_claims=[
            EvidenceClaim(
                text=claim_text,
                claim_type="metric",
                supporting_quote=quote,
                entities=entities or [],
                confidence=0.8,
            )
        ],
    )


def _evidence(*records: EvidenceRecord) -> EvidenceBase:
    bundle = EvidenceBundle(subtask_id="T1", records=list(records), summary="test bundle")
    evidence = EvidenceBase()
    evidence.incorporate(bundle)
    return evidence


@pytest.mark.asyncio
async def test_grounded_primary_source_passes_as_single_source_primary() -> None:
    record = _record(
        record_id="paper-1",
        url="https://arxiv.org/abs/2401.00001",
        content="The method achieves 92% accuracy on Dataset A.",
        claim_text="The method achieves 92% accuracy on Dataset A.",
        quote="The method achieves 92% accuracy on Dataset A.",
        entities=["Method"],
        source_type="paper",
    )

    report = await EvidenceQualityGate().review(TaskContext(), _evidence(record), RubricSignal())

    assert report.passed is True
    assert record.key_claims[0].verification_status == "single_source_primary"
    assert report.cross_source_checks[0].status == "single_source_primary"


@pytest.mark.asyncio
async def test_single_non_primary_source_warns_without_failing() -> None:
    record = _record(
        content="Vendor X reports 40% lower latency in its benchmark.",
        claim_text="Vendor X reports 40% lower latency in its benchmark.",
        quote="Vendor X reports 40% lower latency in its benchmark.",
        entities=["Vendor X"],
    )

    report = await EvidenceQualityGate().review(TaskContext(), _evidence(record), RubricSignal())

    assert report.passed is True
    assert record.key_claims[0].verification_status == "single_source_risky"
    assert report.feedback.recommended_actions


@pytest.mark.asyncio
async def test_missing_supporting_quote_fails_grounding() -> None:
    record = _record(
        content="The benchmark reports 40% lower latency.",
        claim_text="The benchmark reports 40% lower latency.",
        quote="",
        entities=["Benchmark"],
    )

    report = await EvidenceQualityGate().review(TaskContext(), _evidence(record), RubricSignal())

    assert report.passed is False
    assert record.key_claims[0].verification_status == "unsupported"
    assert any(check.status == "missing_quote" for check in report.grounding_checks)


@pytest.mark.asyncio
async def test_quote_not_found_in_source_fails_grounding() -> None:
    record = _record(
        content="The benchmark reports 40% lower latency.",
        claim_text="The benchmark reports 92% accuracy.",
        quote="The benchmark reports 92% accuracy.",
        entities=["Benchmark"],
    )

    report = await EvidenceQualityGate().review(TaskContext(), _evidence(record), RubricSignal())

    assert report.passed is False
    assert record.key_claims[0].verification_status == "unsupported"
    assert any(check.status == "quote_not_in_source" for check in report.grounding_checks)


@pytest.mark.asyncio
async def test_same_claim_with_two_independent_sources_is_verified() -> None:
    record_a = _record(
        record_id="r1",
        url="https://source-a.example/report",
        content="Market adoption reached 30% in 2025.",
        claim_text="Market adoption reached 30% in 2025.",
        quote="Market adoption reached 30% in 2025.",
        entities=["Market adoption"],
    )
    record_b = _record(
        record_id="r2",
        url="https://source-b.example/report",
        content="Market adoption reached 30% in 2025.",
        claim_text="Market adoption reached 30% in 2025.",
        quote="Market adoption reached 30% in 2025.",
        entities=["Market adoption"],
    )

    report = await EvidenceQualityGate().review(TaskContext(), _evidence(record_a, record_b), RubricSignal())

    assert report.passed is True
    assert report.cross_source_checks[0].status == "verified"
    assert {record_a.key_claims[0].verification_status, record_b.key_claims[0].verification_status} == {"verified"}


@pytest.mark.asyncio
async def test_numeric_conflict_across_sources_fails() -> None:
    record_a = _record(
        record_id="r1",
        url="https://source-a.example/report",
        content="Market adoption reached 30% in 2025.",
        claim_text="Market adoption reached 30% in 2025.",
        quote="Market adoption reached 30% in 2025.",
        entities=["Market adoption"],
    )
    record_b = _record(
        record_id="r2",
        url="https://source-b.example/report",
        content="Market adoption reached 45% in 2025.",
        claim_text="Market adoption reached 45% in 2025.",
        quote="Market adoption reached 45% in 2025.",
        entities=["Market adoption"],
    )

    report = await EvidenceQualityGate().review(TaskContext(), _evidence(record_a, record_b), RubricSignal())

    assert report.passed is False
    assert report.cross_source_checks[0].status == "conflicted"
    assert {record_a.key_claims[0].verification_status, record_b.key_claims[0].verification_status} == {"conflicted"}

from deep_research.models.evidence import (
    EvidenceBase,
    EvidenceBundle,
    EvidenceRecord,
    EvidenceStatus,
    normalize_source_url,
)


def test_normalize_source_url_removes_tracking_and_fragment() -> None:
    normalized = normalize_source_url(
        "HTTPS://Example.COM/report/?utm_source=test&b=2&a=1#section"
    )
    assert normalized == "https://example.com/report?a=1&b=2"


def test_evidence_base_preserves_history_and_deduplicates() -> None:
    evidence = EvidenceBase()
    evidence.incorporate(
        EvidenceBundle(
            bundle_id="batch-1",
            subtask_id="T-1",
            records=[
                EvidenceRecord(
                    id="r1",
                    source_url="https://example.com/report?utm_source=one",
                    snippet="Shared finding",
                    validation_status=EvidenceStatus.VERIFIED,
                )
            ],
        )
    )
    evidence.incorporate(
        EvidenceBundle(
            bundle_id="batch-2",
            subtask_id="T-1",
            records=[
                EvidenceRecord(
                    id="r2",
                    source_url="https://example.com/report?utm_source=two",
                    snippet="Shared finding",
                )
            ],
        )
    )

    assert list(evidence.bundles) == ["batch-1", "batch-2"]
    assert len(evidence.all_records) == 1
    assert evidence.bundles["batch-2"].records == []


def test_duplicate_content_retains_corroborating_source() -> None:
    evidence = EvidenceBase()
    evidence.incorporate(
        EvidenceBundle(
            bundle_id="batch-1",
            subtask_id="T-1",
            records=[
                EvidenceRecord(
                    id="r1",
                    source_url="https://source-a.example/item",
                    snippet="Identical published statement",
                )
            ],
        )
    )
    evidence.incorporate(
        EvidenceBundle(
            bundle_id="batch-2",
            subtask_id="T-1",
            records=[
                EvidenceRecord(
                    id="r2",
                    source_url="https://source-b.example/item",
                    snippet="Identical published statement",
                )
            ],
        )
    )

    assert len(evidence.all_records) == 1
    assert evidence.all_records[0].corroborated_by == [
        "https://source-b.example/item"
    ]

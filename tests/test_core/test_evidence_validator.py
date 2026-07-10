import pytest

from deep_research.core.evidence_validator import EvidenceQualityGate
from deep_research.models.actions import ToolCallAction
from deep_research.models.evidence import (
    EvidenceBase,
    EvidenceBundle,
    EvidenceRecord,
    EvidenceRecordValidation,
    EvidenceStatus,
    EvidenceValidationResult,
)
from deep_research.models.rubric import (
    Criterion,
    CriterionKind,
    CriterionStatus,
    Rubric,
)


class FakeLLM:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls = 0

    async def generate(self, *args, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.response


def make_batch(gate: EvidenceQualityGate):
    action = ToolCallAction(
        id="A-1",
        subtask_id="T-1",
        tool_name="web_search",
        tool_input="topic",
    )
    bundle = EvidenceBundle(
        subtask_id="T-1",
        summary="Two independent sources",
        records=[
            EvidenceRecord(
                id="r1",
                source_url="https://source-a.example/report",
                snippet="Finding A",
            ),
            EvidenceRecord(
                id="r2",
                source_url="https://source-b.example/report",
                snippet="Finding B",
            ),
        ],
    )
    return gate.consolidate([bundle], [action], iteration=0)


@pytest.mark.asyncio
async def test_clean_batch_skips_llm_and_marks_records_verified() -> None:
    llm = FakeLLM()
    gate = EvidenceQualityGate(llm)
    batch = make_batch(gate)
    evidence = EvidenceBase()
    for bundle in batch:
        evidence.incorporate(bundle)

    result = await gate.validate(
        batch,
        evidence,
        Rubric(
            criteria=[
                Criterion(
                    guidance="sufficient",
                    kind=CriterionKind.SOURCE_CREDIBILITY,
                    status=CriterionStatus.SUFFICIENT,
                )
            ]
        ),
    )

    assert llm.calls == 0
    assert result.passed is True
    assert all(
        record.validation_status == EvidenceStatus.VERIFIED
        for record in evidence.all_records
    )


@pytest.mark.asyncio
async def test_conflict_rubric_triggers_semantic_validation() -> None:
    llm = FakeLLM()
    gate = EvidenceQualityGate(llm)
    batch = make_batch(gate)
    evidence = EvidenceBase()
    for bundle in batch:
        evidence.incorporate(bundle)

    first_id, second_id = [record.id for record in batch[0].records]
    llm.response = EvidenceValidationResult(
        passed=False,
        requires_follow_up=True,
        record_validations=[
            EvidenceRecordValidation(
                record_id=first_id,
                status=EvidenceStatus.DISPUTED,
                notes="Conflicts with the second source.",
            ),
            EvidenceRecordValidation(
                record_id=second_id,
                status=EvidenceStatus.VERIFIED,
                notes="Supported by primary documentation.",
            ),
        ],
        follow_up_guidance=["Find a third independent source."],
    )

    result = await gate.validate(
        batch,
        evidence,
        Rubric(
            criteria=[
                Criterion(
                    guidance="Verify contradictory findings.",
                    kind=CriterionKind.CONFLICT,
                    status=CriterionStatus.OUTSTANDING,
                )
            ]
        ),
    )

    assert llm.calls == 1
    assert result.requires_follow_up is True
    assert evidence.all_records[0].validation_status == EvidenceStatus.DISPUTED
    assert evidence.all_records[1].validation_status == EvidenceStatus.VERIFIED


@pytest.mark.asyncio
async def test_validator_failure_marks_batch_needs_verification() -> None:
    llm = FakeLLM(error=RuntimeError("validator unavailable"))
    gate = EvidenceQualityGate(llm)
    batch = make_batch(gate)
    evidence = EvidenceBase()
    for bundle in batch:
        evidence.incorporate(bundle)

    result = await gate.validate(
        batch,
        evidence,
        Rubric(
            criteria=[
                Criterion(
                    guidance="Verify source conflict.",
                    kind=CriterionKind.CONFLICT,
                    status=CriterionStatus.OUTSTANDING,
                )
            ]
        ),
    )

    assert result.passed is False
    assert result.requires_follow_up is True
    assert result.validator_error == "validator unavailable"
    assert all(
        record.validation_status == EvidenceStatus.NEEDS_VERIFICATION
        for record in evidence.all_records
    )

import pytest

from deep_research.core.writer import Writer
from deep_research.models.evidence import (
    EvidenceBase,
    EvidenceBundle,
    EvidenceRecord,
    EvidenceStatus,
)
from deep_research.models.topic import TaskContext, TopicSpec


class CapturingLLM:
    def __init__(self) -> None:
        self.prompt = ""

    async def generate_long(self, prompt: str, **kwargs) -> str:
        self.prompt = prompt
        return "report"


@pytest.mark.asyncio
async def test_writer_filters_and_labels_evidence_by_status() -> None:
    llm = CapturingLLM()
    writer = Writer(llm)
    evidence = EvidenceBase()
    evidence.incorporate(
        EvidenceBundle(
            bundle_id="batch-1",
            subtask_id="T-1",
            summary="Neutral context",
            records=[
                EvidenceRecord(
                    id="verified",
                    source_url="https://verified.example/report",
                    snippet="Verified claim",
                    validation_status=EvidenceStatus.VERIFIED,
                ),
                EvidenceRecord(
                    id="disputed",
                    source_url="https://disputed.example/report",
                    snippet="Disputed claim",
                    validation_status=EvidenceStatus.DISPUTED,
                    validation_notes=["Conflicting values remain unresolved."],
                ),
            ],
        )
    )

    report = await writer.synthesize_report(
        TaskContext(topic=TopicSpec(core_topic="Test topic")),
        evidence,
    )

    assert report == "report"
    assert "https://verified.example/report" in llm.prompt
    assert "[disputed] https://disputed.example/report" in llm.prompt
    assert "Use only the Verified evidence section" in llm.prompt

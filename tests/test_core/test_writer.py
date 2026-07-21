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
        return "A supported claim [Iter-1, node9]."


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

    assert "[Iter-1, node9]" not in report
    assert "## 参考来源" in report
    assert "[S1: verified.example](https://verified.example/report)" in report
    assert "https://verified.example/report" in llm.prompt
    assert (
        "[disputed] [disputed.example](https://disputed.example/report)"
        in llm.prompt
    )
    assert "Use only the Verified evidence section" in llm.prompt
    assert "batch-1" not in llm.prompt
    assert "T-1" not in llm.prompt
    assert "citation=[S1: verified.example](https://verified.example/report)" in llm.prompt

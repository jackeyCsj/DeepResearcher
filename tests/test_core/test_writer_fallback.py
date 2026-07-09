from deep_research.core.writer import Writer
from deep_research.models.evidence import (
    EvidenceBase,
    EvidenceBundle,
    EvidenceClaim,
    EvidenceRecord,
)
from deep_research.models.topic import Chapter, Outline, TaskContext, TopicSpec


class DummyLLM:
    pass


def _context() -> TaskContext:
    return TaskContext(
        topic=TopicSpec(query="什么是Harness工程", core_topic="Harness工程"),
        outline=Outline(
            title="Harness工程",
            chapters=[
                Chapter(
                    id="1",
                    title="概念定义",
                    description="说明Harness工程是什么。",
                    rubric_guidance="",
                )
            ],
        ),
    )


def test_fallback_report_hides_internal_evidence_dump() -> None:
    evidence = EvidenceBase()
    evidence.incorporate(
        EvidenceBundle(
            subtask_id="t1",
            records=[
                EvidenceRecord(
                    source_url="https://example.com/harness",
                    title="Harness Engineering Guide",
                    summary=(
                        "# Latest commit\n\n"
                        "## Repository files navigation\n\n"
                        "Harness Engineering 指围绕模型构建约束、工具、反馈和执行控制系统。"
                    ),
                    verification_status="single_source_risky",
                    key_claims=[
                        EvidenceClaim(
                            text="Harness Engineering 指围绕大模型构建约束、工具、反馈和执行控制系统。",
                            supporting_quote="围绕大模型构建约束、工具、反馈和执行控制系统",
                            verification_status="single_source_risky",
                        )
                    ],
                )
            ],
        )
    )

    report = Writer(DummyLLM())._fallback_report(_context(), evidence)

    assert "## 核心结论" in report
    assert "Harness Engineering 指围绕大模型构建约束、工具、反馈和执行控制系统" in report
    assert "Source-level evidence" not in report
    assert "Bundle summary" not in report
    assert "  Claims:" not in report
    assert "Supporting quote:" not in report


def test_verified_evidence_pack_is_compact_for_llm_writer() -> None:
    evidence = EvidenceBase()
    evidence.incorporate(
        EvidenceBundle(
            subtask_id="t1",
            summary="raw bundle summary should not be exposed",
            records=[
                EvidenceRecord(
                    source_url="https://example.com/harness",
                    title="Harness Engineering Guide",
                    summary="Harness Engineering 关注执行控制、反馈闭环和可靠性。",
                    verification_status="verified",
                    key_claims=[
                        EvidenceClaim(
                            text="Harness Engineering 关注执行控制、反馈闭环和可靠性。",
                            supporting_quote="执行控制、反馈闭环和可靠性",
                            verification_status="verified",
                        )
                    ],
                )
            ],
        )
    )

    evidence_pack = Writer(DummyLLM())._build_verified_evidence_pack(evidence)

    assert "Harness Engineering 关注执行控制、反馈闭环和可靠性" in evidence_pack
    assert "Bundle summary" not in evidence_pack
    assert "Source-level evidence" not in evidence_pack
    assert "Claims:" not in evidence_pack
    assert "raw bundle summary" not in evidence_pack

import pytest

from deep_research.core.evidence_validator import EvidenceQualityGate
from deep_research.graph.nodes import create_nodes
from deep_research.graph.orchestration_graph import (
    build_orchestration_graph,
    decide_quality_gate,
)
from deep_research.models.actions import ToolCallAction
from deep_research.models.evidence import (
    EvidenceBundle,
    EvidenceRecord,
    EvidenceValidationResult,
)
from deep_research.models.plan import PlanNode, ResearchPlan, SubtaskType
from deep_research.models.rubric import Criterion, CriterionStatus, Rubric
from deep_research.models.state import ResearchState
from deep_research.models.topic import Chapter, Outline, TaskContext, TopicSpec
from deep_research.rubric.stopping import AdaptiveStopping


class FakeLLM:
    async def generate(self, *args, **kwargs):
        raise AssertionError("Clean evidence should not require semantic validation.")


class FakeRouter:
    async def analyze(self, query: str) -> TopicSpec:
        return TopicSpec(query=query, core_topic=query)


class FakePlanner:
    async def init_plan(self, topic, outline) -> ResearchPlan:
        plan = ResearchPlan()
        plan.add_node(
            PlanNode(
                id="T-1",
                subtask_type=SubtaskType.SEARCH,
                title="Collect evidence",
            )
        )
        return plan

    async def select_actions(self, plan, frontier, evidence=None, rubric=None):
        if not frontier:
            return []
        return [
            ToolCallAction(
                id="A-1",
                subtask_id=frontier[0].id,
                tool_name="web_search",
                tool_input="topic",
            )
        ]

    async def replan(self, plan, evidence=None, rubric=None):
        return plan


class FakeExecutor:
    async def execute_parallel(self, actions):
        action = actions[0]
        if action.subtask_id == "coarse":
            return [EvidenceBundle(subtask_id="coarse", summary="Coarse context")]
        return [
            EvidenceBundle(
                subtask_id=action.subtask_id,
                summary="Validated frontier evidence",
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
        ]


class FakeWriter:
    async def generate_outline(self, topic, evidence) -> Outline:
        return Outline(
            title="Test",
            chapters=[
                Chapter(
                    id="1",
                    title="Evidence",
                    rubric_guidance="Use verified sources.",
                )
            ],
        )

    async def synthesize_report(self, context, evidence, persistent_rubric=None):
        return "final report"


class FakeReflection:
    async def evaluate(self, action, plan, evidence, rubric):
        return True, "", None


class FakeRubricGenerator:
    def __init__(self) -> None:
        self.llm = FakeLLM()

    async def init_persistent(self, context) -> Rubric:
        return Rubric()

    async def update_ephemeral(self, outline, evidence) -> Rubric:
        return Rubric(
            criteria=[
                Criterion(
                    guidance="sufficient",
                    status=CriterionStatus.SUFFICIENT,
                )
            ]
        )


@pytest.mark.asyncio
async def test_quality_gate_forces_follow_up_before_max_iteration() -> None:
    rubric_generator = FakeRubricGenerator()
    nodes = create_nodes(
        FakeRouter(),
        FakePlanner(),
        FakeExecutor(),
        FakeWriter(),
        FakeReflection(),
        rubric_generator,
        AdaptiveStopping(),
        EvidenceQualityGate(rubric_generator.llm),
    )
    state = ResearchState(
        transient_validation_result=EvidenceValidationResult(
            passed=False,
            requires_follow_up=True,
        ),
        ephemeral_rubric=Rubric(
            criteria=[
                Criterion(
                    guidance="sufficient",
                    status=CriterionStatus.SUFFICIENT,
                )
            ]
        ),
        iteration=1,
        max_iterations=5,
    )

    update = await nodes["quality_gate"](state)

    assert update["transient_quality_decision"] == "follow_up"
    assert update["stop_flag"] is False
    assert decide_quality_gate(state.model_copy(update=update)) == "follow_up"


@pytest.mark.asyncio
async def test_full_graph_stops_after_clean_quality_gate() -> None:
    rubric_generator = FakeRubricGenerator()
    graph = build_orchestration_graph(
        FakeRouter(),
        FakePlanner(),
        FakeExecutor(),
        FakeWriter(),
        FakeReflection(),
        rubric_generator,
        AdaptiveStopping(),
        evidence_quality_gate=EvidenceQualityGate(rubric_generator.llm),
    )

    result = await graph.ainvoke(
        ResearchState(
            context=TaskContext(topic=TopicSpec(query="Test topic")),
            max_iterations=3,
        ),
        {"recursion_limit": 40},
    )
    final_state = ResearchState.model_validate(result)

    assert final_state.final_report == "final report"
    assert final_state.validation_history[-1].quality_decision == "stop"
    assert all(
        record.validation_status.value == "verified"
        for record in final_state.evidence_base.all_records
        if record.subtask_id == "T-1"
    )

import pytest

from deep_research.core.planner import GraphPlanner, ReplanDecision
from deep_research.models.plan import Edge, PlanNode, ResearchPlan, SubtaskType


class FailingLLM:
    default_output_tokens = 8192

    async def generate(self, *args, **kwargs):
        raise ValueError("truncated structured response")


class DeltaLLM:
    default_output_tokens = 8192

    async def generate(self, *args, **kwargs):
        return ReplanDecision(
            needs_replan=True,
            new_nodes=[
                PlanNode(
                    id=f"follow-up-{index}",
                    subtask_type=SubtaskType.SEARCH_AGENT,
                    title=f"Follow-up {index}",
                    description=(
                        "下载并提取以下URL全文 "
                        f"https://example.com/source/{index} "
                        "完成后重新运行验证批次以更新证据记录"
                    ),
                    depth=2,
                )
                for index in range(5)
            ],
            new_edges=[
                Edge(source_id="root", target_id=f"follow-up-{index}")
                for index in range(5)
            ],
        )


def _base_plan() -> ResearchPlan:
    plan = ResearchPlan()
    plan.add_node(
        PlanNode(
            id="root",
            subtask_type=SubtaskType.SEARCH_AGENT,
            title="Initial research",
            executed=True,
        )
    )
    plan.add_node(
        PlanNode(
            id="report",
            subtask_type=SubtaskType.REPORT,
            title="Final report",
            depth=3,
        )
    )
    plan.add_edge("root", "report")
    return plan


@pytest.mark.asyncio
async def test_replan_parse_failure_keeps_current_plan() -> None:
    plan = _base_plan()
    planner = GraphPlanner(FailingLLM())

    result = await planner.replan(plan)

    assert result is plan
    assert set(result.nodes) == {"root", "report"}


@pytest.mark.asyncio
async def test_replan_applies_only_small_sanitized_delta() -> None:
    planner = GraphPlanner(DeltaLLM())

    result = await planner.replan(_base_plan())

    follow_ups = [
        node for node in result.nodes.values() if node.id.startswith("follow-up-")
    ]
    assert len(follow_ups) == 3
    assert all("http" not in node.description for node in follow_ups)
    assert all(len(node.description) <= 350 for node in follow_ups)
    assert len([node for node in result.nodes.values() if node.subtask_type == SubtaskType.REPORT]) == 1


def test_search_query_sanitizer_removes_url_lists() -> None:
    planner = GraphPlanner(FailingLLM())
    query = (
        "下载并提取以下URL全文: "
        "https://example.com/a, https://example.org/b, "
        "完成后重新运行验证批次以更新证据记录"
    )

    sanitized = planner._sanitize_search_query(query)

    assert "http" not in sanitized
    assert "example.com" in sanitized
    assert len(sanitized) <= 350


def test_planner_does_not_emit_report_as_execution_action() -> None:
    planner = GraphPlanner(FailingLLM())

    actions = planner._parse_actions(
        [
            {
                "id": "report",
                "type": "writer_report",
                "subtask_id": "report",
                "description": "Write final report",
            }
        ]
    )

    assert actions == []

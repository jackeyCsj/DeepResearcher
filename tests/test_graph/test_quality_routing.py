import pytest

pytest.importorskip("langgraph")
pytest.importorskip("pydantic_settings")

from deep_research.graph.orchestration_graph import decide_adaptive_stop, decide_stop_or_continue
from deep_research.models.state import ResearchState


def test_planner_stop_is_blocked_when_quality_gate_failed() -> None:
    state = ResearchState(stop_flag=True, quality_gate_passed=False)

    assert decide_stop_or_continue(state) == "execute"


def test_planner_stop_allowed_when_quality_gate_passed() -> None:
    state = ResearchState(stop_flag=True, quality_gate_passed=True)

    assert decide_stop_or_continue(state) == "stop"


def test_adaptive_stop_is_blocked_when_quality_gate_failed() -> None:
    state = ResearchState(stop_flag=True, quality_gate_passed=False, iteration=99, max_iterations=1)

    assert decide_adaptive_stop(state) == "continue"


def test_adaptive_stop_allowed_when_quality_gate_passed() -> None:
    state = ResearchState(stop_flag=True, quality_gate_passed=True)

    assert decide_adaptive_stop(state) == "stop"

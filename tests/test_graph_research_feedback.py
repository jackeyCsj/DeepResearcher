from client.graph.graph_builder import _build_research_feedback
from client.graph.graph_builder import build_graph


def test_replan_feedback_includes_revise_issues_and_missing_dimensions():
    feedback = _build_research_feedback(
        {
            "note_reviews": [
                {
                    "verdict": "revise",
                    "relevance": "The note missed the policy dimension.",
                    "completeness": "No regional comparison was supported with data.",
                },
                {"verdict": "approved", "relevance": "Covered."},
                {"verdict": "retry", "depth": "Needs more evidence."},
            ],
            "missing_dimensions": "Compare regulations across regions.",
        }
    )

    assert "The note missed the policy dimension." in feedback
    assert "No regional comparison was supported with data." in feedback
    assert "Compare regulations across regions." in feedback
    assert "Covered." not in feedback
    assert "Needs more evidence." not in feedback


def test_initial_plan_has_no_research_feedback():
    assert _build_research_feedback(None) == ""
    assert _build_research_feedback({"note_reviews": [], "missing_dimensions": ""}) == ""


def test_empty_supervisor_plan_fails_instead_of_writing_unsupported_report():
    import pytest

    class Supervisor:
        def plan(self, **_kwargs):
            return []

    class Writer:
        def run(self, **_kwargs):
            return "# Empty evidence\n\nNo findings were available."

    class Pipeline:
        def add_text(self, **_kwargs):
            return {"file_id": "empty-report.md"}

    graph = build_graph(Supervisor(), lambda _name: None, Writer(), Pipeline())

    with pytest.raises(ValueError, match="empty research plan"):
        graph.invoke({"research_brief": "A focused question", "user_id": "user-1"})

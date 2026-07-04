"""LangGraph orchestration graph for the outer research loop (Algorithm 1).

This is the central state machine that implements:
1. Router → Coarse search → Outline generation → Init plan → Init rubric
2. Loop: Compute frontier → Select actions → Reflect → Execute → Update evidence → Update rubric → Replan
3. Final: Synthesize report

Node topology:
    router → coarse_search → generate_outline → init_plan → init_rubric
                                                              |
                                                              v
                                                    compute_frontier
                                                              |
                                                              v
                                                    planner_actions
                                                    /           \
                                               stop?          actions
                                                  |              |
                                                  v              v
                                          final_synthesis  reflection_gate
                                                  |         /     |     \
                                                 END    pass  revise  fail
                                                           |     |       |
                                                           v     v       v
                                                    execute_parallel     |
                                                           |             |
                                                           v             |
                                                    update_evidence      |
                                                           |             |
                                                           v             |
                                                     update_rubric ------+
                                                    /          \
                                               stop?        continue
                                                  |              |
                                                  v              v
                                          final_synthesis    replan
                                                  |              |
                                                 END             v
                                                          compute_frontier (loop)
"""

from __future__ import annotations
import logging
from typing import Any, Dict, Optional

from langgraph.graph import END, StateGraph

from deep_research.models.state import ResearchState
from deep_research.models.actions import ActionType, BaseAction
from deep_research.graph.nodes import create_nodes
from deep_research.core.router import Router
from deep_research.core.planner import GraphPlanner
from deep_research.core.executor import ExecutionModule
from deep_research.core.writer import Writer
from deep_research.core.reflection import ReflectionGate
from deep_research.rubric.generator import RubricGenerator
from deep_research.rubric.stopping import AdaptiveStopping
from deep_research.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def decide_stop_or_continue(state: ResearchState) -> str:
    """After planner_actions: stop if no actions or stop_flag is set."""
    if state.stop_flag:
        return "stop"
    return "reflect"


def decide_reflection_pass_or_revise(state: ResearchState) -> str:
    """After reflection_gate: pass through, revise, or execute after failures.

    Returns one of: "pass", "revise", "fail_after_revisions"
    """
    passed = getattr(state, "transient_reflection_passed", True)
    if passed:
        return "pass"

    # Check if any action still has revision budget
    for action in getattr(state, "transient_actions", []):
        if action.revision_count < action.max_revisions:
            return "revise"

    return "fail_after_revisions"


def decide_adaptive_stop(state: ResearchState) -> str:
    """After update_rubric: stop if rubric says no gaps or max iterations reached."""
    if state.stop_flag:
        return "stop"
    if state.iteration >= state.max_iterations:
        return "stop"
    return "continue"


def build_orchestration_graph(
    router: Router,
    planner: GraphPlanner,
    executor: ExecutionModule,
    writer: Writer,
    reflection_gate: ReflectionGate,
    rubric_generator: RubricGenerator,
    stopping: AdaptiveStopping,
) -> StateGraph:
    """Build the LangGraph StateGraph for the outer research loop (Algorithm 1).

    Args:
        router: Task understanding module.
        planner: Graph-based dynamic planner.
        executor: Action execution module.
        writer: Report writer.
        reflection_gate: Quality checkpoint.
        rubric_generator: Dynamic rubric generation.
        stopping: Adaptive stopping criterion.

    Returns:
        A compiled StateGraph ready for execution.
    """
    nodes = create_nodes(
        router, planner, executor, writer, reflection_gate, rubric_generator, stopping
    )

    workflow = StateGraph(ResearchState)

    # Register all nodes
    for name, func in nodes.items():
        workflow.add_node(name, func)

    # Define the graph topology
    workflow.set_entry_point("router")

    # Initial pipeline
    workflow.add_edge("router", "coarse_search")
    workflow.add_edge("coarse_search", "generate_outline")
    workflow.add_edge("generate_outline", "init_plan")
    workflow.add_edge("init_plan", "init_rubric")
    workflow.add_edge("init_rubric", "compute_frontier")

    # Main research loop
    workflow.add_edge("compute_frontier", "planner_actions")

    # After planner_actions: stop or continue to reflection
    workflow.add_conditional_edges(
        "planner_actions",
        decide_stop_or_continue,
        {
            "stop": "final_synthesis",
            "reflect": "reflection_gate",
        },
    )

    # After reflection_gate: pass → execute, revise → back to planner, fail → execute anyway
    workflow.add_conditional_edges(
        "reflection_gate",
        decide_reflection_pass_or_revise,
        {
            "pass": "execute_parallel",
            "revise": "planner_actions",
            "fail_after_revisions": "execute_parallel",
        },
    )

    # Execution → evidence update
    workflow.add_edge("execute_parallel", "update_evidence")
    workflow.add_edge("update_evidence", "update_rubric")

    # After update_rubric: stop or continue the loop
    workflow.add_conditional_edges(
        "update_rubric",
        decide_adaptive_stop,
        {
            "stop": "final_synthesis",
            "continue": "replan",
        },
    )

    # Replan → back to frontier (loop continuation)
    workflow.add_edge("replan", "compute_frontier")

    # Final synthesis → END
    workflow.add_edge("final_synthesis", END)

    compiled = workflow.compile()
    return compiled

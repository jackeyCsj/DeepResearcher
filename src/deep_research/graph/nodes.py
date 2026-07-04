"""Node functions for the LangGraph orchestration graph.

Each function corresponds to a node in the StateGraph.
They follow the pattern: async def node(state: ResearchState) -> dict
where the returned dict is merged into the state.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List

from deep_research.models.state import ResearchState
from deep_research.models.topic import TaskContext
from deep_research.models.evidence import EvidenceBase, EvidenceBundle
from deep_research.models.rubric import RubricSignal
from deep_research.models.actions import (
    BaseAction,
    ToolCallAction,
    ActionType,
    ActionRecord,
)
from deep_research.core.router import Router
from deep_research.core.planner import GraphPlanner
from deep_research.core.executor import ExecutionModule
from deep_research.core.writer import Writer
from deep_research.core.reflection import ReflectionGate
from deep_research.rubric.generator import RubricGenerator
from deep_research.rubric.stopping import AdaptiveStopping
from deep_research.config import config

logger = logging.getLogger(__name__)


def create_nodes(
    router: Router,
    planner: GraphPlanner,
    executor: ExecutionModule,
    writer: Writer,
    reflection_gate: ReflectionGate,
    rubric_generator: RubricGenerator,
    stopping: AdaptiveStopping,
) -> Dict[str, Any]:
    """Factory to create all node functions with injected dependencies."""

    async def router_node(state: ResearchState) -> dict:
        """Router: task understanding and analysis."""
        logger.info("Router: analyzing query")
        topic = await router.analyze(state.context.topic.query)
        return {"context": TaskContext(topic=topic, outline=state.context.outline)}

    async def coarse_search_node(state: ResearchState) -> dict:
        """Coarse exploratory retrieval phase to map research boundaries."""
        logger.info("Coarse search: mapping research boundaries")
        core_topic = state.context.topic.core_topic or state.context.topic.query
        coarse_action = ToolCallAction(
            id="coarse-1",
            type=ActionType.TOOL_CALL,
            subtask_id="coarse",
            description=f"Initial broad search for: {core_topic}",
            tool_name="web_search",
            tool_input=core_topic,
            tool_params={"max_results": 5},
        )
        bundles = await executor.execute_parallel([coarse_action])
        evidence_base = EvidenceBase()
        for b in bundles:
            evidence_base.incorporate(b)
        return {"evidence_base": evidence_base}

    async def outline_node(state: ResearchState) -> dict:
        """Generate the fixed outline O from coarse exploration evidence."""
        logger.info("Writer: generating outline")
        outline = await writer.generate_outline(state.context.topic, state.evidence_base)
        return {"context": TaskContext(topic=state.context.topic, outline=outline)}

    async def init_plan_node(state: ResearchState) -> dict:
        """Build initial DAG plan p_0 from topic and outline."""
        logger.info("Planner: initializing research plan")
        plan = await planner.init_plan(state.context.topic, state.context.outline)
        return {"plan": plan}

    async def init_rubric_node(state: ResearchState) -> dict:
        """Generate initial persistent rubric ρ_p."""
        logger.info("Rubric: generating persistent criteria")
        persistent = await rubric_generator.init_persistent(state.context)
        return {"persistent_rubric": persistent}

    async def frontier_node(state: ResearchState) -> dict:
        """Compute the ready frontier F_t (pure computation, no LLM call)."""
        frontier = state.plan.ready_frontier()
        logger.info(f"Frontier: {len(frontier)} ready subtasks")
        return {"transient_frontier": frontier}

    async def planner_action_node(state: ResearchState) -> dict:
        """Planner selects next actions from the ready frontier."""
        rubric_signal = RubricSignal(
            persistent=state.persistent_rubric,
            ephemeral=state.ephemeral_rubric,
        )
        actions = await planner.select_actions(
            state.plan,
            frontier=state.transient_frontier,
            evidence=state.evidence_base,
            rubric=rubric_signal,
        )

        # Determine if we should stop
        should_stop = False
        if not actions:
            should_stop = True
        elif any(a.type == ActionType.WRITER_REPORT for a in actions):
            should_stop = True

        logger.info(f"Planner: selected {len(actions)} actions (stop={should_stop})")
        return {"transient_actions": actions, "stop_flag": should_stop}

    async def reflection_node(state: ResearchState) -> dict:
        """Reflection gate: quality check before execution."""
        if not state.transient_actions:
            return {}

        rubric_signal = RubricSignal(
            persistent=state.persistent_rubric,
            ephemeral=state.ephemeral_rubric,
        )
        all_passed = True
        revised_actions: List[BaseAction] = []

        for action in state.transient_actions:
            passed, feedback, revised = await reflection_gate.evaluate(
                action, state.plan, state.evidence_base, rubric_signal
            )
            if passed:
                revised_actions.append(action)
            elif revised and action.revision_count < action.max_revisions:
                logger.info(f"Action {action.id} revised (attempt {revised.revision_count})")
                revised_actions.append(revised)
                all_passed = False
            else:
                revised_actions.append(action)

        logger.info(f"Reflection: {'all passed' if all_passed else 'some revised'}")
        return {"transient_actions": revised_actions, "transient_reflection_passed": all_passed}

    async def execution_node(state: ResearchState) -> dict:
        """Execute all approved actions in parallel."""
        if not state.transient_actions:
            return {"transient_new_bundles": []}

        logger.info(f"Executor: running {len(state._actions)} action(s)")
        bundles = await executor.execute_parallel(state.transient_actions)
        return {"transient_new_bundles": bundles}

    async def evidence_update_node(state: ResearchState) -> dict:
        """Fold new evidence into global evidence base e_{t+1} = e_t ∪ Δe_t."""
        if not state.transient_new_bundles:
            return {}

        for bundle in state.transient_new_bundles:
            state.evidence_base.incorporate(bundle)

        # Mark corresponding nodes as executed
        for action in state.transient_actions:
            if action.subtask_id in state.plan.nodes:
                node = state.plan.nodes[action.subtask_id]
                node.executed = True
                # Find matching bundle for result summary
                matching = [b for b in state.transient_new_bundles if b.subtask_id == action.subtask_id]
                if matching:
                    node.result_summary = matching[0].summary

        logger.info(f"Evidence: {len(state.transient_new_bundles)} bundle(s) incorporated")
        return {"evidence_base": state.evidence_base, "plan": state.plan}

    async def rubric_update_node(state: ResearchState) -> dict:
        """Update ephemeral rubric ρ^e_{t+1} = G_e(O, e_{t+1})."""
        ephemeral = await rubric_generator.update_ephemeral(
            state.context.outline, state.evidence_base
        )
        has_gaps = ephemeral.has_outstanding_gap()
        logger.info(f"Rubric update: {'gaps remain' if has_gaps else 'no gaps'}")

        # Also check adaptive stopping
        should_stop = stopping.should_stop(
            ephemeral, state.iteration, state.max_iterations
        )

        return {
            "ephemeral_rubric": ephemeral,
            "stop_flag": state.stop_flag or should_stop,
        }

    async def replan_node(state: ResearchState) -> dict:
        """Apply re-planning operator Π(p_t, e_{t+1}, ρ_{t+1})."""
        rubric_signal = RubricSignal(
            persistent=state.persistent_rubric,
            ephemeral=state.ephemeral_rubric,
        )
        updated_plan = await planner.replan(
            state.plan,
            evidence=state.evidence_base,
            rubric=rubric_signal,
        )
        logger.info(f"Replan: {len(updated_plan.nodes)} nodes, {len(updated_plan.edges)} edges")
        return {"plan": updated_plan, "iteration": state.iteration + 1}

    async def synthesis_node(state: ResearchState) -> dict:
        """Writer generates final report y = W(x, O, e_t, ρ_p)."""
        logger.info("Writer: synthesizing final report")
        report = await writer.synthesize_report(
            state.context, state.evidence_base, state.persistent_rubric
        )
        return {"final_report": report}

    return {
        "router": router_node,
        "coarse_search": coarse_search_node,
        "generate_outline": outline_node,
        "init_plan": init_plan_node,
        "init_rubric": init_rubric_node,
        "compute_frontier": frontier_node,
        "planner_actions": planner_action_node,
        "reflection_gate": reflection_node,
        "execute_parallel": execution_node,
        "update_evidence": evidence_update_node,
        "update_rubric": rubric_update_node,
        "replan": replan_node,
        "final_synthesis": synthesis_node,
    }

"""Graph-based dynamic planner implementing Algorithm 2 from the paper.

Maintains the DAG plan p_t = (V_t, E_t), computes the ready frontier F_t,
selects parallel actions, and applies the re-planning operator Π.

Key operations:
- init_plan: Build initial DAG p_0 from topic and outline (coarse-to-fine)
- select_actions: Choose next parallel actions from the ready frontier
- replan: Apply Π(p_t, e_{t+1}, ρ_{t+1}) to expand, prune, or rewire
"""

from __future__ import annotations
import json
import logging
from typing import Dict, List, Optional, Any

from deep_research.models.topic import TopicSpec, Outline
from deep_research.models.plan import ResearchPlan, PlanNode, SubtaskType
from deep_research.models.evidence import EvidenceBase
from deep_research.models.rubric import RubricSignal, Rubric
from deep_research.models.actions import (
    BaseAction,
    ToolCallAction,
    SearchAgentAction,
    LLMReasoningAction,
    ActionType,
)
from deep_research.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """You are a deep research planning expert. Given a research topic,
outline, current plan, execution results, and active rubric, you must maintain a complete,
executable, dynamically updatable research plan as a DAG of subtasks.

Core responsibilities:
1. Design a complete research plan covering all outline chapters
2. Evaluate execution results and decide whether the plan needs updating
3. Ensure task coverage is sufficient, depth is adequate, dependencies are valid
4. Output the next set of parallel-executable actions

DAG constraints:
- Each node has: id, type (search/llm/search_agent/report), depth d(v), dependencies
- Edges encode dependencies (v depends on u → must execute u first)
- Depth-1 nodes are broad exploratory tasks (parallel)
- Deeper nodes are finer-grained investigations
- Only one report node, placed at the final stage
- No cycles allowed

Replanning triggers (only when necessary):
1. Executed task failed or produced invalid results
2. Key chapters not yet covered by any task
3. Collected information insufficient for depth requirements
4. Information conflicts requiring verification tasks
5. New valuable information gaps discovered
6. User requirements changed

When no replanning is needed, reuse existing unexecuted tasks."""


class GraphPlanner:
    """Graph-based dynamic planner.

    Implements the planning component of Algorithm 2:
    - Maintains DAG plan p_t
    - Computes ready frontier F_t
    - Selects parallel actions a_t
    - Applies re-planning operator Π
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm = llm_client

    async def init_plan(self, topic: TopicSpec, outline: Outline) -> ResearchPlan:
        """Build initial DAG plan p_0 from (x, O).

        Coarse-to-fine: starts with depth-1 exploratory searches for each outline chapter,
        then deeper tasks for detailed investigation.

        Args:
            topic: The structured topic specification.
            outline: The report outline with chapters.

        Returns:
            Initial ResearchPlan with coarse phase tasks.
        """
        if not outline.chapters:
            # If no outline yet, create a simple plan
            plan = ResearchPlan()
            plan.add_node(
                PlanNode(
                    id="T-1",
                    subtask_type=SubtaskType.SEARCH,
                    title="Initial broad search",
                    description=f"Explore: {topic.core_topic}",
                    depth=1,
                )
            )
            plan.add_node(
                PlanNode(
                    id="T-2",
                    subtask_type=SubtaskType.OUTLINE,
                    title="Generate outline",
                    description="Generate report outline from initial search",
                    depth=2,
                )
            )
            plan.add_edge("T-1", "T-2")
            plan.add_node(
                PlanNode(
                    id="T-3",
                    subtask_type=SubtaskType.REPORT,
                    title="Generate report",
                    description="Synthesize final report",
                    depth=3,
                )
            )
            plan.add_edge("T-2", "T-3")
            return plan

        chapter_titles = [ch.title for ch in outline.chapters]
        prompt = f"""Research topic: {topic.core_topic}
Sub-questions: {topic.sub_questions}
Outline chapters: {chapter_titles}

Design an initial research plan DAG with the following structure:
1. Depth-1: One parallel search/search_agent task per outline chapter (broad exploration)
2. Depth-2: LLM tasks for cross-validation and integration
3. Depth-3: Gap-filling searches (if needed)
4. Depth-N: One report task (final stage)

Output a ResearchPlan with nodes and edges.
Each search node should be type "search_agent" for complex topics.
"""
        response = await self.llm.generate(prompt, response_model=ResearchPlan, system_prompt=PLANNER_SYSTEM_PROMPT)
        return response

    async def select_actions(
        self,
        plan: ResearchPlan,
        frontier: Optional[List[PlanNode]] = None,
        evidence: Optional[EvidenceBase] = None,
        rubric: Optional[RubricSignal] = None,
    ) -> List[BaseAction]:
        """Given the ready frontier F_t, select parallel actions.

        Returns a list of actions to execute in parallel.
        Returns an empty list to signal stopping.

        Args:
            plan: The current research plan.
            frontier: The ready frontier F_t (computed if not provided).
            evidence: Accumulated evidence (optional).
            rubric: Active rubric signal (optional).

        Returns:
            List of BaseAction to execute in parallel.
        """
        if frontier is None:
            frontier = plan.ready_frontier()

        if not frontier:
            return []

        # Build prompt for the planner to choose actions
        frontier_desc = "\n".join(
            f"  {n.id}: [{n.subtask_type.value}] {n.title} (depth={n.depth})"
            for n in frontier
        )

        rubric_text = ""
        if rubric:
            rubric_text = "\n".join(
                f"- {c.name}: {c.guidance}" for c in rubric.active().criteria
            )

        prompt = f"""Current ready frontier (F_t) of available subtasks:
{frontier_desc}

{"Active rubric:" + rubric_text if rubric_text else "No active rubric."}

Select which subtasks to execute in this parallel batch.
Rules:
1. Prefer subtasks with smallest depth first (coarse before fine)
2. Independent subtasks can execute in parallel
3. Each action's type must match its subtask_type
4. For search/search_agent types: provide specific search queries
5. For llm types: provide specific reasoning instructions
6. Return an empty list if no action should be taken

Return a JSON list of actions, each with: id, type, subtask_id, description, params.
"""
        response = await self.llm.generate(prompt, system_prompt=PLANNER_SYSTEM_PROMPT)

        try:
            raw_actions = response if isinstance(response, list) else json.loads(response)
            return self._parse_actions(raw_actions)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Failed to parse planner actions: {e}")
            return []

    async def replan(
        self,
        plan: ResearchPlan,
        evidence: Optional[EvidenceBase] = None,
        rubric: Optional[RubricSignal] = None,
    ) -> ResearchPlan:
        """Apply re-planning operator Π(p_t, e_{t+1}, ρ_{t+1}).

        May perform:
        - Expand frontier with finer subtasks (coarse-to-fine)
        - Prune dead branches (backtrack from dead ends)
        - Rewire dependencies

        Preserves executed nodes (χ(v)=1 is monotone — no evidence is recomputed).

        Args:
            plan: The current plan p_t.
            evidence: The updated evidence base e_{t+1}.
            rubric: The updated guidance signal ρ_{t+1}.

        Returns:
            Updated ResearchPlan p_{t+1}.
        """
        executed_summary = "\n".join(
            f"  {nid}: {n.title} — {'✓ Done' if n.executed else '☐ Pending'} — {n.result_summary or ''}"
            for nid, n in sorted(plan.nodes.items())
        )

        frontier = plan.ready_frontier()
        frontier_desc = "\n".join(
            f"  {n.id}: [{n.subtask_type.value}] {n.title} (depth={n.depth})"
            for n in frontier
        )

        rubric_text = ""
        if rubric:
            rubric_text = "\n".join(
                f"- {c.name}: {c.guidance}" for c in rubric.active().criteria
            )

        prompt = f"""Current research plan state:
Nodes:
{executed_summary}

Ready frontier:
{frontier_desc}

{"Active rubric:" + rubric_text if rubric_text else "No active rubric."}

Evaluate if the plan needs updating:

Replanning triggers:
1. Executed task failed or produced invalid results
2. Key chapters not yet covered
3. Collected information insufficient for chapter depth
4. Information conflicts requiring verification
5. New valuable information gaps discovered

If NO replanning is needed: return the plan unchanged.
If replanning IS needed: add new search/llm tasks, prune dead branches, adjust dependencies.

Output a ResearchPlan (the complete plan, including all existing and new nodes).
Preserve all executed nodes (executed=true)."""
        response = await self.llm.generate(prompt, response_model=ResearchPlan, system_prompt=PLANNER_SYSTEM_PROMPT)

        # Preserve execution status for existing nodes
        for nid, node in response.nodes.items():
            if nid in plan.nodes:
                node.executed = plan.nodes[nid].executed
                node.result_summary = plan.nodes[nid].result_summary

        return response

    def _parse_actions(self, raw_actions: List[Dict[str, Any]]) -> List[BaseAction]:
        """Parse raw action dicts into BaseAction objects."""
        actions: List[BaseAction] = []
        for raw in raw_actions:
            atype = raw.get("type", "")
            stype = raw.get("subtask_type", "")
            try:
                action_type = ActionType(atype if atype else stype)
            except ValueError:
                continue

            base = BaseAction(
                id=raw.get("id", ""),
                type=action_type,
                subtask_id=raw.get("subtask_id", raw.get("id", "")),
                description=raw.get("description", raw.get("title", "")),
                params=raw.get("params", {}),
            )

            if action_type == ActionType.TOOL_CALL:
                base = ToolCallAction(
                    **base.model_dump(),
                    tool_name=raw.get("tool_name", "web_search"),
                    tool_input=raw.get("tool_input", raw.get("description", "")),
                )
            elif action_type == ActionType.SEARCH_AGENT:
                base = SearchAgentAction(
                    **base.model_dump(),
                    sub_query=raw.get("sub_query", raw.get("description", "")),
                )
            elif action_type == ActionType.LLM_REASONING:
                base = LLMReasoningAction(
                    **base.model_dump(),
                    instruction=raw.get("instruction", raw.get("description", "")),
                )

            actions.append(base)

        return actions

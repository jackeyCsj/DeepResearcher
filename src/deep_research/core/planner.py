"""基于图的动态规划器，对应论文 Algorithm 2。

它维护 DAG 计划 p_t = (V_t, E_t)，计算 ready frontier F_t，
选择可并行执行的动作，并在每轮证据更新后应用重规划算子 Π。

核心操作：
- init_plan：根据主题和大纲生成初始 DAG p_0，体现粗到细规划。
- select_actions：从 ready frontier 中选择下一批并行动作。
- replan：根据新证据和 Rubric 扩展、剪枝或重连 DAG。
"""

from __future__ import annotations
import json
import logging
from typing import Dict, List, Optional, Any

from pydantic import BaseModel, Field, ValidationError

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


class ActionSpec(BaseModel):
    """LLM 用于选择本轮执行动作的轻量结构化输出。"""

    id: str = ""
    type: str = ""
    subtask_id: str = ""
    description: str = ""
    params: Dict[str, Any] = Field(default_factory=dict)
    tool_name: str = ""
    tool_input: str = ""
    sub_query: str = ""
    instruction: str = ""


class ActionList(BaseModel):
    """DeepSeek json_object 模式要求顶层是对象，因此用 actions 包住列表。"""

    actions: List[ActionSpec] = Field(default_factory=list)

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

    When no replanning is needed, reuse existing unexecuted tasks.

"""


class GraphPlanner:
    """基于 DAG 的动态规划器。

    对应 Algorithm 2 的规划组件：
    - 维护 DAG 计划 p_t。
    - 计算可执行前沿 F_t。
    - 选择并行动作 a_t。
    - 应用重规划算子 Π。
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm = llm_client

    async def init_plan(self, topic: TopicSpec, outline: Outline) -> ResearchPlan:
        """根据主题 x 和大纲 O 生成初始 DAG 计划 p_0。

        粗到细策略：先为每个大纲章节创建 depth-1 探索任务，
        再通过后续 replan 扩展出更细粒度调查任务。

        Args:
            topic: Router 生成的结构化主题规格。
            outline: Writer 生成的报告大纲。

        Returns:
            包含粗粒度阶段任务的初始 ResearchPlan。
        """
        if not outline.chapters:
            return self._fallback_initial_plan(topic, outline)

        prompt = self._build_init_plan_prompt(topic, outline)
        try:
            response = await self.llm.generate(
                prompt,
                response_model=ResearchPlan,
                system_prompt=PLANNER_SYSTEM_PROMPT,
                max_tokens=max(self.llm.default_output_tokens, 8192),
            )
            return response
        except (ValidationError, ValueError, json.JSONDecodeError) as e:
            logger.warning("Failed to initialize LLM research plan; using fallback DAG: %s", e)
            return self._fallback_initial_plan(topic, outline)

    def _build_init_plan_prompt(self, topic: TopicSpec, outline: Outline) -> str:
        """构造初始化 ResearchPlan 的提示词，便于主流程和诊断脚本复用。"""
        chapter_titles = [ch.title for ch in outline.chapters]
        return f"""Research topic: {topic.core_topic}
            Sub-questions: {topic.sub_questions}
            Outline chapters: {chapter_titles}

            Design a compact initial research plan DAG with this structure:
            1. Depth-1: At most one search_agent task per outline chapter.
            2. Depth-2: One llm task for cross-validation and integration.
            3. Depth-3: One report task for final synthesis.

            Output a ResearchPlan with nodes and edges.
            Preserve the topic time scope in task titles/descriptions and search tasks.
            Keep descriptions short. Prefer 4-8 nodes total, and never more than 10 nodes.
            Each search node should be type "search_agent" for complex topics.
        """

    async def select_actions(
        self,
        plan: ResearchPlan,
        frontier: Optional[List[PlanNode]] = None,
        evidence: Optional[EvidenceBase] = None,
        rubric: Optional[RubricSignal] = None,
    ) -> List[BaseAction]:
        """给定 ready frontier F_t，选择本轮可并行执行的动作。

        返回空列表表示当前没有可执行动作，外层图会据此进入停止/写作分支。

        Args:
            plan: 当前研究计划。
            frontier: ready frontier F_t；未提供时现场计算。
            evidence: 累计证据库，可选。
            rubric: 当前生效的 RubricSignal，可选。

        Returns:
            本轮要并行执行的 BaseAction 列表。
        """
        if frontier is None:
            frontier = plan.ready_frontier()

        if not frontier:
            return []

        # 将前沿节点和 Rubric 压缩成 Planner 可消费的上下文。
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
            6. Return no actions only when all useful research is complete
            7. For every search_agent action, sub_query must preserve the task time scope.
               If the research scope includes "2025年至今", include explicit time terms such as
               "2025", "2026", "2026年7月", or "2025年至2026年7月" in the sub_query.
            8. For current-market research, include freshness terms such as "最新", "current",
               or "2026" when useful so search tools retrieve up-to-date sources.

            Return an ActionList JSON object:
            {{
              "actions": [
                {{
                  "id": "act-<subtask_id>",
                  "type": "search_agent | llm | writer_report",
                  "subtask_id": "<frontier node id>",
                  "description": "short executable action description",
                  "sub_query": "specific search query for search_agent",
                  "instruction": "specific reasoning instruction for llm",
                  "params": {{}}
                }}
              ]
            }}
        """
        try:
            response = await self.llm.generate(
                prompt,
                response_model=ActionList,
                system_prompt=PLANNER_SYSTEM_PROMPT,
                max_tokens=max(self.llm.default_output_tokens, 4096),
            )
            actions = self._parse_actions([a.model_dump() for a in response.actions])
            return self._ensure_search_action_time_terms(actions)
        except (ValidationError, ValueError, json.JSONDecodeError, TypeError) as e:
            logger.warning("Failed to parse structured planner actions; using frontier fallback: %s", e)
            return self._fallback_actions_from_frontier(frontier)

    def _fallback_actions_from_frontier(self, frontier: List[PlanNode]) -> List[BaseAction]:
        """结构化动作选择失败时，按节点类型确定性生成动作，避免误判停止。"""
        actions: List[BaseAction] = []
        for node in frontier:
            action_id = f"act-{node.id}"
            if node.subtask_type == SubtaskType.SEARCH_AGENT:
                sub_query = self._fallback_search_query(node)
                actions.append(
                    SearchAgentAction(
                        id=action_id,
                        type=ActionType.SEARCH_AGENT,
                        subtask_id=node.id,
                        description=node.description or node.title,
                        sub_query=sub_query,
                    )
                )
            elif node.subtask_type == SubtaskType.SEARCH:
                tool_input = self._fallback_search_query(node)
                actions.append(
                    ToolCallAction(
                        id=action_id,
                        type=ActionType.TOOL_CALL,
                        subtask_id=node.id,
                        description=node.description or node.title,
                        tool_name="web_search",
                        tool_input=tool_input,
                        tool_params={"max_results": 5},
                    )
                )
            elif node.subtask_type == SubtaskType.LLM:
                actions.append(
                    LLMReasoningAction(
                        id=action_id,
                        type=ActionType.LLM_REASONING,
                        subtask_id=node.id,
                        description=node.description or node.title,
                        instruction=node.description or node.title,
                    )
                )
            elif node.subtask_type == SubtaskType.REPORT:
                actions.append(
                    BaseAction(
                        id=action_id,
                        type=ActionType.WRITER_REPORT,
                        subtask_id=node.id,
                        description=node.description or node.title,
                    )
                )
        return actions

    def _ensure_search_action_time_terms(self, actions: List[BaseAction]) -> List[BaseAction]:
        """确保模型生成的搜索动作保留显式时间范围。"""
        for action in actions:
            if isinstance(action, SearchAgentAction):
                action.sub_query = self._append_time_terms(action.sub_query or action.description)
            elif isinstance(action, ToolCallAction):
                action.tool_input = self._append_time_terms(action.tool_input or action.description)
        return actions

    def _fallback_search_query(self, node: PlanNode) -> str:
        """为 fallback 搜索动作补充明确时间词，避免“至今/当前”被搜索引擎弱化。"""
        base_query = node.description or node.title
        return self._append_time_terms(base_query)

    def _append_time_terms(self, query: str) -> str:
        """给搜索 query 补充 2025-2026 时间限定和新鲜度词。"""
        time_terms = ("2025", "2026", "2026年7月", "最新")
        if any(term in query for term in time_terms):
            return query
        return f"{query} 2025 2026 2026年7月 最新"

    async def replan(
        self,
        plan: ResearchPlan,
        evidence: Optional[EvidenceBase] = None,
        rubric: Optional[RubricSignal] = None,
    ) -> ResearchPlan:
        """应用重规划算子 Π(p_t, e_{t+1}, ρ_{t+1})。

        可能执行：
        - 粗到细扩展，新增更细粒度子任务。
        - 剪枝无效分支，从死路回溯。
        - 调整依赖边，让后续执行顺序更合理。

        已执行节点会被保留；χ(v)=1 单调不回退，避免重复计算同一证据。

        Args:
            plan: 当前计划 p_t。
            evidence: 更新后的证据库 e_{t+1}。
            rubric: 更新后的指导信号 ρ_{t+1}。

        Returns:
            更新后的 ResearchPlan p_{t+1}。
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
                Preserve all executed nodes (executed=true).
        """
        
        response = await self.llm.generate(prompt, response_model=ResearchPlan, system_prompt=PLANNER_SYSTEM_PROMPT)

        # LLM 可能重写整个计划对象，因此这里显式恢复已有节点的执行状态和摘要。
        for nid, node in response.nodes.items():
            if nid in plan.nodes:
                node.executed = plan.nodes[nid].executed
                node.result_summary = plan.nodes[nid].result_summary

        return response

    def _parse_actions(self, raw_actions: List[Dict[str, Any]]) -> List[BaseAction]:
        """把 LLM 返回的原始 action 字典解析成强类型 Action 对象。"""
        actions: List[BaseAction] = []
        for raw in raw_actions:
            atype = raw.get("type", "")
            stype = raw.get("subtask_type", "")
            try:
                action_type = ActionType(atype if atype else stype)
            except ValueError:
                continue

            # 先构建通用字段，再根据 action_type 派生为具体动作类型。
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

    def _fallback_initial_plan(self, topic: TopicSpec, outline: Outline) -> ResearchPlan:
        """LLM 计划不可用时，根据大纲确定性生成一个基础 DAG。

        这是初始化阶段的兜底策略。当 LLM 调用失败或返回结果无法解析时，
        不阻塞整个研究流程，而是用规则生成一个合理的默认计划。

        根据大纲是否包含章节，走两条不同路径：
        - 无章节 → 最小线性流水线（搜索 → 合成 → 报告）
        - 有章节 → 扇出-汇聚 DAG（多章节并行搜索 → 交叉验证 → 报告）
        """
        plan = ResearchPlan()
        core_topic = topic.core_topic or topic.query or "research topic"
        chapters = outline.chapters or []

        # ---- 路径 A: 无章节大纲 —— 3 节点线性流水线 ----
        if not chapters:
            # depth=1: 搜索节点 —— 对核心话题做一次宽泛搜索
            plan.add_node(
                PlanNode(
                    id="T-1",
                    subtask_type=SubtaskType.SEARCH_AGENT,
                    title="Initial broad search",
                    description=f"Explore: {core_topic}",
                    depth=1,
                )
            )
            # depth=2: LLM 合成节点 —— 整理初步证据，识别信息缺口
            plan.add_node(
                PlanNode(
                    id="T-2",
                    subtask_type=SubtaskType.LLM,
                    title="Synthesize initial findings",
                    description="Integrate initial evidence and identify remaining gaps",
                    depth=2,
                )
            )
            plan.add_edge("T-1", "T-2")
            # depth=3: 报告生成节点 —— 最终报告合成
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

        # ---- 路径 B: 有章节大纲 —— 扇出-汇聚 DAG ----
        # 阶段1 (depth=1): 每个章节一个搜索节点，全部并行执行
        # 阶段2 (depth=2): 汇聚到 LLM 节点做交叉验证
        # 阶段3 (depth=3): 最终报告生成
        integration_id = "T-INTEGRATE"
        report_id = "T-REPORT"

        # 为每个大纲章节创建一个搜索节点，全部指向汇聚节点
        for index, chapter in enumerate(chapters, start=1):
            node_id = f"T-{index}"
            plan.add_node(
                PlanNode(
                    id=node_id,
                    subtask_type=SubtaskType.SEARCH_AGENT,
                    title=f"Research {chapter.title or f'chapter {index}'}",
                    description=chapter.description or f"Gather evidence for {chapter.title} about {core_topic}",
                    depth=1,
                )
            )
            # 所有章节搜索节点 → 汇聚节点（扇形结构，DAG 调度器会并行执行 depth=1 的节点）
            plan.add_edge(node_id, integration_id)

        # 汇聚节点：交叉验证各章节结果，解决矛盾，识别剩余缺口
        plan.add_node(
            PlanNode(
                id=integration_id,
                subtask_type=SubtaskType.LLM,
                title="Cross-validate and integrate chapter findings",
                description="Compare chapter evidence, resolve conflicts, and identify remaining gaps",
                depth=2,
            )
        )
        # 报告节点：将所有验证过的证据合成为最终报告
        plan.add_node(
            PlanNode(
                id=report_id,
                subtask_type=SubtaskType.REPORT,
                title="Generate final report",
                description="Synthesize final report from all validated evidence",
                depth=3,
            )
        )
        plan.add_edge(integration_id, report_id)
        return plan

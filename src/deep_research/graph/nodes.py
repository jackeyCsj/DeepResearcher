"""LangGraph 外层编排图使用的节点函数。

每个函数对应 StateGraph 中的一个节点，统一形态为：
async def node(state: ResearchState) -> dict

返回的 dict 会由 LangGraph 合并回 ResearchState，因此节点只需要返回自己更新的字段。
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
    """创建所有节点函数，并把核心模块依赖注入闭包中。"""

    async def router_node(state: ResearchState) -> dict:
        """Router：理解用户查询并生成结构化研究主题。"""
        logger.info("Router: analyzing query")
        topic = await router.analyze(state.context.topic.query)
        return {"context": TaskContext(topic=topic, outline=state.context.outline)}

    async def coarse_search_node(state: ResearchState) -> dict:
        """粗粒度探索检索：先摸清研究主题边界，为大纲和初始 DAG 提供材料。"""
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
        """基于粗搜证据生成固定报告大纲 O。"""
        logger.info("Writer: generating outline")
        outline = await writer.generate_outline(state.context.topic, state.evidence_base)
        return {"context": TaskContext(topic=state.context.topic, outline=outline)}

    async def init_plan_node(state: ResearchState) -> dict:
        """根据研究主题和大纲生成初始 DAG 计划 p_0。"""
        logger.info("Planner: initializing research plan")
        plan = await planner.init_plan(state.context.topic, state.context.outline)
        return {"plan": plan}

    async def init_rubric_node(state: ResearchState) -> dict:
        """生成初始持久 Rubric ρ_p，作为全流程质量标准。"""
        logger.info("Rubric: generating persistent criteria")
        persistent = await rubric_generator.init_persistent(state.context)
        return {"persistent_rubric": persistent}

    async def frontier_node(state: ResearchState) -> dict:
        """计算当前 ready frontier F_t；这是纯 DAG 依赖计算，不调用 LLM。"""
        frontier = state.plan.ready_frontier()
        logger.info(f"Frontier: {len(frontier)} ready subtasks")
        return {"transient_frontier": frontier}

    async def planner_action_node(state: ResearchState) -> dict:
        """Planner 节点：从 ready frontier 中挑选本轮要执行的动作。

        这是每轮迭代的决策步骤。输入是当前 DAG 中所有依赖已满足的节点
        （ready_frontier），输出是本轮实际要派发的动作列表。

        决定逻辑由 GraphPlanner.select_actions() 实现，综合考虑：
        - 当前 DAG 计划（哪些节点就绪）
        - 已有证据（哪些缺口已填）
        - Rubric 信号（持久质量标准 + 瞬时缺口）

        同时负责设置停止标志：
        - 没有动作可派发 → 停止
        - Planner 发出 WRITER_REPORT 动作 → 停止（进入最终报告阶段）
        """
        # 把两套 Rubric（持久 ρ_p + 瞬时 ρ^e_t）打包为统一信号传入 Planner
        rubric_signal = RubricSignal(
            persistent=state.persistent_rubric,
            ephemeral=state.ephemeral_rubric,
        )
        # Planner 基于 DAG + 证据 + Rubric 决策本轮动作
        actions = await planner.select_actions(
            state.plan,
            frontier=state.transient_frontier,
            evidence=state.evidence_base,
            rubric=rubric_signal,
        )

        # 停止条件判断（会通过条件边路由到 synthesis 或继续循环）
        should_stop = False
        if not actions:
            # 条件1: 无可派发动作 → DAG 已耗尽或所有缺口已填
            should_stop = True
        elif any(a.type == ActionType.WRITER_REPORT for a in actions):
            # 条件2: Planner 主动发出报告写作指令 → 质量已达标
            should_stop = True

        logger.info(f"Planner: selected {len(actions)} actions (stop={should_stop})")
        return {"transient_actions": actions, "stop_flag": should_stop}

    async def reflection_node(state: ResearchState) -> dict:
        """反思门控：动作真正执行前，先按 Rubric 检查其是否具体、必要且可执行。"""
        if not state.transient_actions:
            return {}

        rubric_signal = RubricSignal(
            persistent=state.persistent_rubric,
            ephemeral=state.ephemeral_rubric,
        )
        all_passed = True
        revised_actions: List[BaseAction] = []

        for action in state.transient_actions:
            # 每个 action 单独评估，避免一个低质量动作污染整批并行动作。
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
        """并行执行所有通过反思门控的动作。"""
        if not state.transient_actions:
            return {"transient_new_bundles": []}

        logger.info(f"Executor: running {len(state.transient_actions)} action(s)")
        bundles = await executor.execute_parallel(state.transient_actions)
        return {"transient_new_bundles": bundles}

    async def evidence_update_node(state: ResearchState) -> dict:
        """把本轮新增证据合并到全局证据库：e_{t+1} = e_t ∪ Δe_t。"""
        if not state.transient_new_bundles:
            return {}

        for bundle in state.transient_new_bundles:
            state.evidence_base.incorporate(bundle)

        # 将对应 DAG 节点标记为已执行，并保存简短结果摘要，供后续 replan 使用。
        for action in state.transient_actions:
            if action.subtask_id in state.plan.nodes:
                node = state.plan.nodes[action.subtask_id]
                node.executed = True
                # 用 subtask_id 对齐 action 和 EvidenceBundle，写回节点结果。
                matching = [b for b in state.transient_new_bundles if b.subtask_id == action.subtask_id]
                if matching:
                    node.result_summary = matching[0].summary

        logger.info(f"Evidence: {len(state.transient_new_bundles)} bundle(s) incorporated")
        return {"evidence_base": state.evidence_base, "plan": state.plan}

    async def rubric_update_node(state: ResearchState) -> dict:
        """根据最新证据刷新瞬时 Rubric：ρ^e_{t+1} = G_e(O, e_{t+1})。"""
        ephemeral = await rubric_generator.update_ephemeral(
            state.context.outline, state.evidence_base
        )
        has_gaps = ephemeral.has_outstanding_gap()
        logger.info(f"Rubric update: {'gaps remain' if has_gaps else 'no gaps'}")

        # Rubric 同时承担“缺口检测”和“停止信号”的职责。
        should_stop = stopping.should_stop(
            ephemeral, state.iteration, state.max_iterations
        )

        return {
            "ephemeral_rubric": ephemeral,
            "stop_flag": state.stop_flag or should_stop,
        }

    async def replan_node(state: ResearchState) -> dict:
        """执行重规划算子 Π(p_t, e_{t+1}, ρ_{t+1})，动态调整 DAG。"""
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
        """Writer 基于主题、大纲、证据和持久 Rubric 合成最终报告。"""
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

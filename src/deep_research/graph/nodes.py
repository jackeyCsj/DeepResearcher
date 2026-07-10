"""LangGraph 外层编排图使用的节点函数。

每个函数对应 StateGraph 中的一个节点，统一形态为：
async def node(state: ResearchState) -> dict

返回的 dict 会由 LangGraph 合并回 ResearchState，因此节点只需要返回自己更新的字段。
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from deep_research.models.state import ResearchState
from deep_research.models.topic import TaskContext
from deep_research.models.evidence import (
    EvidenceBase,
    EvidenceValidationResult,
)
from deep_research.models.rubric import (
    Criterion,
    CriterionKind,
    CriterionStatus,
    Rubric,
    RubricSignal,
)
from deep_research.models.actions import (
    BaseAction,
    ToolCallAction,
    ActionType,
)
from deep_research.core.router import Router
from deep_research.core.planner import GraphPlanner
from deep_research.core.executor import ExecutionModule
from deep_research.core.writer import Writer
from deep_research.core.reflection import ReflectionGate
from deep_research.core.evidence_validator import EvidenceQualityGate
from deep_research.rubric.generator import RubricGenerator
from deep_research.rubric.stopping import AdaptiveStopping

logger = logging.getLogger(__name__)


def create_nodes(
    router: Router,
    planner: GraphPlanner,
    executor: ExecutionModule,
    writer: Writer,
    reflection_gate: ReflectionGate,
    rubric_generator: RubricGenerator,
    stopping: AdaptiveStopping,
    evidence_quality_gate: Optional[EvidenceQualityGate] = None,
) -> Dict[str, Any]:
    """创建所有节点函数，并把核心模块依赖注入闭包中。"""
    evidence_quality_gate = evidence_quality_gate or EvidenceQualityGate(
        rubric_generator.llm
    )

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

        Planner 不在这里决定停止。没有研究动作时仍会让空批次经过
        Rubric、交叉验证和质量门，只有质量门可以进入最终报告。
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

        logger.info("Planner: selected %s actions", len(actions))
        return {"transient_actions": actions, "stop_flag": False}

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

    async def consolidate_evidence_node(state: ResearchState) -> dict:
        """整理本轮 frontier 结果：标准化来源、去重并生成批次质量标记。"""
        batch = evidence_quality_gate.consolidate(
            state.transient_new_bundles,
            state.transient_actions,
            state.iteration,
        )
        logger.info(
            "Evidence consolidation: %s bundle(s), %s record(s)",
            len(batch),
            sum(len(bundle.records) for bundle in batch),
        )
        return {"transient_evidence_batch": batch}

    async def evidence_update_node(state: ResearchState) -> dict:
        """把本轮新增证据合并到全局证据库：e_{t+1} = e_t ∪ Δe_t。"""
        if not state.transient_evidence_batch:
            return {}

        for bundle in state.transient_evidence_batch:
            state.evidence_base.incorporate(bundle)

        # 将对应 DAG 节点标记为已执行，并保存简短结果摘要，供后续 replan 使用。
        for action in state.transient_actions:
            if action.subtask_id in state.plan.nodes:
                node = state.plan.nodes[action.subtask_id]
                node.executed = True
                # 用 subtask_id 对齐 action 和 EvidenceBundle，写回节点结果。
                matching = [
                    bundle
                    for bundle in state.transient_evidence_batch
                    if bundle.subtask_id == action.subtask_id
                ]
                if matching:
                    node.result_summary = matching[0].summary

        logger.info(
            "Evidence: %s normalized bundle(s) incorporated",
            len(state.transient_evidence_batch),
        )
        return {"evidence_base": state.evidence_base, "plan": state.plan}

    async def rubric_update_node(state: ResearchState) -> dict:
        """根据最新证据刷新瞬时 Rubric：ρ^e_{t+1} = G_e(O, e_{t+1})。"""
        ephemeral = await rubric_generator.update_ephemeral(
            state.context.outline, state.evidence_base
        )
        has_gaps = ephemeral.has_outstanding_gap()
        logger.info(f"Rubric update: {'gaps remain' if has_gaps else 'no gaps'}")
        return {"ephemeral_rubric": ephemeral}

    async def cross_validate_evidence_node(state: ResearchState) -> dict:
        """根据最新 Rubric 对本轮证据执行按需交叉验证。"""
        result = await evidence_quality_gate.validate(
            state.transient_evidence_batch,
            state.evidence_base,
            state.ephemeral_rubric,
            state.persistent_rubric,
        )
        updated_rubric = _rubric_with_validation_guidance(
            state.ephemeral_rubric,
            result,
            state.iteration,
        )
        logger.info(
            "Evidence validation: passed=%s, follow_up=%s, issues=%s, llm=%s",
            result.passed,
            result.requires_follow_up,
            len(result.issues),
            result.llm_validation_used,
        )
        return {
            "evidence_base": state.evidence_base,
            "ephemeral_rubric": updated_rubric,
            "transient_validation_result": result,
            "validation_history": [*state.validation_history, result],
        }

    async def quality_gate_node(state: ResearchState) -> dict:
        """质量门通过后才允许自适应停止，否则强制进入重规划。"""
        result = state.transient_validation_result or EvidenceValidationResult()
        max_reached = state.iteration >= state.max_iterations

        if (result.requires_follow_up or not result.passed) and not max_reached:
            decision = "follow_up"
            should_stop = False
        else:
            should_stop = stopping.should_stop(
                state.ephemeral_rubric,
                state.iteration,
                state.max_iterations,
            )
            decision = "stop" if should_stop else "continue"

        result.quality_decision = decision
        validation_history = list(state.validation_history)
        if validation_history:
            validation_history[-1] = result
        logger.info("Quality gate: decision=%s", decision)
        return {
            "transient_quality_decision": decision,
            "transient_validation_result": result,
            "validation_history": validation_history,
            "stop_flag": should_stop,
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
        "consolidate_evidence": consolidate_evidence_node,
        "update_evidence": evidence_update_node,
        "update_rubric": rubric_update_node,
        "cross_validate_evidence": cross_validate_evidence_node,
        "quality_gate": quality_gate_node,
        "replan": replan_node,
        "final_synthesis": synthesis_node,
    }


def _rubric_with_validation_guidance(
    rubric: Rubric,
    result: EvidenceValidationResult,
    iteration: int,
) -> Rubric:
    """把质量门问题转成下一轮 Planner 可消费的瞬时 Rubric。"""
    criteria = list(rubric.criteria)
    existing_names = {criterion.name for criterion in criteria}

    for index, issue in enumerate(result.issues, start=1):
        if not result.requires_follow_up and result.passed:
            break
        name = f"validation_{iteration}_{index}_{issue.issue_type}"
        if name in existing_names:
            continue
        criteria.append(
            Criterion(
                name=name,
                description=issue.description,
                guidance=issue.recommended_action or issue.description,
                kind=_criterion_kind_for_issue(issue.issue_type),
                status=CriterionStatus.OUTSTANDING,
            )
        )
        existing_names.add(name)

    for index, guidance in enumerate(result.follow_up_guidance, start=1):
        name = f"validation_{iteration}_guidance_{index}"
        if name in existing_names:
            continue
        criteria.append(
            Criterion(
                name=name,
                description="Evidence quality follow-up required by the latest batch.",
                guidance=guidance,
                kind=CriterionKind.SOURCE_CREDIBILITY,
                status=CriterionStatus.OUTSTANDING,
            )
        )
        existing_names.add(name)

    return Rubric(criteria=criteria)


def _criterion_kind_for_issue(issue_type: str) -> CriterionKind:
    """把验证问题映射为 Rubric 质量类别。"""
    normalized = issue_type.lower()
    if "conflict" in normalized or "contradict" in normalized:
        return CriterionKind.CONFLICT
    if "source" in normalized or "citation" in normalized:
        return CriterionKind.SOURCE_CREDIBILITY
    if "empty" in normalized or "failure" in normalized:
        return CriterionKind.COVERAGE
    return CriterionKind.OTHER

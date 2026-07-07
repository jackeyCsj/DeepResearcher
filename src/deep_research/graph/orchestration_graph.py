"""外层研究循环的 LangGraph 编排图，对应论文 Algorithm 1。

这是整个系统的主状态机，负责把 DuMate-DeepResearch 的外层编排层落成代码：
1. Router → 粗粒度搜索 → 大纲生成 → 初始化计划 → 初始化 Rubric
2. 循环：计算前沿任务 → 选择动作 → 反思质检 → 执行 → 更新证据 → 更新 Rubric → 重规划
3. 收尾：合成最终报告

节点拓扑：
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
    """planner_actions 之后的路由：没有动作或 stop_flag 置位时进入最终写作。"""
    if state.stop_flag:
        return "stop"
    return "reflect"


def decide_reflection_pass_or_revise(state: ResearchState) -> str:
    """reflection_gate 之后的路由：通过、修订，或修订耗尽后继续执行。

    返回值为 "pass"、"revise" 或 "fail_after_revisions"。
    """
    passed = getattr(state, "transient_reflection_passed", True)
    if passed:
        return "pass"

    # 只要还有动作未耗尽修订次数，就回到 planner_actions 让规划器重新出动作。
    for action in getattr(state, "transient_actions", []):
        if action.revision_count < action.max_revisions:
            return "revise"

    return "fail_after_revisions"


def decide_adaptive_stop(state: ResearchState) -> str:
    """update_rubric 之后的路由：Rubric 无缺口或达到最大轮次时停止。"""
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
    """构建外层研究循环的 LangGraph StateGraph。

    Args:
        router: 任务理解模块。
        planner: 基于 DAG 的动态规划器。
        executor: 动作执行模块。
        writer: 报告写作模块。
        reflection_gate: 执行前质量门控。
        rubric_generator: 动态 Rubric 生成器。
        stopping: 自适应停止判定器。

    Returns:
        已编译、可直接执行的 StateGraph。
    """
    nodes = create_nodes(
        router, planner, executor, writer, reflection_gate, rubric_generator, stopping
    )

    workflow = StateGraph(ResearchState)

    # 注册所有节点函数；节点名必须与后续 add_edge 中的字符串保持一致。
    for name, func in nodes.items():
        workflow.add_node(name, func)

    # 定义外层编排图入口。
    workflow.set_entry_point("router")

    # 初始化流水线：先理解问题，再粗搜定边界，随后生成大纲、计划和持久 Rubric。
    workflow.add_edge("router", "coarse_search")
    workflow.add_edge("coarse_search", "generate_outline")
    workflow.add_edge("generate_outline", "init_plan")
    workflow.add_edge("init_plan", "init_rubric")
    workflow.add_edge("init_rubric", "compute_frontier")

    # 主研究循环从计算 DAG 的 ready frontier 开始。
    workflow.add_edge("compute_frontier", "planner_actions")

    # Planner 选不出可执行动作时，说明研究阶段结束，进入最终合成。
    workflow.add_conditional_edges(
        "planner_actions",
        decide_stop_or_continue,
        {
            "stop": "final_synthesis",
            "reflect": "reflection_gate",
        },
    )

    # 执行前反思门控：通过则执行；可修订则回 Planner；修订耗尽则保守放行，避免死循环。
    workflow.add_conditional_edges(
        "reflection_gate",
        decide_reflection_pass_or_revise,
        {
            "pass": "execute_parallel",
            "revise": "planner_actions",
            "fail_after_revisions": "execute_parallel",
        },
    )

    # 执行结果先转成 EvidenceBundle，再合并到全局证据库。
    workflow.add_edge("execute_parallel", "update_evidence")
    workflow.add_edge("update_evidence", "update_rubric")

    # Rubric 更新后决定是否继续研究；这是论文里的自适应停止机制。
    workflow.add_conditional_edges(
        "update_rubric",
        decide_adaptive_stop,
        {
            "stop": "final_synthesis",
            "continue": "replan",
        },
    )

    # 重规划后回到 frontier，形成“执行 - 评估 - 修正计划”的闭环。
    workflow.add_edge("replan", "compute_frontier")

    # 最终报告生成完成后结束整张图。
    workflow.add_edge("final_synthesis", END)

    compiled = workflow.compile()
    return compiled

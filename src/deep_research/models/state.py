"""研究状态模型：完整 LangGraph 状态 s_t = ⟨z, p_t, e_t, ρ_t⟩。

这是整张 LangGraph 状态机的骨架；所有节点都从这里读取输入，并把更新写回这里。
"""

from __future__ import annotations
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from deep_research.models.topic import TaskContext
from deep_research.models.plan import ResearchPlan, PlanNode
from deep_research.models.evidence import EvidenceBase, EvidenceBundle
from deep_research.models.rubric import Rubric
from deep_research.models.actions import BaseAction, ActionRecord


class ResearchState(BaseModel):
    """完整研究状态 s_t = ⟨z, p_t, e_t, ρ_t⟩。

    它作为外层编排图的 StateModel，承载跨节点传递的全部上下文。
    """

    # 固定上下文 z = (x, O)：研究主题 x 和报告大纲 O。
    context: TaskContext = Field(default_factory=TaskContext)

    # 动态计划 p_t：DAG 任务图会随着证据和 Rubric 被重规划。
    plan: ResearchPlan = Field(default_factory=ResearchPlan)

    # 累计证据 e_t：由每轮执行返回的 EvidenceBundle 合并而来。
    evidence_base: EvidenceBase = Field(default_factory=EvidenceBase)

    # 指导信号 ρ_t = (ρ_p, ρ^e_t)：持久 Rubric + 瞬时 Rubric。
    persistent_rubric: Rubric = Field(default_factory=Rubric)
    ephemeral_rubric: Rubric = Field(default_factory=Rubric)

    # 外层研究循环的轮次控制。
    iteration: int = 0
    max_iterations: int = 15
    stop_flag: bool = False

    # 动作审计轨迹，便于追踪系统做过什么。
    action_history: List[ActionRecord] = Field(default_factory=list)

    # 图流转使用的临时字段；这些字段只在相邻节点之间传递中间结果。
    transient_frontier: List[PlanNode] = Field(default_factory=list)
    transient_actions: List[BaseAction] = Field(default_factory=list)
    transient_new_bundles: List[EvidenceBundle] = Field(default_factory=list)
    transient_reflection_passed: bool = True

    # 最终输出报告。
    final_report: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True
        extra = "allow"

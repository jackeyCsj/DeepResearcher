"""DAG 结构化研究计划模型，实现论文中的图式动态规划形式化。

论文中的定义：
- 计划 p_t = (V_t, E_t)，其中 V_t 是子任务节点，E_t 是依赖边。
- 每个节点 v 带有 ⟨d(v), χ(v)⟩：层级深度和是否已执行。
- ready frontier F_t = { v ∈ V_t : χ(v)=0 ∧ ∀(u,v)∈E_t, χ(u)=1 }
"""

from __future__ import annotations
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class SubtaskType(str, Enum):
    SEARCH = "search"
    LLM = "llm"
    OUTLINE = "outline"
    REPORT = "report"
    SEARCH_AGENT = "search_agent"


class PlanNode(BaseModel):
    """DAG 计划中的一个子任务节点 v。

    对应论文中的定义：每个节点 v 携带 ⟨d(v), χ(v)⟩，
    即层级深度 d(v) 和执行状态 χ(v) ∈ {0, 1}。
    """

    # ---- 节点标识 ----
    id: str
    """节点唯一标识，如 "T-1"、"T-INTEGRATE" """

    subtask_type: SubtaskType
    """任务类型：SEARCH_AGENT(搜索)、LLM(推理合成)、REPORT(报告生成) 等"""

    title: str
    """节点简短标题，用于日志和调度展示"""

    description: str = ""
    """节点的详细任务描述，会作为 LLM prompt 的一部分"""

    # ---- 论文中的结构属性 ----
    depth: int = Field(default=1, ge=1, description="d(v): coarse-to-fine depth")
    """论文 d(v)：层级深度。depth=1 为粗粒度搜索，depth 越大越精细。
        DAG 调度器按 depth 升序执行，保证先粗后细。"""

    executed: bool = Field(default=False, description="χ(v) ∈ {0, 1}")
    """论文 χ(v)：执行状态。0=未执行，1=已完成。
        只有所有前置依赖都已执行(χ=1)的节点才能进入 ready_frontier。"""

    result_summary: Optional[str] = None
    """节点执行完毕后保存的结果摘要，供下游节点和最终报告使用"""

    # ---- 修订控制 ----
    revision_count: int = 0
    """当前已修订次数，每次 reflection 判定 revise 时 +1"""

    max_revisions: int = 3
    """最多允许的修订次数，超过后强制通过避免无限循环"""

    parent_ids: List[str] = Field(default_factory=list)
    """反向依赖：记录哪些节点以此为前置依赖。
        与 Edge 表的 source_id→target_id 互为补充，方便反向遍历。"""


class Edge(BaseModel):
    """依赖边 (u, v) ∈ E_t，表示 v 依赖 u 的完成。"""

    source_id: str
    target_id: str


class ResearchPlan(BaseModel):
    """DAG 结构研究计划 p_t = (V_t, E_t)。"""

    nodes: Dict[str, PlanNode] = Field(default_factory=dict)
    edges: List[Edge] = Field(default_factory=list)

    def ready_frontier(self) -> List[PlanNode]:
        """计算 ready frontier：F_t = { v: χ(v)=0 ∧ ∀(u,v)∈E_t, χ(u)=1 }。

        只有依赖全部满足、且自身尚未执行的节点才会被派发。
        返回结果按 depth 升序排列，保证粗粒度任务优先于细粒度任务。
        """
        executed_ids = {nid for nid, n in self.nodes.items() if n.executed}
        frontier = []
        for node in self.nodes.values():
            if node.executed:
                continue
            deps = [e.source_id for e in self.edges if e.target_id == node.id]
            if all(d in executed_ids for d in deps):
                frontier.append(node)
        frontier.sort(key=lambda n: (n.depth, n.id))
        return frontier

    def add_node(self, node: PlanNode) -> None:
        self.nodes[node.id] = node

    def add_edge(self, source_id: str, target_id: str) -> None:
        self.edges.append(Edge(source_id=source_id, target_id=target_id))

    def prune_branch(self, node_id: str) -> None:
        """删除指定节点及其所有后代，用于死路剪枝。"""
        to_remove = {node_id}
        changed = True
        while changed:
            changed = False
            for e in self.edges:
                if e.source_id in to_remove and e.target_id not in to_remove:
                    to_remove.add(e.target_id)
                    changed = True
        self.edges = [
            e
            for e in self.edges
            if e.source_id not in to_remove and e.target_id not in to_remove
        ]
        for nid in to_remove:
            self.nodes.pop(nid, None)

    @property
    def all_executed(self) -> bool:
        """检查计划中的所有节点是否都已执行。"""
        return all(n.executed for n in self.nodes.values())



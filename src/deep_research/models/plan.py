"""DAG-structured research plan models, implementing the graph-based dynamic planning formalism.

From the paper:
- Plan p_t = (V_t, E_t) where V_t are subtask nodes and E_t are dependency edges.
- Each node v carries ⟨d(v), χ(v)⟩: depth in hierarchy and binary execution status.
- Ready frontier F_t = { v ∈ V_t : χ(v)=0 ∧ ∀(u,v)∈E_t, χ(u)=1 }
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
    """A subtask node v in the DAG plan."""

    id: str
    subtask_type: SubtaskType
    title: str
    description: str = ""
    depth: int = Field(default=1, ge=1, description="d(v): coarse-to-fine depth")
    executed: bool = Field(default=False, description="χ(v) ∈ {0, 1}")
    result_summary: Optional[str] = None
    revision_count: int = 0
    max_revisions: int = 3
    parent_ids: List[str] = Field(default_factory=list)


class Edge(BaseModel):
    """A dependency edge (u, v) ∈ E_t."""

    source_id: str
    target_id: str


class ResearchPlan(BaseModel):
    """The DAG-structured plan p_t = (V_t, E_t)."""

    nodes: Dict[str, PlanNode] = Field(default_factory=dict)
    edges: List[Edge] = Field(default_factory=list)

    def ready_frontier(self) -> List[PlanNode]:
        """F_t = { v: χ(v)=0 ∧ ∀(u,v)∈E_t, χ(u)=1 }.

        Only dispatch subtasks whose dependencies are all satisfied.
        Sorted by depth ascending (coarse before fine).
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
        """Remove a node and all its descendants (dead-end pruning)."""
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
        """Check whether the plan is fully executed."""
        return all(n.executed for n in self.nodes.values())

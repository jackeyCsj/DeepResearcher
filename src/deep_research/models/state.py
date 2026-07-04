"""Research state model: the full LangGraph state s_t = ⟨z, p_t, e_t, ρ_t⟩.

This is the backbone of the entire LangGraph state machine.
Every node reads from and writes to this.
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
    """The full research state s_t = ⟨z, p_t, e_t, ρ_t⟩.

    This serves as the LangGraph StateModel for the orchestration graph.
    """

    # Fixed context z = (x, O)
    context: TaskContext = Field(default_factory=TaskContext)

    # Dynamic plan p_t
    plan: ResearchPlan = Field(default_factory=ResearchPlan)

    # Accumulated evidence e_t
    evidence_base: EvidenceBase = Field(default_factory=EvidenceBase)

    # Guidance signal ρ_t = (ρ_p, ρ^e_t)
    persistent_rubric: Rubric = Field(default_factory=Rubric)
    ephemeral_rubric: Rubric = Field(default_factory=Rubric)

    # Iteration tracking
    iteration: int = 0
    max_iterations: int = 15
    stop_flag: bool = False

    # Audit trail
    action_history: List[ActionRecord] = Field(default_factory=list)

    # Transient fields for graph flow
    transient_frontier: List[PlanNode] = Field(default_factory=list)
    transient_actions: List[BaseAction] = Field(default_factory=list)
    transient_new_bundles: List[EvidenceBundle] = Field(default_factory=list)
    transient_reflection_passed: bool = True

    # Final output
    final_report: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True
        extra = "allow"

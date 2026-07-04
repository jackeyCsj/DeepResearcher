"""Rubric models for test-time optimization.

Implements Section 2.2.3: ρ_t = (ρ_p, ρ^e_t).
- Persistent Rubrics ρ_p: stable topic-level quality dimensions
- Ephemeral Rubrics ρ^e_t: transient evidence-gap criteria
"""

from __future__ import annotations
from typing import List
from pydantic import BaseModel, Field


class Criterion(BaseModel):
    """A single criterion c = (name, description, guidance).

    The guidance field is phrased as an actionable reasoning instruction
    rather than a numeric score (per paper Section 2.2.3).
    """

    name: str = ""
    description: str = ""
    guidance: str = Field(
        default="",
        description="Actionable reasoning instruction (NOT a numeric score)",
    )


class Rubric(BaseModel):
    """A set of criteria ρ = {c₁, ..., cₖ}."""

    criteria: List[Criterion] = Field(default_factory=list)

    def has_outstanding_gap(self) -> bool:
        """Returns True if ANY criterion indicates an evidence gap.

        The ephemeral rubric uses this to signal the adaptive stopping predicate.
        """
        gap_indicators = [
            "insufficient",
            "missing",
            "gap",
            "needs more",
            "not yet",
            "incomplete",
            "lacking",
            "uncovered",
            "not addressed",
        ]
        return any(
            any(indicator in c.guidance.lower() for indicator in gap_indicators)
            for c in self.criteria
        )


class RubricSignal(BaseModel):
    """The full guidance signal ρ_t = (ρ_p, ρ^e_t)."""

    persistent: Rubric = Field(default_factory=Rubric, description="Stable topic-level rubrics ρ_p")
    ephemeral: Rubric = Field(default_factory=Rubric, description="Transient evidence-gap rubrics ρ^e_t")

    def active(self) -> Rubric:
        """Combined rubric for Planner / Search Agent consumption."""
        return Rubric(criteria=self.persistent.criteria + self.ephemeral.criteria)

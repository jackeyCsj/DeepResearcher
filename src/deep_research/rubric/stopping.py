"""Adaptive stopping mechanism for the research loop.

When the ephemeral rubric reports no outstanding evidence gap,
the stopping predicate STOP(s_t) halts the loop.

From the paper:
"Once it reports no outstanding gap, the stopping predicate STOP of Algorithm 1
halts the loop, tying factual sufficiency directly to the stopping rule."
"""

from __future__ import annotations

from deep_research.models.rubric import Rubric


class AdaptiveStopping:
    """Determines whether the research loop should stop.

    STOP predicate: halts when:
    1. Maximum iterations reached (hard bound)
    2. Ephemeral rubric reports no outstanding evidence gap
    """

    def should_stop(
        self,
        ephemeral_rubric: Rubric,
        iteration: int,
        max_iterations: int,
    ) -> bool:
        """Evaluate the STOP predicate.

        Args:
            ephemeral_rubric: The current ephemeral rubric ρ^e_t.
            iteration: The current loop iteration.
            max_iterations: The maximum allowed iterations.

        Returns:
            True if the loop should stop, False to continue.
        """
        # Hard bound: max iterations reached
        if iteration >= max_iterations:
            return True

        # Adaptive stop: no outstanding evidence gaps
        if not ephemeral_rubric.has_outstanding_gap():
            return True

        return False

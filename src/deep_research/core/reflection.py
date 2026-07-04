"""Reflection gate: quality checkpoint before execution.

Implements Algorithm 2 lines 8-10 from the paper:
- Before execution, each action passes a lightweight reflection gate.
- Rejected actions are revised under critic feedback for bounded rounds.
"""

from __future__ import annotations
import logging
from typing import Optional, Tuple

from deep_research.models.actions import BaseAction
from deep_research.models.plan import ResearchPlan
from deep_research.models.evidence import EvidenceBase
from deep_research.models.rubric import RubricSignal
from deep_research.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)


class ReflectionGate:
    """Quality checkpoint: evaluates actions before execution.

    Checks:
    1. Is the action well-specified and actionable?
    2. Does it address the rubric's guidance?
    3. Is the expected evidence justified given current state?
    """

    def __init__(self, llm_client: LLMClient, max_revisions: int = 3) -> None:
        self.llm = llm_client
        self.max_revisions = max_revisions

    async def evaluate(
        self,
        action: BaseAction,
        plan: ResearchPlan,
        evidence: EvidenceBase,
        rubric: RubricSignal,
    ) -> Tuple[bool, str, Optional[BaseAction]]:
        """Evaluate a single action before execution.

        Args:
            action: The proposed action.
            plan: The current research plan.
            evidence: Accumulated evidence.
            rubric: The active rubric signal.

        Returns:
            (passed, feedback, revised_action):
            - If passed=True, the action is approved.
            - If passed=False, revised_action contains the corrected version.
        """
        node = plan.nodes.get(action.subtask_id)
        rubric_text = "\n".join(
            f"- {c.name}: {c.guidance}" for c in rubric.active().criteria
        ) or "No active rubric criteria."

        prompt = f"""Evaluate this research action for quality before execution.

Action type: {action.type.value}
Action description: {action.description}
Subtask: {node.title if node else 'unknown'}
Depth: {node.depth if node else 'N/A'}
Rubric guidance:
{rubric_text}

Check:
1. Is the action well-specified and actionable?
2. Does it address the rubric's guidance?
3. Is the expected evidence justified given current knowledge state?

Respond with JSON:
{{"passed": true/false, "feedback": "reasoning", "needs_revision": true/false, "revision_suggestion": "..."}}
"""
        response = await self.llm.generate(prompt)

        try:
            parsed = response if isinstance(response, dict) else eval(response)
        except Exception:
            return True, "", None

        if parsed.get("passed"):
            return True, "", None

        if parsed.get("needs_revision") and action.revision_count < self.max_revisions:
            revised = action.model_copy(deep=True)
            revised.revision_count += 1
            if parsed.get("revision_suggestion"):
                revised.description = f"{revised.description}\n[Revised: {parsed['revision_suggestion']}]"
            return False, parsed.get("feedback", ""), revised

        return True, "", None

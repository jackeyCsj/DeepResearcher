"""Reflection Gate：动作执行前的轻量质量门控。

对应论文 Algorithm 2 中的反思检查：
- 每个动作在执行前先过一层质量检查。
- 未通过的动作会基于 critic feedback 进行有限轮修订。
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
    """执行前质量检查器。

    主要检查：
    1. 动作是否具体、可执行。
    2. 动作是否响应当前 Rubric 的指导。
    3. 预期证据是否匹配当前研究状态。
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
        """执行前评估单个动作。

        Args:
            action: Planner 生成的候选动作。
            plan: 当前 DAG 研究计划。
            evidence: 已累计的证据库。
            rubric: 当前生效的 RubricSignal。

        Returns:
            (passed, feedback, revised_action)：
            - passed=True 表示动作可直接执行。
            - passed=False 且 revised_action 不为空时，返回修订后的动作。
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
            # 反思解析失败时保守放行，避免评估器故障阻断主研究流程。
            return True, "", None

        if parsed.get("passed"):
            return True, "", None

        if parsed.get("needs_revision") and action.revision_count < self.max_revisions:
            # 修订不改变动作类型，只把 critic 建议附加到描述中供 Planner/Executor 使用。
            revised = action.model_copy(deep=True)
            revised.revision_count += 1
            if parsed.get("revision_suggestion"):
                revised.description = f"{revised.description}\n[Revised: {parsed['revision_suggestion']}]"
            return False, parsed.get("feedback", ""), revised

        return True, "", None

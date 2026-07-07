"""研究循环的自适应停止机制。

当瞬时 Rubric 判断已经没有明显证据缺口时，STOP(s_t) 会终止外层循环。

这把“事实证据是否充分”直接绑定到停止规则，而不是依赖固定检索轮次。
"""

from __future__ import annotations

from deep_research.models.rubric import Rubric


class AdaptiveStopping:
    """判断研究循环是否应该停止。

    STOP 谓词在以下两种情况下触发：
    1. 达到最大迭代轮次。
    2. 瞬时 Rubric 判断没有剩余证据缺口。
    """

    def should_stop(
        self,
        ephemeral_rubric: Rubric,
        iteration: int,
        max_iterations: int,
    ) -> bool:
        """评估 STOP 谓词。

        Args:
            ephemeral_rubric: 当前瞬时 Rubric ρ^e_t。
            iteration: 当前外层循环轮次。
            max_iterations: 最大允许轮次。

        Returns:
            True 表示停止研究循环，False 表示继续。
        """
        # 硬上限：达到最大迭代轮次。
        if iteration >= max_iterations:
            return True

        # 自适应停止：Rubric 判断没有明显证据缺口。
        if not ephemeral_rubric.has_outstanding_gap():
            return True

        return False

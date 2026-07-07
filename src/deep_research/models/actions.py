"""Planner 生成的动作模型，以及执行审计记录。"""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from deep_research.models.evidence import EvidenceBundle


class ActionType(str, Enum):
    TOOL_CALL = "tool_call"
    SEARCH_AGENT = "search_agent"
    WRITER_OUTLINE = "writer_outline"
    WRITER_REPORT = "writer_report"
    LLM_REASONING = "llm"


class BaseAction(BaseModel):
    """Planner 在某一轮生成的基础动作 a_t。"""

    id: str = ""
    type: ActionType
    subtask_id: str = ""
    description: str = ""
    params: Dict[str, Any] = Field(default_factory=dict)
    rubric_guidance: Optional[str] = None
    revision_count: int = 0
    max_revisions: int = 3


class ToolCallAction(BaseAction):
    """直接调用工具生态中的某个工具。"""

    type: ActionType = ActionType.TOOL_CALL
    tool_name: str = ""
    tool_input: str = ""
    tool_params: Dict[str, Any] = Field(default_factory=dict)


class SearchAgentAction(BaseAction):
    """派发内层 Search Agent 执行开放式检索。"""

    type: ActionType = ActionType.SEARCH_AGENT
    sub_query: str = ""
    max_rounds: int = 10
    queries_per_round: int = 3


class LLMReasoningAction(BaseAction):
    """内部 LLM 推理动作，用于去重、合并、交叉验证等轻量分析。"""

    type: ActionType = ActionType.LLM_REASONING
    instruction: str = ""
    evidence_ids: List[str] = Field(default_factory=list)


class ActionRecord(BaseModel):
    """每个已执行动作的审计记录。"""

    action: BaseAction
    result_summary: str = ""
    evidence_bundle: Optional[EvidenceBundle] = None
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    succeeded: bool = True
    error: Optional[str] = None

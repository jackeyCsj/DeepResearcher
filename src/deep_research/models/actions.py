"""Action models for Planner-issued actions and audit records."""

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
    """An action a_t issued by the Planner."""

    id: str = ""
    type: ActionType
    subtask_id: str = ""
    description: str = ""
    params: Dict[str, Any] = Field(default_factory=dict)
    rubric_guidance: Optional[str] = None
    revision_count: int = 0
    max_revisions: int = 3


class ToolCallAction(BaseAction):
    """Direct tool invocation action."""

    type: ActionType = ActionType.TOOL_CALL
    tool_name: str = ""
    tool_input: str = ""
    tool_params: Dict[str, Any] = Field(default_factory=dict)


class SearchAgentAction(BaseAction):
    """Dispatch an inner Search Agent for open-ended retrieval."""

    type: ActionType = ActionType.SEARCH_AGENT
    sub_query: str = ""
    max_rounds: int = 10
    queries_per_round: int = 3


class LLMReasoningAction(BaseAction):
    """Internal reasoning action (dedup, merge, cross-validate)."""

    type: ActionType = ActionType.LLM_REASONING
    instruction: str = ""
    evidence_ids: List[str] = Field(default_factory=list)


class ActionRecord(BaseModel):
    """Audit record for each executed action."""

    action: BaseAction
    result_summary: str = ""
    evidence_bundle: Optional[EvidenceBundle] = None
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    succeeded: bool = True
    error: Optional[str] = None

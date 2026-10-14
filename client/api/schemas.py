from typing import Literal
from pydantic import BaseModel, Field


class AuthRequest(BaseModel):
    username: str
    password: str
    display_name: str | None = None


class UserInfo(BaseModel):
    id: str
    username: str
    display_name: str


class AuthResult(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserInfo


class ClarifyRequest(BaseModel):
    query: str
    user_id: str = "default"


class ClarifyResult(BaseModel):
    is_clear: bool
    brief: str | None = None
    directions: list[str] = []
    message: str | None = None
    session_id: str | None = None


class RefineRequest(BaseModel):
    query: str
    response: str
    user_id: str = "default"
    session_id: str | None = None


class RefineResult(BaseModel):
    brief: str
    session_id: str | None = None


class ResearchRequest(BaseModel):
    brief: str
    user_id: str = "default"
    session_id: str | None = None


class TurnRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None
    task_id: str | None = None
    report_version_id: str | None = None


class IngestRequest(BaseModel):
    src: str
    custom_title: str | None = None
    overwrite: bool = True


class IngestResult(BaseModel):
    title: str
    status: Literal["skipped", "overwritten", "created"]


class ReportContent(BaseModel):
    report_file_id: str
    title: str
    content: str


class ChatMessageOut(BaseModel):
    role: str
    message_type: str
    content: str
    created_at: str
    extra: dict | None = None


class ResearchStepOut(BaseModel):
    sequence: int
    step_type: str
    title: str
    content: str | None = None
    report_file_id: str | None = None
    created_at: str
    extra: dict | None = None


class ChatSessionSummary(BaseModel):
    id: str
    title: str
    raw_query: str
    research_brief: str | None = None
    report_file_id: str | None = None
    status: str
    created_at: str
    updated_at: str


class ReportVersionOut(BaseModel):
    id: str
    run_id: str
    report_file_id: str
    title: str
    version_number: int
    parent_version_id: str | None = None
    created_at: str
    content: str


class ResearchTaskOut(BaseModel):
    id: str
    title: str
    scope: str
    status: str
    intent: str | None = None
    current_version_id: str | None = None
    versions: list[ReportVersionOut] = []


class ChatSessionDetail(ChatSessionSummary):
    messages: list[ChatMessageOut]
    steps: list[ResearchStepOut]
    report: ReportContent | None = None
    tasks: list[ResearchTaskOut] = []
    active_task_id: str | None = None

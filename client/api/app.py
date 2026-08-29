import json
import logging
import os
import shutil
import tempfile

from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request, UploadFile
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from client.agents import Clarifier
from client.api.auth import create_access_token, get_current_user, hash_password, verify_password
from client.base import LLMClient, setup_logging
from client.config import Config
from client.db import ChatRepository, init_db, session_scope
from client.library.library_manager import LibraryManager
from client.orchestrator import Orchestrator
from client.rag.pipeline import Pipeline
from client.db.models import User
from .schemas import (
    AuthRequest,
    AuthResult,
    ClarifyRequest,
    ClarifyResult,
    ChatSessionDetail,
    ChatSessionSummary,
    RefineRequest,
    RefineResult,
    ResearchRequest,
    IngestRequest,
    IngestResult,
    ReportContent,
    UserInfo,
)

logger = logging.getLogger(__name__)

PREVIEW_LENGTH = 150


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(enable_display=False)
    init_db()
    orchestrator = Orchestrator(Config())
    app.state.orchestrator = orchestrator
    app.state.clarifier = Clarifier(llm=orchestrator.llm_client, creative_temperature=orchestrator.config.llm.research_temperature)
    app.state.library_manager = orchestrator.create_library_manager()
    yield
    orchestrator.close()


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.post("/api/auth/register")
def register(body: AuthRequest) -> AuthResult:
    username = body.username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="用户名至少 3 个字符")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 个字符")

    with session_scope() as db:
        repo = ChatRepository(db)
        if repo.get_user_by_username(username):
            raise HTTPException(status_code=409, detail="用户名已存在")
        user = repo.create_user(
            username=username,
            password_hash=hash_password(body.password),
            display_name=body.display_name,
        )
        token = create_access_token(user)
        return AuthResult(access_token=token, user=_user_info(user))


@app.post("/api/auth/login")
def login(body: AuthRequest) -> AuthResult:
    with session_scope() as db:
        repo = ChatRepository(db)
        user = repo.get_user_by_username(body.username.strip())
        if not user or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        token = create_access_token(user)
        return AuthResult(access_token=token, user=_user_info(user))


@app.get("/api/auth/me")
def me(current_user: User = Depends(get_current_user)) -> UserInfo:
    return _user_info(current_user)


@app.post("/api/clarify")
def clarify(body: ClarifyRequest, request: Request, current_user: User = Depends(get_current_user)) -> ClarifyResult:
    clarifier: Clarifier = request.app.state.clarifier
    result = clarifier.analyze(body.query)
    with session_scope() as db:
        repo = ChatRepository(db)
        session = repo.create_session(user_id=current_user.id, raw_query=body.query)
        result.session_id = session.id
        if result.is_clear and result.brief:
            repo.update_session(session.id, research_brief=result.brief, status="brief_ready")
            repo.add_message(session.id, "assistant", result.brief, "brief")
        else:
            repo.add_message(
                session.id,
                "assistant",
                result.message or "请选择一个研究方向。",
                "clarify",
                {"directions": result.directions},
            )
    return result


@app.post("/api/clarify/refine")
def refine(body: RefineRequest, request: Request, current_user: User = Depends(get_current_user)) -> RefineResult:
    clarifier: Clarifier = request.app.state.clarifier
    result = clarifier.refine(raw_query=body.query, user_response=body.response)
    with session_scope() as db:
        repo = ChatRepository(db)
        session_id = body.session_id
        if not session_id or not repo.get_user_session(session_id, current_user.id):
            session = repo.create_session(user_id=current_user.id, raw_query=body.query)
            session_id = session.id
        repo.add_message(session_id, "user", body.response, "clarify_response")
        repo.add_message(session_id, "assistant", result, "brief")
        repo.update_session(session_id, research_brief=result, status="brief_ready")
    return RefineResult(brief=result, session_id=session_id)


@app.post("/api/research")
def research(body: ResearchRequest, request: Request, current_user: User = Depends(get_current_user)):
    orchestrator: Orchestrator = request.app.state.orchestrator
    session_id = body.session_id
    with session_scope() as db:
        repo = ChatRepository(db)
        if not session_id or not repo.get_user_session(session_id, current_user.id):
            session = repo.create_session(user_id=current_user.id, raw_query=body.brief)
            session_id = session.id
        repo.update_session(session_id, research_brief=body.brief, status="researching")

    events = orchestrator.run_research(body.brief, user_id=current_user.id)

    return StreamingResponse(
        format_sse_events(
            events=events,
            llm_client=orchestrator.llm_client,
            session_id=session_id,
        ),
        media_type="text/event-stream",
    )


@app.get("/api/library")
def list_docs(request: Request, current_user: User = Depends(get_current_user)):
    library_manager: LibraryManager = request.app.state.library_manager
    return [
        {
            "title": entry["title"],
            "source_type": entry.get("source_type"),
            "added_at": entry.get("added_at"),
        }
        for entry in library_manager.list_docs()
        if entry.get("original_path")
    ]


@app.get("/api/reports/{report_file_id}")
def get_report(report_file_id: str, request: Request, current_user: User = Depends(get_current_user)) -> ReportContent:
    data_dir = request.app.state.orchestrator.config.data_dir
    path = _report_path(data_dir, current_user.id, report_file_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Report not found")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return ReportContent(
        report_file_id=report_file_id,
        title=_extract_title_from_markdown(content, report_file_id),
        content=content,
    )


@app.post("/api/library/upload")
def upload_file(file: UploadFile, request: Request, current_user: User = Depends(get_current_user)) -> IngestResult:
    library_manager: LibraryManager = request.app.state.library_manager
    filename = file.filename or "upload.pdf"
    safe_name = filename.replace("/", "_").replace("\\", "_")
    tmp_dir = tempfile.mkdtemp(dir=library_manager.data_dir)
    src = os.path.join(tmp_dir, safe_name)
    try:
        with open(src, "wb") as f:
            f.write(file.file.read())
        result = library_manager.ingest(src=src, overwrite=True)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return result


@app.post("/api/library/ingest")
def ingest(body: IngestRequest, request: Request, current_user: User = Depends(get_current_user)) -> IngestResult:
    library_manager: LibraryManager = request.app.state.library_manager
    result = library_manager.ingest(
        src=body.src,
        custom_title=body.custom_title,
        overwrite=body.overwrite,
    )
    return result


@app.delete("/api/library/{title}")
def delete_doc(title: str, request: Request, current_user: User = Depends(get_current_user)):
    library_manager: LibraryManager = request.app.state.library_manager
    library_manager.delete_doc(title)
    return {"message": f"deleted: {title}"}


@app.get("/api/sessions")
def list_sessions(current_user: User = Depends(get_current_user)) -> list[ChatSessionSummary]:
    with session_scope() as db:
        sessions = ChatRepository(db).list_sessions(current_user.id)
        return [_session_summary(session) for session in sessions]


@app.get("/api/sessions/{session_id}")
def get_session_detail(session_id: str, request: Request, current_user: User = Depends(get_current_user)) -> ChatSessionDetail:
    with session_scope() as db:
        session = ChatRepository(db).get_user_session(session_id, current_user.id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        report = None
        if session.report_file_id:
            data_dir = request.app.state.orchestrator.config.data_dir
            path = _report_path(data_dir, current_user.id, session.report_file_id)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                report = ReportContent(
                    report_file_id=session.report_file_id,
                    title=_extract_title_from_markdown(content, session.title),
                    content=content,
                )
        return ChatSessionDetail(
            **_session_summary(session).model_dump(),
            messages=[
                {
                    "role": message.role,
                    "message_type": message.message_type,
                    "content": message.content,
                    "created_at": message.created_at.isoformat(),
                    "extra": message.extra,
                }
                for message in session.messages
            ],
            steps=[
                {
                    "sequence": step.sequence,
                    "step_type": step.step_type,
                    "title": step.title,
                    "content": step.content,
                    "report_file_id": step.report_file_id,
                    "created_at": step.created_at.isoformat(),
                    "extra": step.extra,
                }
                for step in sorted(session.steps, key=lambda item: item.sequence)
            ],
            report=report,
        )


def format_sse_events(events, llm_client: LLMClient, session_id: str):
    try:
        for event in events:
            for node_name, output in event.items():
                if node_name == "plan_node":
                    event_type = "plan"
                    data = {
                        "sub_questions": [
                            {"label": sq.label, "question": sq.question}
                            for sq in output["sub_questions"]
                        ]
                    }
                    _record_step(session_id, "plan", f"共分解出 {len(output['sub_questions'])} 个子问题", extra=data)

                elif node_name == "research_node":
                    event_type = "research"
                    question, note = output["pending_review_pairs"][0]
                    data = {
                        "question": question,
                        "preview": note[:PREVIEW_LENGTH] + "...",
                        "tool_call_counts": output.get("tool_call_counts", {}),
                    }
                    _record_step(session_id, "research", "资料收集完成", content=question, extra=data)

                elif node_name == "review_node":
                    event_type = "review"
                    data = {
                        "round": output["refine_round"],
                        "review_summary": [
                            {
                                "question": r["question"],
                                "verdict": r["verdict"],
                                "failed": r["failed"],
                                "evidence": r.get("evidence", {}),
                            }
                            for r in output["review_summary"]
                        ],
                        "missing_dimensions": output.get("missing_dimensions", ""),
                    }
                    _record_step(session_id, "review", f"审查 · 第 {output['refine_round']} 轮", extra=data)

                elif node_name == "write_node":
                    event_type = "write"
                    data = {
                        "report": output["final_report"],
                        "report_file_id": output.get("report_file_id"),
                    }
                    report_file_id = output.get("report_file_id")
                    with session_scope() as db:
                        repo = ChatRepository(db)
                        repo.update_session(session_id, report_file_id=report_file_id, status="report_ready")
                        repo.add_step(
                            session_id,
                            "write",
                            "报告已生成",
                            report_file_id=report_file_id,
                            extra={"report_file_id": report_file_id},
                        )
                        repo.add_message(
                            session_id,
                            "assistant",
                            "报告已生成",
                            "report",
                            {"report_file_id": report_file_id},
                        )

                else:
                    continue

                yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        stats_data = {
            "total_calls": llm_client.total_calls,
            "prompt_tokens": llm_client.total_prompt_tokens,
            "completion_tokens": llm_client.total_completion_tokens,
            "total_tokens": llm_client.total_prompt_tokens
            + llm_client.total_completion_tokens,
        }
        yield f"event: stats\ndata: {json.dumps(stats_data, ensure_ascii=False)}\n\n"

    except Exception as e:
        # error event
        yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"


def _safe_path_part(value: str, default: str = "default") -> str:
    return Pipeline._safe_path_part(value, default)


def _user_search_cache_dir(data_dir: str, user_id: str) -> str:
    return os.path.join(data_dir, Pipeline.SEARCH_CACHE_DIR, _safe_path_part(user_id))


def _report_path(data_dir: str, user_id: str, report_file_id: str) -> str:
    safe_file = os.path.basename(report_file_id)
    return os.path.join(_user_search_cache_dir(data_dir, user_id), safe_file)


def _extract_title_from_markdown(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or fallback
    return fallback


def _record_step(
    session_id: str,
    step_type: str,
    title: str,
    *,
    content: str | None = None,
    extra: dict | None = None,
):
    with session_scope() as db:
        ChatRepository(db).add_step(
            session_id,
            step_type,
            title,
            content=content,
            extra=extra,
        )


def _user_info(user: User) -> UserInfo:
    return UserInfo(
        id=user.id,
        username=user.username or user.id,
        display_name=user.display_name or user.username or user.id,
    )


def _session_summary(session) -> ChatSessionSummary:
    return ChatSessionSummary(
        id=session.id,
        title=session.title,
        raw_query=session.raw_query,
        research_brief=session.research_brief,
        report_file_id=session.report_file_id,
        status=session.status,
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
    )

import json
import logging
import os
import re
import shutil
import tempfile

from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request, UploadFile
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from client.agents import Clarifier
from client.agents.report_qa import answer_report_question
from client.api.auth import create_access_token, get_current_user, hash_password, verify_password
from client.base import LLMClient, setup_logging
from client.config import Config
from client.db import ChatRepository, init_db, session_scope
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
    ReportVersionOut,
    ResearchTaskOut,
    TurnRequest,
    UserInfo,
)

logger = logging.getLogger(__name__)

PREVIEW_LENGTH = 150
SESSION_SUMMARY_PROMPT = """Summarize this research conversation for future turns. Preserve the user's goal, active research task, report version, requested changes, decisions, unresolved gaps, and useful source names. Do not invent facts. Keep the summary concise and in the conversation's language."""


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


@app.post("/api/chat/turns")
def chat_turn(body: TurnRequest, request: Request, current_user: User = Depends(get_current_user)):
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="消息不能为空")

    with session_scope() as db:
        repo = ChatRepository(db)
        if body.session_id:
            session = repo.get_user_session(body.session_id, current_user.id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
        else:
            session = repo.create_session(current_user.id, message)

        workspace = repo.get_or_create_workspace(session.id)
        tasks = repo.list_research_tasks(session.id)
        task = None
        if body.task_id:
            task = repo.get_session_research_task(body.task_id, session.id)
            if not task:
                raise HTTPException(status_code=404, detail="Research task not found")
        elif workspace.active_task_id:
            task = repo.get_session_research_task(workspace.active_task_id, session.id)

        version = None
        if body.report_version_id:
            version = repo.get_report_version(body.report_version_id)
            if not version or version.task_id not in {item.id for item in tasks}:
                raise HTTPException(status_code=404, detail="Report version not found")
            version_task = repo.get_session_research_task(version.task_id, session.id)
            if not version_task or (task and task.id != version_task.id):
                raise HTTPException(status_code=404, detail="Report version not found")
            task = version_task
        elif task:
            version = repo.get_latest_report_version(task.id)
        if body.report_version_id and not version:
            raise HTTPException(status_code=404, detail="Report version not found")
        if body.task_id and task:
            repo.update_workspace(session.id, active_task_id=task.id)
        if body.session_id:
            repo.add_message(session.id, "user", message, "turn")

        history = [
            {"role": item.role, "content": item.content}
            for item in session.messages[-8:]
        ]
        if not history or history[-1]["content"] != message:
            history.append({"role": "user", "content": message})

        workspace_context = _turn_workspace_context(
            repo=repo,
            session=session,
            workspace=workspace,
            tasks=tasks,
            active_task=task,
            active_version=version,
            history=history,
        )
        session_id = session.id
        pending = dict(workspace.pending_clarification or {})
        legacy_report_file_id = session.report_file_id

    clarifier: Clarifier = request.app.state.clarifier
    pending_intent = pending.get("intent")
    if pending_intent:
        workspace_context["clarification_original_message"] = pending.get("original_message", "")
    decision = clarifier.route_turn(message, workspace_context)
    if pending_intent:
        decision.intent = pending_intent
        decision.research_brief = decision.research_brief or pending.get("research_brief", "")
        decision.target_section = decision.target_section or pending.get("target_section", "")
        if not decision.needs_clarification:
            decision.resolved_query = decision.resolved_query or f"{pending.get('original_message', '')} {message}".strip()
            with session_scope() as db:
                ChatRepository(db).update_workspace(session_id, pending_clarification=None)
    if decision.intent in {"supplementary_research", "deepening"} and (
        (not task and not legacy_report_file_id) or (task and not version)
    ):
        decision.needs_clarification = True
        decision.message = "请先选择一份已有研究报告，或告诉我需要补充/深化的研究主题。"
        decision.directions = []

    if decision.needs_clarification:
        pending_state = {
            "intent": decision.intent,
            "original_message": pending.get("original_message") or message,
            "clarification_messages": (pending.get("clarification_messages") or []) + [message],
            "research_brief": decision.research_brief or pending.get("research_brief", ""),
            "target_section": decision.target_section or pending.get("target_section", ""),
            "directions": decision.directions,
        }
        with session_scope() as db:
            repo = ChatRepository(db)
            repo.update_workspace(session_id, pending_clarification=pending_state)
            repo.add_message(
                session_id,
                "assistant",
                decision.message,
                "clarification",
                {"directions": decision.directions, "intent": decision.intent},
            )
            _update_session_summary(
                repo,
                session_id,
                message,
                decision.message,
                llm_client=request.app.state.orchestrator.llm_client,
            )

        def clarification_stream():
            yield _sse("session", {"session_id": session_id})
            yield _sse("route", {"intent": decision.intent})
            yield _sse("clarification", {"message": decision.message, "directions": decision.directions})

        return StreamingResponse(clarification_stream(), media_type="text/event-stream")

    if decision.intent == "report_qa":
        orchestrator: Orchestrator = request.app.state.orchestrator
        source_file_id = version.report_file_id if version else legacy_report_file_id
        sources = orchestrator.rag_pipeline.retrieve_with_sources(
            query=decision.resolved_query or message,
            user_id=current_user.id,
            preferred_file_id=source_file_id,
        )
        answer = answer_report_question(orchestrator.llm_client, decision.resolved_query or message, sources)
        with session_scope() as db:
            repo = ChatRepository(db)
            repo.add_message(
                session_id,
                "assistant",
                answer,
                "answer",
                {"sources": sources, "task_id": task.id if task else None, "resolved_query": decision.resolved_query or message},
            )
            _update_session_summary(repo, session_id, message, answer, llm_client=orchestrator.llm_client)

        def answer_stream():
            yield _sse("session", {"session_id": session_id, "task_id": task.id if task else None})
            yield _sse("route", {"intent": decision.intent, "task_id": task.id if task else None})
            yield _sse("answer", {"content": answer, "sources": sources})

        return StreamingResponse(answer_stream(), media_type="text/event-stream")

    orchestrator: Orchestrator = request.app.state.orchestrator
    with session_scope() as db:
        repo = ChatRepository(db)
        if decision.intent == "initial_research":
            task = repo.create_research_task(
                session_id,
                title=(decision.research_brief or message).strip()[:120],
                scope=decision.research_brief or message,
                workspace={"approved_notes": [], "source_registry": [], "coverage_map": [], "open_gaps": ""},
            )
            version = None
        elif task is None and legacy_report_file_id:
            task = _create_legacy_report_task(repo, session_id, legacy_report_file_id, message, request)
            version = repo.get_latest_report_version(task.id)

        if task is None:
            raise HTTPException(status_code=400, detail="A research task could not be resolved")

        if decision.intent in {"supplementary_research", "deepening"} and version is None:
            version = repo.get_latest_report_version(task.id)
        parent_version_id = version.id if version else None
        run = repo.create_research_run(
            task.id,
            decision.intent,
            message,
            status="running",
            parent_version_id=parent_version_id,
        )
        repo.update_workspace(session_id, pending_clarification=None, active_task_id=task.id)
        repo.update_session(
            session_id,
            research_brief=decision.research_brief or task.scope,
            status="researching",
        )
        repo.update_research_task(task.id, status="running")
        task_id = task.id
        run_id = run.id
        parent_version = version
        task_scope = task.scope
        task_workspace = dict(task.workspace or {})
        prior_notes = [
            (item.get("question", ""), item.get("note", ""))
            for item in task_workspace.get("approved_notes", [])
            if item.get("note")
        ]

    previous_report = ""
    if parent_version:
        report_path = _report_path(
            orchestrator.config.data_dir,
            current_user.id,
            parent_version.report_file_id,
        )
        if os.path.exists(report_path):
            with open(report_path, "r", encoding="utf-8") as f:
                previous_report = f.read()

    research_brief = decision.research_brief or message
    if decision.intent == "deepening" and decision.target_section:
        research_brief = f"{research_brief}\n重点深化报告章节：{decision.target_section}。"
    planning_context = json.dumps(
        {
            "task_scope": task_scope,
            "coverage_map": task_workspace.get("coverage_map", []),
            "open_gaps": task_workspace.get("open_gaps", ""),
            "source_registry": task_workspace.get("source_registry", []),
            "target_section": decision.target_section,
        },
        ensure_ascii=False,
    )
    feedback_items = [decision.research_brief or message]
    if decision.intent in {"supplementary_research", "deepening"}:
        gaps = task_workspace.get("open_gaps", "")
        sources = task_workspace.get("source_registry", [])
        if gaps:
            feedback_items.append(f"之前评审发现的缺口：{gaps}")
        if sources:
            feedback_items.append("已有来源，除非能提供新的证据角度，否则避免重复：\n" + "\n".join(sources))
    research_feedback = "\n".join(feedback_items)
    stats_baseline = {
        "total_calls": orchestrator.llm_client.total_calls,
        "prompt_tokens": orchestrator.llm_client.total_prompt_tokens,
        "completion_tokens": orchestrator.llm_client.total_completion_tokens,
    }
    events = orchestrator.run_research(
        research_brief,
        user_id=current_user.id,
        base_research_brief=task_scope,
        intent=decision.intent,
        task_id=task_id,
        run_id=run_id,
        parent_version_id=parent_version_id or "",
        planning_context=planning_context,
        research_feedback=research_feedback,
        prior_notes=prior_notes,
        previous_report=previous_report,
    )

    def research_stream():
        yield _sse("session", {"session_id": session_id, "task_id": task_id, "run_id": run_id})
        yield _sse("route", {
            "intent": decision.intent,
            "task_id": task_id,
            "run_id": run_id,
            "report_version_id": parent_version_id,
        })
        yield from format_sse_events(
            events=events,
            llm_client=orchestrator.llm_client,
            session_id=session_id,
            task_id=task_id,
            run_id=run_id,
            intent=decision.intent,
            parent_version_id=parent_version_id,
            user_message=message,
            stats_baseline=stats_baseline,
        )

    return StreamingResponse(research_stream(), media_type="text/event-stream")


@app.get("/api/library")
def list_docs(request: Request, current_user: User = Depends(get_current_user)):
    library_manager = _library_manager_for_user(request, current_user)
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
    library_manager = _library_manager_for_user(request, current_user)
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
    library_manager = _library_manager_for_user(request, current_user)
    result = library_manager.ingest(
        src=body.src,
        custom_title=body.custom_title,
        overwrite=body.overwrite,
    )
    return result


@app.delete("/api/library/{title}")
def delete_doc(title: str, request: Request, current_user: User = Depends(get_current_user)):
    library_manager = _library_manager_for_user(request, current_user)
    library_manager.delete_doc(title)
    return {"message": f"deleted: {title}"}


@app.get("/api/sessions")
def list_sessions(current_user: User = Depends(get_current_user)) -> list[ChatSessionSummary]:
    with session_scope() as db:
        sessions = ChatRepository(db).list_sessions(current_user.id)
        return [_session_summary(session) for session in sessions]


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, current_user: User = Depends(get_current_user)):
    with session_scope() as db:
        if not ChatRepository(db).delete_session(session_id, current_user.id):
            raise HTTPException(status_code=404, detail="Session not found")
    return {"message": "deleted"}


@app.get("/api/sessions/{session_id}")
def get_session_detail(session_id: str, request: Request, current_user: User = Depends(get_current_user)) -> ChatSessionDetail:
    with session_scope() as db:
        session = ChatRepository(db).get_user_session(session_id, current_user.id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        repo = ChatRepository(db)
        workspace = repo.get_or_create_workspace(session_id)
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
        task_outputs = []
        for task in repo.list_research_tasks(session_id):
            versions = []
            task_versions = repo.list_report_versions(task.id)
            for item in task_versions:
                path = _report_path(request.app.state.orchestrator.config.data_dir, current_user.id, item.report_file_id)
                content = ""
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                versions.append(ReportVersionOut(
                    id=item.id,
                    run_id=item.run_id,
                    report_file_id=item.report_file_id,
                    title=item.title,
                    version_number=item.version_number,
                    parent_version_id=item.parent_version_id,
                    created_at=item.created_at.isoformat(),
                    content=content,
                ))
            runs = repo.list_research_runs(task.id)
            task_outputs.append(ResearchTaskOut(
                id=task.id,
                title=task.title,
                scope=task.scope,
                status=task.status,
                intent=runs[-1].intent if runs else None,
                current_version_id=versions[-1].id if versions else None,
                versions=versions,
            ))
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
            tasks=task_outputs,
            active_task_id=workspace.active_task_id,
        )


def format_sse_events(
    events,
    llm_client: LLMClient,
    session_id: str,
    *,
    task_id: str | None = None,
    run_id: str | None = None,
    intent: str | None = None,
    parent_version_id: str | None = None,
    user_message: str = "",
    stats_baseline: dict | None = None,
):
    run_completed = False
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
                    if task_id:
                        data["task_id"] = task_id
                    if run_id:
                        data["run_id"] = run_id
                    _record_step(session_id, "plan", f"共分解出 {len(output['sub_questions'])} 个子问题", extra=data)

                elif node_name == "research_node":
                    event_type = "research"
                    question, note = output["pending_review_pairs"][0]
                    data = {
                        "question": question,
                        "preview": note[:PREVIEW_LENGTH] + "...",
                        "tool_call_counts": output.get("tool_call_counts", {}),
                    }
                    if task_id:
                        data["task_id"] = task_id
                    if run_id:
                        data["run_id"] = run_id
                        data["note"] = note
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
                    if task_id:
                        data["task_id"] = task_id
                    if run_id:
                        data["run_id"] = run_id
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
                        version = None
                        if task_id and run_id and report_file_id:
                            title = _extract_title_from_markdown(output["final_report"], "Research report")
                            version = repo.create_report_version(
                                task_id,
                                run_id,
                                report_file_id,
                                title,
                                parent_version_id=parent_version_id,
                            )
                            task = repo.get_research_task(task_id)
                            task_workspace = dict(task.workspace or {})
                            note_pairs = output.get("prior_notes", []) + output.get("approved_pairs", [])
                            notes_by_question = {
                                question: note for question, note in note_pairs if question and note
                            }
                            all_notes = [
                                {"question": question, "note": note}
                                for question, note in notes_by_question.items()
                            ]
                            task_workspace.update({
                                "approved_notes": all_notes,
                                "coverage_map": list(notes_by_question),
                                "open_gaps": output.get("missing_dimensions", ""),
                                "source_registry": sorted(set(re.findall(
                                    r"https?://[^\s)>]+",
                                    "\n".join(notes_by_question.values()),
                                ))),
                                "report_outline": [
                                    line.lstrip("# ").strip()
                                    for line in output["final_report"].splitlines()
                                    if line.startswith("## ")
                                ],
                            })
                            repo.update_research_task(task_id, workspace=task_workspace)
                            repo.update_research_task(task_id, status="completed")
                            repo.update_research_run(run_id, status="completed", error=None)
                            repo.update_workspace(session_id, active_task_id=task_id)
                            data.update({
                                "task_id": task_id,
                                "run_id": run_id,
                                "report_version_id": version.id,
                                "version_id": version.id,
                                "version_number": version.version_number,
                                "title": title,
                            })
                            run_completed = True
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
                            f"报告已生成{f'（第 {version.version_number} 版）' if version else ''}",
                            "report",
                            {
                                "report_file_id": report_file_id,
                                "task_id": task_id,
                                "run_id": run_id,
                                "report_version_id": version.id if version else None,
                            },
                        )
                        if run_id:
                            _update_session_summary(
                                repo,
                                session_id,
                                user_message,
                                f"已完成{intent or 'research'}，生成报告 {title if version else report_file_id}。",
                                llm_client=llm_client,
                            )

                else:
                    continue

                yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        baseline = stats_baseline or {}
        stats_data = {
            "total_calls": llm_client.total_calls - baseline.get("total_calls", 0),
            "prompt_tokens": llm_client.total_prompt_tokens - baseline.get("prompt_tokens", 0),
            "completion_tokens": llm_client.total_completion_tokens - baseline.get("completion_tokens", 0),
        }
        stats_data["total_tokens"] = stats_data["prompt_tokens"] + stats_data["completion_tokens"]
        if task_id:
            stats_data["task_id"] = task_id
        if run_id:
            stats_data["run_id"] = run_id
        yield f"event: stats\ndata: {json.dumps(stats_data, ensure_ascii=False)}\n\n"

    except Exception as e:
        if run_id:
            _mark_run_failed(run_id, session_id, str(e))
            run_completed = True
        yield f"event: error\ndata: {json.dumps({'message': str(e), 'task_id': task_id, 'run_id': run_id})}\n\n"
    finally:
        if run_id and not run_completed:
            _mark_run_failed(run_id, session_id, "Research stream ended before report creation")


def _safe_path_part(value: str, default: str = "default") -> str:
    return Pipeline._safe_path_part(value, default)


def _library_manager_for_user(request: Request, current_user: User):
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator:
        return orchestrator.create_library_manager(current_user.id)
    return request.app.state.library_manager


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


def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _turn_workspace_context(
    *,
    repo: ChatRepository,
    session,
    workspace,
    tasks,
    active_task,
    active_version,
    history: list[dict[str, str]],
) -> dict:
    task_context = []
    for task in tasks:
        latest = repo.get_latest_report_version(task.id)
        task_context.append({
            "task_id": task.id,
            "title": task.title,
            "scope": task.scope,
            "status": task.status,
            "latest_report": {
                "version_id": latest.id,
                "version_number": latest.version_number,
                "title": latest.title,
            } if latest else None,
            "open_gaps": (task.workspace or {}).get("open_gaps", ""),
        })

    legacy_report = None
    if session.report_file_id and not tasks:
        legacy_report = {
            "report_file_id": session.report_file_id,
            "research_brief": session.research_brief or session.raw_query,
        }
    return {
        "summary": workspace.summary,
        "pending_clarification": workspace.pending_clarification,
        "active_task_id": active_task.id if active_task else workspace.active_task_id,
        "active_report": {
            "task_id": active_task.id,
            "version_id": active_version.id if active_version else None,
            "title": active_version.title if active_version else active_task.title,
            "version_number": active_version.version_number if active_version else None,
        } if active_task else legacy_report,
        "research_tasks": task_context,
        "recent_messages": history,
    }


def _update_session_summary(
    repo: ChatRepository,
    session_id: str,
    user_message: str,
    assistant_message: str,
    *,
    llm_client: LLMClient | None = None,
) -> None:
    workspace = repo.get_or_create_workspace(session_id)
    updated = "\n".join(
        part for part in (
            workspace.summary.strip(),
            f"用户：{user_message.strip()}",
            f"助手：{assistant_message.strip()}",
        ) if part
    )
    if len(updated) > 6000 and llm_client:
        try:
            response = llm_client.invoke(
                messages=[
                    {"role": "system", "content": SESSION_SUMMARY_PROMPT},
                    {"role": "user", "content": updated},
                ],
                temperature=0,
                tag="session:summarize",
            )
            updated = response.content.strip()[:5000]
        except Exception as exc:
            logger.warning("[Session] summary compaction failed: %s", exc)
    if len(updated) > 6000:
        updated = updated[-6000:]
    repo.update_workspace(session_id, summary=updated)


def _create_legacy_report_task(
    repo: ChatRepository,
    session_id: str,
    report_file_id: str,
    message: str,
    request: Request,
):
    session = repo.get_session(session_id)
    scope = session.research_brief or session.raw_query
    report_path = _report_path(
        request.app.state.orchestrator.config.data_dir,
        session.user_id,
        report_file_id,
    )
    content = ""
    if os.path.exists(report_path):
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()
    title = _extract_title_from_markdown(content, session.title)
    task = repo.create_research_task(
        session_id,
        title,
        scope,
        workspace={
            "approved_notes": [{"question": scope, "note": content}] if content else [],
            "source_registry": sorted(set(re.findall(r"https?://[^\s)>]+", content))),
            "coverage_map": [scope] if content else [],
            "open_gaps": "",
        },
    )
    baseline = repo.create_research_run(
        task.id,
        "initial_research",
        session.raw_query,
        status="completed",
    )
    repo.create_report_version(task.id, baseline.id, report_file_id, title)
    repo.update_workspace(session_id, active_task_id=task.id)
    return task


def _mark_run_failed(run_id: str, session_id: str, error: str) -> None:
    with session_scope() as db:
        repo = ChatRepository(db)
        run = repo.get_research_run(run_id)
        if not run or run.status == "completed":
            return
        repo.update_research_run(run_id, status="failed", error=error)
        session = repo.get_session(session_id)
        if session:
            repo.update_session(
                session_id,
                status="report_ready" if session.report_file_id else "failed",
            )
        task = repo.get_research_task(run.task_id)
        if task:
            latest_version = repo.get_latest_report_version(task.id)
            repo.update_research_task(task.id, status="completed" if latest_version else "failed")
        repo.add_message(session_id, "assistant", f"本轮研究未完成：{error}", "error", {"run_id": run_id})


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

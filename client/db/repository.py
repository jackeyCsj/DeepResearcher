from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    ChatMessage,
    ChatSession,
    ReportVersion,
    ResearchRun,
    ResearchStep,
    ResearchTask,
    SessionWorkspace,
    User,
)


_UNSET = object()


class ChatRepository:
    def __init__(self, db: Session):
        self.db = db

    def ensure_user(self, user_id: str, display_name: str | None = None) -> User:
        user = self.db.get(User, user_id)
        if user:
            return user
        user = User(id=user_id, username=user_id, display_name=display_name)
        self.db.add(user)
        self.db.flush()
        return user

    def get_user_by_username(self, username: str) -> User | None:
        return self.db.scalar(select(User).where(User.username == username))

    def create_user(self, username: str, password_hash: str, display_name: str | None = None) -> User:
        user = User(
            id=str(uuid.uuid4()),
            username=username,
            password_hash=password_hash,
            display_name=display_name or username,
        )
        self.db.add(user)
        self.db.flush()
        return user

    def list_sessions(self, user_id: str) -> list[ChatSession]:
        return list(
            self.db.scalars(
                select(ChatSession)
                .where(ChatSession.user_id == user_id)
                .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
            )
        )

    def get_user_session(self, session_id: str, user_id: str) -> ChatSession | None:
        return self.db.scalar(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == user_id,
            )
        )

    def delete_session(self, session_id: str, user_id: str) -> bool:
        # ChatSession.messages / .steps 都配了 cascade="all, delete-orphan"，
        # 删会话会级联删掉聊天消息与研究步骤。
        session = self.get_user_session(session_id, user_id)
        if not session:
            return False
        self.db.delete(session)
        return True

    def create_session(self, user_id: str, raw_query: str) -> ChatSession:
        self.ensure_user(user_id)
        title = raw_query.strip()[:80] or "Untitled research"
        session = ChatSession(
            user_id=user_id,
            title=title,
            raw_query=raw_query,
            status="clarifying",
        )
        self.db.add(session)
        self.db.flush()
        self.add_message(session.id, "user", raw_query, "query")
        return session

    def get_session(self, session_id: str) -> ChatSession | None:
        return self.db.get(ChatSession, session_id)

    def update_session(
        self,
        session_id: str,
        *,
        research_brief: str | None = None,
        report_file_id: str | None = None,
        status: str | None = None,
    ) -> ChatSession | None:
        session = self.get_session(session_id)
        if not session:
            return None
        if research_brief is not None:
            session.research_brief = research_brief
        if report_file_id is not None:
            session.report_file_id = report_file_id
        if status is not None:
            session.status = status
        self.db.flush()
        return session

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_type: str = "chat",
        extra: dict | None = None,
    ) -> ChatMessage:
        message = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            message_type=message_type,
            extra=extra,
        )
        self.db.add(message)
        self.db.flush()
        return message

    def add_step(
        self,
        session_id: str,
        step_type: str,
        title: str,
        *,
        content: str | None = None,
        report_file_id: str | None = None,
        extra: dict | None = None,
    ) -> ResearchStep:
        sequence = self.db.scalar(
            select(func.coalesce(func.max(ResearchStep.sequence), 0)).where(
                ResearchStep.session_id == session_id
            )
        ) + 1
        step = ResearchStep(
            session_id=session_id,
            sequence=sequence,
            step_type=step_type,
            title=title,
            content=content,
            report_file_id=report_file_id,
            extra=extra,
        )
        self.db.add(step)
        self.db.flush()
        return step

    def create_workspace(
        self,
        session_id: str,
        *,
        summary: str = "",
        pending_clarification: dict | None = None,
        active_task_id: str | None = None,
    ) -> SessionWorkspace:
        if not self.get_session(session_id):
            raise ValueError(f"Unknown session: {session_id}")
        if active_task_id is not None:
            self._get_task_for_session(active_task_id, session_id)
        workspace = SessionWorkspace(
            session_id=session_id,
            summary=summary,
            pending_clarification=pending_clarification,
            active_task_id=active_task_id,
        )
        self.db.add(workspace)
        self.db.flush()
        return workspace

    def get_workspace(self, session_id: str) -> SessionWorkspace | None:
        return self.db.get(SessionWorkspace, session_id)

    def get_or_create_workspace(self, session_id: str) -> SessionWorkspace:
        return self.get_workspace(session_id) or self.create_workspace(session_id)

    def update_workspace(
        self,
        session_id: str,
        *,
        summary: str | None = None,
        pending_clarification: dict | None | Any = _UNSET,
        active_task_id: str | None | Any = _UNSET,
    ) -> SessionWorkspace | None:
        workspace = self.get_workspace(session_id)
        if not workspace:
            return None
        if summary is not None:
            workspace.summary = summary
        if pending_clarification is not _UNSET:
            workspace.pending_clarification = pending_clarification
        if active_task_id is not _UNSET:
            if active_task_id is not None:
                self._get_task_for_session(active_task_id, session_id)
            workspace.active_task_id = active_task_id
        self.db.flush()
        return workspace

    def create_research_task(
        self,
        session_id: str,
        title: str,
        scope: str,
        *,
        workspace: dict | None = None,
        status: str = "active",
    ) -> ResearchTask:
        if not self.get_session(session_id):
            raise ValueError(f"Unknown session: {session_id}")
        task = ResearchTask(
            session_id=session_id,
            title=title,
            scope=scope,
            workspace=workspace or {},
            status=status,
        )
        self.db.add(task)
        self.db.flush()
        return task

    def get_research_task(self, task_id: str) -> ResearchTask | None:
        return self.db.get(ResearchTask, task_id)

    def get_session_research_task(self, task_id: str, session_id: str) -> ResearchTask | None:
        return self.db.scalar(
            select(ResearchTask).where(
                ResearchTask.id == task_id,
                ResearchTask.session_id == session_id,
            )
        )

    def list_research_tasks(self, session_id: str) -> list[ResearchTask]:
        return list(
            self.db.scalars(
                select(ResearchTask)
                .where(ResearchTask.session_id == session_id)
                .order_by(ResearchTask.created_at, ResearchTask.id)
            )
        )

    def update_research_task(
        self,
        task_id: str,
        *,
        title: str | None = None,
        scope: str | None = None,
        workspace: dict | None = None,
        status: str | None = None,
    ) -> ResearchTask | None:
        task = self.get_research_task(task_id)
        if not task:
            return None
        if title is not None:
            task.title = title
        if scope is not None:
            task.scope = scope
        if workspace is not None:
            task.workspace = workspace
        if status is not None:
            task.status = status
        self.db.flush()
        return task

    def create_research_run(
        self,
        task_id: str,
        intent: str,
        user_message: str,
        *,
        status: str = "queued",
        parent_version_id: str | None = None,
    ) -> ResearchRun:
        task = self.get_research_task(task_id)
        if not task:
            raise ValueError(f"Unknown research task: {task_id}")
        if parent_version_id is not None:
            self._get_version_for_task(parent_version_id, task_id)
        run = ResearchRun(
            task_id=task_id,
            intent=intent,
            user_message=user_message,
            status=status,
            parent_version_id=parent_version_id,
        )
        self.db.add(run)
        self.db.flush()
        return run

    def get_research_run(self, run_id: str) -> ResearchRun | None:
        return self.db.get(ResearchRun, run_id)

    def list_research_runs(self, task_id: str) -> list[ResearchRun]:
        return list(
            self.db.scalars(
                select(ResearchRun)
                .where(ResearchRun.task_id == task_id)
                .order_by(ResearchRun.created_at, ResearchRun.id)
            )
        )

    def update_research_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        error: str | None | Any = _UNSET,
        parent_version_id: str | None | Any = _UNSET,
    ) -> ResearchRun | None:
        run = self.get_research_run(run_id)
        if not run:
            return None
        if status is not None:
            run.status = status
        if error is not _UNSET:
            run.error = error
        if parent_version_id is not _UNSET:
            if parent_version_id is not None:
                self._get_version_for_task(parent_version_id, run.task_id)
            run.parent_version_id = parent_version_id
        self.db.flush()
        return run

    def create_report_version(
        self,
        task_id: str,
        run_id: str,
        report_file_id: str,
        title: str,
        *,
        parent_version_id: str | None = None,
    ) -> ReportVersion:
        run = self.get_research_run(run_id)
        if not run or run.task_id != task_id:
            raise ValueError("Research run does not belong to the given task")
        if parent_version_id is not None:
            self._get_version_for_task(parent_version_id, task_id)
        version_number = self.db.scalar(
            select(func.coalesce(func.max(ReportVersion.version_number), 0)).where(
                ReportVersion.task_id == task_id
            )
        ) + 1
        version = ReportVersion(
            task_id=task_id,
            run_id=run_id,
            version_number=version_number,
            parent_version_id=parent_version_id,
            report_file_id=report_file_id,
            title=title,
        )
        self.db.add(version)
        self.db.flush()
        return version

    def get_report_version(self, version_id: str) -> ReportVersion | None:
        return self.db.get(ReportVersion, version_id)

    def list_report_versions(self, task_id: str) -> list[ReportVersion]:
        return list(
            self.db.scalars(
                select(ReportVersion)
                .where(ReportVersion.task_id == task_id)
                .order_by(ReportVersion.version_number)
            )
        )

    def get_latest_report_version(self, task_id: str) -> ReportVersion | None:
        return self.db.scalar(
            select(ReportVersion)
            .where(ReportVersion.task_id == task_id)
            .order_by(ReportVersion.version_number.desc())
            .limit(1)
        )

    def _get_task_for_session(self, task_id: str, session_id: str) -> ResearchTask:
        task = self.get_session_research_task(task_id, session_id)
        if not task:
            raise ValueError("Research task does not belong to the given session")
        return task

    def _get_version_for_task(self, version_id: str, task_id: str) -> ReportVersion:
        version = self.get_report_version(version_id)
        if not version or version.task_id != task_id:
            raise ValueError("Report version does not belong to the given task")
        return version

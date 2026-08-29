from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import ChatMessage, ChatSession, ResearchStep, User


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

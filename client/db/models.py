from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str | None] = mapped_column(String(100), unique=True, index=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    sessions: Mapped[list["ChatSession"]] = relationship(back_populates="user")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    raw_query: Mapped[str] = mapped_column(Text)
    research_brief: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_file_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="clarifying")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.id")
    steps: Mapped[list["ResearchStep"]] = relationship(back_populates="session", cascade="all, delete-orphan", order_by="ResearchStep.sequence")
    workspace: Mapped["SessionWorkspace | None"] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        uselist=False,
    )
    research_tasks: Mapped[list["ResearchTask"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ResearchTask.created_at",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    message_type: Mapped[str] = mapped_column(String(64), default="chat")
    content: Mapped[str] = mapped_column(Text)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped[ChatSession] = relationship(back_populates="messages")


class ResearchStep(Base):
    __tablename__ = "research_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    step_type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_file_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped[ChatSession] = relationship(back_populates="steps")


class SessionWorkspace(Base):
    __tablename__ = "session_workspaces"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    pending_clarification: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    active_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("research_tasks.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    session: Mapped[ChatSession] = relationship(back_populates="workspace")
    active_task: Mapped["ResearchTask | None"] = relationship(
        foreign_keys=[active_task_id], post_update=True
    )


class ResearchTask(Base):
    __tablename__ = "research_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    scope: Mapped[str] = mapped_column(Text)
    workspace: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    session: Mapped[ChatSession] = relationship(back_populates="research_tasks")
    runs: Mapped[list["ResearchRun"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="ResearchRun.created_at",
    )
    report_versions: Mapped[list["ReportVersion"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="ReportVersion.version_number",
    )


class ResearchRun(Base):
    __tablename__ = "research_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(
        ForeignKey("research_tasks.id", ondelete="CASCADE"), index=True
    )
    intent: Mapped[str] = mapped_column(String(32))
    user_message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    parent_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("report_versions.id", ondelete="SET NULL"), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    task: Mapped[ResearchTask] = relationship(back_populates="runs")
    parent_version: Mapped["ReportVersion | None"] = relationship(
        foreign_keys=[parent_version_id]
    )
    report_versions: Mapped[list["ReportVersion"]] = relationship(
        back_populates="run", foreign_keys="ReportVersion.run_id"
    )


class ReportVersion(Base):
    __tablename__ = "report_versions"
    __table_args__ = (
        UniqueConstraint("task_id", "version_number", name="uq_report_versions_task_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(
        ForeignKey("research_tasks.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("research_runs.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    parent_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("report_versions.id", ondelete="SET NULL"), nullable=True
    )
    report_file_id: Mapped[str] = mapped_column(String(500))
    title: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    task: Mapped[ResearchTask] = relationship(back_populates="report_versions")
    run: Mapped[ResearchRun] = relationship(
        back_populates="report_versions", foreign_keys=[run_id]
    )
    parent_version: Mapped["ReportVersion | None"] = relationship(
        remote_side=[id], back_populates="child_versions", foreign_keys=[parent_version_id]
    )
    child_versions: Mapped[list["ReportVersion"]] = relationship(
        back_populates="parent_version", foreign_keys=[parent_version_id]
    )

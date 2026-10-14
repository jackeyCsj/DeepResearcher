import pytest
from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.orm import Session

from client.db.models import (
    Base,
    ChatSession,
    ReportVersion,
    ResearchRun,
    ResearchTask,
    SessionWorkspace,
)
from client.db.repository import ChatRepository


def _make_db() -> tuple[Engine, Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine, Session(engine, expire_on_commit=False)


def test_workspace_and_report_versions_persist_as_a_chain():
    engine, db = _make_db()
    repo = ChatRepository(db)
    session = repo.create_session("user-1", "Research federated learning")
    task = repo.create_research_task(
        session.id,
        "Federated learning",
        "Research privacy and evaluation",
        workspace={"open_gaps": ["regulation"]},
    )
    repo.create_workspace(
        session.id,
        summary="The report compares privacy methods.",
        pending_clarification={"intent": "report_revision"},
        active_task_id=task.id,
    )
    first_run = repo.create_research_run(task.id, "new_research", "Research privacy methods")
    first_version = repo.create_report_version(
        task.id, first_run.id, "reports/v1.md", "Federated learning"
    )
    second_run = repo.create_research_run(
        task.id,
        "report_revision",
        "Add regulation coverage",
        parent_version_id=first_version.id,
    )
    second_version = repo.create_report_version(
        task.id,
        second_run.id,
        "reports/v2.md",
        "Federated learning",
        parent_version_id=first_version.id,
    )
    repo.update_research_run(second_run.id, status="completed", error=None)
    db.commit()
    db.close()

    reopened = Session(engine, expire_on_commit=False)
    repo = ChatRepository(reopened)
    workspace = repo.get_workspace(session.id)
    versions = repo.list_report_versions(task.id)

    assert workspace is not None
    assert workspace.summary == "The report compares privacy methods."
    assert workspace.pending_clarification == {"intent": "report_revision"}
    assert workspace.active_task_id == task.id
    assert repo.get_research_task(task.id).workspace == {"open_gaps": ["regulation"]}
    assert [version.version_number for version in versions] == [1, 2]
    assert versions[1].parent_version_id == versions[0].id
    assert repo.get_latest_report_version(task.id).id == versions[1].id
    assert repo.get_research_run(second_run.id).status == "completed"

    reopened.close()
    engine.dispose()


def test_workspace_rejects_task_from_another_session_and_session_delete_cascades():
    engine, db = _make_db()
    repo = ChatRepository(db)
    first_session = repo.create_session("user-1", "First topic")
    second_session = repo.create_session("user-1", "Second topic")
    task = repo.create_research_task(second_session.id, "Second topic", "Scope")

    with pytest.raises(ValueError, match="given session"):
        repo.create_workspace(first_session.id, active_task_id=task.id)

    repo.create_workspace(second_session.id, active_task_id=task.id)
    run = repo.create_research_run(task.id, "new_research", "Initial research")
    repo.create_report_version(task.id, run.id, "reports/topic.md", "Second topic")
    db.commit()

    assert repo.delete_session(second_session.id, "user-1")
    db.commit()
    assert db.scalar(select(func.count()).select_from(SessionWorkspace)) == 0
    assert db.scalar(select(func.count()).select_from(ResearchTask)) == 0
    assert db.scalar(select(func.count()).select_from(ResearchRun)) == 0
    assert db.scalar(select(func.count()).select_from(ReportVersion)) == 0
    assert db.get(ChatSession, first_session.id) is not None

    db.close()
    engine.dispose()

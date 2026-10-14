import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from client.agents.clarifier import Clarifier
from client.agents.report_qa import answer_report_question
from client.api import app as api_module
from client.api.schemas import TurnRequest
from client.db.models import Base, ChatMessage
from client.db.repository import ChatRepository
from client.rag.document import Chunk
from client.rag.pipeline import Pipeline


class FakeLLM:
    def __init__(self, content=None):
        self.content = content
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        if self.content is None:
            return SimpleNamespace(
                tool_calls=[
                    SimpleNamespace(
                        function=SimpleNamespace(
                            arguments=json.dumps({
                                "intent": "report_qa",
                                "needs_clarification": False,
                                "message": "",
                                "directions": [],
                                "research_brief": "",
                                "resolved_query": "What does the report mean by frequency domain?",
                                "target_section": "",
                            })
                        )
                    )
                ]
            )
        return SimpleNamespace(content=self.content)


def test_turn_router_resolves_report_references_from_workspace():
    llm = FakeLLM()
    clarifier = Clarifier(llm)

    result = clarifier.route_turn(
        "What does this mean?",
        {"active_report": {"title": "Frequency-domain methods"}},
    )

    assert result.intent == "report_qa"
    assert result.resolved_query == "What does the report mean by frequency domain?"
    assert "Frequency-domain methods" in llm.calls[0]["messages"][1]["content"]


def test_report_qa_without_sources_does_not_call_llm():
    llm = FakeLLM(content="unexpected")

    answer = answer_report_question(llm, "What is this?", [])

    assert "没有检索到足够依据" in answer
    assert llm.calls == []


def test_report_qa_prompt_carries_source_ids_for_citations():
    llm = FakeLLM(content="报告指出机制差异。[1]")
    sources = [{"title": "Paper A", "file_id": "paper.md", "excerpt": "Mechanism details"}]

    answer = answer_report_question(llm, "Explain the mechanism", sources)

    assert answer.endswith("[1]")
    assert "[1] Paper A (paper.md)" in llm.calls[0]["messages"][1]["content"]


def test_report_retrieval_is_scoped_to_user_and_selected_report(tmp_path):
    pipeline = Pipeline.__new__(Pipeline)
    pipeline.data_dir = str(tmp_path)
    pipeline.mqe = None
    pipeline.embedding = SimpleNamespace(invoke=lambda _query: ([1.0], 0))
    own_library_chunk = Chunk(
        chunk_idx=0,
        content="user library fact",
        file_path=str(tmp_path / "user_libraries" / "user-a" / "converted" / "paper.md"),
        embedding=[1.0],
        tokens=["fact"],
    )
    current_report_chunk = Chunk(
        chunk_idx=0,
        content="current report fact",
        file_path=str(tmp_path / "search_cache" / "user-a" / "report.md"),
        embedding=[1.0],
        tokens=["report"],
    )
    calls = []

    class FakeStore:
        def hybrid_search(self, **kwargs):
            calls.append(kwargs["allowed_path_prefix"])
            return [(own_library_chunk, 0.1)] if len(calls) == 1 else [(current_report_chunk, 0.2)]

    pipeline.vector_store = FakeStore()
    pipeline.reranker = SimpleNamespace(
        rerank=lambda query, chunks, top_k: [(chunk, 1.0) for chunk in chunks[:top_k]]
    )

    sources = pipeline.retrieve_with_sources(
        "query",
        user_id="user-a",
        preferred_file_id="report.md",
    )

    assert calls[0] == [
        str(tmp_path / "user_libraries" / "user-a"),
        str(tmp_path / "search_cache" / "user-a"),
    ]
    assert calls[1] == str(tmp_path / "search_cache" / "user-a" / "report.md")
    assert {source["excerpt"] for source in sources} == {
        "user library fact",
        "current report fact",
    }


def test_chat_turn_rejects_a_session_owned_by_another_user(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def isolated_session_scope():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr(api_module, "session_scope", isolated_session_scope)
    with isolated_session_scope() as db:
        session = ChatRepository(db).create_session("owner", "Private research")

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    with pytest.raises(HTTPException) as exc_info:
        api_module.chat_turn(
            TurnRequest(message="Can you explain this?", session_id=session.id),
            request,
            SimpleNamespace(id="another-user"),
        )

    assert exc_info.value.status_code == 404
    with Session(engine) as db:
        messages = list(db.scalars(select(ChatMessage).where(ChatMessage.session_id == session.id)))
    assert [item.content for item in messages] == ["Private research"]
    engine.dispose()

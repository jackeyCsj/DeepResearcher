import json
from pathlib import Path

import pytest

from client.rag.chunker import TextChunker
from client.rag.document import Chunk
from client.rag.pipeline import Pipeline
from client.rag.vector_store import VectorStore


class FakeEmbedding:
    def __init__(self):
        self.calls = 0

    def invoke(self, texts):
        self.calls += 1
        values = texts if isinstance(texts, list) else [texts]
        embeddings = [[1.0, float(index + 1)] for index, _ in enumerate(values)]
        return (embeddings, 0) if isinstance(texts, list) else (embeddings[0], 0)


def make_pipeline(data_dir: Path) -> Pipeline:
    pipeline = Pipeline.__new__(Pipeline)
    pipeline.chunker = TextChunker()
    pipeline.embedding = FakeEmbedding()
    pipeline.vector_store = VectorStore()
    pipeline.data_dir = str(data_dir)
    return pipeline


def test_pipeline_startup_only_creates_search_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("client.rag.pipeline.Embedding", FakeEmbedding)

    Pipeline(str(tmp_path))

    assert (tmp_path / "search_cache").is_dir()
    assert not (tmp_path / "documents").exists()
    assert not (tmp_path / "downloads").exists()


def test_same_content_uses_one_embedding_and_tracks_both_paths(tmp_path):
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("same content\r\n", encoding="utf-8")
    second.write_text("same content\n", encoding="utf-8")
    pipeline = make_pipeline(tmp_path)

    first_hash = pipeline.add_document(str(first), save=False)
    second_hash = pipeline.add_document(str(second), save=False)

    assert first_hash == second_hash
    assert pipeline.embedding.calls == 1
    record = pipeline.vector_store._documents[first_hash]
    assert set(record["source_paths"]) == {str(first), str(second)}


def test_removing_sources_keeps_vectors_until_last_reference(tmp_path):
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("shared", encoding="utf-8")
    second.write_text("shared", encoding="utf-8")
    pipeline = make_pipeline(tmp_path)
    content_hash = pipeline.add_document(str(first), save=False)
    pipeline.add_document(str(second), save=False)

    pipeline.vector_store.remove_by_filepath(str(first))
    assert content_hash in pipeline.vector_store._documents
    assert pipeline.vector_store._documents[content_hash]["canonical_path"] == str(second)
    assert pipeline.vector_store.chunks

    pipeline.vector_store.remove_by_filepath(str(second))
    assert content_hash not in pipeline.vector_store._documents
    assert pipeline.vector_store.chunks == []


def test_allowed_paths_include_global_docs_and_only_current_user_reports(tmp_path):
    converted = tmp_path / "converted"
    own_cache = tmp_path / "search_cache" / "user-a"
    other_cache = tmp_path / "search_cache" / "user-b"
    for directory in (converted, own_cache, other_cache):
        directory.mkdir(parents=True)

    store = VectorStore()
    paths = [converted / "global.md", own_cache / "own.md", other_cache / "other.md"]
    for index, path in enumerate(paths):
        path.write_text(f"content {index}", encoding="utf-8")
        chunk = Chunk(chunk_idx=0, content=f"content {index}", file_path=str(path), embedding=[1.0, 1.0])
        store.add_document(store.content_hash(chunk.content), [chunk], str(path))

    visible = store._chunks_for([str(converted), str(own_cache)])
    assert {chunk.content for chunk in visible} == {"content 0", "content 1"}


def test_legacy_store_is_read_only_until_first_save_and_is_backed_up(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("legacy content", encoding="utf-8")
    store_path = tmp_path / "vector_store.json"
    legacy_payload = [
        Chunk(
            chunk_idx=0,
            content="legacy content",
            file_path=str(source),
            embedding=[1.0, 2.0],
            tokens=["legacy"],
        ).model_dump()
    ]
    old_bytes = json.dumps(legacy_payload).encode("utf-8")
    store_path.write_bytes(old_bytes)

    store = VectorStore.load_json(str(store_path))
    assert store_path.read_bytes() == old_bytes
    assert not (tmp_path / "vector_store.v1.backup.json").exists()

    store.save_to_json(str(store_path))
    assert (tmp_path / "vector_store.v1.backup.json").read_bytes() == old_bytes
    payload = json.loads(store_path.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert len(payload["documents"]) == 1


def test_failed_legacy_upgrade_keeps_original_file(tmp_path, monkeypatch):
    source = tmp_path / "source.md"
    source.write_text("legacy content", encoding="utf-8")
    store_path = tmp_path / "vector_store.json"
    old_bytes = json.dumps([
        Chunk(chunk_idx=0, content="legacy", file_path=str(source), embedding=[1.0]).model_dump()
    ]).encode("utf-8")
    store_path.write_bytes(old_bytes)
    store = VectorStore.load_json(str(store_path))

    def fail_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr("client.rag.vector_store.os.replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        store.save_to_json(str(store_path))
    assert store_path.read_bytes() == old_bytes

import json
from pathlib import Path

from client.library.library_manager import LibraryManager

from .test_vector_store_v2 import make_pipeline


def test_same_content_different_titles_share_vectors_and_keep_entries(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    first = incoming / "first.md"
    second = incoming / "second.md"
    first.write_text("shared content", encoding="utf-8")
    second.write_text("shared content", encoding="utf-8")
    pipeline = make_pipeline(tmp_path)
    manager = LibraryManager(str(tmp_path), None, None, pipeline)

    first_result = manager.ingest(str(first), custom_title="First")
    second_result = manager.ingest(str(second), custom_title="Second")

    assert first_result.status == "created"
    assert second_result.status == "created"
    assert pipeline.embedding.calls == 1
    entries = manager.list_docs()
    assert {entry["title"] for entry in entries} == {"First", "Second"}
    assert len(pipeline.vector_store._documents) == 1
    record = next(iter(pipeline.vector_store._documents.values()))
    assert len(record["source_paths"]) == 2


def test_title_skip_and_staged_overwrite_preserve_new_markdown(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    first = incoming / "first.md"
    second = incoming / "second.md"
    first.write_text("old content", encoding="utf-8")
    second.write_text("new content", encoding="utf-8")
    pipeline = make_pipeline(tmp_path)
    manager = LibraryManager(str(tmp_path), None, None, pipeline)

    manager.ingest(str(first), custom_title="Same title")
    skipped = manager.ingest(str(second), custom_title="Same title", overwrite=False)
    assert skipped.status == "skipped"
    assert (tmp_path / "converted" / "Same title.md").read_text(encoding="utf-8") == "old content"

    overwritten = manager.ingest(str(second), custom_title="Same title", overwrite=True)
    assert overwritten.status == "overwritten"
    assert (tmp_path / "converted" / "Same title.md").read_text(encoding="utf-8") == "new content"
    entries = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["content_hash"]


def test_delete_ignores_legacy_report_without_original_path(tmp_path):
    pipeline = make_pipeline(tmp_path)
    manager = LibraryManager(str(tmp_path), None, None, pipeline)
    legacy = {
        "title": "Legacy report",
        "converted_path": str(tmp_path / "converted" / "legacy.md"),
        "source_type": "report",
        "added_at": "2026-01-01T00:00:00",
    }
    (tmp_path / "index.json").write_text(json.dumps([legacy]), encoding="utf-8")

    manager.delete_doc("Legacy report")

    assert manager.list_docs() == [legacy]
    assert not (tmp_path / "vector_store.json").exists()

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from threading import RLock
from typing import Iterable

import jieba
from rank_bm25 import BM25Okapi

from .document import Chunk


class VectorStore:
    """Persistent chunk index with content-hash based embedding deduplication."""

    VERSION = 2

    def __init__(self) -> None:
        self.chunks: list[Chunk] = []
        self._file_index: dict[str, list[Chunk]] = {}
        self._documents: dict[str, dict] = {}
        self._lock = RLock()
        self._legacy_loaded = False

    @staticmethod
    def normalize_text(text: str) -> str:
        return text.replace("\r\n", "\n").replace("\r", "\n").strip()

    @classmethod
    def content_hash(cls, text: str) -> str:
        return hashlib.sha256(cls.normalize_text(text).encode("utf-8")).hexdigest()

    @staticmethod
    def _legacy_hash(file_path: str) -> str:
        return "legacy:" + hashlib.sha256(file_path.encode("utf-8")).hexdigest()

    def _rebuild_indexes(self) -> None:
        self.chunks = []
        self._file_index = {}
        for record in self._documents.values():
            chunks = [Chunk(**chunk) if isinstance(chunk, dict) else chunk for chunk in record["chunks"]]
            for chunk in chunks:
                chunk.file_path = record["canonical_path"]
            record["chunks"] = [chunk.model_dump() for chunk in chunks]
            self.add_chunks(chunks)

    def add_chunks(self, chunks: Iterable[Chunk]) -> None:
        with self._lock:
            for chunk in chunks:
                if chunk.tokens is None:
                    chunk.tokens = jieba.lcut(chunk.content)
                self.chunks.append(chunk)
                self._file_index.setdefault(chunk.file_path, []).append(chunk)

    def has_content(self, content_hash: str) -> bool:
        with self._lock:
            return content_hash in self._documents

    def add_source(self, content_hash: str, source_path: str) -> None:
        with self._lock:
            record = self._documents.get(content_hash)
            if record is None:
                return
            if source_path not in record["source_paths"]:
                record["source_paths"].append(source_path)

    def add_document(self, content_hash: str, chunks: list[Chunk], source_path: str) -> None:
        with self._lock:
            record = self._documents.get(content_hash)
            if record is not None:
                if source_path not in record["source_paths"]:
                    record["source_paths"].append(source_path)
                return
            for chunk in chunks:
                chunk.file_path = source_path
            record = {
                "canonical_path": source_path,
                "source_paths": [source_path],
                "chunks": [chunk.model_dump() for chunk in chunks],
            }
            self._documents[content_hash] = record
            self.add_chunks(chunks)

    def _paths_for_allowed(self, allowed_path_prefix: str | Iterable[str] | None) -> list[str] | None:
        if not allowed_path_prefix:
            return None
        if isinstance(allowed_path_prefix, str):
            return [allowed_path_prefix]
        return list(allowed_path_prefix)

    def _chunks_for(self, allowed_path_prefix: str | Iterable[str] | None = None) -> list[Chunk]:
        prefixes = self._paths_for_allowed(allowed_path_prefix)
        if not prefixes:
            return list(self.chunks)
        normalized = []
        for prefix in prefixes:
            value = os.path.normcase(os.path.abspath(prefix))
            normalized.append((value, value + os.sep))
        result = []
        for content_hash, record in self._documents.items():
            source_paths = record.get("source_paths", [])
            allowed = any(
                os.path.normcase(os.path.abspath(path)) == root or os.path.normcase(os.path.abspath(path)).startswith(sep)
                for path in source_paths
                for root, sep in normalized
            )
            if allowed:
                result.extend(self._file_index.get(record["canonical_path"], []))
        return result

    def cosine_search(
        self,
        query_embedding: list[float],
        top_k: int,
        allowed_path_prefix: str | Iterable[str] | None = None,
    ) -> list[tuple[Chunk, float]]:
        score_pairs = []
        mod_query = math.sqrt(sum(x**2 for x in query_embedding))
        if mod_query == 0:
            return []
        with self._lock:
            for chunk in self._chunks_for(allowed_path_prefix):
                ebd = chunk.embedding
                mod_ebd = math.sqrt(sum(x**2 for x in ebd))
                if mod_ebd == 0:
                    continue
                dot = sum(qi * ei for qi, ei in zip(query_embedding, ebd))
                score_pairs.append((chunk, dot / (mod_query * mod_ebd)))
        return sorted(score_pairs, key=lambda x: x[1], reverse=True)[:top_k]

    def bm25_search(
        self,
        query: str,
        top_k: int,
        allowed_path_prefix: str | Iterable[str] | None = None,
    ) -> list[tuple[Chunk, float]]:
        with self._lock:
            chunks = self._chunks_for(allowed_path_prefix)
            if not chunks:
                return []
            bm25 = BM25Okapi([chunk.tokens for chunk in chunks])
            scores = list(zip(chunks, bm25.get_scores(jieba.lcut(query))))
        return sorted(scores, key=lambda x: x[1], reverse=True)[:top_k]

    def hybrid_search(
        self,
        query: str,
        query_embedding: list[float],
        top_k: int,
        k: int = 60,
        allowed_path_prefix: str | Iterable[str] | None = None,
    ) -> list[tuple[Chunk, float]]:
        if not self._chunks_for(allowed_path_prefix):
            return []
        bm25_result = self.bm25_search(query, top_k * 2, allowed_path_prefix)
        cosine_result = self.cosine_search(query_embedding, top_k * 2, allowed_path_prefix)
        result: dict[tuple[str, int], tuple[Chunk, float]] = {}
        for i, (chunk, _) in enumerate(bm25_result):
            result[(chunk.file_path, chunk.chunk_idx)] = (chunk, 1 / (k + i))
        for i, (chunk, _) in enumerate(cosine_result):
            key = (chunk.file_path, chunk.chunk_idx)
            if key in result:
                old_chunk, old_score = result[key]
                result[key] = (old_chunk, old_score + 1 / (k + i))
            else:
                result[key] = (chunk, 1 / (k + i))
        return sorted(result.values(), key=lambda x: x[1], reverse=True)[:top_k]

    def save_to_json(self, file_path: str) -> None:
        with self._lock:
            directory = os.path.dirname(os.path.abspath(file_path)) or "."
            os.makedirs(directory, exist_ok=True)
            if self._legacy_loaded and os.path.exists(file_path):
                backup_path = os.path.join(directory, "vector_store.v1.backup.json")
                if not os.path.exists(backup_path):
                    with open(file_path, "r", encoding="utf-8") as source, open(backup_path, "w", encoding="utf-8") as backup:
                        backup.write(source.read())
            payload = {"version": self.VERSION, "documents": self._documents}
            fd, temp_path = tempfile.mkstemp(prefix=".vector_store.", suffix=".tmp", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_path, file_path)
                self._legacy_loaded = False
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

    @classmethod
    def load_json(cls, file_path: str) -> VectorStore:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        vector_store = cls()
        if isinstance(data, dict) and data.get("version") == cls.VERSION:
            vector_store._documents = data.get("documents", {})
            vector_store._rebuild_indexes()
            return vector_store
        if isinstance(data, list):
            grouped: dict[str, dict] = {}
            for chunk_dict in data:
                chunk = Chunk(**chunk_dict)
                try:
                    with open(chunk.file_path, "r", encoding="utf-8") as source:
                        content_hash = cls.content_hash(source.read())
                except (FileNotFoundError, OSError, UnicodeDecodeError):
                    content_hash = cls._legacy_hash(chunk.file_path)
                record = grouped.get(content_hash)
                if record is None:
                    record = {
                        "canonical_path": chunk.file_path,
                        "source_paths": [chunk.file_path],
                        "chunks": [],
                    }
                    grouped[content_hash] = record
                elif chunk.file_path not in record["source_paths"]:
                    record["source_paths"].append(chunk.file_path)
                if chunk.file_path == record["canonical_path"]:
                    record["chunks"].append(chunk.model_dump())
            vector_store._documents = grouped
            vector_store._rebuild_indexes()
            vector_store._legacy_loaded = True
            return vector_store
        raise ValueError("Unsupported vector store format")

    def remove_by_filepath(self, file_path: str) -> int:
        with self._lock:
            removed = 0
            for content_hash, record in list(self._documents.items()):
                paths = record.get("source_paths", [])
                if file_path not in paths:
                    continue
                paths.remove(file_path)
                removed += len(record.get("chunks", []))
                if not paths:
                    del self._documents[content_hash]
                    continue
                if record.get("canonical_path") == file_path:
                    record["canonical_path"] = paths[0]
            self._rebuild_indexes()
            return removed

import json
import os
import re
import shutil
import tempfile
from datetime import datetime

from .converter import convert_to_markdown
from ..tools import PaperReaderTool
from ..mcp import MCPTool
from ..rag import Pipeline
from ..api.schemas import IngestResult


class LibraryManager:
    def __init__(
        self,
        data_dir,
        paper_tool: PaperReaderTool | None,
        pdfmux_tool: MCPTool | None,
        pipeline: Pipeline
    ):
        self.paper_tool = paper_tool
        self.pdfmux_tool = pdfmux_tool
        self.pipeline = pipeline
        self.data_dir = data_dir
        self.originals_dir = os.path.join(data_dir, "originals")
        self.converted_dir = os.path.join(data_dir, "converted")
        self.index_path = os.path.join(data_dir, "index.json")

        os.makedirs(self.originals_dir, exist_ok=True)
        os.makedirs(self.converted_dir, exist_ok=True)

    def ingest(
        self, src: str, custom_title: str = None, overwrite: bool = True,
    ) -> IngestResult:

        entries = self.list_docs()

        arxiv_match = re.match(r"^\d{4}\.\d{4,5}", src)
        if arxiv_match:
            for entry in entries:
                if entry.get("original_path") and entry.get("arxiv_id") == arxiv_match.group():
                    return IngestResult(
                        title=src,
                        status="skipped"
                    )

        staging_dir = tempfile.mkdtemp(prefix="library-ingest-", dir=self.data_dir)
        staged_index_path = None
        try:
            metadata = convert_to_markdown(
                src=src,
                output_dir=staging_dir,
                paper_tool=self.paper_tool,
                pdfmux_tool=self.pdfmux_tool,
                custom_title=custom_title,
            )

            existing = next(
                (
                    entry
                    for entry in entries
                    if entry["title"] == metadata.title and entry.get("original_path")
                ),
                None,
            )
            if existing and not overwrite:
                return IngestResult(title=metadata.title, status="skipped")

            if arxiv_match:
                if self.paper_tool is None:
                    raise RuntimeError("arXiv original saving requires the paper-search MCP server.")
                original_src = os.path.join(self.paper_tool.download_dir, f"{src}.pdf")
                original_path = os.path.join(self.originals_dir, f"{src}.pdf")
            else:
                original_src = src
                original_path = os.path.join(self.originals_dir, os.path.basename(src))
            if not os.path.exists(original_src):
                raise FileNotFoundError(f"Original document not found: {original_src}")

            staged_original_dir = os.path.join(staging_dir, "original")
            os.makedirs(staged_original_dir, exist_ok=True)
            staged_original_path = os.path.join(staged_original_dir, os.path.basename(original_path))
            shutil.copy2(original_src, staged_original_path)

            content_hash = self.pipeline.add_document(metadata.output_path, save=False)
            staged_index_path = metadata.output_path

            status = "created"
            if existing:
                self._remove_files(existing)
                entries.remove(existing)
                status = "overwritten"

            converted_path = os.path.join(self.converted_dir, os.path.basename(metadata.output_path))
            os.replace(metadata.output_path, converted_path)
            os.replace(staged_original_path, original_path)
            self.pipeline.vector_store.add_source(content_hash, converted_path)
            self.pipeline.vector_store.remove_by_filepath(staged_index_path)
            staged_index_path = None

            entries.append({
                "title": metadata.title,
                "arxiv_id": metadata.arxiv_id,
                "converted_path": converted_path,
                "source_type": metadata.source_type,
                "added_at": datetime.now().isoformat(),
                "original_path": original_path,
                "content_hash": content_hash,
            })
            self._save_index(entries)
            self.pipeline.save()
            return IngestResult(title=metadata.title, status=status)
        finally:
            if staged_index_path:
                self.pipeline.vector_store.remove_by_filepath(staged_index_path)
            shutil.rmtree(staging_dir, ignore_errors=True)

    def list_docs(self) -> list[dict]:
        if not os.path.exists(self.index_path):
            return []
        with open(self.index_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def delete_doc(self, title: str):
        entries = self.list_docs()
        deleted = False

        for entry in entries:
            if entry["title"] == title and entry.get("original_path"):
                existing = entry
                self._remove_files(existing)
                entries.remove(existing)
                deleted = True
                break

        if not deleted:
            return False
        self._save_index(entries)
        self.pipeline.save()
        return True

    def _save_index(self, entries: list[dict]):
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
    
    def _remove_files(self, entry: dict):
        """清理 vector store + 磁盘文件，不 save, 需要额外调用save"""
        self.pipeline.vector_store.remove_by_filepath(entry["converted_path"])
        if os.path.exists(entry["converted_path"]):
            os.remove(entry["converted_path"])
        orig = entry.get("original_path")
        if orig and os.path.exists(orig):
            os.remove(orig)

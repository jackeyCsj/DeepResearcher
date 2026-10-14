import json
import os
import re
import uuid
from datetime import datetime

from .vector_store import VectorStore
from .reranker import Reranker
from .chunker import TextChunker
from .embedding import Embedding
from .document import Document, Chunk
from .mqe import MQE
from ..base import LLMClient


INGEST_PROMPT = """你是一个知识库管理助手。你需要判断搜索结果是否包含有价值的知识内容，值得保存到本地知识库中。

判断标准:
- 值得保存: 包含具体的技术概念、原理解释、方法论、数据或事实，有长期参考价值
- 不值得保存: 内容过于笼统、重复常识、是广告或导航页、与查询主题无关、信息不可靠

如果值得保存，请将搜索结果中的有价值内容提炼整合为结构清晰的知识摘要，使用"小节标题+内容"的格式，去除重复和无关内容。

示例输出格式:

查询: BM25算法原理

摘要:
## BM25算法

### 核心思想
BM25(Best Matching 25)是一种基于概率模型的排序函数，用于估算文档与查询的相关性。它是TF-IDF的改进版本，引入了文档长度归一化和词频饱和机制。

### 计算公式
对查询中的每个词，BM25计算: score(D,Q) = IDF(q) * (tf * (k1+1)) / (tf + k1 * (1 - b + b * dl/avgdl))
- k1: 词频饱和参数，通常取1.2-2.0
- b: 文档长度归一化参数，通常取0.75
- dl/avgdl: 当前文档长度与平均文档长度的比值

### 与TF-IDF的区别
TF-IDF中词频线性增长，出现10次的权重是1次的10倍。BM25引入饱和曲线，词频增长到一定程度后边际收益递减，更符合实际的相关性判断。"""


ingest_schema = {
    "type": "function",
    "function": {
        "name": "evaluate_search_results",
        "description": "评估搜索结果的价值并生成知识摘要",
        "parameters": {
            "type": "object",
            "properties": {
                "worth_saving": {
                    "type": "boolean",
                    "description": "搜索结果是否值得保存。true表示值得，false表示不值得",
                },
                "summary": {
                    "type": "string",
                    "description": "提炼后的知识摘要。worth_saving为false时填空字符串",
                },
            },
            "required": ["worth_saving", "summary"],
        },
    },
}


class Pipeline:
    VECTOR_STORE_FILE = "vector_store.json"
    SEARCH_CACHE_DIR = "search_cache"

    def __init__(
        self, data_dir: str, llm_client: LLMClient | None = None, mqe: MQE | None = None
    ) -> None:
        self.chunker = TextChunker()
        self.reranker = Reranker()
        self.embedding = Embedding()
        self.llm_client = llm_client
        self.data_dir = data_dir
        self.mqe = mqe

        os.makedirs(os.path.join(data_dir, self.SEARCH_CACHE_DIR), exist_ok=True)

        store_path = os.path.join(data_dir, self.VECTOR_STORE_FILE)
        self.vector_store = (
            VectorStore.load_json(store_path)
            if os.path.exists(store_path)
            else VectorStore()
        )

    def add_document(self, file_path: str, save: bool = True):
        document = Document.read_file(file_path)
        content_hash = VectorStore.content_hash(document.text)
        if self.vector_store.has_content(content_hash):
            self.vector_store.add_source(content_hash, file_path)
            if save:
                self.save()
            return content_hash

        chunks = self.chunker.chunk(document)
        text_chunks = [chunk.content for chunk in chunks]
        embedding_list, tokens = self.embedding.invoke(text_chunks)

        for ebd, chunk in zip(embedding_list, chunks):
            chunk.embedding = ebd

        self.vector_store.add_document(content_hash, chunks, file_path)
        if save:
            self.save()
        return content_hash

    @staticmethod
    def _safe_path_part(value: str, default: str) -> str:
        safe = re.sub(r"[^\w\-.\u4e00-\u9fff]+", "_", value.strip())
        safe = safe.strip("._")
        return safe[:120] or default

    @staticmethod
    def _extract_title(markdown: str, fallback: str) -> str:
        for line in markdown.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip() or fallback
        return fallback

    def add_text(self, text: str, query: str, user_id: str = "default") -> dict[str, str]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_user_id = self._safe_path_part(user_id, "default")
        title = self._extract_title(text, query)
        safe_title = self._safe_path_part(title, "research_report")
        file_id = f"{timestamp}_{uuid.uuid4().hex[:8]}_{safe_title}.md"
        user_dir = os.path.join(self.data_dir, self.SEARCH_CACHE_DIR, safe_user_id)
        os.makedirs(user_dir, exist_ok=True)
        file_path = os.path.join(user_dir, file_id)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(text)

        self.add_document(file_path)
        return {"file_path": file_path, "file_id": file_id, "title": title}

    def save(self):
        store_path = os.path.join(self.data_dir, self.VECTOR_STORE_FILE)
        self.vector_store.save_to_json(store_path)

    def retrieve(self, query: str, top_k: int = 5, user_id: str | None = None) -> str:
        sources = self.retrieve_with_sources(query=query, top_k=top_k, user_id=user_id)
        return "".join(f"[{i}] {item['excerpt']}\n" for i, item in enumerate(sources, 1))

    def retrieve_with_sources(
        self,
        query: str,
        top_k: int = 5,
        user_id: str | None = None,
        preferred_file_id: str | None = None,
    ) -> list[dict[str, str]]:
        allowed_path_prefix = None
        if user_id:
            safe_user_id = self._safe_path_part(user_id, "default")
            allowed_path_prefix = [
                os.path.join(self.data_dir, "user_libraries", safe_user_id),
                os.path.join(self.data_dir, self.SEARCH_CACHE_DIR, safe_user_id),
            ]
            if user_id == "default":
                allowed_path_prefix.append(os.path.join(self.data_dir, "converted"))

        result: dict[tuple[str, int], tuple[Chunk, float]] = {}
        query_list = self.mqe.generate_multiple_query(query) if self.mqe else [query]
        for sub_query in query_list:
            query_embedding, _ = self.embedding.invoke(sub_query)
            retrieved = self.vector_store.hybrid_search(
                query=sub_query,
                query_embedding=query_embedding,
                top_k=top_k * 4,
                allowed_path_prefix=allowed_path_prefix,
            )
            for chunk, score in retrieved:
                key = (chunk.file_path, chunk.chunk_idx)
                old_score = result.get(key, (chunk, 0.0))[1]
                result[key] = (chunk, old_score + score)

        if preferred_file_id:
            safe_user_id = self._safe_path_part(user_id or "default", "default")
            preferred_path = os.path.join(
                self.data_dir, self.SEARCH_CACHE_DIR, safe_user_id, os.path.basename(preferred_file_id)
            )
            query_embedding, _ = self.embedding.invoke(query)
            for chunk, score in self.vector_store.hybrid_search(
                query=query,
                query_embedding=query_embedding,
                top_k=top_k * 2,
                allowed_path_prefix=preferred_path,
            ):
                key = (chunk.file_path, chunk.chunk_idx)
                old_score = result.get(key, (chunk, 0.0))[1]
                result[key] = (chunk, old_score + score + 1.0)

        candidates = [chunk for chunk, _ in sorted(result.values(), key=lambda item: item[1], reverse=True)[:top_k * 8]]
        ranked = self.reranker.rerank(query=query, chunks=candidates, top_k=top_k)
        sources = []
        for chunk, _ in ranked:
            file_id = os.path.basename(chunk.file_path)
            title = os.path.splitext(file_id)[0]
            try:
                with open(chunk.file_path, "r", encoding="utf-8") as source_file:
                    title = self._extract_title(source_file.read(4000), title)
            except OSError:
                pass
            sources.append({
                "title": title,
                "file_id": file_id,
                "excerpt": chunk.content,
            })
        return sources

    def ingest_search_results(self, query: str, search_content: str):
        if self.llm_client is None:
            raise RuntimeError("ingest_search_results 需要 llm_client，但未提供")

        messages = [
            {"role": "system", "content": INGEST_PROMPT}, 
            {"role": "user", "content": f"查询: {query}\n\n搜索结果:\n{search_content}"}
        ]

        response = self.llm_client.invoke(messages=messages, tools=[ingest_schema])
        parameters = json.loads(response.tool_calls[0].function.arguments)

        if parameters["worth_saving"]:
            self.add_text(text=parameters["summary"], query=query)

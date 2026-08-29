import logging
from typing import Any

from .document import Chunk

logger = logging.getLogger(__name__)

class Reranker:
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2") -> None:
        self.model_name = model_name
        self.model: Any | None = None

    def _get_model(self) -> Any:
        if self.model is None:
            logger.info("加载 reranker 模型: %s", self.model_name)
            from sentence_transformers import CrossEncoder

            self.model = CrossEncoder(self.model_name)
        return self.model

    def rerank(
        self, 
        query: str, 
        chunks: list[Chunk], 
        top_k: int = 5
    ) -> list[tuple[Chunk, float]]: 
        if not chunks:
            return []
        
        model = self._get_model()
        scores = model.predict([[query, chunk.content] for chunk in chunks])

        reranked_chunks = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)

        return [(chunk, float(score)) for chunk, score in reranked_chunks[:top_k]]

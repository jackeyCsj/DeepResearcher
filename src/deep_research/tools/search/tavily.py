"""Tavily 搜索服务集成。"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

import httpx

from deep_research.config import config
from deep_research.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)
MAX_TAVILY_QUERY_CHARS = 350


class TavilySearchTool(BaseTool):
    """基于 Tavily API 的网页搜索工具。"""

    name = "web_search"
    description = "Search the web using Tavily API"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or config.tavily_api_key
        self._client = httpx.AsyncClient(timeout=30.0)

    async def arun(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "advanced",
        **kwargs: Any,
    ) -> ToolResult:
        """执行一次 Tavily 搜索。

        Args:
            query: 搜索查询字符串。
            max_results: 返回结果数量，通常为 1-10。
            search_depth: Tavily 搜索深度，取值为 "basic" 或 "advanced"。

        Returns:
            包含摘要、拼接正文、来源 URL 和结构化结果的 ToolResult。
        """
        if not self.api_key:
            return ToolResult(
                summary="Tavily API key not configured. Set TAVILY_API_KEY in .env.",
                content="No results: API key missing.",
            )

        normalized_query = self._normalize_query(query)
        response = await self._client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": self.api_key,
                "query": normalized_query,
                "max_results": min(max(int(max_results), 1), 10),
                "search_depth": (
                    search_depth if search_depth in {"basic", "advanced"} else "advanced"
                ),
            },
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = response.text[:500]
            raise RuntimeError(
                f"Tavily search failed with HTTP {response.status_code}: {body}"
            ) from exc
        data = response.json()

        return self._parse_response(data)

    def _normalize_query(self, query: str) -> str:
        """清理空白并限制查询长度，避免 Tavily 对超长请求返回 400。"""
        normalized = " ".join((query or "").split()).strip()
        if not normalized:
            raise ValueError("Tavily search query must not be empty.")
        if len(normalized) > MAX_TAVILY_QUERY_CHARS:
            logger.warning(
                "Truncating Tavily query from %s to %s characters.",
                len(normalized),
                MAX_TAVILY_QUERY_CHARS,
            )
            normalized = normalized[:MAX_TAVILY_QUERY_CHARS].rstrip()
        return normalized

    def _parse_response(self, data: Dict[str, Any]) -> ToolResult:
        results = data.get("results", [])
        source_urls: List[str] = []
        records: List[Dict[str, Any]] = []

        for r in results:
            url = r.get("url", "")
            if url:
                source_urls.append(url)
            records.append({
                "url": url,
                "title": r.get("title", ""),
                "content": r.get("content", ""),
                "score": r.get("score"),
            })

        return ToolResult(
            summary=f"Tavily search returned {len(results)} results",
            content="\n\n".join(
                f"Title: {r.get('title','')}\nURL: {r.get('url','')}\n{r.get('content','')[:500]}"
                for r in results
            ),
            source_urls=source_urls,
            structured_data=records,
        )

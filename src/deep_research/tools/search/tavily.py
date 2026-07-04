"""Tavily search integration."""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

import httpx

from deep_research.config import config
from deep_research.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class TavilySearchTool(BaseTool):
    """Web search using the Tavily API."""

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
        """Execute a Tavily search.

        Args:
            query: The search query string.
            max_results: Number of results to return (1-10).
            search_depth: "basic" or "advanced".

        Returns:
            ToolResult with search results.
        """
        if not self.api_key:
            return ToolResult(
                summary="Tavily API key not configured. Set TAVILY_API_KEY in .env.",
                content="No results: API key missing.",
            )

        response = await self._client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": self.api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": search_depth,
            },
        )
        response.raise_for_status()
        data = response.json()

        return self._parse_response(data)

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

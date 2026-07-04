"""Web crawling tool for URL content extraction."""

from __future__ import annotations
import logging
import re
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

from deep_research.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class WebCrawlerTool(BaseTool):
    """Crawl and extract main content from a URL."""

    name = "crawler"
    description = "Extract readable content from a web page URL"

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )

    async def arun(
        self,
        url: str,
        extract_links: bool = False,
        max_chars: int = 5000,
        **kwargs: Any,
    ) -> ToolResult:
        """Fetch and extract content from a URL.

        Args:
            url: The web page URL to crawl.
            extract_links: Whether to extract hyperlinks from the page.
            max_chars: Maximum characters to extract.

        Returns:
            ToolResult with extracted content.
        """
        try:
            response = await self._client.get(url)
            response.raise_for_status()
        except Exception as e:
            return ToolResult(
                summary=f"Failed to fetch {url}: {e}",
                content=f"Error: {e}",
                source_urls=[url],
            )

        content = self._extract_content(response.text, max_chars)
        links = []
        if extract_links:
            links = self._extract_links(response.text, url)

        return ToolResult(
            summary=f"Extracted {len(content)} chars from {url}",
            content=content,
            source_urls=[url],
            structured_data=[{"url": url, "links": links}] if links else [],
        )

    def _extract_content(self, html: str, max_chars: int) -> str:
        """Extract readable content from HTML, stripping scripts and styles."""
        soup = BeautifulSoup(html, "lxml")

        # Remove non-content elements
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # Try to find main content area
        article = soup.find("article") or soup.find("main") or soup.find("body")
        if article:
            text = article.get_text(separator="\n", strip=True)
        else:
            text = soup.get_text(separator="\n", strip=True)

        # Clean up whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:max_chars]

    def _extract_links(self, html: str, base_url: str) -> list:
        soup = BeautifulSoup(html, "lxml")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("http"):
                links.append({"text": a.get_text(strip=True)[:100], "url": href})
        return links[:20]

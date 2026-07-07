"""网页爬取工具：从 URL 中提取可读正文内容。"""

from __future__ import annotations
import logging
import re
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

from deep_research.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class WebCrawlerTool(BaseTool):
    """抓取网页并提取主要正文。"""

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
        """请求指定 URL 并提取正文内容。

        Args:
            url: 要抓取的网页地址。
            extract_links: 是否额外提取页面中的链接。
            max_chars: 最多返回的正文字符数。

        Returns:
            包含正文、来源 URL 和可选链接结构化数据的 ToolResult。
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
        """从 HTML 中提取可读正文，并移除脚本、样式等非内容元素。"""
        soup = BeautifulSoup(html, "lxml")

        # 删除导航、页脚、脚本等常见非正文元素，降低噪声。
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # 优先使用语义化正文区域；找不到时退回到 body 或整页文本。
        article = soup.find("article") or soup.find("main") or soup.find("body")
        if article:
            text = article.get_text(separator="\n", strip=True)
        else:
            text = soup.get_text(separator="\n", strip=True)

        # 合并过多空行，避免下游 LLM prompt 被无意义空白撑大。
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

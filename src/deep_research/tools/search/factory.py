"""搜索服务提供方工厂。"""

from __future__ import annotations
from typing import Optional

from deep_research.tools.base import BaseTool
from deep_research.tools.search.tavily import TavilySearchTool


def create_search_provider(provider: str = "tavily", **kwargs) -> Optional[BaseTool]:
    """按名称创建搜索工具实例。

    Args:
        provider: 搜索服务名称，例如 "tavily"。
        **kwargs: 传给具体搜索工具的服务专属参数。

    Returns:
        可用时返回 BaseTool 实例；不支持该 provider 时返回 None。
    """
    if provider == "tavily":
        return TavilySearchTool(**kwargs)
    return None

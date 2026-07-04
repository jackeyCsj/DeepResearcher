"""Search provider factory."""

from __future__ import annotations
from typing import Optional

from deep_research.tools.base import BaseTool
from deep_research.tools.search.tavily import TavilySearchTool


def create_search_provider(provider: str = "tavily", **kwargs) -> Optional[BaseTool]:
    """Create a search provider tool by name.

    Args:
        provider: Provider name ("tavily", "duckduckgo", etc.)
        **kwargs: Provider-specific arguments.

    Returns:
        A BaseTool instance or None if the provider is unavailable.
    """
    if provider == "tavily":
        return TavilySearchTool(**kwargs)
    return None

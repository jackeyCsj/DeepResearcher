import pytest

from deep_research.tools.search.tavily import (
    MAX_TAVILY_QUERY_CHARS,
    TavilySearchTool,
)


def test_tavily_normalizes_and_truncates_long_query() -> None:
    tool = TavilySearchTool(api_key="test")

    normalized = tool._normalize_query("  topic   " + ("x" * 500))

    assert len(normalized) == MAX_TAVILY_QUERY_CHARS
    assert "  " not in normalized


def test_tavily_rejects_empty_query() -> None:
    tool = TavilySearchTool(api_key="test")

    with pytest.raises(ValueError, match="must not be empty"):
        tool._normalize_query("   ")

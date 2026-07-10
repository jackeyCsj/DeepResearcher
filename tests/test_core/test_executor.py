import asyncio

import pytest

from deep_research.core.executor import ExecutionModule
from deep_research.models.actions import ToolCallAction
from deep_research.tools.base import BaseTool, ToolResult
from deep_research.tools.registry import ToolRegistry


class FakeLLM:
    pass


class TrackingSearchTool(BaseTool):
    name = "web_search"
    description = "test search"

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def arun(self, **kwargs) -> ToolResult:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        query = kwargs["query"]
        return ToolResult(
            summary="ok",
            source_urls=[f"https://example.com/{query}"],
            structured_data=[
                {
                    "url": f"https://example.com/{query}",
                    "title": f"Result {query}",
                    "content": f"Evidence body for {query}",
                    "score": 0.9,
                }
            ],
        )


@pytest.mark.asyncio
async def test_executor_preserves_search_result_content_and_limits_parallelism() -> None:
    registry = ToolRegistry()
    tool = TrackingSearchTool()
    registry.register(tool)
    executor = ExecutionModule(registry, FakeLLM(), max_parallel_tools=2)
    actions = [
        ToolCallAction(
            id=f"a-{index}",
            subtask_id=f"s-{index}",
            tool_name="web_search",
            tool_input=f"q-{index}",
        )
        for index in range(5)
    ]

    bundles = await executor.execute_parallel(actions)

    assert tool.max_active <= 2
    assert len(bundles) == 5
    assert all(bundle.records[0].title for bundle in bundles)
    assert all(bundle.records[0].snippet.startswith("Evidence body") for bundle in bundles)
    assert all(bundle.records[0].content for bundle in bundles)

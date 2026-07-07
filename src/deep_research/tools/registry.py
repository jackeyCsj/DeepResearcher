"""全局工具注册表。"""

from __future__ import annotations
from typing import Any, Dict, List

from deep_research.tools.base import BaseTool


class ToolRegistry:
    """将工具名映射到 BaseTool 实例的全局注册表。"""

    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise KeyError(
                f"Tool '{name}' not found. Available: {list(self._tools.keys())}"
            )
        return self._tools[name]

    def list_tools(self) -> List[Dict[str, str]]:
        return [
            {"name": t.name, "description": t.description}
            for t in self._tools.values()
        ]

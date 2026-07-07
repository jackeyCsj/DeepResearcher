"""工具生态的抽象基类接口。"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """工具执行后的标准化返回结果。"""

    summary: str = Field(default="", description="Human-readable summary")
    content: str = Field(default="", description="Full output content")
    source_urls: List[str] = Field(default_factory=list)
    structured_data: List[Dict[str, Any]] = Field(default_factory=list)


class BaseTool(ABC):
    """所有工具实现都需要继承的抽象基类。"""

    name: str = ""
    description: str = ""

    @abstractmethod
    async def arun(self, **kwargs: Any) -> ToolResult:
        """异步执行工具，并返回标准化 ToolResult。"""
        ...

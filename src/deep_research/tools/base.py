"""Abstract base tool interface."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Standardized result from a tool execution."""

    summary: str = Field(default="", description="Human-readable summary")
    content: str = Field(default="", description="Full output content")
    source_urls: List[str] = Field(default_factory=list)
    structured_data: List[Dict[str, Any]] = Field(default_factory=list)


class BaseTool(ABC):
    """Abstract base class for all tools in the ecosystem."""

    name: str = ""
    description: str = ""

    @abstractmethod
    async def arun(self, **kwargs: Any) -> ToolResult:
        """Execute the tool asynchronously."""
        ...

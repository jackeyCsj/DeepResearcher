from .registry import ToolRegistry
from .base_tool import BaseTool, ToolParameter, ToolCallError


def __getattr__(name: str):
    if name == "RAGTool":
        from .tool_rag import RAGTool

        return RAGTool
    if name == "PaperReaderTool":
        from .tool_paper import PaperReaderTool

        return PaperReaderTool
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ToolRegistry",
    "BaseTool",
    "ToolParameter",
    "ToolCallError",
    "RAGTool",
    "PaperReaderTool",
]

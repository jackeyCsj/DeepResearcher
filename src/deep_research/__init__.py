"""DuMate-DeepResearch: A multi-agent deep research framework.

Built on the architecture described in:
  "DuMate-DeepResearch: An Auditable Multi-Agent System
   with Recursive Search and Rubric-Grounded Reasoning"
   (Baidu AI Cloud, arXiv:2606.07299)
"""

from deep_research.config import config, ResearchConfig
from deep_research.models import (
    ResearchState,
    TopicSpec,
    Outline,
    Chapter,
    TaskContext,
    ResearchPlan,
    PlanNode,
    SubtaskType,
    EvidenceBase,
    EvidenceBundle,
    EvidenceRecord,
    Rubric,
    Criterion,
    RubricSignal,
    BaseAction,
    ToolCallAction,
    SearchAgentAction,
    ActionType,
)
from deep_research.core import Router, GraphPlanner, ExecutionModule, Writer, ReflectionGate
from deep_research.rubric import RubricGenerator, AdaptiveStopping
from deep_research.tools import BaseTool, ToolResult, ToolRegistry, WebCrawlerTool
from deep_research.utils import LLMClient
from deep_research.graph import build_orchestration_graph
from deep_research.graph.search_subgraph import SimpleSearchAgent, SearchAgentState

__version__ = "0.1.0"

__all__ = [
    "config",
    "ResearchConfig",
    "ResearchState",
    "TopicSpec",
    "Outline",
    "Chapter",
    "TaskContext",
    "ResearchPlan",
    "PlanNode",
    "SubtaskType",
    "EvidenceBase",
    "EvidenceBundle",
    "EvidenceRecord",
    "Rubric",
    "Criterion",
    "RubricSignal",
    "BaseAction",
    "ToolCallAction",
    "SearchAgentAction",
    "ActionType",
    "Router",
    "GraphPlanner",
    "ExecutionModule",
    "Writer",
    "ReflectionGate",
    "RubricGenerator",
    "AdaptiveStopping",
    "BaseTool",
    "ToolResult",
    "ToolRegistry",
    "WebCrawlerTool",
    "LLMClient",
    "build_orchestration_graph",
    "SimpleSearchAgent",
    "SearchAgentState",
]

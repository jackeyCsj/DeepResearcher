"""研究主题、大纲与固定任务上下文模型。"""

from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field


class TopicSpec(BaseModel):
    """Router 生成的主题规格 x。"""

    query: str = Field(default="", description="Original user query")
    core_topic: str = Field(default="", description="Extracted core research topic")
    sub_questions: List[str] = Field(default_factory=list)
    scope: str = Field(default="", description="Bounded scope description")
    language: str = Field(default="zh")
    clarification_needed: bool = Field(default=False)
    clarification_question: Optional[str] = None


class Chapter(BaseModel):
    """大纲中的单个章节，同时也是持久 Rubric 的章节级锚点。"""

    id: str = ""
    title: str = ""
    description: str = Field(default="", description="What this chapter should cover")
    rubric_guidance: str = Field(
        default="",
        description="Persistent rubric instruction for this chapter",
    )


class Outline(BaseModel):
    """报告大纲 O：在粗粒度探索后生成，并在后续研究中保持相对稳定。"""

    title: str = ""
    chapters: List[Chapter] = Field(default_factory=list)


class TaskContext(BaseModel):
    """固定任务上下文 z = (x, O)。"""

    topic: TopicSpec = Field(default_factory=TopicSpec, description="Topic specification x")
    outline: Outline = Field(default_factory=Outline, description="Report outline O")

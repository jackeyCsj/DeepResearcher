"""Topic and task context models."""

from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field


class TopicSpec(BaseModel):
    """The topic specification x produced by the Router."""

    query: str = Field(default="", description="Original user query")
    core_topic: str = Field(default="", description="Extracted core research topic")
    sub_questions: List[str] = Field(default_factory=list)
    scope: str = Field(default="", description="Bounded scope description")
    language: str = Field(default="en")
    clarification_needed: bool = Field(default=False)
    clarification_question: Optional[str] = None


class Chapter(BaseModel):
    """A single chapter/section in the outline, doubles as a persistent rubric anchor."""

    id: str = ""
    title: str = ""
    description: str = Field(default="", description="What this chapter should cover")
    rubric_guidance: str = Field(
        default="",
        description="Persistent rubric instruction for this chapter",
    )


class Outline(BaseModel):
    """Report outline O, produced during coarse exploration, then fixed."""

    title: str = ""
    chapters: List[Chapter] = Field(default_factory=list)


class TaskContext(BaseModel):
    """The fixed context z = (x, O)."""

    topic: TopicSpec = Field(default_factory=TopicSpec, description="Topic specification x")
    outline: Outline = Field(default_factory=Outline, description="Report outline O")

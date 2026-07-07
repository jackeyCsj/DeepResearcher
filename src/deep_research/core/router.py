"""Router 模块：负责研究任务理解与初步分析。

Router 从用户查询中抽取核心主题、子问题和研究范围。
如果问题本身不完整或歧义明显，它会在结构化结果中标出需要澄清。
"""

from __future__ import annotations
import logging

from deep_research.models.topic import TopicSpec
from deep_research.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)

"""
    你是一个研究查询分析器。根据用户的研究问题，提取核心主题，
    识别子问题，确定研究范围，并检测模糊性。输出包含所有已识别字段的结构化TopicSpec。
"""

SYSTEM_PROMPT = """You are a research query analyzer. Given a user's research question,
extract the core topic, identify sub-questions, determine scope, and detect ambiguity.
Output a structured TopicSpec with all identified fields."""


class Router:
    """任务理解模块，产出论文形式化中的主题规格 x。"""

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm = llm_client

    async def analyze(self, query: str) -> TopicSpec:
        """把用户原始问题解析成结构化 TopicSpec。

        Args:
            query: 用户输入的原始研究问题。

        Returns:
            包含 core_topic、sub_questions、scope 等字段的 TopicSpec。
        """
        prompt = f"""Analyze this research query and produce a structured specification:

            Query: {query}

            Extract:
            1. core_topic: The central research topic (concise phrase)
            2. sub_questions: 3-6 key sub-questions that need investigation
            3. scope: The boundary/scope of the research. Preserve explicit time ranges.
               If the query says "2025年至今", interpret it as 2025-01-01 through the runtime current date.
            4. language: The language of the query (en/zh)
            5. clarification_needed: Is the query ambiguous or incomplete?
            6. clarification_question: If ambiguous, what clarification would you ask?
        """
        return await self.llm.generate(prompt, response_model=TopicSpec, system_prompt=SYSTEM_PROMPT)

    async def clarify(self, query: str, user_response: str) -> TopicSpec:
        """结合用户澄清内容，重新生成更精确的 TopicSpec。

        Args:
            query: 原始用户问题。
            user_response: 用户补充的澄清信息。

        Returns:
            更新后的 TopicSpec。
        """
        prompt = f"""Original query: {query}
            User clarification: {user_response}

            Produce an updated structured TopicSpec.
        """
        return await self.llm.generate(prompt, response_model=TopicSpec, system_prompt=SYSTEM_PROMPT)

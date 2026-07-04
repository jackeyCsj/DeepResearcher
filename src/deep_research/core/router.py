"""Router module: task understanding and analysis.

The Router extracts salient information from the user query,
identifies core research topic, sub-questions, and scope.
If the query is ambiguous, it proactively prompts for clarification.
"""

from __future__ import annotations
import logging

from deep_research.models.topic import TopicSpec
from deep_research.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a research query analyzer. Given a user's research question,
extract the core topic, identify sub-questions, determine scope, and detect ambiguity.
Output a structured TopicSpec with all identified fields."""


class Router:
    """Task understanding and analysis. Produces the topic specification x."""

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm = llm_client

    async def analyze(self, query: str) -> TopicSpec:
        """Parse the user query into a structured TopicSpec.

        Args:
            query: The raw user research question.

        Returns:
            TopicSpec with extracted core_topic, sub_questions, scope, etc.
        """
        prompt = f"""Analyze this research query and produce a structured specification:

Query: {query}

Extract:
1. core_topic: The central research topic (concise phrase)
2. sub_questions: 3-6 key sub-questions that need investigation
3. scope: The boundary/scope of the research
4. language: The language of the query (en/zh)
5. clarification_needed: Is the query ambiguous or incomplete?
6. clarification_question: If ambiguous, what clarification would you ask?
"""
        return await self.llm.generate(prompt, response_model=TopicSpec, system_prompt=SYSTEM_PROMPT)

    async def clarify(self, query: str, user_response: str) -> TopicSpec:
        """Refine the topic spec after user clarification.

        Args:
            query: The original user query.
            user_response: The user's clarification response.

        Returns:
            Updated TopicSpec.
        """
        prompt = f"""Original query: {query}
User clarification: {user_response}

Produce an updated structured TopicSpec.
"""
        return await self.llm.generate(prompt, response_model=TopicSpec, system_prompt=SYSTEM_PROMPT)

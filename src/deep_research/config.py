"""Central configuration management using pydantic-settings."""

from __future__ import annotations
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class ResearchConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"
    llm_max_tokens: int = 128000
    llm_temperature: float = 0.7

    # Search
    tavily_api_key: str = ""

    # Research loop limits
    max_plan_iterations: int = 15
    max_search_rounds: int = 10
    queries_per_round: int = 3
    max_parallel_tools: int = 5

    # Reflection
    max_action_revisions: int = 3


config = ResearchConfig()

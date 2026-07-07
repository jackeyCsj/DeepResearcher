"""基于 pydantic-settings 的集中配置管理。"""

from __future__ import annotations
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class ResearchConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM 配置：优先使用通用 LLM_*；也兼容 DeepSeek_* 和旧的 OPENAI_*。
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_provider: str = "openai-compatible"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_max_tokens: int = 128000
    llm_temperature: float = 0.7

    # 搜索后端配置。
    tavily_api_key: str = ""

    # 外层规划循环与内层搜索循环的默认上限。
    max_plan_iterations: int = 15
    max_search_rounds: int = 10
    queries_per_round: int = 3
    max_parallel_tools: int = 5

    # 反思门控允许的最大动作修订次数。
    max_action_revisions: int = 3


config = ResearchConfig()

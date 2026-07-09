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
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "deepseek-chat"
    llm_max_tokens: int = 128000
    llm_default_output_tokens: int = 2048
    llm_request_timeout_seconds: float = 30.0
    llm_max_retries: int = 0
    llm_temperature: float = 0.7

    # 搜索后端配置。
    tavily_api_key: str = ""

    # 外层规划循环与内层搜索循环的默认上限。
    max_plan_iterations: int = 15
    max_search_rounds: int = 10
    queries_per_round: int = 3
    max_parallel_tools: int = 5

    # 证据抽取配置。
    # auto: DashScope/qwen 默认使用搜索片段 fallback，避免逐来源结构化抽取大量超时。
    # llm: 总是调用 LLM 从来源正文抽取 claims。
    # fallback: 总是使用搜索片段/正文开头生成低成本 claims。
    evidence_extraction_mode: str = "auto"
    evidence_extraction_timeout_seconds: float = 12.0


config = ResearchConfig()

"""Async OpenAI-compatible LLM client with retry and JSON mode support."""

from __future__ import annotations
import json
import logging
from typing import Any, Optional, Type

from openai import AsyncOpenAI
from pydantic import BaseModel

from deep_research.config import config

logger = logging.getLogger(__name__)


class LLMClient:
    """Async LLM client wrapping the OpenAI API.

    Supports:
    - Structured output via response_model (Pydantic)
    - JSON mode
    - Retry with exponential backoff
    - Long-form generation via streaming
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or config.openai_api_key
        self.base_url = base_url or config.openai_base_url
        self.model = model or config.llm_model
        self.max_tokens = config.llm_max_tokens
        self.temperature = config.llm_temperature
        self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

    async def generate(
        self,
        prompt: str,
        response_model: Optional[Type[BaseModel]] = None,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Any:
        """Generate a response, optionally parsing into a Pydantic model.

        Args:
            prompt: The user message / main prompt.
            response_model: If provided, the response is parsed into this Pydantic model.
            system_prompt: Optional system message.
            temperature: Override the default temperature.
            max_tokens: Override the default max_tokens.

        Returns:
            Parsed Pydantic model if response_model is given, else raw text string.
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens or 4096,
        }

        if response_model is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "schema": response_model.model_json_schema(),
                },
            }

        response = await self._client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        if content is None:
            raise ValueError("LLM returned None content")

        if response_model is not None:
            try:
                return response_model.model_validate_json(content)
            except Exception as e:
                logger.warning(f"Failed to parse LLM response into {response_model.__name__}: {e}")
                # Fallback: try to extract JSON from the response
                json_start = content.find("{")
                json_end = content.rfind("}")
                if json_start >= 0 and json_end > json_start:
                    return response_model.model_validate_json(content[json_start : json_end + 1])
                raise

        return content

    async def generate_long(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 16000,
    ) -> str:
        """Generate a long-form response using streaming.

        Suitable for final report synthesis.
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        chunks: list[str] = []
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                chunks.append(delta)

        return "".join(chunks)

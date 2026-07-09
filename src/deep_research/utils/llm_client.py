"""异步 OpenAI 兼容 LLM 客户端，支持 DeepSeek 等兼容接口。"""

from __future__ import annotations
import json
import logging
from datetime import datetime
from typing import Any, Optional, get_origin

from openai import AsyncOpenAI, BadRequestError
from pydantic import BaseModel
from pydantic import TypeAdapter

from deep_research.config import config

logger = logging.getLogger(__name__)


class LLMClient:
    """封装 OpenAI 兼容接口的异步 LLM 客户端。

    支持：
    - 通过 response_model 解析为 Pydantic 结构化输出。
    - JSON schema / JSON object response_format。
    - 通过流式接口生成长报告。
    - 使用 LLM_*、DEEPSEEK_* 或 OPENAI_* 环境变量配置不同服务商。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.model = model or config.llm_model
        configured_base_url = base_url or config.llm_base_url
        use_dashscope_default = self.model.startswith("qwen")
        use_deepseek_default = (
            self.model.startswith("deepseek-")
            or (bool(config.deepseek_api_key) and not use_dashscope_default)
        )
        self.base_url = (
            configured_base_url
            or (config.dashscope_base_url if use_dashscope_default else "")
            or (config.deepseek_base_url if use_deepseek_default else "")
            or config.openai_base_url
        )
        self.api_key = self._select_api_key(api_key)
        self.max_tokens = config.llm_max_tokens
        # LLM_MAX_TOKENS may describe a provider/context limit. Keep routine outputs
        # bounded so structured JSON calls do not request an invalid or excessive size.
        self.default_output_tokens = min(self.max_tokens, config.llm_default_output_tokens)
        self.temperature = config.llm_temperature
        if not self.api_key:
            raise ValueError(
                "未配置 LLM API Key。请在 .env 中设置 LLM_API_KEY、"
                "DASHSCOPE_API_KEY、DEEPSEEK_API_KEY 或 OPENAI_API_KEY。"
            )
        self._client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=config.llm_request_timeout_seconds,
            max_retries=config.llm_max_retries,
        )
        self._supports_json_schema_response_format: Optional[bool] = None
        self._supports_json_object_response_format: Optional[bool] = None

    async def generate(
        self,
        prompt: str,
        response_model: Optional[Any] = None,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Any:
        """生成模型回复，并可选解析为 Pydantic 模型。

        Args:
            prompt: 用户侧主提示词。
            response_model: 提供时，将模型回复解析成该 Pydantic 模型。
            system_prompt: 可选系统提示词。
            temperature: 覆盖默认采样温度。
            max_tokens: 覆盖默认最大输出 token 数。

        Returns:
            如果提供 response_model，返回解析后的模型实例；否则返回原始文本。
        """
        # ---- 阶段1: 构造 messages ----
        messages = []
        runtime_context = self._runtime_context_prompt()
        if system_prompt:
            messages.append(
                {
                    "role": "system",
                    "content": f"{runtime_context}\n\n{system_prompt}",
                }
            )
        else:
            messages.append({"role": "system", "content": runtime_context})
        messages.append({"role": "user", "content": prompt})

        # ---- 阶段2: 组装 API 调用参数 ----
        effective_max_tokens = (
            max_tokens
            if max_tokens is not None
            else self.default_output_tokens
        )

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": effective_max_tokens,
        }

        # ---- 阶段3: 自适应结构化输出 ----
        # 根据服务商能力选择 json_schema / json_object / 纯 prompt 三种策略
        response_format_type = self._select_response_format()
        if response_model is not None and response_format_type is not None:
            # 注入 OpenAI response_format 参数（json_schema 或 json_object）
            kwargs["response_format"] = self._response_format_payload(
                response_format_type,
                response_model,
            )
            # 同时在 prompt 末尾追加 JSON schema 文本约束，双重保险
            kwargs["messages"] = self._messages_with_json_instruction(
                messages,
                response_model,
            )

        # ---- 阶段4: 发起 API 调用，失败时自动降级 ----
        try:
            response = await self._client.chat.completions.create(**kwargs)
            # 调用成功 → 缓存该服务商的结构化输出能力，后续直接复用
            if response_model is not None and response_format_type == "json_schema":
                self._supports_json_schema_response_format = True
            elif response_model is not None and response_format_type == "json_object":
                self._supports_json_object_response_format = True
        except BadRequestError as e:
            # 如果是 response_format 不支持导致的 400 错误 → 降级重试
            if response_model is None or not self._is_response_format_unavailable(e):
                raise
            # 自动降级链: json_schema → json_object → 纯 prompt 约束
            response = await self._retry_structured_without_failed_format(
                kwargs,
                messages,
                response_model,
                failed_format=response_format_type,
            )

        # ---- 阶段5: 提取文本内容 ----
        choice = response.choices[0]
        finish_reason = getattr(choice, "finish_reason", None)
        if response_model is not None and finish_reason == "length":
            logger.warning(
                "LLM structured response for %s hit max_tokens=%s and may be truncated.",
                self._response_model_name(response_model),
                kwargs.get("max_tokens"),
            )

        content = choice.message.content
        if content is None:
            content = ""

        # ---- 阶段6: 结构化解析 ----
        if response_model is not None:
            # LLM 偶尔返回空内容，强化约束后重试一次
            if not content.strip():
                logger.warning(
                    "LLM returned empty structured response for %s; retrying once.",
                    self._response_model_name(response_model),
                )
                retry_response = await self._retry_empty_structured_response(
                    kwargs,
                    messages,
                    response_model,
                )
                content = retry_response.choices[0].message.content or ""
            # 将 JSON 文本解析为 Pydantic 模型（兼容 markdown 包裹等异常格式）
            return self._parse_structured_response(content, response_model)

        # 未指定 response_model → 直接返回原始文本
        return content

    def _response_model_name(self, response_model: Any) -> str:
        """为 OpenAI JSON schema response_format 生成稳定 schema 名称。"""
        name = getattr(response_model, "__name__", None)
        if name:
            return name
        return "StructuredResponse"

    def _runtime_context_prompt(self) -> str:
        """给所有 LLM 调用注入运行时日期，避免模型误解“当前/至今”等相对时间。"""
        today = datetime.now().date().isoformat()
        return (
            f"Runtime context: The current date is {today}. "
            "Interpret relative time expressions against this date. "
            "For Chinese phrases such as 当前、目前、今年、至今、最近、现阶段, "
            "use this runtime date rather than model training-time assumptions. "
            f"If the user asks for 2025年至今, cover 2025-01-01 through {today}, "
            "and explicitly include relevant 2026 developments."
        )

    def _response_model_schema(self, response_model: Any) -> dict[str, Any]:
        """兼容 BaseModel 与 List[Model] 等 Pydantic 可解析类型。"""
        if isinstance(response_model, type) and issubclass(response_model, BaseModel):
            return response_model.model_json_schema()
        return TypeAdapter(response_model).json_schema()

    def _is_deepseek_provider(self) -> bool:
        """DeepSeek 兼容接口支持 json_object，但通常不支持 json_schema。"""
        return (
            self.model.startswith("deepseek-")
            or "deepseek" in (self.base_url or "").lower()
        )

    def _is_dashscope_provider(self) -> bool:
        """阿里云百炼 DashScope OpenAI 兼容接口。"""
        return (
            self.model.startswith("qwen")
            or "dashscope" in (self.base_url or "").lower()
            or "aliyuncs" in (self.base_url or "").lower()
        )

    def _select_api_key(self, explicit_api_key: Optional[str]) -> str:
        """按当前 provider 选择匹配的 API key，避免 base_url 和 key 串台。"""
        if explicit_api_key:
            return explicit_api_key
        if config.llm_api_key:
            return config.llm_api_key
        if self._is_dashscope_provider():
            return config.dashscope_api_key or config.openai_api_key
        if self._is_deepseek_provider():
            return config.deepseek_api_key or config.openai_api_key
        return config.openai_api_key or config.dashscope_api_key or config.deepseek_api_key

    def _select_response_format(self) -> Optional[str]:
        """选择当前服务最合适的结构化输出 response_format。"""
        if self._is_deepseek_provider() or self._is_dashscope_provider():
            if self._supports_json_object_response_format is not False:
                return "json_object"
            return None
        if self._supports_json_schema_response_format is not False:
            return "json_schema"
        if self._supports_json_object_response_format is not False:
            return "json_object"
        return None

    def _response_format_payload(
        self,
        response_format_type: str,
        response_model: Any,
    ) -> dict[str, Any]:
        """构造不同服务商兼容的 response_format 参数。"""
        if response_format_type == "json_object":
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": self._response_model_name(response_model),
                "schema": self._response_model_schema(response_model),
            },
        }

    async def _retry_structured_without_failed_format(
        self,
        kwargs: dict[str, Any],
        messages: list[dict[str, str]],
        response_model: Any,
        failed_format: Optional[str],
    ) -> Any:
        """结构化输出格式不可用时，按 json_object -> prompt-only 顺序降级。"""
        if failed_format == "json_schema":
            self._supports_json_schema_response_format = False
            if self._supports_json_object_response_format is not False:
                logger.warning(
                    "LLM provider does not support json_schema response_format; "
                    "retrying with json_object response_format."
                )
                fallback_kwargs = dict(kwargs)
                fallback_kwargs["response_format"] = {"type": "json_object"}
                fallback_kwargs["messages"] = self._messages_with_json_instruction(
                    messages,
                    response_model,
                )
                try:
                    response = await self._client.chat.completions.create(**fallback_kwargs)
                    self._supports_json_object_response_format = True
                    return response
                except BadRequestError as e:
                    if not self._is_response_format_unavailable(e):
                        raise
                    self._supports_json_object_response_format = False

        if failed_format == "json_object":
            self._supports_json_object_response_format = False
            logger.warning(
                "LLM provider does not support json_object response_format; "
                "retrying with prompt-only JSON output."
            )
        elif failed_format == "json_schema":
            logger.warning(
                "LLM provider does not support json_object response_format; "
                "retrying with prompt-only JSON output."
            )
        else:
            logger.warning(
                "LLM provider does not support structured response_format; "
                "retrying with prompt-only JSON output."
            )

        fallback_kwargs = dict(kwargs)
        fallback_kwargs.pop("response_format", None)
        fallback_kwargs["messages"] = self._messages_with_json_instruction(
            messages,
            response_model,
        )
        return await self._client.chat.completions.create(**fallback_kwargs)

    async def _retry_empty_structured_response(
        self,
        kwargs: dict[str, Any],
        messages: list[dict[str, str]],
        response_model: Any,
    ) -> Any:
        """结构化输出为空时，强化 JSON 约束并重试一次。"""
        retry_kwargs = dict(kwargs)
        retry_kwargs["messages"] = self._messages_with_json_instruction(
            messages,
            response_model,
        )
        if self._is_deepseek_provider():
            retry_kwargs["response_format"] = {"type": "json_object"}
        return await self._client.chat.completions.create(**retry_kwargs)

    def _messages_with_json_instruction(
        self,
        messages: list[dict[str, str]],
        response_model: Any,
    ) -> list[dict[str, str]]:
        """在不支持 response_format 的模型服务上，用提示词约束纯 JSON 输出。"""
        schema = json.dumps(
            self._response_model_schema(response_model),
            ensure_ascii=False,
            indent=2,
        )
        instruction = (
            "\n\nReturn ONLY valid JSON. Do not include markdown fences, comments, "
            "or explanatory text. The JSON must conform to this schema:\n"
            f"{schema}"
        )
        fallback_messages = [dict(message) for message in messages]
        fallback_messages[-1]["content"] = fallback_messages[-1]["content"] + instruction
        return fallback_messages

    def _parse_structured_response(self, content: str, response_model: Any) -> Any:
        """把模型文本解析为目标结构，兼容 JSON 外包裹少量说明文字的情况。

        采用三层级联解析策略，逐级容错：
        """
        adapter = TypeAdapter(response_model)

        # 第一层：直接解析整个 content 为 JSON
        # 最佳情况 —— LLM 返回了干净的 JSON 字符串
        try:
            return adapter.validate_json(content)
        except Exception as e:
            logger.debug(
                "Failed to parse LLM response into %s: %s",
                self._response_model_name(response_model),
                e,
            )

            # 第二层：从 content 中提取 JSON 片段再解析
            # 兼容 LLM 在 JSON 前后附加了说明文字或 markdown 代码块的情况
            json_body = self._extract_json_body(content)
            if json_body is not None:
                try:
                    return adapter.validate_json(json_body)
                except Exception:
                    # 第三层：解包 {"items": [...]} 等包裹格式
                    # 兼容 json_object 模式下 LLM 把列表自动包了一层对象的情况
                    unwrapped = self._unwrap_list_response(json_body, response_model)
                    if unwrapped is not None:
                        return adapter.validate_python(unwrapped)

            # 三层全部失败 → 记录警告并抛出异常，由上层调用方处理
            logger.warning(
                "Failed to parse LLM response into %s (chars=%s, head=%r, tail=%r)",
                self._response_model_name(response_model),
                len(content or ""),
                (content or "")[:160],
                (content or "")[-160:],
            )
            raise

    def _unwrap_list_response(self, json_body: str, response_model: Any) -> Optional[Any]:
        """兼容 json_object 模式下把列表包成 {"items": [...]} 的返回。"""
        origin = get_origin(response_model)
        if origin not in (list, list.__class__):
            return None

        try:
            data = json.loads(json_body)
        except json.JSONDecodeError:
            return None

        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return None

        for key in ("items", "results", "data", "criteria", "list"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return None

    def _extract_json_body(self, content: str) -> Optional[str]:
        """从带说明文字的回复中截取第一个合法 JSON object/array。"""
        decoder = json.JSONDecoder()
        starts = [idx for idx in (content.find("{"), content.find("[")) if idx >= 0]
        for start in sorted(starts):
            try:
                _, end = decoder.raw_decode(content[start:])
            except json.JSONDecodeError:
                continue
            return content[start : start + end]
        return None

    def _is_response_format_unavailable(self, error: BadRequestError) -> bool:
        """判断 400 是否由服务商不支持 response_format/json_schema 导致。"""
        message = str(error).lower()
        return (
            "response_format" in message
            or "json_schema" in message
            or "unavailable" in message
        )

    async def generate_long(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 16000,
    ) -> str:
        """使用流式接口生成长文本回复。

        主要用于最终报告合成，避免一次性长输出带来的响应等待问题。
        """
        messages = []
        runtime_context = self._runtime_context_prompt()
        if system_prompt:
            messages.append(
                {
                    "role": "system",
                    "content": f"{runtime_context}\n\n{system_prompt}",
                }
            )
        else:
            messages.append({"role": "system", "content": runtime_context})
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

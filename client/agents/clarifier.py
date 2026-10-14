import json
import logging
from typing import Literal

from pydantic import BaseModel

from ..api.schemas import ClarifyResult
from ..base.llm_client import LLMClient as llm_client
from .prompts import (
    CLARIFIER_SYSTEM,
    CLARIFIER_USER,
    CLARIFIER_REFINE_USER,
    CLARIFIER_TURN_SYSTEM,
    CLARIFIER_TURN_USER,
)

logger = logging.getLogger(__name__)
display = logging.getLogger("client.display")


analyze_schema = {
    "type": "function",
    "function": {
        "name": "analyze_query",
        "description": "Analyze whether the user query is specific enough for research, or needs clarification.",
        "parameters": {
            "type": "object",
            "properties": {
                "is_clear": {
                    "type": "boolean",
                    "description": "True if the query is specific enough to start research directly.",
                },
                "research_brief": {
                    "type": "string",
                    "description": "A refined, detailed research brief. Populated when is_clear is true.",
                },
                "suggested_directions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "3-5 specific research directions the user can choose from. Populated when is_clear is false.",
                },
                "message": {
                    "type": "string",
                    "description": "A conversational message to the user explaining why clarification is needed and how to choose. Populated when is_clear is false.",
                },
            },
            "required": ["is_clear"],
        },
    },
}

turn_schema = {
    "type": "function",
    "function": {
        "name": "route_turn",
        "description": "Classify a conversation turn and clarify it when its intent or target is ambiguous.",
        "parameters": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": ["report_qa", "initial_research", "supplementary_research", "deepening"],
                },
                "needs_clarification": {"type": "boolean"},
                "message": {"type": "string"},
                "directions": {"type": "array", "items": {"type": "string"}},
                "research_brief": {"type": "string"},
                "resolved_query": {"type": "string"},
                "target_section": {"type": "string"},
            },
            "required": ["intent", "needs_clarification", "message", "directions", "research_brief", "resolved_query", "target_section"],
        },
    },
}


class TurnDecision(BaseModel):
    intent: Literal["report_qa", "initial_research", "supplementary_research", "deepening"]
    needs_clarification: bool = False
    message: str = ""
    directions: list[str] = []
    research_brief: str = ""
    resolved_query: str = ""
    target_section: str = ""


class Clarifier:
    def __init__(self, llm: llm_client, system_prompt: str = CLARIFIER_SYSTEM, creative_temperature: float = 0.6):
        self.llm = llm
        self.system_prompt = system_prompt
        self.creative_temperature = creative_temperature

    def run(self, raw_query: str) -> str:
        result = self.analyze(raw_query)
        if result.is_clear:
            return result.brief

        message = result.message
        directions = result.directions
        
        # display
        if message:
            display.info("\n%s", message)
        if directions:
            for i, d in enumerate(directions, 1):
                display.info("  %d. %s", i, d)

        # parse response
        user_response = input("> ").strip()
        if directions and user_response.isdigit():
            idx = int(user_response) - 1
            if 0 <= idx < len(directions):
                user_response = directions[idx]

        response = self.refine(raw_query=raw_query, user_response=user_response)

        return response

    def analyze(self, raw_query: str) -> ClarifyResult:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": CLARIFIER_USER.format(raw_query=raw_query)},
        ]
        response = self.llm.invoke(
            messages=messages,
            tools=[analyze_schema],
            tool_choice={"type": "function", "function": {"name": "analyze_query"}},
            temperature=1,
            tag="clarifier:analyze",
        )

        if not response.tool_calls:
            logger.warning("[Clarifier] function calling 失败，直接使用原始 query")
            return ClarifyResult(is_clear=True, brief=raw_query)

        args: dict = json.loads(response.tool_calls[0].function.arguments)

        if args.get("is_clear"):
            logger.info("[Clarifier] query 足够具体，生成 research_brief")
            return ClarifyResult(
                is_clear=True,
                brief=args.get("research_brief", raw_query),
            )

        logger.info("[Clarifier] query 不够具体，询问用户确认")
        return ClarifyResult(
            is_clear=False,
            directions=args.get("suggested_directions", []),
            message=args.get("message"),
        )

    def refine(self, raw_query: str, user_response: str) -> str:
        if not user_response:
            logger.info("[Clarifier] 用户未回答，直接使用原始 query")
            return raw_query

        refine_messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": CLARIFIER_REFINE_USER.format(
                raw_query=raw_query, user_response=user_response
            )},
        ]
        refine_response = self.llm.invoke(messages=refine_messages, temperature=self.creative_temperature, tag="clarifier:refine")
        logger.info("[Clarifier] 生成 research_brief 完成")

        return refine_response.content

    def route_turn(self, message: str, workspace_context: dict) -> TurnDecision:
        context = json.dumps(workspace_context, ensure_ascii=False, default=str)
        response = self.llm.invoke(
            messages=[
                {"role": "system", "content": CLARIFIER_TURN_SYSTEM},
                {"role": "user", "content": CLARIFIER_TURN_USER.format(
                    workspace_context=context,
                    message=message,
                )},
            ],
            tools=[turn_schema],
            tool_choice={"type": "function", "function": {"name": "route_turn"}},
            temperature=0,
            tag="clarifier:route_turn",
        )

        try:
            raw = response.tool_calls[0].function.arguments if response.tool_calls else response.content
            return TurnDecision.model_validate_json(raw)
        except Exception as exc:
            logger.warning("[Clarifier] turn routing failed; asking for clarification: %s", exc)
            return TurnDecision(
                intent="report_qa",
                needs_clarification=True,
                message="我没能确定你希望我解释现有资料，还是继续开展/补充调研。你想做哪一种？",
            )

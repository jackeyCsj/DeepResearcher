"""逐步运行深度研究主流程的前半段，便于定位结构化输出问题。

示例：
    python examples/debug_pipeline.py --query "帮我调研一下当前电脑内存条的价格为什么会上涨这么多？" --skip-search --raw-plan
    python examples/debug_pipeline.py --query "..." --max-tokens 8192 --raw-plan
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deep_research.config import config
from deep_research.core.executor import ExecutionModule
from deep_research.core.planner import GraphPlanner, PLANNER_SYSTEM_PROMPT
from deep_research.core.router import Router
from deep_research.core.writer import Writer
from deep_research.main import create_default_tools
from deep_research.models.actions import ActionType, ToolCallAction
from deep_research.models.evidence import EvidenceBase
from deep_research.models.plan import ResearchPlan
from deep_research.utils.llm_client import LLMClient


def print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def print_model(label: str, value: Any) -> None:
    print_header(label)
    if hasattr(value, "model_dump_json"):
        print(value.model_dump_json(indent=2))
    else:
        print(value)


async def run_raw_plan_call(llm: LLMClient, planner: GraphPlanner, topic: Any, outline: Any) -> None:
    """直接调用 Planner 的 ResearchPlan 提示词，打印原始返回长度和尾部。"""
    print_header("Raw Planner ResearchPlan Call")
    prompt = planner._build_init_plan_prompt(topic, outline)
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    response_format_type = llm._select_response_format()
    kwargs: dict[str, Any] = {
        "model": llm.model,
        "messages": messages,
        "temperature": llm.temperature,
        "max_tokens": llm.default_output_tokens,
    }
    if response_format_type is not None:
        kwargs["response_format"] = llm._response_format_payload(
            response_format_type,
            ResearchPlan,
        )
        kwargs["messages"] = llm._messages_with_json_instruction(messages, ResearchPlan)

    response = await llm._client.chat.completions.create(**kwargs)
    choice = response.choices[0]
    content = choice.message.content or ""
    print(f"model={llm.model}")
    print(f"base_url={llm.base_url}")
    print(f"response_format={response_format_type}")
    print(f"max_tokens={kwargs['max_tokens']}")
    print(f"finish_reason={getattr(choice, 'finish_reason', None)}")
    print(f"content_chars={len(content)}")
    print("\n--- HEAD ---")
    print(content[:1200])
    print("\n--- TAIL ---")
    print(content[-1200:])

    try:
        plan = llm._parse_structured_response(content, ResearchPlan)
        print("\nparse_ok=True")
        print(f"nodes={len(plan.nodes)} edges={len(plan.edges)}")
    except Exception as exc:
        print("\nparse_ok=False")
        print(f"parse_error={type(exc).__name__}: {exc}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Debug deep research pipeline stages")
    parser.add_argument("--query", required=True, help="Research query to debug")
    parser.add_argument("--skip-search", action="store_true", help="Use empty evidence instead of Tavily search")
    parser.add_argument("--raw-plan", action="store_true", help="Print raw ResearchPlan LLM response before parser fallback")
    parser.add_argument("--max-tokens", type=int, default=None, help="Override LLM max output tokens for this run")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    llm = LLMClient()
    if args.max_tokens is not None:
        llm.max_tokens = args.max_tokens
        llm.default_output_tokens = args.max_tokens

    print_header("Config")
    print(f"model={llm.model}")
    print(f"base_url={llm.base_url}")
    print(f"config.llm_max_tokens={config.llm_max_tokens}")
    print(f"configured llm.max_tokens={llm.max_tokens}")
    print(f"default output tokens={llm.default_output_tokens}")

    tools = create_default_tools()
    router = Router(llm)
    executor = ExecutionModule(tools, llm)
    writer = Writer(llm)
    planner = GraphPlanner(llm)

    topic = await router.analyze(args.query)
    print_model("1. Router TopicSpec", topic)

    evidence = EvidenceBase()
    if not args.skip_search:
        action = ToolCallAction(
            id="debug-coarse",
            type=ActionType.TOOL_CALL,
            subtask_id="debug-coarse",
            description=f"Initial broad search for: {topic.core_topic or topic.query}",
            tool_name="web_search",
            tool_input=topic.core_topic or topic.query,
            tool_params={"max_results": 5},
        )
        bundles = await executor.execute_parallel([action])
        for bundle in bundles:
            evidence.incorporate(bundle)
        print_model("2. Coarse Search EvidenceBase", evidence)
    else:
        print_model("2. Coarse Search EvidenceBase skipped", evidence)

    outline = await writer.generate_outline(topic, evidence)
    print_model("3. Writer Outline", outline)

    if args.raw_plan:
        await run_raw_plan_call(llm, planner, topic, outline)

    try:
        plan = await planner.init_plan(topic, outline)
        print_model("4. Planner ResearchPlan", plan)
        print_header("Ready Frontier")
        frontier = plan.ready_frontier()
        for node in frontier:
            print(f"{node.id}: [{node.subtask_type.value}] {node.title} depth={node.depth}")

        actions = await planner.select_actions(plan, frontier=frontier)
        print_header("5. Planner Selected Actions")
        print(f"actions={len(actions)}")
        for action in actions:
            print(action.model_dump_json(indent=2))
    except ValidationError as exc:
        print_header("Planner init_plan failed")
        print(exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

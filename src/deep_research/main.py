"""DuMate-DeepResearch 框架的 CLI 入口。

用法：
    python -m deep_research.main --query "Your research question"
    python -m deep_research.main --query "Your question" --max-iterations 10
    python -m deep_research.main --query "问题" --model gpt-4o --output report.md
"""

from __future__ import annotations
import argparse
import asyncio
import logging
import sys
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from deep_research.config import config, ResearchConfig
from deep_research.models.state import ResearchState
from deep_research.models.topic import TopicSpec, TaskContext
from deep_research.core.router import Router
from deep_research.core.planner import GraphPlanner
from deep_research.core.executor import ExecutionModule
from deep_research.core.writer import Writer
from deep_research.core.reflection import ReflectionGate
from deep_research.rubric.generator import RubricGenerator
from deep_research.rubric.stopping import AdaptiveStopping
from deep_research.tools.registry import ToolRegistry
from deep_research.tools.search import create_search_provider
from deep_research.tools.crawler import WebCrawlerTool
from deep_research.utils.llm_client import LLMClient
from deep_research.graph.orchestration_graph import build_orchestration_graph

console = Console()


def setup_logging(verbose: bool = False) -> None:
    """配置 Rich 日志输出；verbose=True 时开启 DEBUG 级别。"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, console=console, show_time=False)],
    )
    # 降低第三方库日志噪声，避免淹没研究循环本身的进度信息。
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("langgraph").setLevel(logging.WARNING)
    logging.getLogger("langchain").setLevel(logging.WARNING)


def create_default_tools() -> ToolRegistry:
    """创建并注册默认工具集合。"""
    registry = ToolRegistry()

    search_tool = create_search_provider("tavily")
    if search_tool is not None:
        registry.register(search_tool)

    # 创建网页爬虫工具，用于抓取搜索结果的完整页面内容
    crawler = WebCrawlerTool()
    # 将爬虫工具注册到工具注册表，供执行阶段的深度阅读节点调用
    registry.register(crawler)

    return registry


async def run_research(
    query: str,
    llm_client: Optional[LLMClient] = None,
    tools: Optional[ToolRegistry] = None,
    max_iterations: int = 15,
    verbose: bool = False,
) -> str:
    """运行一次完整的深度研究流程。

    Args:
        query: 用户输入的研究问题。
        llm_client: 可选 LLM 客户端；未提供时按配置创建。
        tools: 可选工具注册表；未提供时创建默认工具集合。
        max_iterations: 外层规划循环最大轮次。
        verbose: 是否开启调试日志。

    Returns:
        最终研究报告文本。
    """
    setup_logging(verbose)

    if llm_client is None:
        llm_client = LLMClient()
    if tools is None:
        tools = create_default_tools()

    # 实例化外层编排图所需的核心模块。
    router = Router(llm_client)
    planner = GraphPlanner(llm_client)
    executor = ExecutionModule(tools, llm_client)
    writer = Writer(llm_client)
    reflection_gate = ReflectionGate(llm_client)
    rubric_generator = RubricGenerator(llm_client)
    stopping = AdaptiveStopping()

    # 将核心模块装配成 LangGraph 主编排图。
    graph = build_orchestration_graph(
        router, planner, executor, writer,
        reflection_gate, rubric_generator, stopping,
    )

    # 初始化全局 ResearchState；后续所有节点都围绕这个状态读写。
    initial_state = ResearchState(
        context=TaskContext(
            topic=TopicSpec(query=query),
        ),
        max_iterations=max_iterations,
    )

    console.print("[bold blue]DuMate-DeepResearch[/bold blue]")
    console.print(f"[dim]Research:[/dim] {query}")
    console.print(f"[dim]Max iterations:[/dim] {max_iterations}")
    console.print()

    # 运行图并显示一个粗粒度进度条；实际步骤由 LangGraph 内部状态机驱动。
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task(
            "[cyan]Researching...[/cyan]", total=max_iterations
        )

        final_state = await graph.ainvoke(
            initial_state,
            {"recursion_limit": max_iterations * 3 + 10},
        )
        if isinstance(final_state, dict):
            final_state = ResearchState.model_validate(final_state)

        progress.update(task, completed=max_iterations)

    console.print()
    console.print("[bold green]✓ Research complete![/bold green]")
    console.print(f"[dim]Iterations:[/dim] {final_state.iteration}")
    console.print(
        f"[dim]Evidence collected:[/dim] {len(final_state.evidence_base.all_records)} records"
    )

    if final_state.final_report:
        console.print(f"[dim]Report length:[/dim] {len(final_state.final_report)} chars")
        return final_state.final_report
    else:
        console.print("[yellow]Warning: No report was generated.[/yellow]")
        return ""


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="DuMate-DeepResearch: Multi-agent deep research framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m deep_research.main --query "How do low-code platforms impact traditional development?"
  python -m deep_research.main --query "问题" --model gpt-4o --output report.md --verbose
        """,
    )

    parser.add_argument(
        "--query", "-q",
        type=str,
        required=True,
        help="The research question to investigate",
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        default=config.llm_model,
        help=f"LLM model to use (default: {config.llm_model})",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output file path for the report (printed to stdout if not set)",
    )
    parser.add_argument(
        "--max-iterations", "-i",
        type=int,
        default=config.max_plan_iterations,
        help=f"Maximum planning iterations (default: {config.max_plan_iterations})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose debug logging",
    )

    return parser.parse_args(argv)


async def main_async(argv: Optional[list] = None) -> int:
    """异步主入口。"""
    args = parse_args(argv)

    # 命令行参数优先级高于 .env 中的默认配置。
    config.llm_model = args.model
    config.max_plan_iterations = args.max_iterations

    report = await run_research(
        query=args.query,
        max_iterations=args.max_iterations,
        verbose=args.verbose,
    )

    if not report:
        return 1

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        console.print(f"[green]Report saved to:[/green] {args.output}")
    else:
        console.print()
        console.print("[bold]=== REPORT ===[/bold]")
        console.print(report)

    return 0


def main(argv: Optional[list] = None) -> int:
    """同步入口：负责把异步 main 包装成普通 CLI 调用。"""
    return asyncio.run(main_async(argv))


if __name__ == "__main__":
    sys.exit(main())

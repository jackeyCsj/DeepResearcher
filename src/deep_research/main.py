"""CLI entry point for the DuMate-DeepResearch framework.

Usage:
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
    """Configure logging with rich handler."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, console=console, show_time=False)],
    )
    # Quiet down noisy libs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("langgraph").setLevel(logging.WARNING)
    logging.getLogger("langchain").setLevel(logging.WARNING)


def create_default_tools() -> ToolRegistry:
    """Create and register default tools."""
    registry = ToolRegistry()

    search_tool = create_search_provider("tavily")
    if search_tool is not None:
        registry.register(search_tool)

    crawler = WebCrawlerTool()
    registry.register(crawler)

    return registry


async def run_research(
    query: str,
    llm_client: Optional[LLMClient] = None,
    tools: Optional[ToolRegistry] = None,
    max_iterations: int = 15,
    verbose: bool = False,
) -> str:
    """Run a full deep research session.

    Args:
        query: The research question.
        llm_client: Optional LLM client (created from config if not provided).
        tools: Optional tool registry (created with defaults if not provided).
        max_iterations: Maximum planning loop iterations.
        verbose: Enable debug logging.

    Returns:
        The final research report as a string.
    """
    setup_logging(verbose)

    if llm_client is None:
        llm_client = LLMClient()
    if tools is None:
        tools = create_default_tools()

    # Instantiate all modules
    router = Router(llm_client)
    planner = GraphPlanner(llm_client)
    executor = ExecutionModule(tools, llm_client)
    writer = Writer(llm_client)
    reflection_gate = ReflectionGate(llm_client)
    rubric_generator = RubricGenerator(llm_client)
    stopping = AdaptiveStopping()

    # Build the orchestration graph
    graph = build_orchestration_graph(
        router, planner, executor, writer,
        reflection_gate, rubric_generator, stopping,
    )

    # Initialize state
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

    # Run with progress display
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

        final_state = await graph.arun(
            initial_state,
            {"recursion_limit": max_iterations * 3 + 10},
        )

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
    """Parse command-line arguments."""
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
    """Async main entry point."""
    args = parse_args(argv)

    # Override config from args
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
    """Synchronous entry point."""
    return asyncio.run(main_async(argv))


if __name__ == "__main__":
    sys.exit(main())

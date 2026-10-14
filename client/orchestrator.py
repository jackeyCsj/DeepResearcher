import os, json

from client.agents import Supervisor, Researcher, Writer
from client.base import LLMClient
from client.config import Config
from client.context import HistoryCompactor, TokenCounter, ContextBuilder
from client.graph import build_graph
from client.library import LibraryManager
from client.mcp import create_mcp_clients, register_mcp_tools
from client.rag import Pipeline
from client.search import SearchTool
from client.tools import ToolRegistry, RAGTool, PaperReaderTool


class Orchestrator:
    def __init__(self, config: Config):
        self.config = config
        self.llm_client = LLMClient(model=config.llm.model, timeout=config.llm.timeout)
        token_counter = TokenCounter()
        history_compactor = HistoryCompactor(llm_client=self.llm_client, token_counter=token_counter)
        self.context_builder = ContextBuilder(
            history_compactor=history_compactor,
            token_counter=token_counter,
        )
        self.rag_pipeline = Pipeline(data_dir=config.data_dir, llm_client=self.llm_client)
        self.mcp_clients = create_mcp_clients(
            os.path.join(self.config.config_dir, "mcp_servers.json")
        )
        tool_registry = ToolRegistry()
        register_mcp_tools(registry=tool_registry, clients=self.mcp_clients)

        tavily_tool = tool_registry.tools.get("mcp__tavily__tavily_search")
        brave_tool = tool_registry.tools.get("mcp__brave-search__brave_web_search")
        if not tavily_tool and not brave_tool:
            raise ValueError(
                "至少需要配置 TAVILY_API_KEY 或 BRAVE_API_KEY 才能启用 search 工具"
            )
        search_tool = SearchTool(tavily_tool=tavily_tool, brave_tool=brave_tool)
        
        download_tool = tool_registry.tools.get("mcp__paper-search__download_arxiv")
        read_tool = tool_registry.tools.get("mcp__paper-search__read_arxiv_paper")
        if download_tool and read_tool:
            paper_reader_tool = PaperReaderTool(download_tool=download_tool, read_tool=read_tool)
            self.paper_reader = paper_reader_tool
        else:
            paper_reader_tool = None
            self.paper_reader = None

        rag_tool = RAGTool(pipeline=self.rag_pipeline)
        
        pdfmux_tool = tool_registry.tools.get("mcp__pdfmux__convert_pdf")
        self.pdfmux_tool = pdfmux_tool

        tool_registry.register_tool(search_tool)
        if paper_reader_tool:
            tool_registry.register_tool(paper_reader_tool)
        tool_registry.register_tool(rag_tool)

        with open(os.path.join(self.config.config_dir, "agents.json")) as f:
            agent_configs = json.load(f)

        whitelist = agent_configs["researcher"]["allowed_tools"]
        optional_tool_prefixes = (
            "mcp__github__",
            "mcp__fetch__",
            "mcp__paper-search__",
        )
        optional_tools = {"read_arxiv_paper"}
        available_whitelist = []
        for name in whitelist:
            if name in tool_registry.tools:
                available_whitelist.append(name)
            elif name.startswith(optional_tool_prefixes) or name in optional_tools:
                continue
            else:
                available_whitelist.append(name)
        self.researcher_tools = tool_registry.get_tools(available_whitelist)
        
    def run_research(
        self,
        brief: str,
        user_id: str = "default",
        *,
        base_research_brief: str | None = None,
        intent: str = "initial_research",
        task_id: str = "",
        run_id: str = "",
        parent_version_id: str = "",
        planning_context: str = "",
        research_feedback: str = "",
        prior_notes: list[tuple[str, str]] | None = None,
        previous_report: str = "",
    ):
        review_llm = LLMClient(model=self.config.llm.review_model, timeout=self.config.llm.timeout) if self.config.llm.review_model else None
        supervisor = Supervisor(llm=self.llm_client, context_builder=self.context_builder, max_steps=self.config.max_steps, review_llm=review_llm)
        writer = Writer(llm=self.llm_client, context_builder=self.context_builder, temperature=self.config.llm.writer_temperature)
        researcher_tools = [
            RAGTool(pipeline=self.rag_pipeline, user_id=user_id)
            if tool.name == "rag_search"
            else tool
            for tool in self.researcher_tools
        ]

        # make sure that every researcher's history is independent
        def create_researcher(researcher_id: str = "R-?"):
            return Researcher(
                name=researcher_id,
                llm=self.llm_client,
                context_builder=self.context_builder,
                tool_list=researcher_tools,
                max_steps=self.config.max_steps,
                temperature=self.config.llm.research_temperature,
            )

        graph = build_graph(supervisor, create_researcher, writer, self.rag_pipeline, self.config.max_rounds)
        graph_generator = graph.stream({
            "research_brief": brief,
            "base_research_brief": base_research_brief or brief,
            "user_id": user_id,
            "intent": intent,
            "task_id": task_id,
            "run_id": run_id,
            "parent_version_id": parent_version_id,
            "planning_context": planning_context,
            "research_feedback": research_feedback,
            "prior_notes": prior_notes or [],
            "previous_report": previous_report,
        })
        for event in graph_generator:
            yield event

    def create_library_manager(self, user_id: str | None = None) -> LibraryManager:
        data_dir = self.config.data_dir
        if user_id:
            safe_user_id = Pipeline._safe_path_part(user_id, "default")
            data_dir = os.path.join(data_dir, "user_libraries", safe_user_id)
        manager = LibraryManager(
            data_dir=data_dir,
            paper_tool=self.paper_reader,
            pdfmux_tool=self.pdfmux_tool,
            pipeline=self.rag_pipeline,
        )
        return manager

    def close(self):
        if self.paper_reader:
            self.paper_reader.cleanup()
        for client in self.mcp_clients:
            client.disconnect()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

import json
import logging
import os
import asyncio
import shutil
import time
import threading
from concurrent.futures import Future

from dotenv import load_dotenv
from typing import Any
from mcp.types import CallToolResult, Tool
from pydantic import BaseModel, Field
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession
from ..tools.base_tool import ToolCallError

logger = logging.getLogger(__name__)

load_dotenv()


class MCPServerConfig(BaseModel):
    name: str
    command: str
    args: list[str]
    env: dict[str, str] | None = None
    optional: bool = False
    required_env: list[str] = Field(default_factory=list)
    connect_timeout: float = 45.0

    def to_stdio_params(self) -> StdioServerParameters:
        env = {**os.environ, **self.env} if self.env else os.environ
        config = StdioServerParameters(
            command=self.command, 
            args=self.args, 
            env=env,
        )
        return config


class MCPClient:
    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.name = config.name
        self.server_config: StdioServerParameters = config.to_stdio_params()
        self.connect_timeout = config.connect_timeout
        self._thread = None
        self._queue = None
        self._ready_event = None
        self._loop = None
        self._connect_error = None
        self.tools = []

    def connect(self) -> list[Tool]:
        self._queue = asyncio.Queue()

        self._ready_event = threading.Event()
        self._thread = threading.Thread(target=self._run_background, daemon=True)
        self._thread.start()

        if not self._ready_event.wait(timeout=self.connect_timeout):
            raise TimeoutError(
                f"MCP 服务连接超时: {self.name} ({self.connect_timeout:.0f}s)"
            )

        if self._connect_error:
            logger.error("[MCP] 连接失败: %s - %s", self.name, self._connect_error)
            raise self._connect_error

        logger.info("[MCP] 连接: %s (%d 个工具)", self.name, len(self.tools))
        return self.tools

    def _run_background(self):
        asyncio.run(self._async_main())

    async def _async_main(self):
        self._loop = asyncio.get_running_loop()

        try:
            async with stdio_client(self.server_config) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self.tools = (await session.list_tools()).tools
                    # (
                    #     self._session.list_tools(),
                    #     await self._session.list_resources(),
                    #     await self._session.list_prompts(),
                    # )
                    self._connect_error = None
                    self._ready_event.set()

                    while True:
                        command = await self._queue.get()
                        if command is None:
                            break

                        future: Future
                        name, args, future = command
                        try:
                            result = await session.call_tool(name=name, arguments=args)
                            future.set_result(result)
                        except Exception as e:
                            future.set_exception(e)
        except Exception as e:
            self._connect_error = e
            self._ready_event.set()

    def call_tool(self, name: str, args: dict[str, Any], _max_retries: int = 3):
        if self._loop is None:
            raise RuntimeError("MCPClient 未连接")

        for attempt in range(_max_retries + 1):
            future = Future()
            self._loop.call_soon_threadsafe(self._queue.put_nowait, (name, args, future))
            try:
                result: CallToolResult = future.result()
            except Exception as e:
                if "already borrowed" in str(e).lower() and attempt < _max_retries:
                    logger.warning("[MCP] %s: already borrowed, 重试 %d/%d", name, attempt + 1, _max_retries)
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise

            if result.isError:
                error_text = result.content[0].text if result.content else "Unknown error"
                if "already borrowed" in error_text.lower() and attempt < _max_retries:
                    logger.warning("[MCP] %s: already borrowed, 重试 %d/%d", name, attempt + 1, _max_retries)
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise ToolCallError(message=f"工具调用失败: {error_text}", tool_name=name)

            return "\n".join(item.text for item in result.content)

        raise ToolCallError(message="工具调用失败: already borrowed 重试次数用尽", tool_name=name)

    def disconnect(self):
        if self._thread is None:
            return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, None)
        self._thread.join()
        self._loop = None


def load_mcp_server_configs(json_path: str) -> list[MCPServerConfig]:
    with open(json_path, "r", encoding="utf-8") as f:
        configs: dict[str, dict] = json.load(f)

    server_configs: list[MCPServerConfig] = []
    project_root = os.path.abspath(os.path.join(os.path.dirname(json_path), os.pardir))
    npm_cache_dir = os.path.join(project_root, "data", "npm-cache")
    for name, config in configs.items():
        optional = config.get("optional", False)
        required_env = config.get("required_env", [])
        raw_env: dict[str, str] = config.get("env") or {}
        env: dict[str, str] = {}
        missing_required: list[str] = []

        for key, value in raw_env.items():
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                env_name = value[2:-1]
                env_value = os.getenv(env_name)
                if env_value is None:
                    if env_name in required_env:
                        missing_required.append(env_name)
                    env[key] = ""
                else:
                    env[key] = env_value
            else:
                env[key] = "" if value is None else str(value)

        if missing_required:
            message = (
                f"[MCP] 跳过 {name}: 缺少环境变量 "
                f"{', '.join(missing_required)}"
            )
            if optional:
                logger.warning(message)
                continue
            raise ValueError(message)

        command = config["command"]
        resolved_command = shutil.which(command)
        if resolved_command is None:
            message = f"[MCP] command not found for {name}: {command}"
            if optional:
                logger.warning("%s; skipping optional MCP server", message)
                continue
            raise FileNotFoundError(message)

        command_basename = os.path.basename(resolved_command).lower()
        if command_basename in {"npx", "npx.cmd", "npx.exe", "npm", "npm.cmd", "npm.exe"}:
            os.makedirs(npm_cache_dir, exist_ok=True)
            env.setdefault("npm_config_cache", npm_cache_dir)
            env.setdefault("NPM_CONFIG_CACHE", npm_cache_dir)

        server_config = MCPServerConfig(
            name=name,
            command=resolved_command,
            args=config["args"],
            env=env or None,
            optional=optional,
            required_env=required_env,
            connect_timeout=config.get("connect_timeout", 45.0),
        )
        server_configs.append(server_config)

    return server_configs


def create_mcp_clients(json_path: str) -> list[MCPClient]:
    server_configs = load_mcp_server_configs(json_path)

    clients = []
    for config in server_configs:
        client = MCPClient(config)
        try:
            client.connect()
        except Exception:
            if config.optional:
                logger.warning("[MCP] 跳过可选服务: %s", config.name, exc_info=True)
                continue
            raise
        clients.append(client)

    return clients

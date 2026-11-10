# Deep Research

一个自主多 Agent 研究系统：把研究问题拆分成并行子问题，搜索网页、学术论文和本地文献，经过质量审查后生成带引用的 Markdown 报告。Web 应用支持账号登录、持续会话、报告问答、补充研究和报告版本管理；命令行可运行单次研究。

## 功能

- **迭代研究**：Supervisor 规划子问题、并行 Researcher 搜索，Supervisor 根据证据审查结果并重试或补充规划，最后由 Writer 整合报告。
- **多轮会话**：可在同一会话中继续提问。请求路由到报告问答、首轮/新主题研究、补充研究或章节深化；需要更多信息时先向用户澄清。
- **报告版本**：补充研究和章节深化会生成完整的新报告版本，并保留旧版本及版本关系。
- **本地文献 RAG**：支持导入 PDF、Markdown、TXT 和 arXiv 文献；检索采用 BM25 与向量混合召回，再使用 Cross-Encoder 重排。报告和会话状态保存在本地数据目录与 PostgreSQL 中。
- **流式 Web 界面**：通过 SSE 展示研究计划、资料收集、审查和报告生成进度；支持查看历史会话、报告引用及版本。
- **MCP 工具**：通过配置加载 Tavily、网页抓取、论文搜索、PDF 转换和 GitHub 搜索等可选工具。

## 环境要求

- Python 3.10 或更高版本，建议使用 Conda。
- Node.js 20.9 或更高版本及 npm。
- Docker Compose，用于运行 PostgreSQL。
- LLM API 凭证、Tavily Search API key，以及可用的 OpenAI 兼容 Embedding 服务。
- `requirements.txt` 当前安装 CUDA 12.6 版 PyTorch。没有 NVIDIA/CUDA 环境时，需要按机器环境调整 PyTorch 安装方式。

## 安装与配置

克隆仓库并创建本地环境文件：

```bash
git clone https://github.com/jackeyCsj/DeepResearcher.git
cd DeepResearcher
cp .env.example .env
```

PowerShell 创建环境文件：

```powershell
Copy-Item .env.example .env
```

在 `.env` 中至少配置以下项目：

```dotenv
# LLM：模型前缀选择提供商。这里以 DeepSeek 为例。
LLM_MODEL_ID=deepseek-v4-flash
DEEPSEEK_API_KEY=你的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com

# 搜索：当前 configs/mcp_servers.json 默认启用 Tavily。
TAVILY_API_KEY=你的密钥

# Embedding：当前代码使用 OpenAI 兼容 API，并默认从 GLM_API_KEY 读取凭证。
EMBEDDING_MODEL_ID=embedding-3
GLM_API_KEY=你的Embedding服务密钥
EMBEDDING_BASE_URL=https://open.bigmodel.cn/api/paas/v4/

# Web 会话数据库与认证。
DATABASE_URL=postgresql+psycopg://csj:csj@localhost:5432/deep_research
AUTH_SECRET_KEY=请替换为随机且私有的长密钥
```

支持的 LLM 模型名前缀：`deepseek`、`glm`、`gemini`、`gpt`、`qwen` 和 `claude`。各前缀使用的密钥变量及兼容 API 地址见 [.env.example](.env.example) 和 `client/base/llm_client.py`。`REVIEW_MODEL_ID` 可选，用不同模型进行研究质量审查。

> **Embedding 配置说明：** `.env.example` 中目前仍有 hashing/local embedding 的示例配置，但当前 `client/rag/embedding.py` 尚未实现这些 provider 分支；代码要求设置 `EMBEDDING_MODEL_ID`、`GLM_API_KEY` 和 `EMBEDDING_BASE_URL`。首次检索还可能加载并下载 Cross-Encoder 重排模型。

## 启动

安装 Python 依赖并启动 PostgreSQL：

```bash
conda create -n deep_research python=3.11 -y
conda activate deep_research
pip install -r requirements.txt
docker compose up -d postgres
```

安装并启动前端：

```bash
cd web
npm ci
npm run dev
```

另开一个终端，在仓库根目录启动后端：

```bash
conda activate deep_research
python server.py
```

打开 <http://localhost:3000>，注册账号后即可使用。FastAPI 默认运行在 <http://localhost:8001>。`server.py` 使用开发模式自动重载；生产环境请用部署服务器启动 `client.api.app:app`，并妥善配置数据库、CORS、密钥和代理。

### Mock 模式

Mock 模式不需要后端或 API 凭证，使用模拟会话和研究事件：

```bash
cd web
npm run dev:mock
```

PowerShell 下可用以下命令启动 Mock 模式：

```powershell
$env:NEXT_PUBLIC_MOCK="true"
npm run dev
```

### CLI 单次研究

CLI 不需要 PostgreSQL。需配置 LLM、搜索及 Embedding 环境变量：

```bash
conda activate deep_research
python main.py "比较 RAG 与微调在企业知识问答中的适用场景"
```

不传问题时会交互式提示输入。可用参数：

```text
--model MODEL          覆盖 LLM_MODEL_ID
--max-rounds N         最大审查轮数
--max-steps N           每个 Researcher 的最大搜索步数
--timeout SECONDS       LLM 调用超时
--data-dir PATH         数据目录，默认 data/
```

## 文献库

Web 文献库支持上传 PDF、Markdown 和 TXT 文件。PDF 转换需要启用 `pdfmux` MCP 服务；arXiv 导入需要 `paper-search` MCP 服务。直接导入服务端已有文件或 arXiv ID 可使用：

```bash
python library_cli.py list
python library_cli.py add 2301.00001
python library_cli.py add ./paper.pdf --title "自定义标题"
python library_cli.py delete "自定义标题"
```

CLI 文献库使用默认数据目录；Web 文献库按登录用户分别保存。搜索、PDF、论文和 GitHub MCP 服务的启用状态、启动命令及可选环境变量在 [configs/mcp_servers.json](configs/mcp_servers.json) 中配置。启用相应服务前，确保其运行时可用：Tavily/Brave 需要 `npx`，Fetch 需要 `uvx`，GitHub MCP 当前通过 Docker 启动。Brave 服务在默认配置中关闭；至少启用一个搜索服务，当前默认启用 Tavily。

## 多轮会话行为

- **报告问答**：依据当前报告和该用户文献库中的检索片段回答并展示来源；没有足够证据时说明检索不足，不会自动启动研究。
- **补充研究**：调查报告未覆盖的方向，整合已有笔记和新证据，生成新版完整报告。
- **章节深化**：针对指定章节或主题继续检索并生成新版完整报告。
- **新主题研究**：留在当前聊天会话中，但创建独立研究任务和报告版本链。

PostgreSQL 保存账号、会话消息、研究步骤、会话摘要、研究任务、运行状态和报告版本元数据。报告文件、向量索引及文献文件保存在 `data/`。`.gitignore` 已忽略运行时数据；不要提交 API key、私有文献或本地生成报告。

## HTTP API

除注册和登录外，API 需要 `Authorization: Bearer <token>`。主要端点如下：

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/api/auth/register` | 注册账号 |
| `POST` | `/api/auth/login` | 登录并获取 Bearer token |
| `GET` | `/api/auth/me` | 获取当前账号 |
| `POST` | `/api/chat/turns` | 提交新消息；SSE 返回路由、澄清、问答来源或研究进度 |
| `GET` | `/api/sessions` | 列出当前用户会话 |
| `GET` | `/api/sessions/{session_id}` | 读取消息、研究任务和报告版本 |
| `DELETE` | `/api/sessions/{session_id}` | 删除会话及关联数据库记录 |
| `GET` | `/api/reports/{report_file_id}` | 获取当前用户的报告文件 |
| `GET` | `/api/library` | 列出当前用户的文献 |
| `POST` | `/api/library/upload` | 上传文献 |
| `POST` | `/api/library/ingest` | 导入服务端路径或 arXiv ID |
| `DELETE` | `/api/library/{title}` | 删除文献 |

旧的 `/api/clarify`、`/api/clarify/refine` 和 `/api/research` 接口仍保留，用于兼容原有流程。

## 开发检查

```bash
conda activate deep_research
python -m pytest

cd web
npm run lint
npm run build
```

## 项目结构

```text
client/
  agents/       Clarifier、Supervisor、Researcher、Writer 与问答生成
  api/          FastAPI 路由、认证、请求/响应模型及 SSE
  db/           SQLAlchemy 模型与会话/任务/版本仓库
  graph/        LangGraph 研究状态图
  rag/          分块、Embedding、向量存储、混合检索和重排
  search/       Brave/Tavily 搜索适配器
  mcp/          MCP 客户端与工具注册
  library/      PDF、文本和 arXiv 文献导入
  context/      Token 计数和 agent 历史压缩
  orchestrator.py 组装依赖并启动研究图
web/            Next.js 前端
configs/        MCP 服务和 Agent 工具白名单
tests/          后端测试
data/           本地索引、文献、报告及缓存（运行时生成）
```

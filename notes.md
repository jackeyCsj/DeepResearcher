# 项目笔记

## 1. 项目定位

SAGE Research 是一个自主多 Agent 研究系统：用户输入研究问题后，系统会先判断问题是否清晰，再把研究目标拆成多个子问题，并行检索和阅读资料，经过质量审查后生成带引用的 Markdown 研究报告。

核心链路可以概括为：

```text
用户问题
  ↓
Clarifier 澄清/生成 research brief
  ↓
Supervisor 拆分子问题
  ↓
Researcher xN 并行 ReAct 检索与写研究笔记
  ↓
Supervisor 审查笔记，通过 / 重试 / 重新规划
  ↓
Writer 合并通过的笔记，生成最终报告
  ↓
报告自动写入本地 RAG 知识库
```

项目同时提供两种使用方式：

- CLI：`main.py`，适合命令行直接运行研究任务。
- Web：`server.py` 启动 FastAPI 后端，`web/` 中的 Next.js 前端通过 API 和 SSE 实时展示进度。

## 2. 项目结构

```text
D:\MultiAgentResearch
├── main.py                    # CLI 入口
├── server.py                  # FastAPI / Uvicorn 启动入口
├── library_cli.py             # 文献库相关 CLI
├── requirements.txt           # Python 依赖
├── configs/
│   ├── agents.json            # 各 Agent 允许调用的工具白名单
│   └── mcp_servers.json       # MCP 服务配置
├── data/                      # 运行时数据目录，不应提交生成内容
│   ├── vector_store.json      # RAG 向量/分块索引持久化文件，运行后生成
│   ├── search_cache/          # 报告或搜索摘要回存后的 Markdown
│   ├── originals/             # 原始上传文件或 arXiv PDF
│   ├── converted/             # 转换后的 Markdown 文献
│   └── index.json             # 文献库元数据索引，运行后生成
├── client/
│   ├── api/                   # FastAPI app 和 Pydantic schema
│   ├── agents/                # Clarifier / Supervisor / Researcher / Writer
│   ├── base/                  # LLMClient、AgentBase、Message、日志
│   ├── context/               # token 统计、历史压缩、上下文构建
│   ├── graph/                 # LangGraph 状态图
│   ├── library/               # 文献导入、转换、删除
│   ├── mcp/                   # MCP client 和工具适配
│   ├── rag/                   # 分块、embedding、BM25/向量混合检索、rerank
│   ├── search/                # Brave / Tavily 搜索包装
│   ├── tools/                 # 内置工具注册、RAG 工具、论文阅读工具
│   └── orchestrator.py        # 后端总编排器
└── web/
    ├── app/                   # Next.js App Router 页面和全局样式
    ├── components/            # 输入、澄清、研究进度、报告、文献库组件
    └── lib/                   # API client 和 mock SSE
```

> 注意：仓库指南里提到的 `sage_research/` 在当前代码中实际对应的是 `client/` 目录。

## 3. 技术栈

### 后端

- Python，FastAPI，Uvicorn。
- LangGraph 负责研究流水线状态图。
- OpenAI SDK 作为 OpenAI-compatible 模型客户端，同时额外适配 Anthropic Claude。
- Pydantic 用于 Agent 结构化输出和 API schema。
- MCP 用于动态接入外部工具，如网页抓取、论文搜索、PDF 转换、GitHub 搜索等。
- RAG 检索依赖 `jieba`、`rank-bm25`、OpenAI-compatible embedding API 和 `sentence-transformers` CrossEncoder。

### 前端

- Next.js 16，React 19，TypeScript。
- Tailwind CSS 4。
- `react-markdown`、`remark-gfm`、`remark-math`、`rehype-katex`、`rehype-raw` 用于渲染 Markdown 报告、表格、数学公式和引用。
- 前端通过 `fetch` 调用 REST API，并用 SSE 流式接收研究进度。

## 4. 后端入口与整体编排

### CLI 入口

`main.py` 做这些事情：

1. 解析命令行参数：研究问题、模型、最大审查轮数、Researcher 最大步数、超时、数据目录。
2. 创建 `Config`。
3. 创建 `Orchestrator`。
4. 先用 `Clarifier.run()` 把原始问题变成 research brief。
5. 调用 `orch.run_research(research_brief)`，并把事件流交给 `stream_events()` 打印。
6. 最后输出 LLM 调用次数和 token 统计。

### Web 后端入口

`server.py` 只负责：

```python
uvicorn.run("client.api.app:app", host="0.0.0.0", port=8001, reload=True)
```

真正的 API 在 `client/api/app.py`：

- `/api/clarify`：判断问题是否清晰，返回建议方向或 brief。
- `/api/clarify/refine`：把用户补充说明整合成 brief。
- `/api/research`：运行完整研究流水线，并以 `text/event-stream` 返回 SSE。
- `/api/library`：列出本地文献库。
- `/api/library/upload`：上传 PDF / Markdown / TXT 并导入知识库。
- `/api/library/ingest`：按路径或 arXiv ID 导入文献。
- `/api/library/{title}`：删除文献及其索引。

### Orchestrator

`client/orchestrator.py` 是后端核心组装点：

1. 创建 `LLMClient`。
2. 创建 `TokenCounter`、`HistoryCompactor`、`ContextBuilder`。
3. 创建 RAG `Pipeline`。
4. 读取 `configs/mcp_servers.json` 并启动 MCP clients。
5. 注册 MCP 工具、内置 `search`、`read_arxiv_paper`、`rag_search`。
6. 读取 `configs/agents.json` 中 researcher 的工具白名单。
7. 每次 `run_research()` 时新建 `Supervisor`、`Writer`，并通过工厂函数为每个子问题创建独立 `Researcher`。

这里有一个重要设计：每个 Researcher 都是临时创建的，因此每个子问题的短期历史彼此隔离；Supervisor 和 Writer 则负责跨子问题的规划、审查和汇总。

## 5. LangGraph 数据流

研究状态图定义在 `client/graph/graph_builder.py`。

状态 `State` 主要字段：

- `research_brief`：澄清后的研究目标。
- `sub_questions`：Supervisor 拆出来的子问题。
- `pending_review_pairs`：等待审查的 `(子问题, 笔记)`。
- `approved_pairs`：已通过审查的 `(子问题, 笔记)`。
- `review_result`：Supervisor 的结构化审查结果。
- `retry_items`：需要补充研究的问题和失败原因。
- `refine_round`：审查/修订轮次。
- `final_report`：Writer 生成的最终报告。
- `tool_call_counts`：每个 Researcher 调用工具的次数，供前端展示。

状态图节点：

```text
START
  ↓
plan_node
  ↓ Send 多个 sub_question
research_node（并行）
  ↓
review_node
  ├── 全部 approved → write_node
  ├── 只有 approved/retry 且无缺失维度 → retry 的问题回到 research_node
  └── 有 revise 或 missing_dimensions → 回到 plan_node 重新规划
  ↓
write_node
  ↓
END
```

`max_rounds` 默认是 3。超过最大轮数后，即使仍有不足，也会进入 `write_node` 生成报告，避免无限循环。

## 6. Agent 分工

### Clarifier

`Clarifier` 负责把用户原始问题变成可执行的研究 brief。

- 如果问题已经明确，返回 `is_clear=true` 和 `brief`。
- 如果问题太宽泛，返回若干 suggested directions。
- 用户选择或补充后，`refine()` 再生成最终 brief。

前端 `ClarifyPanel.tsx` 会先调用 `/api/clarify`，必要时展示建议方向，再调用 `/api/clarify/refine`。

### Supervisor

`client/agents/supervisor.py` 负责两件事：

1. `plan()`：把 research brief 拆成结构化 `SubQuestion` 列表，每个子问题有 `label`、`question` 和 `rationale`。
2. `review()`：审查每条研究笔记，输出 `NoteReview`，判定为：
   - `approved`：通过，可进入最终报告。
   - `retry`：相关方向没错，但深度、引用、来源或完整性不足，需要同一个子问题继续研究。
   - `revise`：方向或覆盖有问题，需要重新规划。

审查标准包括 relevance、depth、citations、sources、completeness。解析结构化输出时优先读 tool call；如果弱模型没有正确返回 tool call，会尝试从普通文本里修复 JSON。

### Researcher

`client/agents/researcher.py` 是实际检索和写笔记的 Agent。它接收单个子问题，在限定步数内执行 ReAct 循环，调用搜索、网页抓取、论文、GitHub、RAG 等工具，最后输出研究笔记。

### Writer

`client/agents/writer.py` 将所有通过审查的研究笔记合并成最终 Markdown 报告。

Writer 还做了引用后处理：

- `_renumber_citations()`：把多条 note 的引用按 URL 或文本去重，并重编号。
- `_resequence_citations()`：按最终正文首次出现顺序重新排序引用编号。
- `_sort_adjacent_citations()`：把相邻引用如 `[4][2]` 调整为 `[2][4]`。

最终报告生成后，`write_node` 会调用 `pipeline.add_text(text=result, query=research_brief)`，自动回存到本地 RAG 知识库。

## 7. Researcher 的 ReAct 循环

Researcher 的核心逻辑在 `Researcher.run()`：

1. 根据是否有 `note_feedback` 选择普通研究提示词或 retry 提示词。
2. 把用户消息加入自己的 `_history`。
3. 在 `max_steps` 内循环：
   1. 先调用 `context_builder.compress_old_rounds()` 压缩旧工具观察。
   2. 构建带 system prompt 和历史消息的上下文。
   3. 调用 LLM，并传入工具 schema。
   4. 如果模型返回 `tool_calls`：
      - 记录 assistant tool call 消息。
      - 逐个执行工具。
      - 把工具结果以 `role="tool"` 写回历史。
   5. 如果模型没有返回 tool call，但正文看起来像 `tool_name({...})`：
      - 用 `_parse_text_tool_call()` 从文本中兜底解析工具调用。
      - 生成 fake tool call id，继续执行工具。
   6. 如果模型返回普通研究结论：
      - 认为 ReAct 完成，跳出循环。
4. 如果达到最大步数还没结束，会追加 `RESEARCHER_MAX_STEPS_PROMPT` 强制总结。
5. 如果正常结束，会调用 `_compress()` 把原始研究输出压缩成干净的研究笔记。
6. 返回 `(note, tool_call_counts)`。

工具执行时还有两个控制：

- 普通工具结果超过 `MAX_TOOL_RESULT_CHARS = 20000` 会截断。
- `mcp__fetch__fetch` 的网页全文会先经过 `_denoise()` 去噪；去噪后超过 `MAX_DENOISE_RESULT_CHARS = 10000` 再截断。

## 8. Note 压缩与上下文压缩

项目里有两类压缩，目标不同。

### 研究 note 压缩

位置：`client/agents/researcher.py::Researcher._compress()`

触发时机：

- Researcher 正常完成 ReAct，即模型输出了最终研究结论后。

做法：

- 使用 `RESEARCHER_COMPRESS_SYSTEM` 和 `RESEARCHER_COMPRESS_USER`。
- 再调用一次 LLM，把原始研究输出整理成结构化、去重、带引用的研究笔记。
- 这个压缩后的 note 才会进入 Supervisor 审查和 Writer 汇总。

如果 Researcher 是因为 `max_steps` 耗尽而强制总结，则当前代码直接使用 forced summary 的内容作为结果，不再额外调用 `_compress()`。

### 上下文历史压缩

位置：

- `client/context/context_builder.py`
- `client/context/history_compactor.py`

有两种机制：

1. `ContextBuilder.build_context()`
   - 先计算 system prompt token 和 history token。
   - 如果历史超过预算 `max_tokens * (1 - reserve_ratio) - system_tokens`，触发 `HistoryCompactor.summarize_all()`。
   - `summarize_all()` 会把整个历史压缩成一条 `[Compacted]` 用户消息。

2. `ContextBuilder.compress_old_rounds()`
   - Researcher 每一步 ReAct 调用前都会检查。
   - 当历史 token 达到可用预算的 40% 以上时，触发 `HistoryCompactor.compress_old_rounds()`。
   - 该函数按 assistant tool call 找出旧轮次，只保留最近 `keep_recent=1` 轮完整观察。
   - 旧的、较长的 tool result 会被批量压缩，并替换为：

     ```text
     [Compressed] Tool: <tool_name> | Args: <tool_args>
     <压缩后的观察内容>
     ```

这样做的效果是：Researcher 可以保留探索轨迹和关键事实，但不会让网页全文、搜索结果或论文片段把上下文窗口挤爆。

## 9. 数据库与持久化

当前项目没有使用传统数据库服务，也没有 SQLite、PostgreSQL、Chroma 或 FAISS。

持久化主要靠文件系统：

- `data/vector_store.json`
  - 保存 RAG 的所有 `Chunk`，包括正文、来源路径、分块编号、embedding、BM25 tokens。
- `data/index.json`
  - 保存文献库元数据，如 title、arxiv_id、converted_path、source_type、added_at、original_path。
- `data/originals/`
  - 保存上传的原始文件或 arXiv PDF。
- `data/converted/`
  - 保存转换后的 Markdown 文献。
- `data/search_cache/`
  - 保存自动回存的报告或搜索摘要 Markdown。
  - RAG Pipeline 初始化时保证存在的文档目录。

因此这里的“数据库”可以理解为轻量级 JSON + 文件目录存储。优点是简单、方便本地运行；缺点是并发写入、超大规模索引和复杂查询能力有限。

## 10. 记忆机制

项目里的记忆分为短期记忆和长期记忆两层。

### 短期记忆

短期记忆就是每个 Agent 的 `_history`，定义在 `client/base/agent.py`。

- Supervisor 的历史记录规划和审查过程。
- 每个 Researcher 有独立历史，记录当前子问题中的 user prompt、assistant tool call、tool result 和最终回答。
- Writer 的历史记录最终写作 prompt 和报告。

`ContextBuilder` 每次构造 LLM 消息时都会把 `_history` 加进去，并按 token 预算触发压缩。

### 长期记忆

当前实际可用的长期记忆主要是 RAG 知识库：

- 文献上传或导入后进入 `data/converted/` 和 `data/vector_store.json`。
- 最终报告会自动通过 `pipeline.add_text()` 保存到 `data/search_cache/`，再进入向量索引。
- Researcher 可以调用 `rag_search` 查询这些历史资料。

`ContextBuilder` 里预留了 `memory_manager` 参数，并写了：

- `memory_manager.get_semantic_index()`
- `memory_manager.retrieve(query)`

但当前仓库中没有实际的 `client/memory/` 实现目录。因此除非后续补上 MemoryManager，否则长期记忆的主要实现就是本地 RAG。

## 11. RAG 实现

RAG 入口是 `client/rag/pipeline.py::Pipeline`，作为工具暴露时由 `client/tools/tool_rag.py::RAGTool` 包装为 `rag_search`。

### 文档导入

文档导入链路：

```text
LibraryManager.ingest()
  ↓
convert_to_markdown()
  ├── arXiv ID → PaperReaderTool 下载/读取
  ├── PDF → pdfmux MCP 转 Markdown
  └── Markdown/TXT → 直接复制
  ↓
Pipeline.add_document()
  ↓
Document.read_file()
  ↓
TextChunker.chunk()
  ↓
Embedding.invoke()
  ↓
VectorStore.add_chunks()
  ↓
VectorStore.save_to_json()
```

`TextChunker` 默认：

- `chunk_size = 500`
- `chunk_overlap = 100`
- 分隔优先级：空行、换行、中文句号、英文句号、空格。

### Embedding

`client/rag/embedding.py::Embedding` 使用 OpenAI-compatible embeddings API。

环境变量：

- `EMBEDDING_MODEL_ID`
- `GLM_API_KEY`（默认作为 embedding API key）
- `EMBEDDING_BASE_URL`
- `EMBEDDING_TIMEOUT`

批量大小 `MAX_BATCH_SIZE = 64`。

### VectorStore

`client/rag/vector_store.py::VectorStore` 是内存中的轻量向量库，持久化到 JSON。

它支持：

- `bm25_search()`：用 `jieba.lcut()` 分词后跑 `BM25Okapi`。
- `cosine_search()`：手写 cosine similarity。
- `hybrid_search()`：BM25 和 cosine 各取候选，再用 RRF 风格分数 `1 / (k + rank)` 融合，默认 `k = 60`。
- `remove_by_filepath()`：删除某个文献对应的全部 chunk。

### Rerank

`client/rag/reranker.py::Reranker` 使用：

```text
cross-encoder/ms-marco-MiniLM-L-6-v2
```

`Pipeline.retrieve()` 会先取 `top_k * 4` 个候选，再用 CrossEncoder 重排，默认返回前 5 个片段。

### MQE

`client/rag/mqe.py::MQE` 支持 Multi-Query Expansion：

- 默认会让 LLM 为用户 query 生成 3 个子查询。
- 对原 query + 子查询分别检索。
- 对相同 chunk 的分数累加。
- 最后统一 rerank。

不过 `Pipeline.__init__()` 默认 `mqe=None`，所以当前默认检索是不启用 MQE 的单 query 混合检索。

### 搜索结果入库

`Pipeline.ingest_search_results()` 可以让 LLM 判断搜索结果是否值得保存：

- 值得保存：提炼成结构化知识摘要，并调用 `add_text()` 入库。
- 不值得保存：跳过。

当前主研究图里明确自动入库的是最终报告；搜索结果入库能力已实现，但是否被工具调用取决于后续接线。

## 12. 工具与 MCP

Researcher 可用工具白名单在 `configs/agents.json`：

- `search`
- `mcp__fetch__fetch`
- `mcp__paper-search__search_arxiv`
- `mcp__paper-search__search_google_scholar`
- `read_arxiv_paper`
- `mcp__github__search_repositories`
- `mcp__github__search_code`
- `rag_search`

`configs/mcp_servers.json` 定义了这些 MCP 服务：

- `brave-search`：Brave Search MCP，需要 `BRAVE_API_KEY`。
- `tavily`：Tavily MCP，需要 `TAVILY_API_KEY`。
- `fetch`：网页全文抓取。
- `paper-search`：arXiv / Google Scholar / 论文读取。
- `pdfmux`：PDF 转 Markdown。
- `github`：GitHub MCP，需要 `GITHUB_TOKEN`，通过 Docker 运行。

`SearchTool` 会优先尝试 Tavily，如果 Tavily 报错或为空，再 fallback 到 Brave。若两者都没配置，Orchestrator 初始化会报错。

## 13. 前端数据流

主要页面是 `web/app/page.tsx`，内部状态机：

```text
input
  ↓ 用户提交问题
sending
  ↓
clarify
  ↓ brief ready
researching
  ↓ report ready
report
```

关键组件：

- `QueryInput.tsx`：首页输入框。
- `ClarifyPanel.tsx`：调用 clarify/refine API，展示建议方向，并把 brief 交给研究进度组件。
- `ResearchProgress.tsx`：调用 `startResearch()`，消费 SSE 事件，渲染 plan / research / review / write 时间线。
- `ReportView.tsx`：渲染最终 Markdown 报告、引用跳转，以及 MD、Word、PDF 导出。
- `LibraryDrawer.tsx`：列出、上传、删除本地文献。
- `StreamingText.tsx`：打字机和 dots 动画效果。

API client 在 `web/lib/api.ts`：

- `clarify()`
- `refine()`
- `startResearch()`
- `listDocs()`
- `uploadFile()`
- `deleteDoc()`

`startResearch()` 使用 `fetch(...).body.getReader()` 手动读取 SSE 数据块，并按 `event:` / `data:` 解析成前端事件。

SSE 事件类型：

- `plan`：子问题列表。
- `research`：某个子问题完成的 note 预览和工具调用次数。
- `review`：某轮审查结果。
- `write`：最终报告。
- `stats`：LLM 调用次数和 token 统计。
- `error`：错误信息。

## 14. 配置与环境变量

核心配置在 `client/config.py`：

- `Config.config_dir = "configs"`
- `Config.data_dir = "data"`
- `Config.max_rounds = 3`
- `Config.max_steps = 3`
- 默认模型 `LLM_MODEL_ID = deepseek-v4-flash`
- Researcher temperature 默认 0.6
- Writer temperature 默认 0.3
- LLM timeout 默认 120 秒
- Context 最大 token 默认 30000，保留比例 15%

`client/base/llm_client.py` 根据模型名前缀选择环境变量：

- `deepseek*` → `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`
- `glm*` → `GLM_API_KEY`、`GLM_BASE_URL`
- `gemini*` → `GOOGLE_API_KEY`、`GOOGLE_BASE_URL`
- `gpt*` → `OPENAI_API_KEY`
- `qwen*` → `QWEN_API_KEY`、`QWEN_BASE_URL`
- `claude*` → `ANTHROPIC_API_KEY`

Embedding 另外需要：

- `EMBEDDING_MODEL_ID`
- `EMBEDDING_BASE_URL`
- `GLM_API_KEY`

搜索至少需要配置：

- `TAVILY_API_KEY` 或 `BRAVE_API_KEY`

可选：

- `REVIEW_MODEL_ID`：让 Supervisor 审查使用不同模型。
- `GITHUB_TOKEN`：启用 GitHub MCP。
- `UNPAYWALL_EMAIL`：paper-search MCP 用于论文检索。

## 15. 运行命令

后端：

```bash
pip install -r requirements.txt
python server.py
```

前端：

```bash
cd web
npm ci
npm run dev
```

前端 mock 模式：

```bash
cd web
npm run dev:mock
```

CLI：

```bash
python main.py "你的研究问题"
python main.py --model deepseek-v4-flash --max-rounds 2 --max-steps 3
```

验证：

```bash
pytest
cd web && npm run lint
cd web && npm run build
```

## 16. 需要注意的实现细节

- 当前 README 在某些终端编码下可能显示乱码，但源码文件本身按 UTF-8 读取正常。
- 共享 pytest 回归测试位于 `tests/`。
- RAG 的 `VectorStore` 是纯 Python 内存列表 + JSON 持久化；数据量很大时应考虑替换为专门向量数据库。
- `ContextBuilder` 预留了 MemoryManager 接口，但当前没有实际 memory 模块；不要误以为已经有独立的长期记忆数据库。
- `Reranker` 初始化会加载 `cross-encoder/ms-marco-MiniLM-L-6-v2`，首次运行可能需要下载模型。
- `Embedding` 初始化要求 embedding 模型、API key、base URL 都存在；如果只配置 LLM 但没有配置 embedding，RAG Pipeline 初始化会失败。
- `Orchestrator` 初始化要求至少有 Tavily 或 Brave 搜索服务，否则会抛出错误。
- `write_node` 会把最终报告自动回存到本地 RAG，因此后续研究可以通过 `rag_search` 检索之前的报告内容。

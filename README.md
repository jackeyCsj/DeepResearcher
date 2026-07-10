# DuMate-DeepResearch

基于百度 DuMate-DeepResearch 论文架构的多智能体深度研究框架。  
论文: [DuMate-DeepResearch: An Auditable Multi-Agent System with Recursive Search and Rubric-Grounded Reasoning](https://arxiv.org/abs/2606.07299) (Baidu AI Cloud)

## 架构

系统分为**三层**，对应论文图2的设计：

### 1. 编排层 (Orchestration Layer)
- **Router**: 任务理解与分析，提取核心研究主题
- **GraphPlanner**: 基于 DAG 的动态规划（Algorithm 2），支持粗到细扩展、反思、重规划
- **ExecutionModule**: 并行执行动作（工具调用 / Search Agent 派发）
- **EvidenceQualityGate**: frontier 证据归纳、来源检查、按需交叉验证与质量门
- **Writer**: 大纲生成 + 最终报告合成

### 2. Rubric 测试时优化 (Rubric-Based Test-Time Optimization)
- **持久规则 (Persistent Rubrics)** ρ_p: 稳定的话题级质量标准
- **瞬时规则 (Ephemeral Rubrics)** ρ^e_t: 基于最新证据缺口动态刷新
- **自适应停止**: 当信息缺口消失时自动终止

### 3. 搜索层 (Search Layer)
- **Search Agent A¹**: 内层独立搜索智能体，每子任务最多 10 轮检索
- **渐进式特异性**: 从宽泛到具体，逐步聚焦



![ChatGPT Image 2026年7月9日 23_10_10](%E9%99%84%E4%BB%B6/ChatGPT%20Image%202026%E5%B9%B47%E6%9C%889%E6%97%A5%2023_10_10.png)





### 工作流程

```
Query → Router → Coarse Search → Outline → Init Plan → Init Rubric
  ↓
Loop:
  Compute Frontier → Select Actions → Reflect → Execute
  → Consolidate Evidence → Update Evidence → Update Rubric
  → Cross Validate Evidence → Quality Gate → Replan
  ↓ (当无信息缺口或达最大迭代)
Final Report Synthesis
```

## 安装

```bash
# 创建 conda 环境
conda create -n deep_research python=3.10
conda activate deep_research

# 安装依赖
pip install pydantic pydantic-settings langgraph langchain-core openai httpx tiktoken
pip install beautifulsoup4 lxml tavily-python pyyaml python-dotenv rich
pip install pytest pytest-asyncio

# 安装本项目
pip install -e .
```

## 配置

复制 `.env.example` 为 `.env` 并填入 API 密钥。项目使用 OpenAI-compatible 客户端，默认可直接接入 DeepSeek:

```env
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat

TAVILY_API_KEY=tvly-...

MAX_PLAN_ITERATIONS=15
MAX_SEARCH_ROUNDS=10
QUERIES_PER_ROUND=3
```

如果想继续使用 OpenAI，也可以改为：

```env
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o
```

## 使用

```bash
# CLI 模式
python -m deep_research.main --query "How do low-code/no-code platforms impact traditional software development?"

# 指定模型和输出文件
python -m deep_research.main --query "问题" --model gpt-4o --output report.md

# 调试模式
python -m deep_research.main --query "your question" --verbose
```

## 项目结构

```
src/deep_research/
├── __init__.py          # 包入口，导出所有公共 API
├── config.py            # 配置管理 (pydantic-settings)
├── main.py              # CLI 入口
├── models/              # 核心数据模型
│   ├── state.py         # ResearchState s_t = ⟨z, p_t, e_t, ρ_t⟩
│   ├── plan.py          # DAG: ResearchPlan, PlanNode, ready_frontier()
│   ├── evidence.py      # EvidenceRecord, EvidenceBundle
│   ├── rubric.py        # Rubric, Criterion, has_outstanding_gap()
│   ├── topic.py         # TopicSpec, Outline, Chapter
│   └── actions.py       # ToolCall, SearchAgent, LLMReasoning
├── core/                # 核心模块
│   ├── router.py        # 任务理解
│   ├── planner.py       # 图式动态规划 (Algorithm 2)
│   ├── executor.py      # 并行执行器
│   ├── evidence_validator.py # 证据归纳、交叉验证与质量门
│   ├── writer.py        # 大纲+报告合成
│   └── reflection.py    # 反思门控
├── graph/               # LangGraph 图定义
│   ├── orchestration_graph.py  # 主图拓扑
│   ├── nodes.py         # 所有节点函数
│   └── search_subgraph.py      # 内层 Search Agent
├── rubric/              # Rubric 系统
│   ├── generator.py     # 持久+瞬时规则生成
│   └── stopping.py      # 自适应停止
├── tools/               # 工具生态
│   ├── base.py          # BaseTool ABC
│   ├── registry.py      # 工具注册表
│   ├── crawler.py       # 网页爬取
│   └── search/          # 搜索引擎适配
│       ├── tavily.py    # Tavily API
│       └── factory.py   # 工厂模式
└── utils/
    └── llm_client.py    # OpenAI-compatible LLM 客户端
```

## 验证

```bash
# 运行所有测试
pytest tests/ -v

# 运行模型测试
pytest tests/test_models/ -v
```

## 引用

```bibtex
@article{yan2026dumate,
  title={DuMate-DeepResearch: An Auditable Multi-Agent System with Recursive Search and Rubric-Grounded Reasoning},
  author={Lingyong Yan and Can Xu and Yukun Zhao and Wenxuan Li and Qingyang Chen and Jiulong Wu and Wenli Song and Xiangnan Li and Weixian Shi and Yiqun Chen and Xuchen Ma and Yuchen Li and Jiashu Zhao and Shuaiqiang Wang and Jianmin Wu and Dawei Yin},
  journal={arXiv preprint arXiv:2606.07299},
  year={2026}
}
```

## License

MIT

## 更新日志

### 2026-05-12

- 修复 LangGraph 主编排图运行入口兼容问题：将旧式 `graph.arun(...)` 调整为当前 `CompiledStateGraph` 支持的 `graph.ainvoke(...)`。
- 增加 `ResearchState.model_validate(...)` 兼容处理，解决 `ainvoke()` 返回 `dict` 后下游仍按状态对象访问字段的问题。
- 修复执行节点中的动作字段笔误，将 `state._actions` 更正为 `state.transient_actions`，避免执行阶段访问不存在字段。

### 2026-05-28

- 增强 OpenAI-compatible LLM 客户端对 DeepSeek 的结构化输出兼容性：DeepSeek 场景优先使用 `response_format={"type": "json_object"}`。
- 保留 OpenAI JSON Schema 路径，并增加 `json_schema → json_object → prompt-only JSON` 的自动降级链路。
- 使用 Pydantic `TypeAdapter.validate_json(...)` 统一解析结构化输出，兼容 `TopicSpec`、`Outline`、`ResearchPlan`、`Rubric` 与 `list[Criterion]` 等类型。
- 增加对 `{"items": [...]}`、`{"criteria": [...]}` 等列表包装格式的自动拆包，解决 DeepSeek `json_object` 顶层对象限制带来的列表解析问题。

### 2026-06-11

- 修复 `LLM_MAX_TOKENS` 配置未生效的问题：原先 `generate()` 实际默认仍使用 `4096`，导致较长 `ResearchPlan` JSON 容易被截断。
- 新增 `default_output_tokens`，将常规结构化输出控制在合理范围内，同时避免把超大的上下文上限直接当作输出上限传给模型。
- 为 Planner 初始化计划增加更紧凑的 DAG 输出约束，限制节点数量和描述长度，降低 JSON 截断概率。
- 新增 `examples/debug_pipeline.py`，支持按 `Router → Outline → Planner → Ready Frontier → Actions` 顺序单步诊断并打印中间结果。

### 2026-06-24

- 修复 `select_actions()` 中动作选择结果解析不稳定的问题：由普通文本 `json.loads(...)` 改为结构化 `ActionList` 输出。
- 为 DeepSeek 动作选择引入顶层对象格式：`{"actions": [...]}`，避免 JSON 顶层数组在 `json_object` 模式下不稳定。
- 增加 `_fallback_actions_from_frontier(...)`，当 LLM 动作选择失败时按 `PlanNode.subtask_type` 生成确定性动作，避免误判为 `0 actions` 后提前进入最终报告。
- 对搜索动作增加后处理，确保 `SearchAgentAction.sub_query` 与 `ToolCallAction.tool_input` 保留必要的时间和新鲜度关键词。

### 2026-07-07

- 为所有 LLM 调用统一注入运行时日期上下文，避免模型误解“当前、今年、至今、最近”等相对时间表达。
- 明确将“2025年至今”解释为 `2025-01-01` 至当前运行日期，确保 Router、Outline、Planner 和最终报告都覆盖 2026 年进展。
- 加强 Planner 搜索动作提示词：要求 `search_agent.sub_query` 显式包含 `2025`、`2026`、`2026年7月` 或 `最新` 等时间词。
- 通过诊断脚本验证：`TopicSpec.scope`、报告大纲、DAG 节点与搜索动作均能正确保留 `2025-2026` 时间范围。

### 2026-07-10

- 新增 frontier 批次证据整理流程，在每轮并行执行后统一进行结果归纳、来源规范化、重复证据消除和失败结果检查。
- 新增 Rubric 更新后的证据交叉验证与质量门，根据冲突、来源单一和覆盖缺口决定是否触发语义验证。
- 为证据记录和证据包增加验证状态及审计信息，区分已验证、待验证、存在争议和无效证据。
- 调整自适应停止路由：只有证据质量门通过后才允许进入最终报告，否则根据验证反馈重新规划补充任务。
- 最终 Writer 默认仅使用已验证证据支撑确定性结论，并将未解决的争议证据列入报告限制说明。
- 增加证据去重、交叉验证触发、质量门路由、验证器异常和最终写作过滤等单元测试与图集成测试。
- 修复质量循环启用后重复重规划导致 DAG 持续膨胀的问题：重规划改为最多新增 3 个节点的增量决策，不再反复输出完整 `ResearchPlan`。
- 修复 Replan 结构化 JSON 达到输出上限时直接终止研究的问题；解析或生成失败时保留当前计划并继续执行。
- 搜索证据现在保留 Tavily 返回的标题、正文摘要和相关度，避免验证器因只有 URL、没有证据内容而持续要求补充全文。
- 增加 Tavily 查询清理、350 字符长度保护和工具并发上限，并确保最终报告只能由证据质量门放行。
- 修复 Rubric 结构化输出包含未转义引号时的初始化崩溃：解析失败会自动请求一次 JSON 格式修复。
- Persistent 与 Ephemeral Rubric 增加确定性兜底标准，即使模型连续返回无效 JSON 也能继续研究流程。

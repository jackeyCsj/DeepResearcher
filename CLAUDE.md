# CLAUDE.md

## 项目概述

DuMate-DeepResearch: 基于百度 DuMate-DeepResearch 论文（arXiv:2606.07299）的多智能体深度研究框架。使用 Python 3.10 + LangGraph + Pydantic 实现。

## 环境

- **Conda 环境**: `deep_research` (Python 3.10.20)
- **Python 路径**: `D:/miniconda/envs/deep_research/python.exe`
- **项目根目录**: `D:/MultiAgentResearch/`
- **包安装**: `pip install -e .` (editable mode)

## 关键命令

```bash
# 运行研究
python -m deep_research.main --query "your question"

# 运行测试
pytest tests/ -v

# 安装依赖
pip install -e .

# 代码风格 (当前无配置，后续添加 ruff)
```

## LLM 配置

项目使用 OpenAI-compatible 客户端，默认可接入 DeepSeek：

```env
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
```

也兼容旧的 OpenAI 配置：`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`LLM_MODEL=gpt-4o`。

## 项目结构

```
src/deep_research/
├── models/       # Pydantic 数据模型 (state, plan, evidence, rubric, topic, actions)
├── core/         # 核心逻辑 (router, planner, executor, writer, reflection)
├── graph/        # LangGraph 图定义 (orchestration, nodes, search_subgraph)
├── rubric/       # Rubric 系统 (generator, stopping)
├── tools/        # 工具生态 (base, registry, crawler, search/)
└── utils/        # 工具函数 (llm_client)
```

## 核心设计模式

### 1. DAG 规划 (ResearchPlan)
- **ready_frontier()**: 公式 F_t = {v: χ(v)=0 ∧ ∀(u,v)∈E_t, χ(u)=1}
- **prune_branch()**: 递归删除节点及其所有后代
- 深度排序: depth-1 先执行（粗粒度优先于细粒度）

### 2. LangGraph 图拓扑
- 外层编排图 (orchestration_graph.py): 14 个节点 + 3 个条件边
- 内层搜索子图 (search_subgraph.py): Search Agent A¹
- 条件边: stop/continue, pass/revise/fail, adaptive-stop

### 3. Rubric 系统
- 持久规则 ρ_p: 从大纲生成，全程有效
- 瞬时规则 ρ^e_t: 每轮根据证据缺口刷新
- 自适应停止: has_outstanding_gap() → False 时终止

### 4. 状态管理 (ResearchState)
s_t = ⟨z, p_t, e_t, ρ_t⟩
- z = (x, O): 固定上下文（话题 + 大纲）
- p_t = (V_t, E_t): DAG 计划
- e_t: 累积证据
- ρ_t = (ρ_p, ρ^e_t): 指导信号

## 修改指南

### 添加新工具
1. 在 `tools/` 下创建新类，继承 `BaseTool`
2. 实现 `arun()` 方法，返回 `ToolResult`
3. 在 `tools/registry.py` 中注册，或在 `create_default_tools()` 中创建

### 添加新搜索后端
1. 在 `tools/search/` 下创建新文件
2. 添加到 `tools/search/factory.py` 中的 `create_search_provider()`

### 修改规划逻辑
- `core/planner.py` 中的 `GraphPlanner` 类
- 关键方法: `init_plan()`, `select_actions()`, `replan()`

### 添加新图节点
1. 在 `graph/nodes.py` 的 `create_nodes()` 工厂中添加节点函数
2. 在 `graph/orchestration_graph.py` 的 `build_orchestration_graph()` 中注册节点和边

## 注意事项
- 所有 transient 字段使用 `transient_` 前缀（Pydantic 不支持 `_` 前缀）
- 所有工具类异步执行（`async def arun()`）
- LLM 调用通过 `LLMClient` 统一管理，支持结构化输出
- 模型字段尽量提供默认值，避免 Pydantic 验证错误



## Behavioral Guidelines

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

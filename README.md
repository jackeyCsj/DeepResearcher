# DuMate-DeepResearch

基于百度 DuMate-DeepResearch 论文架构的多智能体深度研究框架。  
论文: [DuMate-DeepResearch: An Auditable Multi-Agent System with Recursive Search and Rubric-Grounded Reasoning](https://arxiv.org/abs/2606.07299) (Baidu AI Cloud)

## 架构

系统分为**三层**，对应论文图2的设计：

### 1. 编排层 (Orchestration Layer)
- **Router**: 任务理解与分析，提取核心研究主题
- **GraphPlanner**: 基于 DAG 的动态规划（Algorithm 2），支持粗到细扩展、反思、重规划
- **ExecutionModule**: 并行执行动作（工具调用 / Search Agent 派发）
- **Writer**: 大纲生成 + 最终报告合成

### 2. Rubric 测试时优化 (Rubric-Based Test-Time Optimization)
- **持久规则 (Persistent Rubrics)** ρ_p: 稳定的话题级质量标准
- **瞬时规则 (Ephemeral Rubrics)** ρ^e_t: 基于最新证据缺口动态刷新
- **自适应停止**: 当信息缺口消失时自动终止

### 3. 搜索层 (Search Layer)
- **Search Agent A¹**: 内层独立搜索智能体，每子任务最多 10 轮检索
- **渐进式特异性**: 从宽泛到具体，逐步聚焦

### 工作流程

```
Query → Router → Coarse Search → Outline → Init Plan → Init Rubric
  ↓
Loop:
  Compute Frontier → Select Actions → Reflect → Execute → Update Evidence → Update Rubric → Replan
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

复制 `.env.example` 为 `.env` 并填入 API 密钥:

```env
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o

TAVILY_API_KEY=tvly-...

MAX_PLAN_ITERATIONS=15
MAX_SEARCH_ROUNDS=10
QUERIES_PER_ROUND=3
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

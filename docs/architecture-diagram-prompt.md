# Architecture Diagram Prompt

## Option 1: Mermaid.js (推荐，可在GitHub/VS Code直接渲染)

将以下代码粘贴到支持Mermaid的编辑器（如 VS Code + Markdown Preview Mermaid Support 插件，或 https://mermaid.live）：

```mermaid
---
title: DuMate-DeepResearch Architecture - LangGraph StateGraph
---
graph TB
    subgraph Phase1["Phase 1: Initial Pipeline"]
        R[Router<br/>任务理解分析] --> CS[Coarse Search<br/>粗探索检索]
        CS --> GO[Generate Outline<br/>生成报告大纲]
        GO --> IP[Init Plan p₀<br/>初始化DAG计划]
        IP --> IR[Init Rubric ρₚ<br/>初始化持久规则]
    end

    subgraph Loop["Phase 2: Research Loop (Algorithm 2)"]
        CF[Compute Frontier Fₜ<br/>计算就绪前沿] --> PA[Planner Actions<br/>选择并行动作]

        PA -->|"if stop_flag / empty"| FS[Final Synthesis<br/>最终报告合成]
        PA -->|"if has actions"| RG[Reflection Gate<br/>反思门控]

        RG -->|"pass ✅"| EP[Execute Parallel<br/>并行执行]
        RG -->|"revise 🔄<br/>未达最大修正次数"| PA
        RG -->|"fail_after_revisions<br/>已达最大次数"| EP

        EP --> UE[Update Evidence<br/>eₜ₊₁ = eₜ ∪ Δeₜ<br/>标记节点χ(v)=1]
        UE --> UR[Update Rubric<br/>ρᵉₜ₊₁ = Gₑ(O, eₜ₊₁)]

        UR -->|"continue<br/>有信息缺口"| RP[Replan Π<br/>重规划算子<br/>扩展/剪枝/重连]
        UR -->|"stop<br/>无缺口或达最大迭代"| FS

        RP --> CF
    end

    subgraph Execution["Execution Targets"]
        direction LR
        T1[Tool Call<br/>直接工具调用] --> TR[ToolResult<br/>证据记录]
        T2[Search Agent A¹<br/>内层搜索智能体<br/>最多10轮检索] --> TR
        T3[LLM Reasoning<br/>去重/合并/交叉验证] --> TR
    end

    EP --> Execution

    subgraph SearchAgent["Inner Search Agent (Subgraph)"]
        direction TB
        SA_R[Search Router<br/>分析子任务] --> SA_P[Search Planner<br/>规划检索策略]
        SA_P --> SA_EX[Search Execute<br/>并行搜索<br/>每轮最多3查询]
        SA_EX --> SA_EV[Search Evaluate<br/>评估是否充足]
        SA_EV -->|"continue 🔄"| SA_P
        SA_EV -->|"stop ✅"| SA_RES[Return Evidence<br/>返回证据包]
    end

    T2 --> SearchAgent

    subgraph DataFlow["Data Flow"]
        d1[("Query<br/>用户输入")]
        d2[("(x, O)<br/>TopicSpec + Outline")]
        d3[("ρₚ<br/>Persistent Rubric<br/>稳定质量标准")]
        d4[("ρᵉₜ<br/>Ephemeral Rubric<br/>瞬时缺口规则")]
        d5[("eₜ<br/>EvidenceBase<br/>累积证据")]
        d6[("Report<br/>最终报告")]
    end

    d1 --> R
    R --> d2
    IR --> d3
    UR --> d4
    UE --> d5
    FS --> d6

    d3 -.->|"注入 Writer"| FS
    d4 -.->|"注入 Planner"| PA

    style R fill:#4A90D9,color:#fff
    style CS fill:#4A90D9,color:#fff
    style GO fill:#4A90D9,color:#fff
    style IP fill:#4A90D9,color:#fff
    style IR fill:#4A90D9,color:#fff
    style CF fill:#50B86C,color:#fff
    style PA fill:#50B86C,color:#fff
    style RG fill:#F5A623,color:#fff
    style EP fill:#D0021B,color:#fff
    style UE fill:#50B86C,color:#fff
    style UR fill:#9B59B6,color:#fff
    style RP fill:#50B86C,color:#fff
    style FS fill:#4A90D9,color:#fff
    style d6 fill:#4A90D9,color:#fff
```

## Option 2: 流程图风格（纯文本描述）

如果上述 Mermaid 渲染不理想，可手动绘制以下结构：

```
┌─────────────────────────────────────────────────────────────┐
│  Phase 1: Initial Pipeline                                  │
│  Router → Coarse Search → Generate Outline → Init Plan →    │
│  Init Rubric                                                │
│                                                             │
│                    ↓                                        │
│                                                             │
│  ┌──────────────── Research Loop ────────────────────────┐  │
│  │                                                       │  │
│  │  Compute Frontier Fₜ                                  │  │
│  │       │                                               │  │
│  │       ↓                                               │  │
│  │  Planner Actions (select parallel actions)             │  │
│  │       │                                               │  │
│  │  ┌────┴────┐                                          │  │
│  │  │         │                                          │  │
│  │ stop    has actions                                    │  │
│  │  │         │                                          │  │
│  │  │         ↓                                          │  │
│  │  │    Reflection Gate (quality check)                  │  │
│  │  │         │        │        │                        │  │
│  │  │      pass ✅  revise  fail_after                    │  │
│  │  │         │        │(≤3x)    │                        │  │
│  │  │         ↓    ←───┘        │                        │  │
│  │  │    Execute Parallel        │                        │  │
│  │  │      ├── Tool Call         │                        │  │
│  │  │      ├── Search Agent A¹   │                        │  │
│  │  │      └── LLM Reasoning     │                        │  │
│  │  │         │                  │                        │  │
│  │  │         ↓                  │                        │  │
│  │  │    Update Evidence eₜ₊₁    │                        │  │
│  │  │         │                  │                        │  │
│  │  │         ↓                  │                        │  │
│  │  │    Update Rubric ρᵉₜ₊₁    │                        │  │
│  │  │         │        │        │                        │  │
│  │  │    continue     stop       │                        │  │
│  │  │    (has gap) (no gap)      │                        │  │
│  │  │         │        │         │                        │  │
│  │  │         ↓        │         │                        │  │
│  │  │    Replan Π      │         │                        │  │
│  │  │    (expand/      │         │                        │  │
│  │  │     prune/       │         │                        │  │
│  │  │     rewire)      │         │                        │  │
│  │  │         │        │         │                        │  │
│  │  └─────────┘        │         │                        │  │
│  │       │             │         │                        │  │
│  │       ↓             │         │                        │  │
│  │  (back to Compute   │         │                        │  │
│  │   Frontier)         │         │                        │  │
│  │                     │         │                        │  │
│  └─────────────────────┘         │                        │
│                           │      │                        │
│                           ↓      │                        │
│                     Final Report  │                        │
│                     Synthesis     │                        │
│                     (Writer +     │                        │
│                      Persistent   │                        │
│                      Rubric ρₚ)   │                        │
│                           │       │                        │
│                           ↓       │                        │
│                        [END]      │                        │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Inner Search Agent (Subgraph A¹)                           │
│                                                             │
│  Search Router → Search Planner → Search Execute →          │
│  Search Evaluate ──(continue)──→ Search Planner (loop)      │
│       │                                                     │
│       └──(stop)──→ Return Evidence Bundle                   │
│                                                             │
│  Max 10 rounds, 3 queries/round                             │
│  Progressive specificity: broad → domain → OEM/supplier     │
│  Only direct tool calls (no further agent dispatch)         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Data Flow                                                  │
│                                                             │
│  Query → [Router] → TopicSpec (x)                           │
│  Coarse Evidence → [Writer] → Outline (O)                   │
│  (x, O) → [Planner] → Plan p₀ = (V₀, E₀)                   │
│  (x, O) → [RubricGenerator] → Persistent ρₚ                 │
│  (O, eₜ₊₁) → [RubricGenerator] → Ephemeral ρᵉₜ₊₁           │
│  ρₚ injected into Writer for final synthesis                 │
│  (ρₚ, ρᵉₜ) injected into Planner for action selection        │
│  Search Agent returns EvidenceBundle to outer loop           │
└─────────────────────────────────────────────────────────────┘
```

## Option 3: 类 PlantUML 风格

另一种选择，使用简单的文本块 + 箭头，适合在 PR description 或 issue 中使用：

```
─── Phase 1: Initial Pipeline ───
Router ──→ CoarseSearch ──→ GenerateOutline ──→ InitPlan ──→ InitRubric
                                                                  │
                                                                  v
─── Phase 2: Research Loop (Algorithm 1 & 2) ─────────────────────
                                                          │
ComputeFrontier(Fₜ) ←──── Replan(Π) ←─── UpdateRubric(ρᵉₜ₊₁)
       │                                         │
       v                                    ┌────┴────┐
PlannerActions(aₜ)                         continue  stop
       │                                      │       │
  ┌────┴────┐                                 v       │
 stop   has_actions                       Replan ─────┘
   │         │                               │
   v         v                               v
FinalSynth  ReflectionGate              ComputeFrontier(loop)
                │
          ┌─────┼─────┐
         pass revise fail_after
          │     │(≤3x)   │
          v     v        v
       ExecuteParallel────┘
        ├─ ToolCall
        ├─ SearchAgent ──→ [Subgraph: Inner Search Agent]
        │                      Router→Planner→Execute→Evaluate(loop)
        └─ LLMReasoning
          │
          v
      UpdateEvidence(eₜ₊₁)
```

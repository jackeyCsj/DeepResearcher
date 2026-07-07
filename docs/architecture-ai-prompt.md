# Architecture Diagram AI Prompt

## English Version (Best for DALL-E / Midjourney / Stable Diffusion)

```
Create a clean, professional system architecture diagram for "DuMate-DeepResearch: A Multi-Agent Deep Research Framework" in a modern flat design style. The diagram should have a clear top-to-bottom layout with three horizontal layers (swimlanes).

COLOR PALETTE:
- Orchestration Layer background: light blue (#E8F4FD)
- Rubric Layer background: light purple (#F3E8FD)  
- Search Layer background: light green (#E8FDE8)
- Node fill colors: Blue (#4A90D9) for pipeline nodes, Green (#50B86C) for loop nodes, Orange (#F5A623) for decision/reflection nodes, Red (#D0021B) for execution nodes, Purple (#9B59B6) for rubric nodes
- Arrow color: dark gray (#555555)
- Text: dark (#333333), use sans-serif font

LAYOUT - Three horizontal swimlanes from top to bottom:

ZONE 1 (TOP) - "Orchestration Layer":
Draw these connected nodes in a left-to-right pipeline:
[Router] → [Coarse Search] → [Generate Outline] → [Init Plan p₀] → [Init Rubric ρₚ]

Then below this pipeline, draw a large LOOP labeled "Research Loop (Algorithm 1 & 2)" containing these connected nodes:

[Compute Frontier Fₜ] → [Planner Actions]
[Planner Actions] has a DIAMOND decision node with two outgoing arrows:
- Left arrow labeled "stop ❌" going to [Final Report Synthesis]
- Right arrow labeled "has actions ✅" going to [Reflection Gate]

[Reflection Gate] is a DIAMOND with THREE outgoing arrows:
- Left: "pass ✅" → [Execute Parallel]
- Middle: "revise 🔄 (≤3 attempts)" looping BACK to [Planner Actions]
- Right: "fail_after_revisions" → [Execute Parallel]

[Execute Parallel] → [Update Evidence eₜ₊₁] → [Update Rubric ρᵉₜ₊₁]
[Update Rubric] is a DIAMOND with two arrows:
- Left: "stop (no gaps)" → [Final Report Synthesis]
- Right: "continue (has gaps)" → [Replan Π (expand/prune/rewire)]
[Replan] → back to [Compute Frontier Fₜ] (forming the loop)

ZONE 2 (MIDDLE) - "Rubric-Based Test-Time Optimization":
Draw a vertical column on the right side connected to the orchestration layer with dashed lines:
- [Rubric Generator] with two outputs:
  - Solid line to [Persistent Rubric ρₚ] (labeled "injected into Writer")
  - Solid line to [Ephemeral Rubric ρᵉₜ] (labeled "refreshed each cycle, injected into Planner")
- [Adaptive Stopping] connected to the loop's stop condition

ZONE 3 (BOTTOM) - "Search Layer (Sub-agents)":
Draw [Execute Parallel] with a downward arrow labeled "dispatch sub-tasks" leading to:
- [Tool Call Node] (icon: magnifying glass / gear)
- [Search Agent A¹] (icon: robot head) - THIS SHOULD BE A SUBCONTAINER showing its internal flow:
  [Search Router] → [Search Planner] → [Search Execute (3 queries/round)] → [Search Evaluate]
  With a feedback arrow from [Search Evaluate] back to [Search Planner] labeled "continue 🔄"
  And an exit arrow labeled "stop ✅ → Return Evidence"
- [LLM Reasoning Node] (icon: brain)

ADDITIONAL LABELS (place as annotations):
- "Fₜ = {v: χ(v)=0 ∧ ∀(u,v)∈Eₜ, χ(u)=1}" near Compute Frontier
- "ρₜ = (ρₚ, ρᵉₜ)" near the Rubric layer
- "Max 10 rounds" inside Search Agent subgraph
- "Persistent Rubric ρₚ only" on the arrow from Rubric to Writer

OUTPUT FORMAT: 16:9 aspect ratio, clean sans-serif font, professional technical diagram style suitable for a research paper or technical documentation, white background, 2D flat design (not 3D).
```

## 中文精简版 (For Chinese AI image generators like 通义万相/文心一格)

```
请绘制一张"DuMate-DeepResearch多智能体深度研究框架"的系统架构图，采用现代扁平化设计风格，自上而下的三层布局。

色彩方案：
- 编排层背景：浅蓝色 (#E8F4FD)
- Rubric层背景：浅紫色 (#F3E8FD)
- 搜索层背景：浅绿色 (#E8FDE8)
- 节点颜色：蓝色(管线节点)、绿色(循环节点)、橙色(决策/反思节点)、红色(执行节点)、紫色(Rubric节点)
- 使用无衬线字体

从上到下三个泳道区域：

第一层"编排层"：
顶部一行从左到右：Router → Coarse Search → Generate Outline → Init Plan → Init Rubric
下方是一个大循环"Research Loop"，包含：
Compute Frontier → Planner Actions（菱形分支）
  - stop → Final Report Synthesis
  - has actions → Reflection Gate（菱形，三分支：pass→执行 / revise→回退重试 / fail→执行）
Execute Parallel → Update Evidence → Update Rubric（菱形分支：stop→合成报告 / continue→Replan→回到Compute Frontier）

第二层"Rubric测试时优化层"（右侧纵向）：
Rubric Generator → Persistent Rubric（虚线指向Writer）和 Ephemeral Rubric（虚线指向Planner）
Adaptive Stopping 连接到循环的终止条件

第三层"搜索层"（底部）：
Execute Parallel 向下分叉为三个执行目标：
  - Tool Call（工具图标）
  - Search Agent A¹（子容器，内部有Search Router→Planner→Execute→Evaluate的循环，标注"最多10轮"）
  - LLM Reasoning（大脑图标）

关键公式标注：
- Fₜ = {v: χ(v)=0 ∧ ∀(u,v)∈Eₜ, χ(u)=1} 标注在 Compute Frontier 旁
- ρₜ = (ρₚ, ρᵉₜ) 标注在 Rubric 层

风格：16:9比例、白色背景、2D扁平化、专业技术架构图风格，适合论文或技术文档使用。
```

## 用于 Mermaid 代码生成器的提示 (If used for text-to-diagram tools like Diagrams.net / Excalidraw)

```
Generate a system architecture diagram with these elements arranged in 3 horizontal lanes:

Lane 1 (Top) - Orchestration Layer:
Sequence: Router → CoarseSearch → GenerateOutline → InitPlan → InitRubric
Loop (below): ComputeFrontier → PlannerActions[decision] →|stop| FinalSynthesis
                    ↓has actions → ReflectionGate[3-way decision]
                    pass → ExecuteParallel → UpdateEvidence → UpdateRubric[decision]
                    revise → back to PlannerActions
                    fail → ExecuteParallel
              UpdateRubric →|continue| Replan → back to ComputeFrontier
              UpdateRubric →|stop| FinalSynthesis

Lane 2 (Middle) - Rubric Layer (right side):
RubricGenerator → PersistentRubric (dashed to Writer)
               → EphemeralRubric (dashed to Planner)
AdaptiveStopping → stop condition

Lane 3 (Bottom) - Search Layer:
ExecuteParallel branches to:
  - ToolCall (gear icon)
  - SearchAgent A¹ (sub-container with internal loop: SearchRouter→SearchPlanner→SearchExecute→SearchEvaluate→loop/exit)
  - LLMReasoning (brain icon)

Use flat design, blue/green/orange/purple color scheme, sans-serif font, 16:9 ratio.
```

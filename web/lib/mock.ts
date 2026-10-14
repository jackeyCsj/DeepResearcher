// Mock SSE events — simulate full research pipeline without backend.
// Enable via NEXT_PUBLIC_MOCK=true env var, or `npm run dev:mock`.

import type {
  ChatSessionDetail,
  ChatSessionSummary,
  ClarifyResult,
  RefineResult,
  ResearchEvent,
  LibraryDoc,
  IngestResult,
} from "./api";

const MOCK_BRIEF = "对比 Transformer、Mamba 和 RWKV 三种架构在长文本建模任务上的效率与性能";

const MOCK_REPORT = `# Transformer、Mamba 与 RWKV 架构长文本建模对比

## 摘要

本报告对比三种序列建模架构在长文本任务上的表现。Transformer 凭借自注意力机制在性能上领先，但计算复杂度为 $O(n^2)$；Mamba 通过状态空间模型实现线性复杂度；RWKV 结合 RNN 与 Transformer 优势，在效率与性能间取得平衡。

## 1. Transformer 架构

Transformer 的自注意力机制使其能够捕捉任意距离的依赖关系，但序列长度 $n$ 增加时，计算和内存开销以 $O(n^2)$ 增长。稀疏注意力 [1] 和 FlashAttention [2] 等优化技术在一定程度上缓解了这一问题。

### 1.1 复杂度分析

标准 Transformer 的注意力计算需要 $n \\times n$ 的矩阵乘法。当 $n$ 超过 8K 时，单卡显存往往不足以容纳注意力矩阵。

## 2. Mamba 架构

Mamba 基于结构化状态空间模型（SSM），通过选择性扫描机制实现输入感知的序列建模 [3]。其计算复杂度为 $O(n)$，在长序列上具有显著效率优势。

### 2.1 核心机制

Mamba 的关键创新在于将 SSM 的参数与输入关联，使模型能够根据当前 token 动态调整状态转移。这使得 Mamba 在保留线性复杂度的同时，获得了接近 Transformer 的建模能力。

## 3. RWKV 架构

RWKV 采用线性注意力与时间混合机制，将传统 RNN 的训练效率与 Transformer 的并行性结合 [4]。其 WKV 算子实现线性复杂度下的全局依赖捕捉。

## 4. 对比分析

| 架构 | 复杂度 | 长文本效率 | 建模质量 | 生态成熟度 |
|------|--------|-----------|---------|-----------|
| Transformer | $O(n^2)$ | 低 | 最高 | 最成熟 |
| Mamba | $O(n)$ | 高 | 接近 Transformer | 快速发展 |
| RWKV | $O(n)$ | 高 | 良好 | 中等 |

在 Long Range Arena 基准上，Mamba 在大多数任务中达到或超过 Transformer 性能，同时推理速度提升 5-10 倍 [5]。

## 结论

对于长文本建模任务，Mamba 和 RWKV 在效率上具有明显优势，但 Transformer 在模型生态和工具链上更为成熟。实际应用中可根据任务需求在效率与性能间权衡。

## Sources

[1] Child et al. "Generating Long Sequences with Sparse Transformers." arXiv:1904.10509
[2] Dao et al. "FlashAttention: Fast and Memory-Efficient Exact Attention." NeurIPS 2022
[3] Gu & Dao. "Mamba: Linear-Time Sequence Modeling with Selective State Spaces." arXiv:2312.00752
[4] Peng et al. "RWKV: Reinventing RNNs for the Transformer Era." EMNLP 2023
[5] Tay et al. "Long Range Arena: A Benchmark for Efficient Transformers." ICLR 2021
`;

export function mockClarify(_query: string): Promise<ClarifyResult> {
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({
        is_clear: false,
        brief: null,
        directions: [
          "对比三种架构在长文本（8K+ token）上的推理速度和显存占用",
          "分析它们在 Long Range Arena 等基准测试上的性能差异",
          "调查各架构在生产环境中的实际部署情况和生态成熟度",
        ],
        message: "这是个很好的研究方向！我有几个建议方向供你参考，你也可以输入自己的具体关注点：",
        session_id: "mock-session",
      });
    }, 1200);
  });
}

export function mockRefine(_query: string, _response: string): Promise<RefineResult> {
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({ brief: MOCK_BRIEF, session_id: "mock-session" });
    }, 2000);
  });
}

const mockSessions: ChatSessionDetail[] = [];

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

export function mockListSessions(): ChatSessionSummary[] {
  return mockSessions.map((session) => ({
    id: session.id,
    title: session.title,
    raw_query: session.raw_query,
    research_brief: session.research_brief,
    report_file_id: session.report_file_id,
    status: session.status,
    created_at: session.created_at,
    updated_at: session.updated_at,
  }));
}

export function mockGetSession(sessionId: string): Promise<ChatSessionDetail> {
  const session = mockSessions.find((item) => item.id === sessionId);
  if (!session) return Promise.reject(new Error("聊天记录不存在"));
  return Promise.resolve(clone(session));
}

export function mockDeleteSession(sessionId: string): Promise<void> {
  const index = mockSessions.findIndex((item) => item.id === sessionId);
  if (index >= 0) mockSessions.splice(index, 1);
  return Promise.resolve();
}

function newMockSession(sessionId: string, firstMessage: string): ChatSessionDetail {
  const now = new Date().toISOString();
  return {
    id: sessionId,
    title: firstMessage.slice(0, 48),
    raw_query: firstMessage,
    research_brief: null,
    report_file_id: null,
    status: "active",
    created_at: now,
    updated_at: now,
    messages: [],
    steps: [],
    report: null,
    tasks: [],
  };
}

export function startMockTurn(
  message: string,
  existingSessionId: string | null,
  onEvent: (event: ResearchEvent) => void,
  onComplete?: () => void,
  options: { taskId?: string | null; reportVersionId?: string | null } = {},
): () => void {
  let cancelled = false;
  let researchAbort: (() => void) | null = null;
  let answerTimer: ReturnType<typeof setTimeout> | null = null;
  const sessionId = existingSessionId || `mock-${crypto.randomUUID()}`;
  let session = mockSessions.find((item) => item.id === sessionId);
  if (!session) {
    session = newMockSession(sessionId, message);
    mockSessions.unshift(session);
  }
  session.messages.push({ role: "user", message_type: "chat", content: message, created_at: new Date().toISOString() });
  session.updated_at = new Date().toISOString();

  const hasReport = Boolean(session.tasks?.some((task) => task.versions.length > 0) || session.report);
  const lower = message.toLowerCase();
  const isAmbiguous = /不够好|不太好|不满意|有问题/.test(message);
  const intent = /补充|遗漏|缺失|没有调研到|修订|修改报告/.test(message)
    ? "supplementary_research"
    : /详细|深入|展开|多讲一些/.test(message)
      ? "deepening"
      : hasReport && /什么意思|是什么|解释|为什么|怎么理解/.test(message)
        ? "report_qa"
        : hasReport && !/另外研究|新主题|研究一下/.test(message)
          ? "report_qa"
          : "initial_research";
  onEvent({ type: "session", session_id: sessionId });

  if (isAmbiguous) {
    onEvent({ type: "clarification", message: "你希望我重点补充哪个部分，还是解释报告中的某个结论？", directions: ["检查报告有哪些重要缺口", "补充实验对比部分", "解释报告中的核心结论"] });
    session.messages.push({ role: "assistant", message_type: "clarification", content: "你希望我重点补充哪个部分，还是解释报告中的某个结论？", created_at: new Date().toISOString() });
    answerTimer = setTimeout(() => { if (!cancelled) onComplete?.(); }, 150);
  } else if (intent === "report_qa") {
    onEvent({ type: "route", intent, task_id: options.taskId || undefined, report_version_id: options.reportVersionId || undefined });
    answerTimer = setTimeout(() => {
      if (cancelled) return;
      const content = lower.includes("频域")
        ? "频域方法把信号表示成不同频率成分，便于观察模型如何处理长距离依赖。当前模拟报告没有相关章节，因此这里不能从报告中确认更具体的结论。"
        : "报告认为 Mamba 和 RWKV 以线性复杂度降低了长序列的计算开销；具体比较见报告的架构分析与对比章节。";
      const sources = [{ title: "当前研究报告", file_id: session?.report_file_id || undefined, excerpt: "长文本建模架构对比与复杂度分析" }];
      onEvent({ type: "answer", content, sources });
      session?.messages.push({ role: "assistant", message_type: "answer", content, created_at: new Date().toISOString() });
      onComplete?.();
    }, 500);
  } else {
    const taskId = intent === "initial_research" ? `task-${crypto.randomUUID()}` : options.taskId || session.tasks?.at(-1)?.id || `task-${crypto.randomUUID()}`;
    const runId = `run-${crypto.randomUUID()}`;
    onEvent({ type: "route", intent, task_id: taskId, run_id: runId });
    const task = session.tasks?.find((item) => item.id === taskId);
    const targetTask = task || {
      id: taskId,
      title: intent === "initial_research" ? message.slice(0, 48) : session.title,
      intent,
      current_version_id: null,
      versions: [],
    };
    if (!task) session.tasks?.push(targetTask);
    researchAbort = startMockResearch(message, (rawEvent) => {
      if (cancelled) return;
      let event = { ...rawEvent, task_id: taskId, run_id: runId } as ResearchEvent;
      if (rawEvent.type === "write") {
        const versionId = `version-${crypto.randomUUID()}`;
        const title = rawEvent.report.match(/^#\s+(.+)$/m)?.[1] || targetTask.title;
        event = { ...rawEvent, task_id: taskId, run_id: runId, version_id: versionId, report_version_id: versionId, title };
        targetTask.versions.push({ id: versionId, run_id: runId, version_number: targetTask.versions.length + 1, parent_version_id: targetTask.current_version_id, report_file_id: rawEvent.report_file_id || "mock-report.md", title, content: rawEvent.report, created_at: new Date().toISOString() });
        targetTask.current_version_id = versionId;
        session!.report_file_id = rawEvent.report_file_id || "mock-report.md";
        session!.report = { report_file_id: session!.report_file_id, title: targetTask.title, content: rawEvent.report };
        session!.status = "report_ready";
        session!.messages.push({ role: "assistant", message_type: "report", content: "报告已生成，右侧已切换到最新版本。", created_at: new Date().toISOString() });
      }
      session!.updated_at = new Date().toISOString();
      onEvent(event);
      if (rawEvent.type === "stats") onComplete?.();
    });
  }

  return () => {
    cancelled = true;
    if (answerTimer) clearTimeout(answerTimer);
    researchAbort?.();
  };
}

let _mockRunning = false;

export function startMockResearch(
  _brief: string,
  onEvent: (event: ResearchEvent) => void,
): () => void {
  if (_mockRunning) {
    console.warn("Mock research already running — skipping duplicate start");
    return () => {};
  }
  _mockRunning = true;
  let cancelled = false;
  const timers: ReturnType<typeof setTimeout>[] = [];

  function schedule(delay: number, fn: () => void) {
    const t = setTimeout(() => {
      if (!cancelled) fn();
    }, delay);
    timers.push(t);
  }

  // 1. Plan — after 1.5s (clarify settled → brief shown → plan)
  schedule(1500, () => {
    onEvent({
      type: "plan",
      sub_questions: [
        { label: "长文本推理效率", question: "对比 Transformer、Mamba、RWKV 在 8K+ token 序列上的推理速度和显存占用" },
        { label: "基准测试性能", question: "分析三种架构在 Long Range Arena 等长文本基准测试上的性能差异" },
        { label: "生产部署成熟度", question: "调查各架构在生产环境中的实际部署情况、工具链和社区生态" },
      ],
    });
  });

  // 2. Research events — ~4s apart to show each sub-question completing
  schedule(4500, () => {
    onEvent({
      type: "research",
      question: "对比 Transformer、Mamba、RWKV 在 8K+ token 序列上的推理速度和显存占用",
      preview: "FlashAttention 将标准自注意力的显存占用从 O(n²) 降到 O(n)。Mamba 的选择性扫描在 16K token 时推理速度比 FlashAttention-2 Transformer 快 5 倍...",
      tool_call_counts: {
        "mcp__brave-search__brave_web_search": 2,
        "mcp__fetch__fetch": 2,
        "rag_search": 1,
        "mcp__paper-search__search_arxiv": 1,
      },
    });
  });

  schedule(8500, () => {
    onEvent({
      type: "research",
      question: "分析三种架构在 Long Range Arena 等长文本基准测试上的性能差异",
      preview: "在 LRA 基准的 Pathfinder-256 任务上，Mamba 达到 94.2% 准确率（Transformer 92.8%），在 ListOps 任务上 S4 变体达到 59.7%...",
      tool_call_counts: {
        "mcp__brave-search__brave_web_search": 1,
        "mcp__paper-search__search_google_scholar": 1,
        "mcp__paper-search__read_arxiv_paper": 1,
        "mcp__fetch__fetch": 1,
      },
    });
  });

  schedule(12500, () => {
    onEvent({
      type: "research",
      question: "调查各架构在生产环境中的实际部署情况、工具链和社区生态",
      preview: "HuggingFace Transformers 已支持 Mamba 模型，RWKV 官方提供 .pth 权重可直接加载。Mamba 的 CUDA 实现已合并到官方仓库...",
      tool_call_counts: {
        "mcp__brave-search__brave_web_search": 2,
        "mcp__github__search_repositories": 1,
        "mcp__github__get_file_contents": 1,
        "mcp__fetch__fetch": 1,
        "rag_search": 1,
      },
    });
  });

  // 3. Review — after all research done, show "审查中" shimmer briefly
  schedule(16500, () => {
    onEvent({
      type: "review",
      round: 1,
      review_summary: [
        {
          question: "对比 Transformer、Mamba、RWKV 在 8K+ token 序列上的推理速度和显存占用",
          verdict: "approved",
          failed: {},
          evidence: {
            relevance: "内容直接对比三种架构的推理效率 ✓",
            depth: "包含 FlashAttention 等具体优化技术 ✓",
            citations: "4 处数据引用满足阈值 ✓",
            sources: "arxiv + web 多源交叉验证 ✓",
            completeness: "覆盖推理速度、显存占用两个维度 ✓",
          },
        },
        {
          question: "分析三种架构在 Long Range Arena 等长文本基准测试上的性能差异",
          verdict: "approved",
          failed: {},
          evidence: {
            relevance: "LRA 基准对比为核心内容 ✓",
            depth: "含具体任务和数值 ✓",
            citations: "足够的数据支撑 ✓",
            sources: "多源验证 ✓",
            completeness: "覆盖 Pathfinder、ListOps 等主要子任务 ✓",
          },
        },
        {
          question: "调查各架构在生产环境中的实际部署情况、工具链和社区生态",
          verdict: "approved",
          failed: {},
          evidence: {
            relevance: "部署和生态分析切题 ✓",
            depth: "涵盖 HF 支持、GitHub、CUDA 实现 ✓",
            citations: "引用充分 ✓",
            sources: "GitHub + web 多源 ✓",
            completeness: "覆盖工具链、社区、生产部署三个层面 ✓",
          },
        },
      ],
    });
  });

  // 4. Write — report after review settles
  schedule(20000, () => {
    onEvent({ type: "write", report: MOCK_REPORT, report_file_id: "mock-report.md" });
  });

  // 5. Stats
  schedule(21000, () => {
    onEvent({
      type: "stats",
      total_calls: 14,
      prompt_tokens: 38500,
      completion_tokens: 8200,
      total_tokens: 46700,
    });
    _mockRunning = false;
  });

  return () => {
    cancelled = true;
    _mockRunning = false;
    timers.forEach(clearTimeout);
  };
}

// --- Mock library ---

const _mockDocs: LibraryDoc[] = [
  { title: "Attention Is All You Need", source_type: "arxiv", added_at: "2026-06-20T14:30:00Z" },
  { title: "Mamba: Linear-Time Sequence Modeling with Selective State Spaces", source_type: "arxiv", added_at: "2026-06-21T09:15:00Z" },
];

export function mockListDocs(): Promise<LibraryDoc[]> {
  return new Promise((resolve) => setTimeout(() => resolve([..._mockDocs]), 300));
}

export function mockDeleteDoc(title: string): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(() => {
      const idx = _mockDocs.findIndex((d) => d.title === title);
      if (idx !== -1) _mockDocs.splice(idx, 1);
      resolve();
    }, 300);
  });
}

export function mockUploadFile(file: File): Promise<IngestResult> {
  return new Promise((resolve) => {
    setTimeout(() => {
      const title = file.name.replace(/\.[^.]+$/, "");
      _mockDocs.unshift({ title, source_type: "upload", added_at: new Date().toISOString() });
      resolve({ title, status: "created" });
    }, 500);
  });
}

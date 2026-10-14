const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8001";
const MOCK = process.env.NEXT_PUBLIC_MOCK === "true";

function authHeaders(token: string): HeadersInit {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
}

async function readError(res: Response, fallback: string): Promise<Error> {
  try {
    const data = await res.json();
    return new Error(data.detail || fallback);
  } catch {
    return new Error(fallback);
  }
}

export interface UserInfo {
  id: string;
  username: string;
  display_name: string;
}

export interface AuthResult {
  access_token: string;
  token_type: "bearer";
  user: UserInfo;
}

export async function register(username: string, password: string): Promise<AuthResult> {
  if (MOCK) {
    return {
      access_token: "mock-token",
      token_type: "bearer",
      user: { id: "mock-user", username, display_name: username },
    };
  }
  const res = await fetch(`${API_BASE}/api/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new Error((await res.json()).detail || "注册失败");
  return res.json();
}

export async function login(username: string, password: string): Promise<AuthResult> {
  if (MOCK) {
    return {
      access_token: "mock-token",
      token_type: "bearer",
      user: { id: "mock-user", username, display_name: username },
    };
  }
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new Error((await res.json()).detail || "登录失败");
  return res.json();
}

export async function getMe(token: string): Promise<UserInfo> {
  if (MOCK) {
    return { id: "mock-user", username: "mock", display_name: "Mock User" };
  }
  const res = await fetch(`${API_BASE}/api/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("登录已过期");
  return res.json();
}

export interface ClarifyResult {
  is_clear: boolean;
  brief: string | null;
  directions: string[];
  message: string | null;
  session_id: string | null;
}

export interface RefineResult {
  brief: string;
  session_id: string | null;
}

export async function clarify(query: string, token: string): Promise<ClarifyResult> {
  if (MOCK) {
    const { mockClarify } = await import("./mock");
    return mockClarify(query);
  }
  const res = await fetch(`${API_BASE}/api/clarify`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ query }),
  });
  if (!res.ok) throw await readError(res, "分析问题失败");
  return res.json();
}

export async function refine(
  query: string,
  response: string,
  sessionId: string | null,
  token: string,
): Promise<RefineResult> {
  if (MOCK) {
    const { mockRefine } = await import("./mock");
    return mockRefine(query, response);
  }
  const res = await fetch(`${API_BASE}/api/clarify/refine`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ query, response, session_id: sessionId }),
  });
  if (!res.ok) throw await readError(res, "整理研究方向失败");
  return res.json();
}

export interface IngestResult {
  title: string;
  status: "skipped" | "overwritten" | "created";
}

export interface LibraryDoc {
  title: string;
  source_type: string;
  added_at: string;
}

export async function listDocs(token: string): Promise<LibraryDoc[]> {
  if (MOCK) {
    const { mockListDocs } = await import("./mock");
    return mockListDocs();
  }
  const res = await fetch(`${API_BASE}/api/library`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw await readError(res, "读取文献库失败");
  return res.json();
}

export async function deleteDoc(title: string, token: string): Promise<void> {
  if (MOCK) {
    const { mockDeleteDoc } = await import("./mock");
    return mockDeleteDoc(title);
  }
  const res = await fetch(`${API_BASE}/api/library/${encodeURIComponent(title)}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw await readError(res, "删除文献失败");
}

export async function getReport(reportFileId: string, token: string): Promise<{ report_file_id: string; title: string; content: string }> {
  const res = await fetch(
    `${API_BASE}/api/reports/${encodeURIComponent(reportFileId)}`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (!res.ok) throw await readError(res, "读取报告失败");
  return res.json();
}

export async function uploadFile(file: File, token: string): Promise<IngestResult> {
  if (MOCK) {
    const { mockUploadFile } = await import("./mock");
    return mockUploadFile(file);
  }
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/library/upload`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!res.ok) throw await readError(res, "上传文件失败");
  return res.json();
}

// --- SSE Research Events ---

export type ResearchEvent =
  | { type: "session"; session_id: string }
  | { type: "route"; intent: "report_qa" | "initial_research" | "supplementary_research" | "deepening"; task_id?: string; run_id?: string; report_version_id?: string }
  | { type: "clarification"; message: string; directions?: string[] }
  | { type: "answer"; content: string; sources: { title: string; file_id?: string; excerpt?: string }[] }
  | ({ type: "plan"; sub_questions: { label: string; question: string }[] } & StreamMeta)
  | ({ type: "research"; question: string; preview: string; tool_call_counts: Record<string, number> } & StreamMeta)
  | ({ type: "review"; round: number; review_summary: { question: string; verdict: string; failed: Record<string, boolean>; evidence?: Record<string, string> }[]; missing_dimensions?: string } & StreamMeta)
  | ({ type: "write"; report: string; report_file_id?: string; version_id?: string; report_version_id?: string; title?: string } & StreamMeta)
  | ({ type: "stats"; total_calls: number; prompt_tokens: number; completion_tokens: number; total_tokens: number } & StreamMeta)
  | { type: "error"; message: string; task_id?: string; run_id?: string };

interface StreamMeta {
  task_id?: string;
  run_id?: string;
  version_id?: string;
}

export interface ChatSessionSummary {
  id: string;
  title: string;
  raw_query: string;
  research_brief: string | null;
  report_file_id: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ChatSessionDetail extends ChatSessionSummary {
  active_task_id?: string | null;
  messages: { role: string; message_type: string; content: string; created_at: string; extra?: Record<string, unknown> | null }[];
  steps: { sequence: number; step_type: string; title: string; content: string | null; report_file_id: string | null; created_at: string; extra?: Record<string, unknown> | null }[];
  report: { report_file_id: string; title: string; content: string } | null;
  tasks?: {
    id: string;
    title: string;
    intent: string;
    scope?: string | null;
    status?: string;
    current_version_id: string | null;
    versions: {
      id: string;
      run_id: string;
      version_number?: number;
      parent_version_id?: string | null;
      report_file_id: string;
      title: string;
      content: string;
      created_at: string;
    }[];
  }[];
}

export async function listSessions(token: string): Promise<ChatSessionSummary[]> {
  if (MOCK) {
    const { mockListSessions } = await import("./mock");
    return mockListSessions();
  }
  const res = await fetch(`${API_BASE}/api/sessions`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw await readError(res, "读取聊天记录失败");
  return res.json();
}

export async function getSession(sessionId: string, token: string): Promise<ChatSessionDetail> {
  if (MOCK) {
    const { mockGetSession } = await import("./mock");
    return mockGetSession(sessionId);
  }
  const res = await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw await readError(res, "读取聊天详情失败");
  return res.json();
}

export function startChatTurn(
  message: string,
  sessionId: string | null,
  onEvent: (event: ResearchEvent) => void,
  token: string,
  options: { taskId?: string | null; reportVersionId?: string | null } = {},
  onComplete?: () => void,
): () => void {
  if (MOCK) {
    let cancelled = false;
    let mockAbort: (() => void) | null = null;
    import("./mock").then(({ startMockTurn }) => {
      if (!cancelled) mockAbort = startMockTurn(message, sessionId, onEvent, onComplete, options);
    });
    return () => {
      cancelled = true;
      mockAbort?.();
    };
  }

  const controller = new AbortController();
  let active = true;
  fetch(`${API_BASE}/api/chat/turns`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({
      message,
      session_id: sessionId,
      ...(options.taskId ? { task_id: options.taskId } : {}),
      ...(options.reportVersionId ? { report_version_id: options.reportVersionId } : {}),
    }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok || !res.body) throw await readError(res, "发送消息失败");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      function dispatch(block: string) {
        let eventType = "";
        const dataLines: string[] = [];
        for (const line of block.split(/\r?\n/)) {
          if (line.startsWith("event:")) eventType = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
        }
        if (!active || !eventType || dataLines.length === 0) return;
        try {
          onEvent({ type: eventType, ...JSON.parse(dataLines.join("\n")) } as ResearchEvent);
        } catch {
          onEvent({ type: "error", message: "服务器返回了无法解析的研究事件" });
        }
      }

      while (active) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split(/\r?\n\r?\n/);
        buffer = blocks.pop() || "";
        blocks.forEach(dispatch);
      }
      buffer += decoder.decode();
      if (buffer.trim()) dispatch(buffer);
      if (active) onComplete?.();
    })
    .catch((cause: unknown) => {
      if (!active || (cause instanceof Error && cause.name === "AbortError")) return;
      onEvent({ type: "error", message: cause instanceof Error ? cause.message : "发送消息失败" });
      onComplete?.();
    });

  return () => {
    active = false;
    controller.abort();
  };
}

export async function deleteSession(sessionId: string, token: string): Promise<void> {
  if (MOCK) {
    const { mockDeleteSession } = await import("./mock");
    return mockDeleteSession(sessionId);
  }
  const res = await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw await readError(res, "删除对话失败");
}

export function startResearch(
  brief: string,
  onEvent: (event: ResearchEvent) => void,
  sessionId: string | null,
  token: string,
): () => void {
  if (MOCK) {
    let cancelled = false;
    let mockAbort: (() => void) | null = null;
    import("./mock").then(({ startMockResearch }) => {
      if (!cancelled) {
        mockAbort = startMockResearch(brief, onEvent);
      }
    });
    return () => {
      cancelled = true;
      mockAbort?.();
    };
  }

  const controller = new AbortController();

  fetch(`${API_BASE}/api/research`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ brief, session_id: sessionId }),
    signal: controller.signal,
  })
    .then((res) => {
      if (!res.ok || !res.body) {
        return readError(res, "研究请求失败").then((error) => {
          throw error;
        });
      }
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      function pump(): Promise<void> {
        return reader.read().then(({ done, value }) => {
          if (done) return;
          buffer += decoder.decode(value, { stream: true });

          const blocks = buffer.split("\n\n");
          buffer = blocks.pop()!;

          for (const block of blocks) {
            let eventType = "";
            let data = "";
            for (const line of block.split("\n")) {
              if (line.startsWith("event: ")) eventType = line.slice(7);
              else if (line.startsWith("data: ")) data = line.slice(6);
            }
            if (eventType && data) {
              onEvent({ type: eventType, ...JSON.parse(data) } as ResearchEvent);
            }
          }

          return pump();
        });
      }

      return pump();
    })
    .catch((err) => {
      if (err.name !== "AbortError") {
        onEvent({ type: "error", message: err.message });
      }
    });

  return () => controller.abort();
}

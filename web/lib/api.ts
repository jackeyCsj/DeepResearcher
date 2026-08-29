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
  | { type: "plan"; sub_questions: { label: string; question: string }[] }
  | { type: "research"; question: string; preview: string; tool_call_counts: Record<string, number> }
  | { type: "review"; round: number; review_summary: { question: string; verdict: string; failed: Record<string, boolean>; evidence?: Record<string, string> }[]; missing_dimensions?: string }
  | { type: "write"; report: string; report_file_id?: string }
  | { type: "stats"; total_calls: number; prompt_tokens: number; completion_tokens: number; total_tokens: number }
  | { type: "error"; message: string };

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
  messages: { role: string; message_type: string; content: string; created_at: string; extra?: Record<string, unknown> | null }[];
  steps: { sequence: number; step_type: string; title: string; content: string | null; report_file_id: string | null; created_at: string; extra?: Record<string, unknown> | null }[];
  report: { report_file_id: string; title: string; content: string } | null;
}

export async function listSessions(token: string): Promise<ChatSessionSummary[]> {
  if (MOCK) return [];
  const res = await fetch(`${API_BASE}/api/sessions`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw await readError(res, "读取聊天记录失败");
  return res.json();
}

export async function getSession(sessionId: string, token: string): Promise<ChatSessionDetail> {
  const res = await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw await readError(res, "读取聊天详情失败");
  return res.json();
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

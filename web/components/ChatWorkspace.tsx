"use client";

import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import ResearchProgress, { type ResearchStats } from "@/components/ResearchProgress";
import StreamingText from "@/components/StreamingText";
import UserMenu from "@/components/UserMenu";
import { startChatTurn, type ChatSessionDetail, type ResearchEvent, type ResearchTraceItem, type UserInfo } from "@/lib/api";

interface ReportReference {
  taskId?: string | null;
  versionId?: string | null;
  reportFileId?: string | null;
  versionNumber?: number;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  messageType?: string;
  taskId?: string | null;
  runId?: string | null;
  sources?: { title: string; file_id?: string; excerpt?: string }[];
  directions?: string[];
  report?: ReportReference;
}

export default function ChatWorkspace({
  detail,
  token,
  user,
  onLogout,
  selectedTaskId,
  selectedReportVersionId,
  onSession,
  onReport,
  onStats,
  onTurnComplete,
  onOpenReport,
}: {
  detail: ChatSessionDetail | null;
  token: string;
  user: UserInfo;
  onLogout: () => void;
  selectedTaskId: string | null;
  selectedReportVersionId: string | null;
  onSession: (sessionId: string) => void;
  onReport: (event: Extract<ResearchEvent, { type: "write" }>) => void;
  onStats: (stats: ResearchStats) => void;
  onTurnComplete: (sessionId: string | null) => void;
  onOpenReport: (reference: ReportReference) => void;
}) {
  const [sessionId, setSessionId] = useState<string | null>(detail?.id ?? null);
  const sessionIdRef = useRef(sessionId);
  const [messages, setMessages] = useState<ChatMessage[]>(() => toMessages(detail));
  const [draft, setDraft] = useState("");
  const [turnEvents, setTurnEvents] = useState<ResearchEvent[]>([]);
  const [turnId, setTurnId] = useState(0);
  const [streaming, setStreaming] = useState(false);
  const [routeIntent, setRouteIntent] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [failedTurn, setFailedTurn] = useState<{ message: string; turnId: string } | null>(null);
  const abortRef = useRef<(() => void) | null>(null);
  const turnRef = useRef(0);
  const failedRef = useRef(false);
  const submittedRef = useRef<{ message: string; turnId: string } | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    const nearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 120;
    if (nearBottom) bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, turnEvents]);

  useEffect(() => () => {
    turnRef.current += 1;
    abortRef.current?.();
  }, []);

  function appendAssistant(content: string, additions: Partial<ChatMessage> = {}) {
    setMessages((current) => [...current, {
      id: crypto.randomUUID(),
      role: "assistant",
      content,
      ...additions,
    }]);
  }

  function handleEvent(turn: number, event: ResearchEvent) {
    if (turn !== turnRef.current) return;
    setTurnEvents((current) => [...current, event]);
    switch (event.type) {
      case "session":
        sessionIdRef.current = event.session_id;
        setSessionId(event.session_id);
        onSession(event.session_id);
        break;
      case "route":
        setRouteIntent(event.intent);
        break;
      case "clarification":
        appendAssistant(event.message, { directions: event.directions || [] });
        break;
      case "answer":
        appendAssistant(event.content, { sources: event.sources || [] });
        break;
      case "write":
        onReport(event);
        appendAssistant(`报告已生成${event.version_number ? `（第 ${event.version_number} 版）` : ""}。`, {
          taskId: event.task_id,
          runId: event.run_id,
          report: {
            taskId: event.task_id,
            versionId: event.report_version_id || event.version_id,
            reportFileId: event.report_file_id,
            versionNumber: event.version_number,
          },
        });
        break;
      case "stats":
        onStats({
          total_calls: event.total_calls,
          prompt_tokens: event.prompt_tokens,
          completion_tokens: event.completion_tokens,
          total_tokens: event.total_tokens,
        });
        break;
      case "error":
        failedRef.current = true;
        setError(event.message);
        setFailedTurn(submittedRef.current);
        break;
    }
  }

  function startTurn(message: string, turnId: string, appendUser: boolean) {
    setError("");
    setFailedTurn(null);
    setStreaming(true);
    failedRef.current = false;
    submittedRef.current = { message, turnId };
    setRouteIntent(null);
    setTurnEvents([]);
    const nextTurn = turnRef.current + 1;
    turnRef.current = nextTurn;
    setTurnId(nextTurn);
    if (appendUser) {
      setMessages((current) => [...current, { id: crypto.randomUUID(), role: "user", content: message }]);
    }
    abortRef.current = startChatTurn(
      message,
      sessionIdRef.current,
      (nextEvent) => handleEvent(nextTurn, nextEvent),
      token,
      { taskId: selectedTaskId, reportVersionId: selectedReportVersionId, turnId },
      () => {
        if (nextTurn !== turnRef.current) return;
        setStreaming(false);
        abortRef.current = null;
        if (!failedRef.current) onTurnComplete(sessionIdRef.current);
      },
    );
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || streaming) return;
    setDraft("");
    startTurn(message, crypto.randomUUID(), true);
  }

  function retryFailedTurn() {
    if (!failedTurn || streaming) return;
    startTurn(failedTurn.message, failedTurn.turnId, false);
  }

  function autoResize() {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
  }

  const hasResearchEvents = turnEvents.some((event) =>
    ["plan", "research", "review", "write", "stats"].includes(event.type),
  );

  return (
    <main className="flex h-full min-h-0 w-full flex-col">
      <header className="flex shrink-0 items-center justify-between border-b border-foreground/8 px-5 py-3.5 sm:px-8">
        <div className="min-w-0">
          <h1 className="truncate text-[16px] font-medium">{detail?.title || "Deep Research"}</h1>
          {routeIntent && <p className="mt-0.5 text-[12px] text-muted-foreground">{intentLabel(routeIntent)}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {streaming && <span className="text-[12px] text-accent">处理中</span>}
          <UserMenu user={user} onLogout={onLogout} />
        </div>
      </header>

      <div ref={scrollRef} data-scroll-container className="min-h-0 flex-1 overflow-y-auto px-4 py-6 thin-scroll sm:px-8">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-5">
          {messages.length === 0 && (
            <div className="flex min-h-[35vh] flex-col items-center justify-center text-center">
              <h2 className="text-2xl font-medium">你想调研什么？</h2>
              <p className="mt-2 text-[14px] text-foreground/60">可以先提一个问题，之后也能继续追问或补充研究。</p>
            </div>
          )}
          {messages.map((message) => {
            const persistedEvents = message.runId && detail
              ? buildPersistedRunEvents(detail, message)
              : [];
            return (
              <div key={message.id} className="flex min-w-0 flex-col gap-3">
                <MessageBubble
                  message={message}
                  onUseDirection={(value) => setDraft(value)}
                  onOpenReport={onOpenReport}
                />
                {persistedEvents.length > 0 && (
                  <div className="w-full">
                    <p className="mb-1 pl-7 text-[12px] font-medium text-foreground/60">本轮调研过程</p>
                    <ResearchProgress events={persistedEvents} onReport={() => undefined} />
                  </div>
                )}
              </div>
            );
          })}
          {streaming && !turnEvents.some((event) => event.type === "route" || event.type === "clarification" || event.type === "answer") && (
            <div className="flex justify-start">
              <div className="rounded-lg bg-surface px-4 py-3 text-[14px] text-foreground/65">
                <StreamingText text="正在分析请求" mode="dots" />
              </div>
            </div>
          )}
          {hasResearchEvents && (
            <ResearchProgress
              key={turnId}
              events={turnEvents.filter((event) => event.type !== "error")}
              onReport={() => undefined}
            />
          )}
          {error && (
            <div role="alert" className="flex flex-wrap items-center justify-between gap-3 border-t border-error/20 pt-3 text-[13px] text-error">
              <p className="min-w-0 flex-1">{error}</p>
              {failedTurn && (
                <button
                  type="button"
                  disabled={streaming}
                  onClick={retryFailedTurn}
                  className="shrink-0 rounded-md border border-error/30 px-3 py-1.5 font-medium transition-colors hover:bg-error/5 disabled:opacity-50"
                >
                  再试一次
                </button>
              )}
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <form onSubmit={submit} className="shrink-0 border-t border-foreground/8 bg-surface/55 px-4 py-3 sm:px-8">
        <div className="mx-auto flex w-full max-w-3xl items-end gap-2 rounded-lg border border-foreground/15 bg-surface px-3 py-2 focus-within:border-accent/50">
          <textarea
            ref={textareaRef}
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value);
              autoResize();
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            disabled={streaming}
            placeholder={detail?.messages.length ? "继续提问，或要求补充研究..." : "输入研究问题..."}
            rows={1}
            className="max-h-[180px] min-h-8 flex-1 resize-none bg-transparent py-1 text-[14px] leading-6 outline-none placeholder:text-muted-foreground disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={!draft.trim() || streaming}
            aria-label="发送消息"
            title="发送消息"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent text-surface transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-35"
          >
            {streaming ? (
              <span className="h-3.5 w-3.5 rounded-full border-2 border-surface/50 border-t-surface animate-spin" />
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4" aria-hidden="true">
                <path d="M5 12h14M12 5l7 7-7 7" />
              </svg>
            )}
          </button>
        </div>
        <p className="mx-auto mt-1.5 w-full max-w-3xl text-right text-[11px] text-foreground/40">Enter 发送 · Shift+Enter 换行</p>
      </form>
    </main>
  );
}

function toMessages(detail: ChatSessionDetail | null): ChatMessage[] {
  return (detail?.messages || []).map((message, index) => ({
    id: `${detail?.id}-${index}-${message.created_at}`,
    role: message.role === "user" ? "user" : "assistant",
    content: message.content,
    messageType: message.message_type,
    taskId: asString(message.extra?.task_id),
    runId: asString(message.extra?.run_id),
    report: message.message_type === "report" ? {
      taskId: asString(message.extra?.task_id),
      versionId: asString(message.extra?.report_version_id),
      reportFileId: asString(message.extra?.report_file_id),
      versionNumber: asNumber(message.extra?.version_number),
    } : undefined,
    sources: Array.isArray(message.extra?.sources)
      ? message.extra.sources.filter(isSource).map((source) => ({
        title: source.title,
        file_id: source.file_id,
        excerpt: source.excerpt,
      }))
      : undefined,
    directions: Array.isArray(message.extra?.directions)
      ? message.extra.directions.filter((direction): direction is string => typeof direction === "string")
      : undefined,
  }));
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" ? value : undefined;
}

function buildPersistedRunEvents(detail: ChatSessionDetail, message: ChatMessage): ResearchEvent[] {
  if (!message.runId) return [];
  const steps = detail.steps.filter((step) => step.extra?.run_id === message.runId);
  const events: ResearchEvent[] = [];
  for (const step of steps) {
    const extra = step.extra || {};
    const taskId = asString(extra.task_id) || message.taskId;
    const meta = { ...(taskId ? { task_id: taskId } : {}), run_id: message.runId };
    if (step.step_type === "plan" && Array.isArray(extra.sub_questions)) {
      events.push({
        type: "plan",
        sub_questions: extra.sub_questions.filter(isSubQuestion),
        ...meta,
      });
    } else if (step.step_type === "research") {
      events.push({
        type: "research",
        question: step.content || asString(extra.question) || "",
        preview: asString(extra.preview) || "",
        note: asString(extra.note),
        research_trace: Array.isArray(extra.research_trace)
          ? extra.research_trace.filter(isResearchTrace)
          : undefined,
        tool_call_counts: isCountMap(extra.tool_call_counts) ? extra.tool_call_counts : {},
        ...meta,
      });
    } else if (step.step_type === "review" && Array.isArray(extra.review_summary)) {
      events.push({
        type: "review",
        round: asNumber(extra.round) || 1,
        review_summary: extra.review_summary.filter(isReviewItem),
        missing_dimensions: asString(extra.missing_dimensions),
        ...meta,
      });
    }
  }

  const reportVersion = message.report?.versionId
    ? detail.tasks?.flatMap((task) => task.versions).find((version) => version.id === message.report?.versionId)
    : undefined;
  if (message.messageType === "report") {
    events.push({
      type: "write",
      report: reportVersion?.content || "",
      report_file_id: message.report?.reportFileId || undefined,
      report_version_id: message.report?.versionId || undefined,
      version_id: message.report?.versionId || undefined,
      task_id: message.report?.taskId || message.taskId || undefined,
      run_id: message.runId,
    });
  } else if (message.messageType === "error" && message.runId) {
    events.push({
      type: "error",
      message: message.content,
      task_id: message.taskId || undefined,
      run_id: message.runId,
    });
  }
  return events;
}

function isSubQuestion(value: unknown): value is { label: string; question: string } {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return typeof item.label === "string" && typeof item.question === "string";
}

function isCountMap(value: unknown): value is Record<string, number> {
  return !!value && typeof value === "object" && Object.values(value).every((item) => typeof item === "number");
}

function isReviewItem(value: unknown): value is Extract<ResearchEvent, { type: "review" }>['review_summary'][number] {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return typeof item.question === "string" && typeof item.verdict === "string" && !!item.failed && typeof item.failed === "object";
}

function isResearchTrace(value: unknown): value is ResearchTraceItem {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return typeof item.tool === "string" && typeof item.result === "string" && !!item.arguments && typeof item.arguments === "object";
}

function isSource(value: unknown): value is { title: string; file_id?: string; excerpt?: string } {
  if (!value || typeof value !== "object") return false;
  const source = value as Record<string, unknown>;
  return typeof source.title === "string";
}

function MessageBubble({
  message,
  onUseDirection,
  onOpenReport,
}: {
  message: ChatMessage;
  onUseDirection: (value: string) => void;
  onOpenReport: (reference: ReportReference) => void;
}) {
  const isUser = message.role === "user";
  return (
    <div className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div className={`max-w-[88%] text-[14px] leading-relaxed ${isUser ? "rounded-lg bg-foreground/85 px-4 py-2.5 text-surface" : "w-full"}`}>
        {!isUser && <p className="mb-1 font-mono text-[10px] uppercase text-muted-foreground">Assistant</p>}
        <div className={!isUser ? "rounded-lg bg-surface px-4 py-3 whitespace-pre-wrap" : "whitespace-pre-wrap"}>{message.content}</div>
        {message.report && (
          <button
            type="button"
            onClick={() => onOpenReport(message.report!)}
            className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-foreground/12 bg-surface px-3 py-1.5 text-[12px] font-medium text-foreground/75 transition-colors hover:border-accent/40 hover:text-foreground"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5" aria-hidden="true">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <path d="M14 2v6h6M8 13h8M8 17h8" />
            </svg>
            查看报告{message.report.versionNumber ? ` · V${message.report.versionNumber}` : ""}
          </button>
        )}
        {!!message.sources?.length && (
          <div className="mt-2 space-y-1.5 px-2">
            {message.sources.map((source, index) => (
              <div key={`${source.file_id || source.title}-${index}`} className="text-[12px] text-foreground/65">
                <p className="font-medium">{source.title}</p>
                {source.excerpt && <p className="mt-0.5 line-clamp-2">{source.excerpt}</p>}
              </div>
            ))}
          </div>
        )}
        {!!message.directions?.length && (
          <div className="mt-2 flex flex-wrap gap-2">
            {message.directions.map((direction) => (
              <button
                key={direction}
                type="button"
                onClick={() => onUseDirection(direction)}
                className="rounded-md border border-foreground/12 bg-surface px-2.5 py-1.5 text-left text-[12px] hover:border-accent/45 hover:bg-accent/5"
              >
                {direction}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function intentLabel(intent: string) {
  const labels: Record<string, string> = {
    report_qa: "报告问答",
    initial_research: "首轮研究",
    supplementary_research: "补充研究",
    deepening: "章节深化",
  };
  return labels[intent] || intent;
}

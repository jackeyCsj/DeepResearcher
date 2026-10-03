"use client";

import { useEffect, useRef, useState } from "react";
import AuthOverlay from "@/components/AuthOverlay";
import ChatSidebar from "@/components/ChatSidebar";
import QueryInput from "@/components/QueryInput";
import ClarifyPanel, { resetClarifyCache } from "@/components/ClarifyPanel";
import ResearchProgress from "@/components/ResearchProgress";
import ReportView from "@/components/ReportView";
import StreamingText from "@/components/StreamingText";
import UserMenu from "@/components/UserMenu";
import {
  getMe,
  getSession,
  deleteDoc,
  deleteSession,
  listDocs,
  listSessions,
  uploadFile,
  type ChatSessionDetail,
  type ChatSessionSummary,
  type LibraryDoc,
  type UserInfo,
} from "@/lib/api";

type Stage = "input" | "sending" | "clarify" | "researching" | "report";
type MainMode = "chat" | "library";

export default function Home() {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<UserInfo | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [mode, setMode] = useState<MainMode>("chat");
  const [selectedDetail, setSelectedDetail] = useState<ChatSessionDetail | null>(null);
  const [stage, setStage] = useState<Stage>("input");
  const [query, setQuery] = useState("");
  const [brief, setBrief] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [report, setReport] = useState("");
  const [reportFileId, setReportFileId] = useState<string | null>(null);
  const [stats, setStats] = useState<{ total_calls: number; total_tokens: number } | null>(null);
  const [reportWidth, setReportWidth] = useState(45);
  const [isResizingReport, setIsResizingReport] = useState(false);
  const splitRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isResizingReport) return;

    function handlePointerMove(event: PointerEvent) {
      const split = splitRef.current;
      if (!split) return;
      const bounds = split.getBoundingClientRect();
      const nextWidth = ((bounds.right - event.clientX) / bounds.width) * 100;
      setReportWidth(Math.min(65, Math.max(28, nextWidth)));
    }

    function stopResizing() {
      setIsResizingReport(false);
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", stopResizing);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", stopResizing);
    };
  }, [isResizingReport]);

  useEffect(() => {
    const savedToken = window.localStorage.getItem("sage_token");
    if (!savedToken) {
      queueMicrotask(() => setAuthLoading(false));
      return;
    }
    getMe(savedToken)
      .then((me) => {
        setToken(savedToken);
        setUser(me);
        listSessions(savedToken).then(setSessions);
      })
      .catch(() => {
        window.localStorage.removeItem("sage_token");
      })
      .finally(() => setAuthLoading(false));
  }, []);

  async function refreshSessions(nextToken = token) {
    if (!nextToken) return;
    const items = await listSessions(nextToken);
    setSessions(items);
  }

  function handleAuthenticated(nextToken: string, nextUser: UserInfo) {
    window.localStorage.setItem("sage_token", nextToken);
    setToken(nextToken);
    setUser(nextUser);
    refreshSessions(nextToken);
  }

  function resetWorkspace() {
    resetClarifyCache();
    setMode("chat");
    setStage("input");
    setQuery("");
    setBrief("");
    setSessionId(null);
    setReport("");
    setReportFileId(null);
    setStats(null);
  }

  function handleLogout() {
    window.localStorage.removeItem("sage_token");
    setToken(null);
    setUser(null);
    setSessions([]);
    setSelectedDetail(null);
    resetWorkspace();
  }

  function handleNewChat() {
    setSelectedDetail(null);
    resetWorkspace();
  }

  async function handleDeleteSession(id: string) {
    if (!token) return;
    if (!window.confirm("确定删除这个对话吗？聊天记录与研究报告将一并删除，且无法恢复。")) return;
    try {
      await deleteSession(id, token);
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "删除失败");
      return;
    }
    // 删掉的是当前打开的会话时回到初始态，
    // 进行中的研究会随 ResearchProgress 卸载而 abort。
    if (sessionId === id || selectedDetail?.id === id) {
      resetWorkspace();
    }
    await refreshSessions();
  }

  function handleQuerySubmit(q: string) {
    setSelectedDetail(null);
    setMode("chat");
    setQuery(q);
    setSessionId(null);
    setReportFileId(null);
    setReport("");
    setStats(null);
    setStage("sending");
    setTimeout(() => setStage("clarify"), 400);
  }

  function handleBriefReady(b: string, sid: string | null) {
    setBrief(b);
    setSessionId(sid);
    setStage("researching");
    refreshSessions();
  }

  async function handleSelectSession(id: string, openReport = false) {
    if (!token) return;
    // 切换会话时丢弃上一个对话的澄清缓存，否则模块级单例会跨对话残留，
    // 导致切回/新开对话时命中错误的 query 状态。
    resetClarifyCache();
    const detail = await getSession(id, token);
    setMode("chat");
    setSelectedDetail(detail);
    setSessionId(detail.id);
    setStage("input");
    setStats(null);
    if (openReport && detail.report) {
      setReport(detail.report.content);
      setReportFileId(detail.report.report_file_id);
    } else {
      setReport("");
      setReportFileId(detail.report_file_id);
    }
  }

  function handleOpenLibrary() {
    setMode("library");
    setSelectedDetail(null);
    setReport("");
    setStats(null);
    refreshSessions();
  }

  function handleCloseReport() {
    setReport("");
    setReportFileId(null);
    setStats(null);
  }

  function handleReportResizeKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      setReportWidth((width) => Math.min(65, width + 4));
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      setReportWidth((width) => Math.max(28, width - 4));
    }
  }

  const authenticated = Boolean(token && user);
  const reportReady = Boolean(report);

  return (
    <>
      {authenticated && user && (
        <>
          <div className="app-shell flex h-screen w-full overflow-hidden">
            <ChatSidebar
              sessions={sessions}
              selectedSessionId={sessionId}
              mode={mode}
              onNewChat={handleNewChat}
              onSelectSession={(id) => handleSelectSession(id)}
              onDeleteSession={(id) => void handleDeleteSession(id)}
              onOpenLibrary={handleOpenLibrary}
            />

            <div
              ref={splitRef}
              className={["workspace-split relative flex min-w-0 flex-1 overflow-hidden", isResizingReport ? "select-none" : ""].join(" ")}
            >
              <UserMenu user={user} onLogout={handleLogout} />
              <div
                className="min-w-0 shrink-0 overflow-hidden"
                style={{ width: reportReady ? `${100 - reportWidth}%` : "100%" }}
              >
                {mode === "library" ? (
                  <LibraryMain token={token!} />
                ) : selectedDetail ? (
                  <HistoryMain
                    detail={selectedDetail}
                    reportReady={reportReady}
                    onOpenReport={() => {
                      if (selectedDetail.report) {
                        setReport(selectedDetail.report.content);
                        setReportFileId(selectedDetail.report.report_file_id);
                      }
                    }}
                  />
                ) : (
                  <LiveResearchMain
                    stage={stage}
                    query={query}
                    brief={brief}
                    token={token!}
                    sessionId={sessionId}
                    reportReady={reportReady}
                    onSubmit={handleQuerySubmit}
                    onBriefReady={handleBriefReady}
                    onReport={(r, s, fileId) => {
                      setReport(r);
                      if (fileId) setReportFileId(fileId);
                      if (s) setStats({ total_calls: s.total_calls, total_tokens: s.total_tokens });
                      setStage("report");
                      refreshSessions();
                    }}
                  />
                )}
              </div>

              {reportReady && (
                <>
                  <div
                    role="separator"
                    aria-label="调整对话与文档宽度"
                    aria-orientation="vertical"
                    aria-valuemin={28}
                    aria-valuemax={65}
                    aria-valuenow={Math.round(reportWidth)}
                    tabIndex={0}
                    title="拖动调整对话与文档宽度"
                    onPointerDown={(event) => {
                      event.preventDefault();
                      setIsResizingReport(true);
                    }}
                    onKeyDown={handleReportResizeKeyDown}
                    className="group flex w-2 shrink-0 cursor-col-resize touch-none items-center justify-center bg-transparent outline-none hover:bg-accent/10 focus-visible:bg-accent/10"
                  >
                    <span className="h-14 w-px bg-foreground/15 transition-colors group-hover:bg-accent/65 group-focus-visible:bg-accent/65" />
                  </div>
                  <div
                    data-report-panel
                    className="min-h-0 min-w-0 flex-1 overflow-y-auto border-l border-foreground/8 bg-surface/40 thin-scroll"
                  >
                    <ReportView
                      report={report}
                      stats={stats}
                      reportFileId={reportFileId}
                      onClose={handleCloseReport}
                    />
                  </div>
                </>
              )}
            </div>
          </div>
        </>
      )}

      {!authLoading && !authenticated && <AuthOverlay onAuthenticated={handleAuthenticated} />}
    </>
  );
}

function LiveResearchMain({
  stage,
  query,
  brief,
  token,
  sessionId,
  reportReady,
  onSubmit,
  onBriefReady,
  onReport,
}: {
  stage: Stage;
  query: string;
  brief: string;
  token: string;
  sessionId: string | null;
  reportReady: boolean;
  onSubmit: (q: string) => void;
  onBriefReady: (brief: string, sessionId: string | null) => void;
  onReport: (report: string, stats: { total_calls: number; total_tokens: number } | null, reportFileId: string | null) => void;
}) {
  if (stage === "input" || stage === "sending") {
    return (
      <main className="flex h-full w-full flex-1 flex-col items-center px-4">
        <HeroSection onSubmit={onSubmit} sending={stage === "sending"} />
      </main>
    );
  }

  return (
    <main className="h-full w-full overflow-y-auto px-4 thin-scroll" data-scroll-container>
      <div className="mx-auto flex w-full max-w-3xl flex-col items-center gap-4 pb-8 pt-16">
        <ClarifyPanel query={query} token={token} onBriefReady={onBriefReady} />
        {(stage === "researching" || reportReady) && (
          <ResearchProgress
            brief={brief}
            token={token}
            sessionId={sessionId}
            onReport={onReport}
          />
        )}
      </div>
    </main>
  );
}

function HistoryMain({
  detail,
  reportReady,
  onOpenReport,
}: {
  detail: ChatSessionDetail;
  reportReady: boolean;
  onOpenReport: () => void;
}) {
  return (
    <main className="h-full w-full overflow-y-auto px-6 pb-10 pt-16 thin-scroll">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
        {detail.messages.map((message, idx) => (
          <div key={idx} className={message.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <div
              className={[
                "max-w-[84%] rounded-2xl px-4 py-2.5 text-[14px] leading-relaxed whitespace-pre-wrap",
                message.role === "user"
                  ? "bg-foreground/85 text-surface rounded-br-sm"
                  : "bg-surface text-foreground rounded-bl-sm",
              ].join(" ")}
            >
              {message.content}
            </div>
          </div>
        ))}

        {detail.steps.length > 0 && (
          <div className="mt-2 rounded-2xl bg-surface/80 p-4">
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground mb-3">处理步骤</p>
            <ul className="space-y-2">
              {detail.steps.map((step) => {
                const isReportStep = step.step_type === "write" && detail.report;
                let className = "w-full text-left rounded-xl px-3 py-2 text-[14px] ";
                if (isReportStep) {
                  className += reportReady
                    ? "bg-approved/15 text-approved"
                    : "bg-background hover:bg-approved/10 text-approved";
                } else {
                  className += "bg-background text-foreground/70";
                }
                return (
                  <li key={step.sequence}>
                    <button onClick={isReportStep ? onOpenReport : undefined} className={className}>
                      <span className="mr-2 text-muted-foreground">{step.sequence}.</span>
                      {step.title}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </div>
    </main>
  );
}

function LibraryMain({ token }: { token: string }) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [docs, setDocs] = useState<LibraryDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    listDocs(token)
      .then((items) => {
        if (active) setDocs(items);
      })
      .catch((cause) => {
        if (active) setError(cause instanceof Error ? cause.message : "读取文献库失败");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [token]);

  async function handleUpload(file: File) {
    setUploading(true);
    setError("");
    try {
      await uploadFile(file, token);
      setDocs(await listDocs(token));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "上传文献失败");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleDelete(title: string) {
    setDeleting(title);
    setError("");
    try {
      await deleteDoc(title, token);
      setDocs((items) => items.filter((item) => item.title !== title));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除文献失败");
    } finally {
      setDeleting(null);
    }
  }

  return (
    <main className="flex-1 min-w-0 overflow-y-auto px-5 sm:px-10 pt-20 pb-12 thin-scroll">
      <div className="flex max-w-3xl flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-medium">文献库</h1>
          <p className="mt-2 text-[14px] text-foreground/65">展示显式上传或导入的文献。调研报告保留在聊天记录中。</p>
        </div>
        <button
          type="button"
          disabled={uploading}
          onClick={() => fileInputRef.current?.click()}
          className="rounded-md bg-foreground px-4 py-2 text-[13px] text-surface transition-opacity hover:opacity-85 disabled:cursor-wait disabled:opacity-55"
        >
          {uploading ? "正在上传..." : "上传文献"}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.md,.markdown,.txt"
          className="hidden"
          onChange={(event) => {
            const file = event.currentTarget.files?.[0];
            if (file) void handleUpload(file);
          }}
        />
      </div>

      {error && <p className="mt-5 max-w-3xl text-[13px] text-error">{error}</p>}

      <div className="mt-8 max-w-3xl border-y border-foreground/10">
        {loading && <p className="py-6 text-[14px] text-foreground/55">正在读取文献...</p>}
        {!loading && docs.length === 0 && (
          <p className="py-6 text-[14px] text-foreground/55">暂无文献，可上传 PDF、Markdown 或 TXT 文件。</p>
        )}
        {docs.map((doc) => (
          <div key={doc.title} className="flex min-h-20 items-center justify-between gap-4 border-b border-foreground/8 py-4 last:border-b-0">
            <div className="min-w-0">
              <p className="break-words text-[15px] font-medium">{doc.title}</p>
              <p className="mt-1 text-[12px] text-foreground/55">
                {formatLibrarySource(doc.source_type)} · {new Date(doc.added_at).toLocaleString("zh-CN")}
              </p>
            </div>
            <button
              type="button"
              disabled={deleting === doc.title}
              onClick={() => void handleDelete(doc.title)}
              className="shrink-0 rounded-md px-3 py-2 text-[12px] text-error hover:bg-error/10 disabled:cursor-wait disabled:opacity-50"
            >
              {deleting === doc.title ? "删除中..." : "删除"}
            </button>
          </div>
        ))}
      </div>
    </main>
  );
}

function formatLibrarySource(sourceType: string) {
  const labels: Record<string, string> = {
    arxiv: "arXiv",
    pdf: "PDF",
    markdown: "Markdown",
    text: "文本",
    upload: "上传",
  };
  return labels[sourceType] || sourceType;
}

function HeroSection({
  onSubmit,
  sending,
}: {
  onSubmit: (q: string) => void;
  sending?: boolean;
}) {
  const [showSubtitle, setShowSubtitle] = useState(false);
  const className = ["flex flex-1 flex-col items-center w-full", sending ? "hero-exit" : ""].join(" ");

  return (
    <div className={className}>
      <div className="flex flex-1 flex-col items-center justify-center">
        <h1 className="text-4xl font-medium w-full text-center">
          <StreamingText text="Deep Research" mode="typewriter" speed="slow" pause={350} onComplete={() => setShowSubtitle(true)} />
        </h1>
        <div
          className={[
            "w-full overflow-hidden transition-all duration-1000 ease-[cubic-bezier(0.2,0.8,0.2,1)]",
            showSubtitle ? "max-h-16 opacity-100 mt-3" : "max-h-0 opacity-0 mt-0",
          ].join(" ")}
        >
          <p className="text-lg text-foreground/65 tracking-wide text-center pl-[1.1em]">
            输入一个研究问题，开始探索。
          </p>
        </div>
      </div>
      <div className="w-full flex justify-center pb-8">
        <QueryInput onSubmit={onSubmit} disabled={sending} />
      </div>
    </div>
  );
}

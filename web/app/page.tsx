"use client";

import { useEffect, useRef, useState } from "react";
import AuthOverlay from "@/components/AuthOverlay";
import ChatSidebar from "@/components/ChatSidebar";
import ChatWorkspace from "@/components/ChatWorkspace";
import ReportView from "@/components/ReportView";
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
import type { ResearchStats } from "@/components/ResearchProgress";

type MainMode = "chat" | "library";

interface SelectedReport {
  taskId: string | null;
  versionId: string | null;
  reportFileId: string | null;
  title: string;
  content: string;
}

export default function Home() {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<UserInfo | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [mode, setMode] = useState<MainMode>("chat");
  const [selectedDetail, setSelectedDetail] = useState<ChatSessionDetail | null>(null);
  const [sessionLoading, setSessionLoading] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [workspaceGeneration, setWorkspaceGeneration] = useState(0);
  const [selectedReport, setSelectedReport] = useState<SelectedReport | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [stats, setStats] = useState<ResearchStats | null>(null);
  const [reportWidth, setReportWidth] = useState(45);
  const [isResizingReport, setIsResizingReport] = useState(false);
  const splitRef = useRef<HTMLDivElement>(null);
  const sessionLoadRef = useRef(0);
  const currentSessionRef = useRef<string | null>(null);

  useEffect(() => {
    currentSessionRef.current = currentSessionId;
  }, [currentSessionId]);

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
    try {
      const items = await listSessions(nextToken);
      setSessions(items);
    } catch {
      // Keep the current workspace usable when refreshing the sidebar fails.
    }
  }

  function handleAuthenticated(nextToken: string, nextUser: UserInfo) {
    window.localStorage.setItem("sage_token", nextToken);
    setToken(nextToken);
    setUser(nextUser);
    refreshSessions(nextToken);
  }

  function resetWorkspace() {
    sessionLoadRef.current += 1;
    setSessionLoading(false);
    setMode("chat");
    setCurrentSessionId(null);
    currentSessionRef.current = null;
    setSelectedDetail(null);
    setWorkspaceGeneration((value) => value + 1);
    setSelectedReport(null);
    setReportOpen(false);
    setStats(null);
  }

  function handleLogout() {
    window.localStorage.removeItem("sage_token");
    setToken(null);
    setUser(null);
    setSessions([]);
    resetWorkspace();
  }

  function handleNewChat() {
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
    if (currentSessionId === id || selectedDetail?.id === id) {
      resetWorkspace();
    }
    await refreshSessions();
  }

  async function handleSelectSession(id: string, openReport = false) {
    if (!token) return;
    setWorkspaceGeneration((value) => value + 1);
    const loadId = ++sessionLoadRef.current;
    setSessionLoading(true);
    let detail: ChatSessionDetail;
    try {
      detail = await getSession(id, token);
    } catch (cause) {
      if (loadId === sessionLoadRef.current) setSessionLoading(false);
      if (loadId !== sessionLoadRef.current) return;
      window.alert(cause instanceof Error ? cause.message : "读取聊天详情失败");
      return;
    }
    if (loadId !== sessionLoadRef.current) return;
    setSessionLoading(false);
    setMode("chat");
    setSelectedDetail(detail);
    setCurrentSessionId(detail.id);
    currentSessionRef.current = detail.id;
    setStats(null);
    const latest = latestReport(detail);
    if (latest) setSelectedReport(latest);
    else setSelectedReport(null);
    if (openReport && latest) {
      setReportOpen(true);
    }
  }

  function handleOpenLibrary() {
    sessionLoadRef.current += 1;
    setSessionLoading(false);
    setMode("library");
    refreshSessions();
  }

  function handleCloseReport() {
    setReportOpen(false);
  }

  function handleReportReady(event: { task_id?: string; version_id?: string; report_version_id?: string; report_file_id?: string; title?: string; report: string }) {
    const title = event.title || reportTitle(event.report);
    setSelectedReport({
      taskId: event.task_id || null,
      versionId: event.report_version_id || event.version_id || null,
      reportFileId: event.report_file_id || null,
      title,
      content: event.report,
    });
    setReportOpen(true);
  }

  function handleTurnComplete(id: string | null) {
    if (!id || !token) return;
    void refreshSessions();
    getSession(id, token).then((detail) => {
      if (currentSessionRef.current !== id) return;
      setSelectedDetail(detail);
      const latest = latestReport(detail);
      setSelectedReport((current) => current || latest);
    }).catch(() => undefined);
  }

  function selectTask(taskId: string) {
    const task = selectedDetail?.tasks?.find((item) => item.id === taskId);
    if (!task) return;
    const version = task.versions.find((item) => item.id === task.current_version_id) || task.versions.at(-1);
    if (version) setSelectedReport({
      taskId: task.id,
      versionId: version.id,
      reportFileId: version.report_file_id,
      title: version.title || task.title,
      content: version.content,
    });
  }

  function selectVersion(versionId: string) {
    const task = selectedDetail?.tasks?.find((item) => item.id === selectedReport?.taskId);
    const version = task?.versions.find((item) => item.id === versionId);
    if (task && version) setSelectedReport({
      taskId: task.id,
      versionId: version.id,
      reportFileId: version.report_file_id,
      title: version.title || task.title,
      content: version.content,
    });
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
  const reportReady = reportOpen && Boolean(selectedReport?.content);
  const tasks = selectedDetail?.tasks || [];
  const selectedTask = tasks.find((task) => task.id === selectedReport?.taskId);

  return (
    <>
      {authenticated && user && (
        <>
          <div className="app-shell flex h-screen w-full overflow-hidden">
            <ChatSidebar
              sessions={sessions}
              selectedSessionId={currentSessionId}
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
                ) : sessionLoading ? (
                  <div className="flex h-full items-center justify-center text-[14px] text-foreground/55">正在读取对话...</div>
                ) : (
                  <ChatWorkspace
                    key={`${selectedDetail?.id || "new"}-${workspaceGeneration}`}
                    detail={selectedDetail}
                    token={token!}
                    hasReport={Boolean(selectedReport || selectedDetail?.report || selectedDetail?.report_file_id)}
                    selectedTaskId={selectedReport?.taskId || selectedDetail?.active_task_id || null}
                    selectedReportVersionId={selectedReport?.versionId || null}
                    onSession={(id) => {
                      setCurrentSessionId(id);
                      currentSessionRef.current = id;
                      void refreshSessions();
                    }}
                    onReport={handleReportReady}
                    onStats={setStats}
                    onTurnComplete={handleTurnComplete}
                    onOpenReport={() => setReportOpen(true)}
                  />
                )}
              </div>

              {reportReady && selectedReport && (
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
                    <div className="border-b border-foreground/8 bg-surface px-4 py-3">
                      <div className="flex flex-wrap gap-2">
                        {tasks.length > 0 && (
                          <label className="min-w-0 flex-1">
                            <span className="sr-only">研究任务</span>
                            <select
                              value={selectedTask?.id || ""}
                              onChange={(event) => selectTask(event.target.value)}
                              className="w-full rounded-md border border-foreground/12 bg-background px-2.5 py-2 text-[12px] outline-none focus:border-accent/45"
                            >
                              {tasks.map((task) => <option key={task.id} value={task.id}>{task.title}</option>)}
                            </select>
                          </label>
                        )}
                        {selectedTask && selectedTask.versions.length > 0 && (
                          <label className="w-28 shrink-0">
                            <span className="sr-only">报告版本</span>
                            <select
                              value={selectedReport.versionId || selectedTask.current_version_id || ""}
                              onChange={(event) => selectVersion(event.target.value)}
                              className="w-full rounded-md border border-foreground/12 bg-background px-2.5 py-2 text-[12px] outline-none focus:border-accent/45"
                            >
                              {selectedTask.versions.map((version, index) => (
                                <option key={version.id} value={version.id}>
                                  {`V${version.version_number || index + 1} · ${version.title || selectedTask.title}`}
                                </option>
                              ))}
                            </select>
                          </label>
                        )}
                      </div>
                    </div>
                    <ReportView
                      report={selectedReport.content}
                      stats={stats}
                      reportFileId={selectedReport.reportFileId}
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

function LibraryMain({ token }: { token: string }) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [docs, setDocs] = useState<LibraryDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
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

function latestReport(detail: ChatSessionDetail): SelectedReport | null {
  const tasks = detail.tasks || [];
  const activeTask = tasks.find((task) => task.id === detail.active_task_id);
  const orderedTasks = activeTask
    ? [activeTask, ...tasks.filter((task) => task.id !== activeTask.id)]
    : [...tasks].reverse();
  for (const task of orderedTasks) {
    const version = task.versions.find((item) => item.id === task.current_version_id) || task.versions.at(-1);
    if (version) return {
      taskId: task.id,
      versionId: version.id,
      reportFileId: version.report_file_id,
      title: version.title || task.title,
      content: version.content,
    };
  }
  if (detail.report) return {
    taskId: null,
    versionId: null,
    reportFileId: detail.report.report_file_id,
    title: detail.report.title,
    content: detail.report.content,
  };
  return null;
}

function reportTitle(report: string) {
  return report.match(/^#\s+(.+)$/m)?.[1]?.trim() || "研究报告";
}

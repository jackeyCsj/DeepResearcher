"use client";

import { useRef, useState } from "react";
import type { ChatSessionSummary } from "@/lib/api";

export default function ChatSidebar({
  sessions,
  selectedSessionId,
  mode,
  onNewChat,
  onSelectSession,
  onOpenLibrary,
}: {
  sessions: ChatSessionSummary[];
  selectedSessionId: string | null;
  mode: "chat" | "library";
  onNewChat: () => void;
  onSelectSession: (sessionId: string) => void;
  onOpenLibrary: () => void;
}) {
  const [width, setWidth] = useState(276);
  const draggingRef = useRef(false);

  function startDrag() {
    draggingRef.current = true;
    const onMove = (e: MouseEvent) => {
      if (!draggingRef.current) return;
      setWidth(Math.min(440, Math.max(220, e.clientX)));
    };
    const onUp = () => {
      draggingRef.current = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }

  return (
    <aside
      className="relative shrink-0 bg-surface/55 border-r border-foreground/8 flex flex-col min-h-0"
      style={{ width }}
    >
      <div className="px-4 pt-5 pb-3">
        <button
          onClick={onNewChat}
          className="w-full rounded-xl bg-foreground text-surface px-3 py-2 text-[13px] hover:opacity-90 active:scale-[0.98]"
        >
          新建调研
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto thin-scroll px-3 pb-3">
        <p className="px-1 pb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">聊天记录</p>
        {sessions.length === 0 && (
          <p className="px-1 py-3 text-[13px] text-muted-foreground">暂无历史记录</p>
        )}
        {sessions.map((session) => {
          const active = mode === "chat" && selectedSessionId === session.id;
          return (
            <button
              key={session.id}
              onClick={() => onSelectSession(session.id)}
              className={`mb-1.5 w-full rounded-xl px-3 py-2.5 text-left transition-colors ${
                active ? "bg-foreground text-surface" : "hover:bg-background/70"
              }`}
            >
              <p className="truncate text-[14px] font-medium">{session.title}</p>
              <p className={`mt-1 truncate text-[12px] ${active ? "text-surface/65" : "text-muted-foreground"}`}>
                {session.status === "report_ready" ? "报告已生成" : session.status}
              </p>
            </button>
          );
        })}
      </div>

      <div className="border-t border-foreground/8 p-3">
        <button
          onClick={onOpenLibrary}
          className={`w-full rounded-xl px-3 py-2.5 text-[13px] transition-colors ${
            mode === "library" ? "bg-foreground text-surface" : "bg-surface hover:bg-background/70"
          }`}
        >
          文献库
        </button>
      </div>

      <div
        onMouseDown={startDrag}
        className="absolute right-0 top-0 h-full w-1 cursor-col-resize hover:bg-accent/30"
      />
    </aside>
  );
}

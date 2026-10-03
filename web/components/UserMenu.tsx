"use client";

import type { UserInfo } from "@/lib/api";

export default function UserMenu({ user, onLogout }: { user: UserInfo; onLogout: () => void }) {
  return (
    <div className="absolute left-7 top-7 z-40 flex items-center gap-3 rounded-2xl border border-foreground/10 bg-surface/90 px-3 py-2 shadow-sm backdrop-blur-sm">
      <div className="text-right">
        <p className="text-[13px] font-medium leading-none">{user.display_name}</p>
        <p className="mt-1 text-[11px] text-muted-foreground leading-none">@{user.username}</p>
      </div>
      <button
        onClick={onLogout}
        className="rounded-lg border border-foreground/10 px-2.5 py-1.5 text-[12px] text-foreground/65 hover:text-error hover:border-error/30"
      >
        退出
      </button>
    </div>
  );
}

"use client";

import type { UserInfo } from "@/lib/api";

export default function UserMenu({ user, onLogout }: { user: UserInfo; onLogout: () => void }) {
  return (
    <div className="flex min-w-0 shrink-0 items-center gap-2 rounded-md border border-foreground/10 bg-surface px-2 py-1.5 sm:gap-3 sm:px-3">
      <div className="min-w-0 text-right">
        <p className="max-w-24 truncate text-[12px] font-medium leading-none sm:max-w-36 sm:text-[13px]">{user.display_name}</p>
        <p className="mt-1 hidden truncate text-[11px] leading-none text-muted-foreground sm:block">@{user.username}</p>
      </div>
      <button
        type="button"
        onClick={onLogout}
        className="shrink-0 rounded border border-foreground/10 px-2 py-1 text-[11px] text-foreground/65 transition-colors hover:border-error/30 hover:text-error sm:px-2.5 sm:py-1.5 sm:text-[12px]"
      >
        退出
      </button>
    </div>
  );
}

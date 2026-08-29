"use client";

import { useState } from "react";
import { login, register, type UserInfo } from "@/lib/api";

export default function AuthOverlay({
  onAuthenticated,
}: {
  onAuthenticated: (token: string, user: UserInfo) => void;
}) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const result =
        mode === "login"
          ? await login(username.trim(), password)
          : await register(username.trim(), password);
      onAuthenticated(result.access_token, result.user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center bg-background/80 pt-14 backdrop-blur-sm">
      <form onSubmit={handleSubmit} className="w-full max-w-sm rounded-2xl bg-surface px-7 py-6 shadow-xl border border-foreground/10">
        <div className="mb-5">
          <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-muted-foreground">SAGE Research</p>
          <h2 className="mt-2 text-2xl font-medium">{mode === "login" ? "登录后继续" : "创建账号"}</h2>
          <p className="mt-1 text-[14px] text-foreground/55">登录后会按用户隔离聊天记录和调研报告。</p>
        </div>

        <label className="block text-[13px] text-foreground/60 mb-1">用户名</label>
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className="w-full rounded-xl bg-input-bg border border-foreground/10 px-3 py-2.5 text-[14px] outline-none focus:border-accent"
          autoComplete="username"
          minLength={3}
          required
        />

        <label className="block text-[13px] text-foreground/60 mb-1 mt-3">密码</label>
        <input
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded-xl bg-input-bg border border-foreground/10 px-3 py-2.5 text-[14px] outline-none focus:border-accent"
          type="password"
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          minLength={6}
          required
        />

        {error && <p className="mt-3 text-[13px] text-error">{error}</p>}

        <button
          type="submit"
          disabled={loading}
          className="mt-5 w-full rounded-xl bg-foreground px-4 py-2.5 text-[14px] text-surface hover:opacity-90 disabled:opacity-50"
        >
          {loading ? "处理中..." : mode === "login" ? "登录" : "注册并登录"}
        </button>

        <button
          type="button"
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError("");
          }}
          className="mt-3 w-full text-[13px] text-muted-foreground hover:text-foreground"
        >
          {mode === "login" ? "还没有账号？注册" : "已有账号？登录"}
        </button>
      </form>
    </div>
  );
}

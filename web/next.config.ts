import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  devIndicators: false,
  // 研究是昂贵且非幂等的长任务：StrictMode 会把 effect 跑两遍，
  // 导致每次提问建两个会话、每轮研究真的跑两遍（双倍 LLM 消耗）。
  // 这里关掉，从源头消除重复请求。注意：改这里需要重启 dev server 才生效。
  reactStrictMode: false,
};

export default nextConfig;

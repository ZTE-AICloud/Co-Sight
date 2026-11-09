// SPDX-License-Identifier: Apache-2.0
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Target `127.0.0.1` rather than `localhost`: when several listeners
// exist on the same port across IP families (loopback-specific SSH binds vs.
// Node's wildcard listen), macOS routes connections by socket specificity,
// so `localhost` can resolve into the wrong process. An explicit IPv4 loopback
// is what the embedded server in production binds to anyway.
const DASHBOARD_PORT = parseInt(process.env.DASHBOARD_PORT || "4830", 10);

// Agent Runtime 目标地址（仅本 dev server 的 proxy 使用）
// 默认指向本机，配合本地 Mock 服务开箱即用；要连其他环境用环境变量覆盖：
//   AGENT_RUNTIME_HOST=<host> AGENT_RUNTIME_PORT=<port> npm run dev
const AGENT_RUNTIME_HOST = process.env.AGENT_RUNTIME_HOST || "127.0.0.1";
const AGENT_RUNTIME_PORT = process.env.AGENT_RUNTIME_PORT || "15907";
const AGENT_RUNTIME_HTTP = `http://${AGENT_RUNTIME_HOST}:${AGENT_RUNTIME_PORT}`;
const AGENT_RUNTIME_WS = `ws://${AGENT_RUNTIME_HOST}:${AGENT_RUNTIME_PORT}`;

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // 使用相对路径，前端会在 index.html 的实际 URL 下自动解析资源路径
  base: "./",
  define: {
    // 构建时注入 API base path，供 dev 模式（无服务端注入）使用
    __DEV_API_BASE__: JSON.stringify(
      mode !== "production" ? `http://127.0.0.1:${DASHBOARD_PORT}` : ""
    ),
  },
  server: {
    port: 5183,
    proxy: {
      // Agent Runtime WebSocket 代理（必须在 /api/agent-runtime 之前，否则被 REST 代理拦截）
      "/api/agent-runtime/v1/ws": {
        target: AGENT_RUNTIME_WS,
        ws: true,
        changeOrigin: true,
      },
      // Agent Runtime API 代理
      "/api/agent-runtime": {
        target: AGENT_RUNTIME_HTTP,
        changeOrigin: true,
      },
      // 代理 /api/cosight-viewer 到后端（开发环境跨端口）
      "/api/cosight-viewer": {
        target: `http://127.0.0.1:${DASHBOARD_PORT}`,
        changeOrigin: true,
      },
      // WebSocket 代理
      "/api/cosight-viewer/v1/ws": {
        target: `ws://127.0.0.1:${DASHBOARD_PORT}`,
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
}));

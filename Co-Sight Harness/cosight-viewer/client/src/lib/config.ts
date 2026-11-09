// SPDX-License-Identifier: Apache-2.0
/**
 * @file config.ts
 * @description 应用配置常量，根据运行场景动态确定 API 基础路径。
 *
 * 优先级：
 *   1. window.__API_BASE__ — 服务端注入（生产环境，零延迟）
 *   2. __DEV_API_BASE__ — Vite define（开发环境，构建时确定）
 */

// Vite 构建时注入（见 vite.config.ts define）
declare const __DEV_API_BASE__: string | undefined;

// 服务端 HTML 注入（见 server/index.js）
declare global {
  interface Window {
    __API_BASE__?: string;
  }
}

function resolveApiBase(): string {
  // 1. 服务端注入（生产环境）
  if (typeof window !== "undefined" && typeof window.__API_BASE__ === "string") {
    return window.__API_BASE__;
  }
  // 2. Vite define（开发环境）
  if (typeof __DEV_API_BASE__ !== "undefined" && __DEV_API_BASE__) {
    return __DEV_API_BASE__;
  }
  // 3. 兜底：相对根路径
  return "";
}

export const API_BASE = resolveApiBase();

// WebSocket 路径（相对于 API_BASE 所在 origin）
export const WS_PATH = "/ws";

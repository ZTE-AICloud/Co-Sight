// SPDX-License-Identifier: Apache-2.0
/**
 * @file api-config.ts
 * @description 会话服务（smart-factory）地址配置
 *
 * REST **走 viewer 的同源反代**：`/api/smart-factory/v1` 由 viewer 服务端
 * （4830）转发到 `127.0.0.1:4100`。浏览器只访问 iframe 自己的源，不存在跨源，
 * 也不依赖“当前主机是不是 localhost”。
 *
 * WebSocket 同样走 viewer 的同源反代：`/api/smart-factory/v1/ws` 由 viewer 服务端
 * 以裸 TCP 转发到 `127.0.0.1:4100`，浏览器不再直连回环地址。
 */

/** viewer 自己的源；SSR/构建期没有 window 时返回空串，退回相对路径。 */
function viewerOrigin(): string {
  if (typeof window === "undefined" || !window.location) return "";
  const origin = window.location.origin;
  return origin && origin !== "null" ? origin : "";
}

/** REST/WS 共用的接口前缀（与 `smart-factory/server/src/app.ts` 的挂载点一致）。 */
const API_PREFIX = "/api/smart-factory/v1";

/** 会话服务的 HTTP 基地址（同源反代） */
export const AGENT_RUNTIME_API_URL = `${viewerOrigin()}${API_PREFIX}`;

/**
 * 会话服务的 WebSocket 入口（同源反代）。
 *
 * 保持**相对路径**，由 `chat-socket.ts` 按当前页面 origin 拼成
 * `ws(s)://<当前主机>/api/smart-factory/v1/ws`，局域网/远程访问也走同一主机。
 */
export const AGENT_RUNTIME_WS_URL = `${API_PREFIX}/ws`;

/** 认证 Token（smart-factory 无鉴权；保留常量以兼容现有请求封装） */
export const AGENT_RUNTIME_TOKEN = "admin";

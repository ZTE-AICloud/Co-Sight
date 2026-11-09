// SPDX-License-Identifier: Apache-2.0
/**
 * @file fs-api.ts
 * @description 会话文件只读预览（**cosight-viewer 自己的 server**）。
 *
 * 浏览器不能直接读本机文件，必须由 viewer 的 Node 服务代读：
 * - `GET {API_BASE}/session-files/read?path=<绝对路径>` → UTF-8 文本
 * - `GET {API_BASE}/session-files/raw/<路径分段>` → 原始字节流（图片 / 下载）
 *
 * 不再调用 smart-factory 的 `/fs/*`：文件读取归 viewer 自己，会话服务只负责
 * 会话与消息。服务端实现见 `server/routes/session-files.js`。
 */

import { API_BASE } from "../lib/config";
import { requestBareJson } from "./bare-json";

export interface FsFile {
  path: string;
  name: string;
  size: number;
  mtime: string;
  content: string;
}

/** API_BASE 可能是服务端注入的绝对地址，也可能是空串（相对根路径）。 */
const BASE = API_BASE.replace(/\/+$/, "");

export interface ResolveItem {
  /** 正文里的原始路径（相对或绝对） */
  path: string;
  /** 候选根：按顺序尝试，取第一个真实存在的文件 */
  roots: string[];
}

export interface ResolveResult {
  path: string;
  /** 真实绝对路径；不存在 / 无法解析为 null */
  resolved: string | null;
}

export const fsApi = {
  read(path: string): Promise<FsFile> {
    const search = new URLSearchParams({ path });
    return requestBareJson<FsFile>(`${BASE}/session-files/read?${search.toString()}`);
  },

  /**
   * 批量把正文里的相对路径解析成真实文件。
   *
   * 相对路径的基准**不一定**是会话 cwd（可能是 agent 根 / `development/` / 工作区根），
   * 所以由服务端按候选根依次尝试，只返回真实存在的那个。一次问一批，避免逐链接请求。
   */
  async resolve(items: ResolveItem[]): Promise<ResolveResult[]> {
    if (items.length === 0) return [];
    const body = await requestBareJson<{ items: ResolveResult[] }>(
      `${BASE}/session-files/resolve`,
      15000,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items }),
      }
    );
    return body.items;
  },

  /**
   * 原始字节流地址。路径按**分段**编码：HTML 里的 `./style.css` 只有这样才会
   * 落到 `/session-files/raw/.../style.css`，而不是被解析成应用根下的路径。
   *
   * Windows 盘符路径（`C:/...`）的第一段是 `C:`；服务端会识别盘符并原样使用，
   * 不会错误地补前导 `/`。
   */
  rawUrl(path: string): string {
    const segments = path.split("/").map(encodeURIComponent).join("/");
    return `${BASE}/session-files/raw${segments.startsWith("/") ? "" : "/"}${segments}`;
  },
};

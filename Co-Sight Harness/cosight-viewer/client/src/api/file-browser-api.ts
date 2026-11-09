// SPDX-License-Identifier: Apache-2.0
/**
 * @file file-browser-api.ts
 * @description 本机文件浏览（发送框「添加文件」的数据源）。
 *
 * 由 viewer 自己的 server 提供（`server/routes/fs.js`），不依赖 smart-factory：
 * 端侧单机形态下选中的是**真实绝对路径**，发送时随消息交给会话服务。
 *
 * 与 `fs-api.ts`（会话文件预览）分开：那份负责按路径读文件内容，
 * 这份只列目录，供选择器使用。
 */

import { API_BASE } from "../lib/config";

export type FsRootKind =
  "home" | "desktop" | "downloads" | "documents" | "drive" | "mount" | "root" | string;

/** 一个可浏览的根（常用目录 / 盘符 / 挂载点）。 */
export interface FsRoot {
  label: string;
  /** 真实绝对路径 */
  path: string;
  kind: FsRootKind;
}

export interface FsEntry {
  name: string;
  /** 绝对路径，选中后原样回传 */
  path: string;
  type: "dir" | "file";
  size: number;
  mtime: string;
}

export interface FsListing {
  path: string;
  /** 上一级；已在文件系统根时为 null */
  parent: string | null;
  items: FsEntry[];
  /** 目录条目超过服务端上限：`items` 只是前面一部分 */
  truncated: boolean;
}

export interface FsCapabilities {
  /** local-path = 选择器返回本机绝对路径；upload = 商用云版上传 */
  attachmentMode: "local-path" | "upload" | string;
}

/** API_BASE 可能是服务端注入的绝对地址，也可能是空串（相对根路径）。 */
const BASE = API_BASE.replace(/\/+$/, "");

export class FsApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "FsApiError";
    this.status = status;
    this.code = code;
  }
}

async function requestJson<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`);
  } catch (error) {
    throw new FsApiError(0, "NETWORK", error instanceof Error ? error.message : "网络错误");
  }

  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // 非 JSON 响应交给下面的状态码分支
  }

  if (!response.ok) {
    const error = (body as { error?: { code?: unknown; message?: unknown } } | null)?.error;
    throw new FsApiError(
      response.status,
      typeof error?.code === "string" ? error.code : "UNKNOWN",
      typeof error?.message === "string" ? error.message : `HTTP ${response.status}`,
    );
  }

  return body as T;
}

export const fileBrowserApi = {
  /** 可浏览的根：常用目录在前，盘符 / 挂载点在后。 */
  roots(): Promise<{ items: FsRoot[] }> {
    return requestJson<{ items: FsRoot[] }>("/fs/roots");
  },

  /**
   * 列一层目录；不传 path 时由服务端退回主目录。
   *
   * `root` 是**浏览边界**（会话工作区）：传了它，服务端会拒绝 `root` 之外的路径，
   * 不传则保持原来的"整机可浏览"行为（附件选择器用）。
   */
  list(path?: string, root?: string): Promise<FsListing> {
    const params = new URLSearchParams();
    if (path !== undefined) params.set("path", path);
    if (root !== undefined) params.set("root", root);
    const search = params.toString();
    return requestJson<FsListing>(`/fs/list${search === "" ? "" : `?${search}`}`);
  },

  /** 附件来源能力：本地单机是 local-path，商用云版将来是 upload。 */
  capabilities(): Promise<FsCapabilities> {
    return requestJson<FsCapabilities>("/fs/capabilities");
  },
};

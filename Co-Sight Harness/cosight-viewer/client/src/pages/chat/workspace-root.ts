// SPDX-License-Identifier: Apache-2.0
/**
 * @file workspace-root.ts
 * @description 会话工作区根的推导：用于会话页右侧「工作区」浏览。
 *
 * 优先级（与产品约定一致）：
 * 1. 从智能体 `dir` **向前反推**：`<workspace>/.smart-factory/agents/<id>`；
 * 2. `dir` 不符合约定布局时，用 agent 自带的 `workspaceId` 向框架查目录；
 * 3. 仍拿不到（例如目录实例会话没有 agent）→ **当前默认工作区**（`/workspaces/active`）。
 *
 * 浏览范围由这个根限定（见 viewer server `/fs/list` 的 `root` 参数），
 * 不把"工作区"退化成整机文件管理器。
 */

import {
  fetchActiveWorkspaceDirectory,
  fetchWorkspaceDirectory,
} from "../../api/harness-api";
import { normalizePath } from "./useSessionFiles";

/** 智能体目录的约定布局：`<workspace>/.smart-factory/agents/<id>`。 */
const AGENT_DIR_PATTERN = /^(.+)\/\.smart-factory\/agents\/[^/]+$/;

export interface WorkspaceRootAgent {
  dir?: string;
  workspaceId?: string;
}

/**
 * 只做纯字符串推导：`dir` 符合约定布局时返回工作区目录，否则 null。
 *
 * 导出给单测；运行期请用 `resolveWorkspaceRoot`（含网络兜底）。
 */
export function workspaceRootFromAgentDir(dir: string | undefined): string | null {
  if (dir === undefined || dir.trim() === "") return null;
  const normalized = normalizePath(dir).replace(/\/+$/, "");
  const match = AGENT_DIR_PATTERN.exec(normalized);
  return match?.[1] ?? null;
}

/**
 * 解析会话工作区根；agent 为空（目录实例会话 / 尚未选智能体）时直接用当前默认工作区。
 *
 * 任何一步失败都不抛错：拿不到就返回 null，由面板显示"无法确定工作区"，
 * 不能因为一次可选查询失败把整个对话页弄崩。
 */
export async function resolveWorkspaceRoot(
  agent: WorkspaceRootAgent | null | undefined
): Promise<string | null> {
  const derived = workspaceRootFromAgentDir(agent?.dir);
  if (derived !== null) return derived;

  if (agent?.workspaceId !== undefined && agent.workspaceId !== "") {
    const byId = await fetchWorkspaceDirectory(agent.workspaceId);
    if (byId !== null && byId.trim() !== "") return normalizePath(byId);
  }

  const active = await fetchActiveWorkspaceDirectory();
  return active !== null && active.trim() !== "" ? normalizePath(active) : null;
}

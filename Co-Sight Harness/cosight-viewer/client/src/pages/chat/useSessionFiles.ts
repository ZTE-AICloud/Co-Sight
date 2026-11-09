// SPDX-License-Identifier: Apache-2.0
/**
 * @file useSessionFiles.ts
 * @description 本次对话产生/修改的文件（v1：只认 Write/Edit 系工具）。
 *
 * ## 判定逻辑
 *
 * 唯一的结构化信号是工具调用流（实时 `tool.executed` 事件、历史 `messages/list`
 * 的 `tool_use` / `tool_result` 消息）。规则：
 *
 * ```
 * 工具名 ∈ { Write, Edit, MultiEdit, NotebookEdit }
 * 且结果成功（非 pending、非 error）
 * 且 input 里有 file_path / path / notebook_path
 * ```
 *
 * 同一路径按出现顺序去重，保留最后一次；`Write` 标“写入”、`Edit` 系标“修改”。
 * 正在执行中的写入（`toolExecutions`）也会进来，标 `writing`，让用户能看到
 * “过程”；失败/中止后它自然消失。
 *
 * ## 已知不覆盖
 *
 * - `Bash` 里的 `> out.html`、`python gen.py` 等脚本写入；
 * - MCP 工具写文件。
 *
 * 这两类要靠后续的 mtime 兜底（v2），本期不做。
 *
 * ## runtime 根
 *
 * 优先用服务端给的 `runtimeDir`（`GET /agents` / `GET /agents/{id}` 的字段）——
 * 它就是会话的 cwd，相对路径的口径与引擎完全一致。
 * 老响应没有该字段时回退：普通智能体 `<agent.dir>/development/<product.path>`
 * （`product.path` 来自 `GET /agents/{id}/production`，形如 `output/agents/<name>/v3`）；
 * 内置智能体 `<agent.dir>` 本身。
 *
 * 根只用于两件事：把相对路径补成绝对路径、判断文件是否在产物目录内
 * （在根内走 `artifacts/*`，根外走 `fs/*`）。拿不到根时不影响列表展示，
 * 只是所有文件都按“根外”预览。
 */

import { useEffect, useMemo, useState } from "react";

import { fetchAgentProduction } from "../../api/harness-api";
import type { ChatMessage, ToolExecution } from "./useChatSession";

/** 会产生文件写入的工具。TodoWrite 没有路径字段，自然不会被命中。 */
const WRITE_TOOLS = new Set(["Write", "Edit", "MultiEdit", "NotebookEdit"]);

const PATH_KEYS = ["file_path", "path", "notebook_path"] as const;

export interface SessionFile {
  /** 归一化后的绝对路径（拿不到根时可能是原始相对路径 / `~/...`） */
  path: string;
  name: string;
  /** 写入 or 修改；`Write` 可能是覆盖，不武断叫“新建” */
  change: "written" | "modified";
  tool: string;
  /** 毫秒时间戳；执行中的写入用 `Number.MAX_SAFE_INTEGER` 排到最后 */
  at: number;
  /** 仍在执行 */
  writing: boolean;
  /** 是否落在 runtime 根内 */
  inRoot: boolean;
  /** 相对 runtime 根的路径；根外为 null */
  relativePath: string | null;
}

/**
 * 路径归一化：去 `file://`、解一次百分号编码、统一 `/`、收掉重复分隔符。
 *
 * Windows 的 `file:///C:/...` 解出来会多一个前导 `/`，这里顺手去掉盘符前的那个。
 */
export function normalizePath(raw: string): string {
  let path = raw.trim();
  if (path === "") return "";
  if (path.startsWith("file://")) path = path.slice("file://".length);
  try {
    path = decodeURIComponent(path);
  } catch {
    // 不是合法百分号编码：保留原文，交给后端 400 / 404
  }
  path = path.replace(/\\/g, "/");
  path = path.replace(/^\/(?=[A-Za-z]:\/)/, "");
  // UNC 路径（`//server/share`）开头的双斜杠要保留，只收中间的重复分隔符
  if (path.startsWith("//")) {
    path = `//${path.slice(2).replace(/\/{2,}/g, "/")}`;
  } else {
    path = path.replace(/\/{2,}/g, "/");
  }
  return path;
}

/** 去重键：Windows 盘符路径大小写不敏感；其余平台保持原样。 */
export function pathKey(path: string): string {
  return /^[A-Za-z]:\//.test(path) ? path.toLowerCase() : path;
}

function baseNameOf(path: string): string {
  const index = path.lastIndexOf("/");
  return index < 0 ? path : path.slice(index + 1);
}

function isAbsolutePath(path: string): boolean {
  return path.startsWith("/") || /^[A-Za-z]:\//.test(path) || path === "~" || path.startsWith("~/");
}

/**
 * 工具给的路径 → 可比较的绝对路径。
 *
 * 绝对路径（含 `~`）原样返回；相对路径在拿到 runtime 根时拼到根下，
 * 拿不到根时保留原样（预览会退回 `/fs/read`，由后端给出 400/404）。
 */
export function resolveSessionPath(raw: string, root: string | null): string {
  const normalized = normalizePath(raw);
  if (normalized === "" || isAbsolutePath(normalized) || root === null) return normalized;
  return normalizePath(`${root}/${normalized}`);
}

/**
 * 正文里相对链接的候选基准（按优先级从高到低）。
 *
 * 相对路径是自由文本，基准**不一定**是会话 cwd：模型常按 `development/` 或智能体根
 * 写路径，甚至按工作区根。这里把所有合理基准列出来，交给服务端逐个试、取真实存在的那个
 * （见 `useResolvedLinks`），而不是只赌一个。
 *
 * 工作区根由 `dir` 的固定布局反推：`<workspace>/.smart-factory/agents/<id>`
 * （与服务端 `agentRoot()` 同构）；反推不出来就不放这一项。
 */
export function agentLinkRoots(runtimeRoot: string | null, agentDir?: string): string[] {
  const roots: string[] = [];
  const push = (value: string | null | undefined) => {
    const normalized = value === undefined || value === null ? "" : normalizePath(value);
    if (normalized === "" || roots.includes(normalized)) return;
    roots.push(normalized);
  };

  push(runtimeRoot);

  const dir = agentDir === undefined ? "" : normalizePath(agentDir);
  if (dir !== "") {
    push(`${dir}/development`);
    push(dir);
    const workspace = dir.replace(/\/\.smart-factory\/agents\/[^/]+$/, "");
    if (workspace !== dir) push(workspace);
  }

  return roots;
}

/**
 * 从一条路径合成 `SessionFile`。
 *
 * 用于正文里**显式写出的绝对路径**：它可能不是 `Write/Edit` 写出来的
 * （比如 PPTX 是脚本生成的），因而不在产物集合里，但用户明确给了路径，
 * 仍然应该能点开。根信息照常按 runtime 根计算。
 */
export function sessionFileFromPath(path: string, root: string | null): SessionFile {
  const resolved = resolveSessionPath(path, root);
  return {
    path: resolved,
    name: baseNameOf(resolved),
    change: "written",
    tool: "link",
    at: Date.now(),
    writing: false,
    ...rootInfoOf(resolved, root),
  };
}

function pathOfToolInput(input: Record<string, unknown> | undefined): string | null {
  if (!input) return null;
  for (const key of PATH_KEYS) {
    const value = input[key];
    if (typeof value === "string" && value.trim() !== "") return value;
  }
  return null;
}

/** 工具消息是否是一次成功的写入；是则返回路径。 */
export function writtenPathOfMessage(message: ChatMessage): string | null {
  if (message.role !== "tool") return null;
  if (!message.toolName || !WRITE_TOOLS.has(message.toolName)) return null;
  if (message.toolPending || message.toolError) return null;
  return pathOfToolInput(message.toolInput);
}

interface RawFile {
  rawPath: string;
  change: "written" | "modified";
  tool: string;
  at: number;
  writing: boolean;
}

function changeOf(tool: string): "written" | "modified" {
  return tool === "Write" ? "written" : "modified";
}

function rootInfoOf(path: string, root: string | null): Pick<SessionFile, "inRoot" | "relativePath"> {
  if (!root) return { inRoot: false, relativePath: null };
  const prefix = `${root}/`;
  const matches = /^[A-Za-z]:\//.test(root)
    ? path.toLowerCase().startsWith(prefix.toLowerCase())
    : path.startsWith(prefix);
  if (!matches) return { inRoot: false, relativePath: null };
  return { inRoot: true, relativePath: path.slice(prefix.length) };
}

export interface UseSessionFilesInput {
  messages: ChatMessage[];
  toolExecutions: ToolExecution[];
  agentId: string | null;
  agentDir?: string;
  /**
   * 服务端现算的 runtime 工作目录（`Agent.runtimeDir`）。会话的 cwd 就是它，
   * 所以相对路径直接以它为根 —— 比 `dir + /production` 推导更准，也少一次请求。
   */
  agentRuntimeDir?: string;
  agentSource?: string;
}

export interface UseSessionFilesResult {
  files: SessionFile[];
  runtimeRoot: string | null;
}

export function useSessionFiles({
  messages,
  toolExecutions,
  agentId,
  agentDir,
  agentRuntimeDir,
  agentSource,
}: UseSessionFilesInput): UseSessionFilesResult {
  const [runtimeRoot, setRuntimeRoot] = useState<string | null>(null);

  // 换智能体就重算 root；内置智能体不走 /production（那接口对它返回 409）
  useEffect(() => {
    setRuntimeRoot(null);

    // 服务端已经给出 runtime 目录（会话 cwd）时直接用它：同步、无额外请求，
    // 也不受 /production 在产物未就绪时返回空的影响。
    if (agentRuntimeDir !== undefined && agentRuntimeDir !== "") {
      const normalizedRuntimeDir = normalizePath(agentRuntimeDir);
      if (normalizedRuntimeDir !== "") {
        setRuntimeRoot(normalizedRuntimeDir);
        return;
      }
    }

    if (!agentId || !agentDir) return;

    const normalizedDir = normalizePath(agentDir);
    if (agentSource === "builtin") {
      setRuntimeRoot(normalizedDir);
      return;
    }

    let cancelled = false;
    void fetchAgentProduction(agentId).then((production) => {
      if (cancelled) return;
      const relative = production?.product?.path;
      if (!relative) return;
      setRuntimeRoot(normalizePath(`${normalizedDir}/development/${relative}`));
    });
    return () => {
      cancelled = true;
    };
  }, [agentId, agentDir, agentRuntimeDir, agentSource]);

  const rawFiles = useMemo<RawFile[]>(() => {
    const collected: RawFile[] = [];

    for (const message of messages) {
      const rawPath = writtenPathOfMessage(message);
      if (rawPath === null || !message.toolName) continue;
      collected.push({
        rawPath,
        change: changeOf(message.toolName),
        tool: message.toolName,
        at: message.timestamp,
        writing: false,
      });
    }

    // 正在执行中的写入：结果还没到，先展示“写入中”
    for (const execution of toolExecutions) {
      if (!WRITE_TOOLS.has(execution.toolName)) continue;
      const rawPath = pathOfToolInput(execution.input);
      if (rawPath === null) continue;
      collected.push({
        rawPath,
        change: changeOf(execution.toolName),
        tool: execution.toolName,
        at: Number.MAX_SAFE_INTEGER,
        writing: true,
      });
    }

    return collected;
  }, [messages, toolExecutions]);

  const files = useMemo<SessionFile[]>(() => {
    const byKey = new Map<string, SessionFile>();

    for (const raw of rawFiles) {
      const path = resolveSessionPath(raw.rawPath, runtimeRoot);
      if (path === "") continue;
      const key = pathKey(path);
      const file: SessionFile = {
        path,
        name: baseNameOf(path),
        change: raw.change,
        tool: raw.tool,
        at: raw.at,
        writing: raw.writing,
        ...rootInfoOf(path, runtimeRoot),
      };

      const existing = byKey.get(key);
      /*
       * 已完成优先于“写入中”；同类里后到的覆盖先到的。执行中的条目时间戳是
       * MAX_SAFE_INTEGER，不能直接按时间比较，所以先看 writing。
       */
      if (
        existing === undefined ||
        (existing.writing && !file.writing) ||
        (existing.writing === file.writing && file.at >= existing.at)
      ) {
        byKey.set(key, file);
      }
    }

    return [...byKey.values()].sort((left, right) => left.at - right.at);
  }, [rawFiles, runtimeRoot]);

  return { files, runtimeRoot };
}

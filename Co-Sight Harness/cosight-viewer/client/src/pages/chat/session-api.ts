// SPDX-License-Identifier: Apache-2.0
/**
 * @file session-api.ts
 * @description `/chat` 恢复会话时的会话查询与反查（smart-factory）。
 *
 * 服务端实际路径（`smart-factory/server/docs/04-api/4.03-会话.md` §4 / §6）：
 * - 查询：`GET /sessions/detail?sessionId=…`
 * - 反查：`GET /sessions/list?resumeSessionId=…`（按引擎 resume 标识找会话）
 *
 * 响应是**裸 JSON**（`Session` / `{ items, total }`），没有 agent-runtime 的
 * `{ code, message, data }` 信封 —— 所以这里不走 `api/agent-api.ts` 的 `fetchApi`。
 *
 * 取不到时一律返回 `null`：恢复会话不因这次查询而失败，它只用来把界面还原得更准。
 */

import { AGENT_RUNTIME_API_URL } from "../../config/api-config";

/**
 * smart-factory `Session` 里本模块用得到的那几项（`4.03-会话.md` §3.1）。
 *
 * 服务端以后加字段不影响这里；`agentId` 只在 `instance` 上，不在顶层。
 */
interface ServiceSession {
  id: string;
  modelId: string;
  /** 引擎 resume 标识；`null` 表示还没起过 run。 */
  resumeSessionId: string | null;
  /** 会话级审批模式。 */
  mode: string;
  /** 会话级推理强度。 */
  effort: string;
  instance: { agentId: string | null };
}

/** `/chat` 恢复会话时需要的会话信息。 */
export interface ChatSessionDetail {
  id: string;
  /** `null` = 自由对话（目录会话，没有绑定智能体） */
  agentId: string | null;
  modelId: string;
  /** 审批模式（smart-factory 字段名是 `mode`）。 */
  approvalMode: string;
  effort: string;
  resumeSessionId: string | null;
}

/** `GET /sessions/list` 的分页响应。 */
interface ServiceSessionPage {
  items: ServiceSession[];
  total: number;
}

/**
 * `GET /messages/list` 返回的会话消息（`4.04-消息.md` §2 / §3）。
 *
 * `content` 恒为对象：`text` 是 `{ text }`，`tool_use` 是
 * `{ toolCallId, toolName, input }`，`tool_result` 是
 * `{ toolCallId, output, isError }`。与 WS `history` 拍平成字符串的形态不同 ——
 * 正是靠这几个字段才能把工具调用和结果配对、渲染成工具卡。
 */
export interface ServiceMessage {
  id: string;
  sessionId: string;
  runId: string | null;
  seq: number;
  role: string;
  type: string;
  content: Record<string, unknown>;
  createdAt: string;
}

/** `GET /messages/list` 的响应：items 一律按 seq 升序。 */
export interface ServiceMessagePage {
  items: ServiceMessage[];
  nextAfterSeq: number | null;
}

/** 超时；与 `api/harness-api.ts` 的请求封装同一口径。 */
const REQUEST_TIMEOUT_MS = 10000;

/**
 * 读一份裸 JSON。
 *
 * 非 2xx 与网络失败都返回 `null`：调用方（恢复流程）只拿它做"锦上添花"，
 * 不该因为详情查不到就把整次恢复判失败。
 */
async function requestSessionJson<T>(path: string): Promise<T | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${AGENT_RUNTIME_API_URL}${path}`, {
      method: "GET",
      signal: controller.signal,
    });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch (error) {
    console.warn(`[chat] failed to load ${path}:`, error);
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/** `Session` → 恢复流程认的形状（`agentId` 与 `mode` 是仅有的两处改名）。 */
function toChatSessionDetail(session: ServiceSession): ChatSessionDetail {
  return {
    id: session.id,
    agentId: session.instance.agentId,
    modelId: session.modelId,
    approvalMode: session.mode,
    effort: session.effort,
    resumeSessionId: session.resumeSessionId,
  };
}

/**
 * 按会话 id 取详情（含 agentId / modelId / effort / approvalMode）。
 *
 * 实际路径是 `sessions/detail?sessionId=`，不是 agent-runtime 的 `/sessions/{id}`。
 */
export async function fetchAgentRuntimeSession(
  sessionId: string
): Promise<ChatSessionDetail | null> {
  const session = await requestSessionJson<ServiceSession>(
    `/sessions/detail?sessionId=${encodeURIComponent(sessionId)}`
  );
  return session ? toChatSessionDetail(session) : null;
}

/** 详情查询的三种结果：存在 / 明确不存在 / 暂时查不到（网络或 5xx）。 */
export type AgentRuntimeSessionOutcome =
  | { status: "ok"; detail: ChatSessionDetail }
  | { status: "missing" }
  | { status: "error" };

/**
 * 带状态的详情查询：区分「会话确实不存在」与「这次没查到」。
 *
 * 恢复时需要这个区别：404 说明会话已被清理，应提示并停止；网络/5xx 只是
 * 暂时读不到，沿用旧行为（不带详情继续恢复），不能误报成“会话不存在”。
 */
export async function fetchAgentRuntimeSessionOutcome(
  sessionId: string
): Promise<AgentRuntimeSessionOutcome> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(
      `${AGENT_RUNTIME_API_URL}/sessions/detail?sessionId=${encodeURIComponent(sessionId)}`,
      { method: "GET", signal: controller.signal }
    );
    if (response.status === 404) return { status: "missing" };
    if (!response.ok) return { status: "error" };
    const session = (await response.json()) as ServiceSession;
    return { status: "ok", detail: toChatSessionDetail(session) };
  } catch (error) {
    console.warn(`[chat] failed to load session ${sessionId}:`, error);
    return { status: "error" };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * 取会话最近一屏消息（恢复会话的历史来源）。
 *
 * 用 REST 而不是 WS `history`：后者把 `content` 拍平成字符串，丢掉了
 * `toolName` / `toolCallId` / `isError`，无法还原工具调用卡。
 * 不带游标时返回 `seq` 最大的 `limit` 条，且按 `seq` 升序。
 *
 * 取不到时返回 `null`：历史失败不阻断恢复（仍可继续对话），调用方按空历史处理。
 */
export async function fetchSessionMessages(
  sessionId: string,
  limit: number
): Promise<ServiceMessagePage | null> {
  return requestSessionJson<ServiceMessagePage>(
    `/messages/list?sessionId=${encodeURIComponent(sessionId)}&limit=${limit}`
  );
}

/** `GET /runs/detail` 里本模块用得到的终态信息（`4.05-运行.md`）。 */
export interface ServiceRunDetail {
  id: string;
  /** 子代理 run 的父 run；顶层为 null。终态解释要一路走到顶层，否则可能误报子 run 的状态。 */
  parentRunId: string | null;
  status: "pending" | "running" | "succeeded" | "failed" | "aborted";
  error: string | null;
  finishedAt: string | null;
}

/**
 * 取一次 run 的终态。
 *
 * 服务重启会把活跃 run 直接判 `failed / 服务重启`，这条终态**不会**以事件或
 * 消息补发（进程已经换了），只能靠这个只读接口在重连/恢复后重新推导。
 */
export async function fetchRunDetail(runId: string): Promise<ServiceRunDetail | null> {
  return requestSessionJson<ServiceRunDetail>(
    `/runs/detail?runId=${encodeURIComponent(runId)}`
  );
}

/**
 * 反查：按引擎 resume 标识找智能体会话，返回 `sessionId`。
 *
 * 实际路径是 `sessions/list?resumeSessionId=`（服务端支持逗号分隔多值，这里只传一个）。
 * `resumeSessionId` 不要求全局唯一：命中多条时服务端按 `createdAt` 降序返回，取最新一条。
 */
export async function fetchSessionIdByResumeSessionId(
  resumeSessionId: string
): Promise<string | null> {
  const page = await requestSessionJson<ServiceSessionPage>(
    `/sessions/list?resumeSessionId=${encodeURIComponent(resumeSessionId)}&page=1&pageSize=1`
  );
  return page?.items[0]?.id ?? null;
}

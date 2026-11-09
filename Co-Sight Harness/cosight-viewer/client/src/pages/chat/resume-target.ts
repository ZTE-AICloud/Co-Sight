// SPDX-License-Identifier: Apache-2.0
/**
 * @file resume-target.ts
 * @description 观测页「恢复对话」把一条看板会话落到 smart-factory 的会话 id。
 *
 * 两个 id 不是一回事：看板会话 id 是 Claude Code 的会话 UUID，smart-factory
 * 的 `sess_…` 才是 `/chat?agentRuntimeSessionId=` 要的参数。
 * 前者曾经由「Run Agent」写进 `agent_runtime_session_id`；老数据没有这个字段时，
 * 只能拿看板 id 去 `sessions/list?resumeSessionId=` 反查。
 */

import { fetchSessionIdByResumeSessionId } from "./session-api";

/** 反查只需要这两项，避免依赖整个 `Session` 类型。 */
export interface ResumeTargetSource {
  /** 看板会话 id（Claude Code 会话 UUID）。 */
  id: string;
  /** 由「Run Agent」写入的 smart-factory 会话 id；老数据为 null。 */
  agent_runtime_session_id?: string | null;
}

/**
 * 取出 `/chat?agentRuntimeSessionId=` 需要的会话 id。
 *
 * 优先用会话上已记录的 id（免一次请求）；没有时才反查。两处都查不到返回 `null`，
 * 由调用方提示「恢复失败」，而不是带着空 id 跳过去。
 */
export async function resolveResumeTarget(
  session: ResumeTargetSource
): Promise<string | null> {
  if (session.agent_runtime_session_id) {
    return session.agent_runtime_session_id;
  }
  return fetchSessionIdByResumeSessionId(session.id);
}

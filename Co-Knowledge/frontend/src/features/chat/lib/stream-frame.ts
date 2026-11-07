/**
 * 一帧 SSE 事件 → 正文 / 检索证据。属于「对话协议」的解析，和 `api/stream.js`
 * （负责切帧）是上下游关系：那边只保证 `onEvent` 拿到 `{event, data}`。
 * 零 Vue 依赖。
 *
 * 事件形状（服务端编排 SSE 端点）：
 *   - `event: token`     → `{"conversation_id": …, "content": "…"}`
 *   - `event: retrieval` → `{"conversation_id": …, "evidence": {…}}`
 * `done` / `error` 由 `streamPost` 当作终态处理，不会进到这里。
 */
import { normalizeEvidence, type RetrievalEvidence } from './evidence'

export type StreamFrame =
  | { type: 'text', content: string }
  | { type: 'retrieval', evidence: RetrievalEvidence }
  | { type: 'unknown' }

/**
 * 解析一帧。事件名不认识、JSON 坏了、证据校验失败一律返回 `unknown`，
 * 调用方静默忽略（服务端可能插入新事件；把原始 JSON 当正文渲染出来更糟）。
 */
export function parseEvent (event: string, payload: unknown): StreamFrame {
  try {
    const parsed = typeof payload === 'string' ? JSON.parse(payload) : null
    if (!parsed || typeof parsed !== 'object') {
      return { type: 'unknown' }
    }
    const record = parsed as Record<string, unknown>
    if (event === 'retrieval') {
      const evidence = normalizeEvidence(record.evidence)
      return evidence ? { type: 'retrieval', evidence } : { type: 'unknown' }
    }
    if (event === 'token') {
      return typeof record.content === 'string'
        ? { type: 'text', content: record.content }
        : { type: 'unknown' }
    }
    return { type: 'unknown' }
  } catch (e) {
    return { type: 'unknown' }
  }
}

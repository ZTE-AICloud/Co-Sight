/**
 * 右侧「检索链路与效果」的阶段耗时解析（零 Vue 依赖，可直接单测）。
 *
 * 数据有两个来源，刻意分开：
 *   - 服务端阶段（问题理解 / 向量检索 / 关键字检索 / 重排序）来自 `evidence.timings`；
 *   - 「生成回答」用客户端 `totalMs - retrievalMs`（retrievalMs 是收到证据帧的时刻）。
 *
 * 为什么生成不用服务端数字：服务端只测到检索结束；流式合成在 `_streamer` 消费
 * generator 时才真正生成，服务端阶段之和也不含网络/排队/提示词组装。客户端的
 * 「证据帧 → 流结束」才是用户感知的生成时间。
 *
 * 老后端/旧会话没有 `timings`：`retrievalMs` 回落到旧的客户端整段相位，
 * 问题理解/重排序显示 `—`（真实语义：没有测到，不伪造 0）。
 */
import { asTimingMs, type RetrievalEvidence } from './evidence'

/** 面板需要的最小消息字段（结构类型，避免依赖 ChatMessage / Vue）。 */
export interface TraceReplyLike {
  /** 客户端：从发请求到收到 `event: retrieval` 帧 */
  retrievalMs?: number
  /** 客户端：从发请求到流结束 */
  totalMs?: number
}

export interface TraceTimings {
  understandingMs?: number
  /** 检索合计（老后端 / 只有合计值时用于展示） */
  retrievalMs?: number
  /** 混合检索：向量检索分项 */
  vectorRetrievalMs?: number
  /** 混合检索：关键字检索分项 */
  keywordRetrievalMs?: number
  /** 图谱检索分项（图谱工作流只有这一路） */
  graphRetrievalMs?: number
  rerankMs?: number
  generateMs?: number
}

/** 检索面板里可独立展示的检索器类型 */
export type RetrievalStageKey = 'vector' | 'keyword' | 'graph'

export interface RetrievalStageTiming {
  key: RetrievalStageKey
  ms?: number
}

const DASH = '—'

/**
 * 合并服务端阶段耗时与客户端整段相位。
 *
 * - 展示用 `retrievalMs` 优先服务端实测（纯检索），缺失时回落客户端相位；
 * - `generateMs` 必须用客户端相位做基线，否则会把改写/重排算进生成。
 */
export function resolveTraceTimings (
  evidence: RetrievalEvidence | null | undefined,
  reply: TraceReplyLike | null | undefined
): TraceTimings {
  const serverTimings = evidence?.timings
  const serverRetrieval = asTimingMs(serverTimings?.retrievalMs)
  const clientRetrieval = asTimingMs(reply?.retrievalMs)
  const total = asTimingMs(reply?.totalMs)

  return {
    understandingMs: asTimingMs(serverTimings?.understandingMs),
    retrievalMs: serverRetrieval ?? clientRetrieval,
    vectorRetrievalMs: asTimingMs(serverTimings?.vectorRetrievalMs),
    keywordRetrievalMs: asTimingMs(serverTimings?.keywordRetrievalMs),
    graphRetrievalMs: asTimingMs(serverTimings?.graphRetrievalMs),
    rerankMs: asTimingMs(serverTimings?.rerankMs),
    generateMs: (total !== undefined && clientRetrieval !== undefined)
      ? Math.max(0, total - clientRetrieval)
      : undefined
  }
}

/**
 * 检索阶段的展示拆分。
 *
 * 实测到分项时按实际执行的检索器分别展示：混合/条件工作流是
 * `vectorRetrievalMs` / `keywordRetrievalMs`，图谱工作流是 `graphRetrievalMs`。
 * 只有合计 `retrievalMs`（老后端 / 旧会话）时回落到单段占位，`fallbackKey`
 * 由调用方按证据类型决定 —— 图谱证据要显示「图谱检索」，不能再标成「向量检索」。
 * 缺失的占位阶段显示 `—`。
 */
export function resolveRetrievalStages (
  timings: TraceTimings,
  fallbackKey: RetrievalStageKey = 'vector'
): RetrievalStageTiming[] {
  const { vectorRetrievalMs, keywordRetrievalMs, graphRetrievalMs } = timings
  if (vectorRetrievalMs === undefined &&
      keywordRetrievalMs === undefined &&
      graphRetrievalMs === undefined) {
    return [{ key: fallbackKey, ms: timings.retrievalMs }]
  }
  const stages: RetrievalStageTiming[] = []
  if (vectorRetrievalMs !== undefined) {
    stages.push({ key: 'vector', ms: vectorRetrievalMs })
  }
  if (keywordRetrievalMs !== undefined) {
    stages.push({ key: 'keyword', ms: keywordRetrievalMs })
  }
  if (graphRetrievalMs !== undefined) {
    stages.push({ key: 'graph', ms: graphRetrievalMs })
  }
  return stages
}

/**
 * 面板统一格式：按量级换单位；缺数据用 `—`，不显示 `NaN` / 负数。
 *
 * 全部统一成毫秒会在长回答上出现 `123456 ms` 这种越界读数：
 * 1 秒以上用秒，1 分钟以上用分秒。
 */
export function formatMs (value?: number): string {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
    return DASH
  }
  const ms = Math.round(value)
  if (ms < 1000) {
    return `${ms} ms`
  }
  const totalSeconds = ms / 1000
  if (totalSeconds < 60) {
    return `${totalSeconds.toFixed(1)} s`
  }
  const wholeSeconds = Math.round(totalSeconds)
  const minutes = Math.floor(wholeSeconds / 60)
  const seconds = wholeSeconds % 60
  return seconds ? `${minutes} min ${seconds} s` : `${minutes} min`
}

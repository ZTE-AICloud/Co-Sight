/**
 * 「知识库依据」的数据模型与校验（零 Vue 依赖，可直接单测）。
 *
 * 两个入口的输入都当**不可信**处理：
 *   - 服务端 SSE 帧（`output.evidence`）；
 *   - localStorage 里恢复出来的旧会话（外部可写）。
 * 任何形状不对的字段都退回默认值，绝不让页面因为一条坏数据白屏。
 */

/** 文档库 / 图谱库。服务端按 base 前缀（`graph_`）判定。 */
export type EvidenceKind = 'document' | 'graph'

export interface EvidenceItem {
  /** 展示序号，从 1 开始（排序与后端一致） */
  index: number
  kind: EvidenceKind
  /** 知识库基名（`doc_<uuid>` / `graph_<uuid>`），视图层再映射成可读名 */
  kb: string
  /** 来源文件名（服务端优先用 `metadata.source`） */
  source: string
  /** 来源文件 id（sourceDocId；部分检索路径为空） */
  sourceId: string
  chunkId: string
  /** 切片序号（文档库 chunk_index / 图谱 chunk_order） */
  chunkIndex: string
  /** 分数：类型随检索链路不同（相似度 / ES / RRF / 重排相关度），只做展示 */
  score: number | null
  /** 图谱节点标签（如「故障」） */
  label: string
  text: string
  /** 服务端或存储层截断过正文 */
  truncated: boolean
}

export interface EvidenceStats {
  /** 当前实际展示的条数 */
  count: number
  /** 截断前的总条数（正常与 count 相等） */
  total: number
  sources: number
  knowledgeBases: number
}

/**
 * 本轮检索链路的服务端实测阶段耗时（毫秒）。
 *
 * 字段可缺省表示「该阶段没有执行」（例如工作流没配重排算子），视图层用 `—`
 * 区分「没跑」和「跑了 0ms」。生成回答不在其中：流式生成的真实耗时由客户端测量。
 *
 * `retrievalMs` 是检索合计；`vectorRetrievalMs` / `keywordRetrievalMs` /
 * `graphRetrievalMs` 是按检索器类型拆出的分项。两者是「合计 vs 分项」，不能相加。
 */
export interface EvidenceTimings {
  understandingMs?: number
  retrievalMs?: number
  vectorRetrievalMs?: number
  keywordRetrievalMs?: number
  graphRetrievalMs?: number
  rerankMs?: number
}

export interface RetrievalEvidence {
  /** 改写后的检索问句 */
  query: string
  items: EvidenceItem[]
  stats: EvidenceStats
  /** 服务端阶段耗时；老后端 / 旧会话没有这个字段 */
  timings?: EvidenceTimings
}

/** 单次响应最多展示多少条（与后端 MAX_EVIDENCE_ITEMS 对齐） */
export const MAX_EVIDENCE_ITEMS = 20
/** 单条正文最多多少字符（与后端 MAX_EVIDENCE_TEXT_CHARS 对齐） */
export const MAX_EVIDENCE_TEXT_CHARS = 2000
/** 落盘时只保留前几条（localStorage 配额有限） */
export const MAX_STORED_EVIDENCE_ITEMS = 6
/** 落盘时单条正文上限 */
export const MAX_STORED_EVIDENCE_TEXT_CHARS = 160
/** 分数展示保留几位小数（与 `/retrieve` 页一致） */
const SCORE_DECIMALS = 4

interface NormalizeOptions {
  maxItems?: number
  maxTextChars?: number
}

function asString (value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/** chunkIndex 这类字段线上可能是字符串或数字，统一成字符串。 */
function asText (value: unknown): string {
  if (typeof value === 'string') {
    return value
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    return String(value)
  }
  return ''
}

function asScore (value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function asPositiveInt (value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    return Math.floor(value)
  }
  return 0
}

/**
 * 阶段耗时是不可信输入：只接受有限的非负 number（含 0）。
 * 不接受字符串/布尔（后端契约就是数字；宽松转换只会掩盖契约漂移）。
 */
export function asTimingMs (value: unknown): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
    return undefined
  }
  return value
}

/** 只保留契约里列出的阶段（含混合检索的两个分项）；无效值丢弃，全空时不输出。 */
function normalizeTimings (raw: unknown): EvidenceTimings | undefined {
  if (!raw || typeof raw !== 'object') {
    return undefined
  }
  const record = raw as Record<string, unknown>
  const timings: EvidenceTimings = {}
  const understanding = asTimingMs(record.understandingMs)
  if (understanding !== undefined) {
    timings.understandingMs = understanding
  }
  const retrieval = asTimingMs(record.retrievalMs)
  if (retrieval !== undefined) {
    timings.retrievalMs = retrieval
  }
  const vectorRetrieval = asTimingMs(record.vectorRetrievalMs)
  if (vectorRetrieval !== undefined) {
    timings.vectorRetrievalMs = vectorRetrieval
  }
  const keywordRetrieval = asTimingMs(record.keywordRetrievalMs)
  if (keywordRetrieval !== undefined) {
    timings.keywordRetrievalMs = keywordRetrieval
  }
  const graphRetrieval = asTimingMs(record.graphRetrievalMs)
  if (graphRetrieval !== undefined) {
    timings.graphRetrievalMs = graphRetrieval
  }
  const rerank = asTimingMs(record.rerankMs)
  if (rerank !== undefined) {
    timings.rerankMs = rerank
  }
  return Object.keys(timings).length ? timings : undefined
}

function statsFor (items: EvidenceItem[], total: number): EvidenceStats {
  const sources = new Set<string>()
  const knowledgeBases = new Set<string>()
  for (const item of items) {
    if (item.source) {
      sources.add(item.source)
    }
    if (item.kb) {
      knowledgeBases.add(item.kb)
    }
  }
  return {
    count: items.length,
    total: Math.max(total, items.length),
    sources: sources.size,
    knowledgeBases: knowledgeBases.size
  }
}

function normalizeItem (raw: unknown, index: number, maxTextChars: number): EvidenceItem | null {
  if (!raw || typeof raw !== 'object') {
    return null
  }
  const record = raw as Record<string, unknown>
  const kind: EvidenceKind = record.kind === 'graph' ? 'graph' : 'document'
  const text = asString(record.text)
  const source = asString(record.source)
  const label = asString(record.label)
  if (!text && !source && !label) {
    return null
  }
  const truncated = record.truncated === true || text.length > maxTextChars
  return {
    index: asPositiveInt(record.index) || index + 1,
    kind,
    kb: asString(record.kb),
    source,
    sourceId: asString(record.sourceId),
    chunkId: asString(record.chunkId),
    chunkIndex: asText(record.chunkIndex),
    score: asScore(record.score),
    label,
    text: text.length > maxTextChars ? text.slice(0, maxTextChars) : text,
    truncated
  }
}

/**
 * 把服务端/存储里的未知值收敛成 `RetrievalEvidence`。
 * 不是对象、没有 items 数组等结构性错误返回 null（调用方当「没有证据」）；
 * 单条坏数据只丢那一条。
 */
export function normalizeEvidence (
  raw: unknown,
  options: NormalizeOptions = {}
): RetrievalEvidence | null {
  if (!raw || typeof raw !== 'object') {
    return null
  }
  const record = raw as Record<string, unknown>
  const rawItems = record.items
  if (!Array.isArray(rawItems)) {
    return null
  }
  const maxItems = Math.max(0, options.maxItems ?? MAX_EVIDENCE_ITEMS)
  const maxTextChars = Math.max(0, options.maxTextChars ?? MAX_EVIDENCE_TEXT_CHARS)

  const items: EvidenceItem[] = []
  for (const rawItem of rawItems) {
    if (items.length >= maxItems) {
      break
    }
    const item = normalizeItem(rawItem, items.length, maxTextChars)
    if (item) {
      // 过滤坏数据后重新编号，保证展示序号连续、UI key 不撞
      item.index = items.length + 1
      items.push(item)
    }
  }

  const rawStats = (record.stats && typeof record.stats === 'object')
    ? record.stats as Record<string, unknown>
    : {}
  const rawTotal = asPositiveInt(rawStats.total)
  const timings = normalizeTimings(record.timings)
  return {
    query: asString(record.query),
    items,
    stats: statsFor(items, rawTotal || items.length),
    ...(timings ? { timings } : {})
  }
}

/**
 * 落盘前的压缩：只留前 6 条、正文 160 字。`total` 保留服务端的总数，
 * 恢复后仍能提示「共 N 条，仅保留前 M 条」。
 */
export function compactEvidence (evidence: RetrievalEvidence): RetrievalEvidence {
  const items = evidence.items
    .slice(0, MAX_STORED_EVIDENCE_ITEMS)
    .map(item => {
      const overflow = item.text.length > MAX_STORED_EVIDENCE_TEXT_CHARS
      return {
        ...item,
        text: overflow
          ? item.text.slice(0, MAX_STORED_EVIDENCE_TEXT_CHARS)
          : item.text,
        truncated: item.truncated || overflow
      }
    })
  const timings = normalizeTimings(evidence.timings)
  return {
    query: evidence.query,
    items,
    stats: statsFor(items, evidence.stats.total),
    ...(timings ? { timings } : {})
  }
}

/**
 * 分数展示：0 / 空 / 非数字不显示（图谱未重排时 score=0，显示它没有意义）。
 * 保留 4 位小数的口径与 `/retrieve` 页一致。
 */
export function formatEvidenceScore (score: unknown): string {
  const value = asScore(score)
  if (value === null || value === 0) {
    return ''
  }
  return value.toFixed(SCORE_DECIMALS)
}

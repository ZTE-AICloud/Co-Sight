/**
 * 会话持久化（localStorage）。**纯存储层**：key 拼装、读/写/清、版本校验、
 * 损坏数据兜底、条数上限。零 Vue 依赖 —— 所以这些「刷新后恢复不出来」的分支
 * 全部可以直接单测（见 `tests/unit/chat-session-storage.spec.js`）。
 *
 * 设计约束（都别改，改了会破坏恢复语义）：
 *   - 所有 localStorage 访问都在 try 里：隐私模式 / 配额满时是**抛异常**的，
 *     存储只是「刷新后能恢复」的加分项，绝不能让它把整个页面拖白屏；
 *   - 版本号对不上一律当「没有会话」，比重开一个会话更糟；
 *   - 上限只截**存储**，内存里的对话不受影响（页面里能一直往上翻，刷新后只留最近 50 条）。
 */
import {
  asTimingMs,
  compactEvidence,
  normalizeEvidence,
  type RetrievalEvidence
} from './evidence'
import { renderMarkdown } from './markdown'

/** 每个会话最多存这么多条（只截**存储**，内存里的对话不受影响） */
export const SESSION_MAX_MESSAGES = 50

export type ChatRole = 'user' | 'assistant'

/** 内存里的一条消息。`html` 是 `text` 的派生物，不进存储。 */
export interface ChatMessage {
  role: ChatRole
  text: string
  thinking: string
  html: string
  /** 服务端还没回完（流式中） */
  pending: boolean
  /** 用户点了「停止生成」 */
  stopped: boolean
  /** 失败气泡（红色 + 失败文案） */
  error: boolean
  /** 本轮检索依据（仅助手消息有） */
  evidence?: RetrievalEvidence | null
  /**
   * 以下为右侧检索链路面板的客户端耗时。
   *
   * `retrievalMs`/`totalMs` 会随消息落盘：刷新后「生成回答/总耗时」仍能算出来；
   * `startedAt`/`firstTokenMs` 仍是纯瞬态（页面生命周期内的 performance.now()，
   * 刷新后没有意义）。
   */
  startedAt?: number
  retrievalMs?: number
  firstTokenMs?: number
  totalMs?: number
  /** 答案反馈（赞 / 踩），仅当前会话内有效 */
  vote?: number
}

/** 落盘形状：只存恢复需要的字段（`html` 是派生物，恢复时重算，也就不必把 HTML 存进去） */
export interface StoredMessage {
  role: ChatRole
  text: string
  thinking: string
  error: boolean
  /** 证据在落盘前已压缩（见 `compactEvidence`）；恢复时仍按不可信输入校验 */
  evidence?: unknown
  /** 面板的客户端耗时（可选）。服务端阶段耗时就装在 evidence.timings 里 */
  retrievalMs?: number
  totalMs?: number
}

/**
 * 恢复一条消息：瞬态标记在这里**规整掉**。
 *   - `pending` 一律置 false —— 刷新时正在生成的那条会留下 `pending: true`，
 *     原样恢复就是一个永远转圈、永远不会有下文的空气泡；
 *   - `stopped` 也清掉 —— 「已停止生成」描述的是当时那条流，刷新后流已经不存在；
 *   - `error` 保留 —— 它是气泡自身的含义（红色 + 失败文案），刷新后依然成立。
 * 正文和思考都空的（比如刷新时还没出第一个字）直接丢弃，不恢复空气泡。
 *
 * 入参是 `unknown`：存储里的东西是**外部可写**的，形状一律当不可信。
 */
export function restoreMessage (raw: unknown): ChatMessage | null {
  if (!raw || typeof raw !== 'object') {
    return null
  }
  const stored = raw as Partial<Record<
    'role' | 'text' | 'thinking' | 'error' | 'evidence' | 'retrievalMs' | 'totalMs',
    unknown
  >>
  if (stored.role !== 'user' && stored.role !== 'assistant') {
    return null
  }
  const text = typeof stored.text === 'string' ? stored.text : ''
  const thinking = typeof stored.thinking === 'string' ? stored.thinking : ''
  if (!text && !thinking) {
    return null
  }
  const retrievalMs = asTimingMs(stored.retrievalMs)
  const totalMs = asTimingMs(stored.totalMs)
  return {
    role: stored.role,
    text,
    thinking,
    html: renderMarkdown(text),
    pending: false,
    stopped: false,
    error: stored.error === true,
    // 存储可能被外部改坏：校验失败就当没有证据，不影响消息本身恢复
    evidence: stored.evidence ? normalizeEvidence(stored.evidence) : null,
    // 面板耗时同样按不可信输入处理；坏值只是让面板显示 —，不影响消息
    ...(retrievalMs !== undefined ? { retrievalMs } : {}),
    ...(totalMs !== undefined ? { totalMs } : {})
  }
}

/** 证据落盘前压缩：localStorage 配额有限，刷新后只需要能看出「用过哪个库/哪条片段」。 */
function storedEvidence (msg: ChatMessage): unknown {
  return msg.evidence ? compactEvidence(msg.evidence) : undefined
}

/** 面板的客户端耗时：只落两个有限非负数字，坏值直接不写。 */
function storedTimingFields (msg: ChatMessage): Pick<StoredMessage, 'retrievalMs' | 'totalMs'> {
  const fields: Pick<StoredMessage, 'retrievalMs' | 'totalMs'> = {}
  const retrievalMs = asTimingMs(msg.retrievalMs)
  if (retrievalMs !== undefined) {
    fields.retrievalMs = retrievalMs
  }
  const totalMs = asTimingMs(msg.totalMs)
  if (totalMs !== undefined) {
    fields.totalMs = totalMs
  }
  return fields
}

// ----------------------------------------------------------------------
// 多会话历史
//
// 存储形状是 `{activeConversationId, sessions: [...]}`，保留最近若干段会话，
// 页面左侧可切换。版本号对不上当「没有会话」——不尝试恢复半懂不懂的旧结构。
// 存储仍是**加分项**：抛异常/配额满时只是刷新后恢复不了，不能影响页面本身。
// ----------------------------------------------------------------------

/** 多会话历史的 key 前缀 */
export const SESSIONS_STORAGE_PREFIX = 'chat-test:sessions:'
/** 多会话存储形状版本 */
export const SESSIONS_VERSION = 3
/** 最多保留多少段历史会话（超出丢最旧的；当前会话永远保留） */
export const SESSIONS_MAX_COUNT = 30

export interface StoredSessionEntry {
  conversationId: string
  savedAt: number
  messages: StoredMessage[]
  /** 0.1.7：用户重命名后的标题；缺省时由第一条用户消息生成 */
  title?: string
  /** 0.1.7：置顶会话排在列表前面 */
  pinned?: boolean
}

export interface RestoredSessionEntry {
  conversationId: string
  savedAt: number
  messages: ChatMessage[]
  title?: string
  pinned?: boolean
}

export interface RestoredSessions {
  activeConversationId: string
  sessions: RestoredSessionEntry[]
}

interface StoredSessionsPayload {
  version: number
  activeConversationId: string
  sessions: StoredSessionEntry[]
}

export function sessionsKey (workflowId: string): string {
  return `${SESSIONS_STORAGE_PREFIX}${workflowId}`
}

function restoreEntry (raw: unknown): RestoredSessionEntry | null {
  if (!raw || typeof raw !== 'object') {
    return null
  }
  const entry = raw as Partial<Record<'conversationId' | 'savedAt' | 'messages' | 'title' | 'pinned', unknown>>
  if (typeof entry.conversationId !== 'string' || !entry.conversationId || !Array.isArray(entry.messages)) {
    return null
  }
  const messages = entry.messages
    .map(restoreMessage)
    .filter((msg): msg is ChatMessage => msg !== null)
  if (!messages.length) {
    return null
  }
  return {
    conversationId: entry.conversationId,
    savedAt: typeof entry.savedAt === 'number' ? entry.savedAt : 0,
    messages,
    ...(typeof entry.title === 'string' && entry.title.trim() ? { title: entry.title.trim() } : {}),
    ...(entry.pinned === true ? { pinned: true } : {})
  }
}

/** 按置顶优先、再按最近使用排序（历史列表用；不改原数组） */
export function sortSessionsByRecent (
  sessions: readonly RestoredSessionEntry[]
): RestoredSessionEntry[] {
  return [...sessions].sort((left, right) => (
    Number(!!right.pinned) - Number(!!left.pinned) || right.savedAt - left.savedAt
  ))
}

/**
 * 读某个工作流的多段会话。
 *
 * 任何一步损坏都回 null 或丢弃坏条目，绝不抛。
 */
export function readStoredSessions (workflowId: string): RestoredSessions | null {
  if (!workflowId) {
    return null
  }
  let raw: string | null = null
  try {
    raw = window.localStorage.getItem(sessionsKey(workflowId))
  } catch (e) {
    return null
  }

  if (!raw) {
    return null
  }

  try {
    const data = JSON.parse(raw) as Partial<StoredSessionsPayload> | null
    if (!data || data.version !== SESSIONS_VERSION || !Array.isArray(data.sessions)) {
      return null
    }
    const seen = new Set<string>()
    const sessions: RestoredSessionEntry[] = []
    for (const item of data.sessions) {
      const entry = restoreEntry(item)
      if (!entry || seen.has(entry.conversationId)) {
        continue
      }
      seen.add(entry.conversationId)
      sessions.push(entry)
    }
    if (!sessions.length) {
      return null
    }
    const active = typeof data.activeConversationId === 'string' ? data.activeConversationId : ''
    const activeExists = sessions.some(entry => entry.conversationId === active)
    return {
      activeConversationId: activeExists ? active : sortSessionsByRecent(sessions)[0].conversationId,
      sessions
    }
  } catch (e) {
    return null
  }
}

/**
 * 写多段会话。空会话不落盘；超过上限丢最旧的；当前会话即使很旧也保留。
 * 没有可写的会话时删掉 key（避免留下一个 `{sessions: []}` 的空壳）。
 */
export function writeStoredSessions (
  workflowId: string,
  activeConversationId: string,
  sessions: readonly RestoredSessionEntry[]
): void {
  if (!workflowId) {
    return
  }
  const nonEmpty = sessions.filter(entry => entry.messages.length > 0)
  if (!nonEmpty.length) {
    clearStoredSessions(workflowId)
    return
  }
  const sorted = sortSessionsByRecent(nonEmpty)
  const active = sorted.find(entry => entry.conversationId === activeConversationId)
  const others = sorted.filter(entry => entry.conversationId !== activeConversationId)
  const kept = [
    ...(active ? [active] : []),
    ...others
  ].slice(0, SESSIONS_MAX_COUNT)

  const payload: StoredSessionsPayload = {
    version: SESSIONS_VERSION,
    activeConversationId,
    sessions: kept.map(entry => ({
      conversationId: entry.conversationId,
      savedAt: entry.savedAt,
      messages: entry.messages.slice(-SESSION_MAX_MESSAGES).map(msg => ({
        role: msg.role,
        text: msg.text,
        thinking: msg.thinking,
        error: !!msg.error,
        evidence: storedEvidence(msg),
        ...storedTimingFields(msg)
      })),
      ...(entry.title ? { title: entry.title } : {}),
      ...(entry.pinned ? { pinned: true } : {})
    }))
  }
  try {
    window.localStorage.setItem(sessionsKey(workflowId), JSON.stringify(payload))
  } catch (e) {
    // 配额满 / 隐私模式：会话本身还能用，只是刷新后恢复不了
  }
}

/** 清掉多段会话 */
export function clearStoredSessions (workflowId: string): void {
  if (!workflowId) {
    return
  }
  try {
    window.localStorage.removeItem(sessionsKey(workflowId))
  } catch (e) {
    // 同上：清不掉也不该挡住「新会话」本身
  }
}

/** 把当前消息快照成一条会话条目（内存态，写盘时再裁字段）。 */
export function snapshotEntry (
  conversationId: string,
  messages: readonly ChatMessage[]
): RestoredSessionEntry {
  return {
    conversationId,
    savedAt: Date.now(),
    messages: messages.slice(-SESSION_MAX_MESSAGES)
  }
}

// ----------------------------------------------------------------------
// 上次选择的工作流
//
// 刷新后如果总是回到列表里的第一条，用户会以为「历史丢了」——历史还在，只是挂在
// 另一个工作流的键下。记住上次选择，恢复的体验才完整。存储失败不影响功能。
// ----------------------------------------------------------------------

export const LAST_WORKFLOW_STORAGE_KEY = 'chat-test:last-workflow'

export function readLastWorkflow (): string {
  try {
    return window.localStorage.getItem(LAST_WORKFLOW_STORAGE_KEY) || ''
  } catch (e) {
    return ''
  }
}

export function writeLastWorkflow (workflowId: string): void {
  try {
    if (workflowId) {
      window.localStorage.setItem(LAST_WORKFLOW_STORAGE_KEY, workflowId)
    } else {
      window.localStorage.removeItem(LAST_WORKFLOW_STORAGE_KEY)
    }
  } catch (e) {
    // 隐私模式 / 配额满：只是记不住上次选择，页面照常可用
  }
}

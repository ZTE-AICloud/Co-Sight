/**
 * 消息状态 + 多段会话历史（新建/切换/删除/恢复/落盘）。
 *
 * 这一层的全部「为什么」集中在四处，改动前先读完：
 *   1. **恢复时要规整瞬态标记**（pending/stopped 清零、error 保留）—— 见
 *      `lib/session-storage.ts` 的 `restoreMessage`；
 *   2. **写盘要节流**：流式期间每一帧都在改 `messages`，深度 watch 会每一帧都排一次写，
 *      不节流就等于每帧把整段会话序列化一遍；节流窗口内的最后一帧由 `flush()`（对话
 *      结束 / 切工作流 / 路由离开三处）立即兜底，**不能只靠定时器** —— 关页/刷新时
 *      定时器很可能还没到点；
 *   3. **换工作流要先把旧会话落到旧键**：watch 回调里此刻内存里还是旧状态，
 *      先 `flush(oldId)` 再读新的，否则旧工作流最新几条会丢；
 *   4. **多段历史是 v2 结构**：旧 v1 的单会话键会在读取时回落成「唯一一段历史」，
 *      「新会话」只切 id、不清历史（否则「历史」功能等于没有）。
 */
import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { sessionTitle } from '@/features/chat/lib/chat-history'
import { newConversationId } from '@/features/chat/lib/conversation'
import {
  readStoredSessions,
  sortSessionsByRecent,
  writeStoredSessions,
  type ChatMessage,
  type RestoredSessionEntry
} from '@/features/chat/lib/session-storage'

/** 流式期间每帧都在改 messages，节流合并写；最后一帧由 `flush()` 立即兜底 */
export const SESSION_SAVE_THROTTLE_MS = 500

/** 历史列表项（视图只读；`messages` 不直接暴露，避免视图误改历史） */
export interface ChatSessionSummary {
  conversationId: string
  savedAt: number
  /** 用户重命名优先；否则取第一条用户消息（截断） */
  title: string
  messageCount: number
  /** 0.1.7：置顶会话优先排列 */
  pinned: boolean
}

export interface ChatSessionExport {
  conversationId: string
  savedAt: number
  title: string
  messages: ChatMessage[]
}

export interface ChatSessionApi {
  /** 当前会话的消息（内存里是完整的，落盘时只留最近 50 条） */
  messages: Ref<ChatMessage[]>
  /** 会话 id：服务端多轮改写的键；切换历史会话就换它 */
  conversationId: Ref<string>
  /** 本次是不是从 localStorage 恢复出来的（只影响那一句提示） */
  sessionRestored: Ref<boolean>
  /** 当前工作流的历史会话（按最近使用排序，不含空会话） */
  sessions: Ref<ChatSessionSummary[]>
  /** 「新会话」：保留历史，换新 id 与空消息 */
  newConversation: () => void
  /** 切到某段历史会话（会先把当前会话落盘） */
  selectConversation: (conversationId: string) => void
  /** 删除一段历史会话；删的是当前会话时自动切到最近一段或新建 */
  deleteConversation: (conversationId: string) => void
  /** 重命名会话（0.1.7） */
  renameConversation: (conversationId: string, title: string) => void
  /** 置顶 / 取消置顶（0.1.7） */
  togglePin: (conversationId: string) => void
  /** 清空当前工作流的全部历史会话（0.1.7） */
  clearAll: () => void
  /** 读取某段会话的消息（导出用；当前会话取内存态） */
  sessionMessages: (conversationId: string) => ChatMessage[]
  /** 全部会话的可导出快照（置顶优先） */
  exportSessions: () => ChatSessionExport[]
  /**
   * 立即把当前快照写进**指定**工作流的键（切换/离开时传旧 id）。
   * 下面那行 disable：本仓 .eslintrc 把**基础** no-unused-vars 开成 error 又用
   * @typescript-eslint/parser 解析，任何 interface 里的函数类型成员都会被误报成
   * 「形参未使用」（连 `(string) => void` 这种匿名写法也一样）；参数名留着是为了可读性。
   */
  // eslint-disable-next-line no-unused-vars -- TS 函数类型形参被基础规则误报
  flush: (workflowId: string) => void
}

/**
 * 会话状态机。`selectedWorkflowId` 由调用方持有（它同时是下拉的 v-model），
 * 这里只**订阅**它的变化来切会话。
 */
export function useChatSession (selectedWorkflowId: Ref<string>): ChatSessionApi {
  const messages = ref<ChatMessage[]>([])
  const conversationId = ref(newConversationId())
  const sessionRestored = ref(false)
  /** 已落盘的会话条目（当前会话在 `messages` 里，不重复存） */
  const entries = ref<RestoredSessionEntry[]>([])

  let saveTimer: ReturnType<typeof setTimeout> | null = null

  /** 当前会话快照（没消息时返回 null：空会话不入历史、不落盘） */
  function currentEntry (): RestoredSessionEntry | null {
    if (!messages.value.length) {
      return null
    }
    const previous = entries.value.find(entry => entry.conversationId === conversationId.value)
    return {
      conversationId: conversationId.value,
      savedAt: Date.now(),
      messages: messages.value.slice(),
      ...(previous?.title ? { title: previous.title } : {}),
      ...(previous?.pinned ? { pinned: true } : {})
    }
  }

  /** 历史 + 当前（当前覆盖同 id 的旧条目），用于写盘与列表 */
  function allEntries (): RestoredSessionEntry[] {
    const current = currentEntry()
    const others = entries.value.filter(entry => entry.conversationId !== conversationId.value)
    return current ? [...others, current] : others
  }

  const sessions = computed<ChatSessionSummary[]>(() => sortSessionsByRecent(allEntries()).map(entry => ({
    conversationId: entry.conversationId,
    savedAt: entry.savedAt,
    title: entry.title || sessionTitle(entry.messages),
    messageCount: entry.messages.length,
    pinned: !!entry.pinned
  })))

  function persist (): void {
    const snapshot = allEntries()
    entries.value = snapshot
    writeStoredSessions(selectedWorkflowId.value, conversationId.value, snapshot)
  }

  function cancelPendingSave (): void {
    if (saveTimer !== null) {
      clearTimeout(saveTimer)
      saveTimer = null
    }
  }

  /** 节流写（trailing）：流式期间每帧都改 messages，没必要每帧都序列化整段会话 */
  function scheduleSessionSave (): void {
    if (saveTimer !== null || !selectedWorkflowId.value) {
      return
    }
    saveTimer = setTimeout(() => {
      saveTimer = null
      persist()
    }, SESSION_SAVE_THROTTLE_MS)
  }

  /** 立即写。`workflowId` 必须显式传：切工作流时要写进**旧**键，不能读当前值 */
  function flush (workflowId: string): void {
    cancelPendingSave()
    if (!workflowId) {
      return
    }
    const snapshot = allEntries()
    entries.value = snapshot
    writeStoredSessions(workflowId, conversationId.value, snapshot)
  }

  /** 读某个工作流的历史；没有就开一个全新会话 */
  function load (workflowId: string): void {
    const restored = readStoredSessions(workflowId)
    if (!restored || !restored.sessions.length) {
      entries.value = []
      conversationId.value = newConversationId()
      messages.value = []
      sessionRestored.value = false
      return
    }
    entries.value = restored.sessions
    const active = restored.sessions.find(entry => entry.conversationId === restored.activeConversationId)
      || sortSessionsByRecent(restored.sessions)[0]
    conversationId.value = active.conversationId
    messages.value = active.messages.slice()
    sessionRestored.value = active.messages.length > 0
  }

  function newConversation (): void {
    // 先把当前会话落进历史（否则「新会话」会把刚聊完的一段丢掉）
    cancelPendingSave()
    persist()
    conversationId.value = newConversationId()
    messages.value = []
    sessionRestored.value = false
    // 当前为空：写盘会保留其余历史，只更新 activeConversationId
    persist()
  }

  function selectConversation (targetId: string): void {
    if (!targetId || targetId === conversationId.value) {
      return
    }
    cancelPendingSave()
    persist()
    const target = entries.value.find(entry => entry.conversationId === targetId)
    if (!target) {
      return
    }
    conversationId.value = target.conversationId
    messages.value = target.messages.slice()
    sessionRestored.value = target.messages.length > 0
    persist()
  }

  function deleteConversation (targetId: string): void {
    if (!targetId) {
      return
    }
    cancelPendingSave()
    const remaining = allEntries().filter(entry => entry.conversationId !== targetId)
    entries.value = remaining

    if (targetId !== conversationId.value) {
      writeStoredSessions(selectedWorkflowId.value, conversationId.value, remaining)
      return
    }
    const next = sortSessionsByRecent(remaining)[0]
    if (next) {
      conversationId.value = next.conversationId
      messages.value = next.messages.slice()
      sessionRestored.value = next.messages.length > 0
    } else {
      conversationId.value = newConversationId()
      messages.value = []
      sessionRestored.value = false
    }
    persist()
  }

  /** 修改某段会话的元数据（重命名 / 置顶）；当前会话尚未进 entries 时补一条。 */
  function updateEntryMeta (targetId: string, patch: Partial<RestoredSessionEntry>): void {
    const index = entries.value.findIndex(entry => entry.conversationId === targetId)
    if (index >= 0) {
      entries.value = entries.value.map((entry, i) => (i === index ? { ...entry, ...patch } : entry))
      return
    }
    if (targetId === conversationId.value && messages.value.length) {
      entries.value = [...entries.value, {
        conversationId: targetId,
        savedAt: Date.now(),
        messages: messages.value.slice(),
        ...patch
      }]
    }
  }

  function renameConversation (targetId: string, title: string): void {
    const clean = String(title || '').trim()
    if (!targetId || !clean) {
      return
    }
    updateEntryMeta(targetId, { title: clean })
    persist()
  }

  function togglePin (targetId: string): void {
    if (!targetId) {
      return
    }
    const entry = entries.value.find(item => item.conversationId === targetId)
    updateEntryMeta(targetId, { pinned: !entry?.pinned })
    persist()
  }

  function sessionMessages (targetId: string): ChatMessage[] {
    if (targetId === conversationId.value) {
      return messages.value.slice()
    }
    return entries.value.find(entry => entry.conversationId === targetId)?.messages.slice() || []
  }

  function exportSessions (): ChatSessionExport[] {
    return sortSessionsByRecent(allEntries()).map(entry => ({
      conversationId: entry.conversationId,
      savedAt: entry.savedAt,
      title: entry.title || sessionTitle(entry.messages),
      messages: entry.messages.slice()
    }))
  }

  function clearAll (): void {
    cancelPendingSave()
    entries.value = []
    conversationId.value = newConversationId()
    messages.value = []
    sessionRestored.value = false
    // 空集合会同时清掉 v2 与 v1 键（见 writeStoredSessions）
    writeStoredSessions(selectedWorkflowId.value, conversationId.value, [])
  }

  /**
   * 换工作流 = 换会话集合。先把手里这份落到**旧** workflowId 的键下（此刻内存里还是
   * 旧状态），再读新工作流自己的历史；没有就开一个全新的 conversationId。
   *
   * 不同工作流绝不共用 conversationId：服务端 chat memory 按 `conversation_id` 存问答，
   * 共用会把 A 工作流的上下文带进 B 工作流的追问里。
   * `restored.messages.length` 只影响那一句提示，不参与任何逻辑。
   */
  watch(selectedWorkflowId, (newId, oldId) => {
    if (oldId) {
      flush(oldId)
    }
    if (!newId) {
      entries.value = []
      messages.value = []
      conversationId.value = newConversationId()
      sessionRestored.value = false
      return
    }
    load(newId)
  })

  // 每次消息/会话 id 变化都排一次（节流的）落盘；深度监听是必须的：
  // 流式改的是消息对象内部字段，引用没变
  watch([messages, conversationId], scheduleSessionSave, { deep: true })

  // 路由离开：最后一次立即写（定时器很可能赶不上）
  onBeforeUnmount(() => flush(selectedWorkflowId.value))

  return {
    messages,
    conversationId,
    sessionRestored,
    sessions,
    newConversation,
    selectConversation,
    deleteConversation,
    renameConversation,
    togglePin,
    clearAll,
    sessionMessages,
    exportSessions,
    flush
  }
}

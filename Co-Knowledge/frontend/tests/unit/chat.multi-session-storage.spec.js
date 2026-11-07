// @vitest-environment jsdom
// `restoreMessage` 会重算 markdown（DOMPurify 需要 window）。
import {
  LAST_WORKFLOW_STORAGE_KEY,
  SESSIONS_MAX_COUNT,
  SESSIONS_STORAGE_PREFIX,
  SESSIONS_VERSION,
  SESSION_MAX_MESSAGES,
  clearStoredSessions,
  readLastWorkflow,
  readStoredSessions,
  sessionsKey,
  sortSessionsByRecent,
  writeLastWorkflow,
  writeStoredSessions
} from '@/features/chat/lib/session-storage'

function createFakeStorage () {
  const store = new Map()
  return {
    store,
    getItem: key => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => { store.set(key, String(value)) },
    removeItem: key => { store.delete(key) }
  }
}

function message (role, text, overrides = {}) {
  return {
    role,
    text,
    thinking: '',
    html: '',
    pending: false,
    stopped: false,
    error: false,
    ...overrides
  }
}

function entry (conversationId, text, savedAt = 1) {
  return {
    conversationId,
    savedAt,
    messages: [message('user', text), message('assistant', '答案')]
  }
}

describe('multi-session-storage', () => {
  let storage

  beforeEach(() => {
    storage = createFakeStorage()
    globalThis.window = { localStorage: storage }
  })

  afterEach(() => {
    delete globalThis.window
  })

  it('sessionsKey 带 workflowId', () => {
    expect(sessionsKey('wf-1')).toBe(`${SESSIONS_STORAGE_PREFIX}wf-1`)
    expect(sessionsKey('wf-1')).not.toBe(sessionsKey('wf-2'))
  })

  it('v2 写盘同样保留面板客户端耗时', () => {
    // Arrange
    const sessions = [{
      conversationId: 'conv-a',
      savedAt: 1,
      messages: [message('assistant', '答案', { retrievalMs: 3953, totalMs: 4696 })]
    }]

    // Act
    writeStoredSessions('wf-1', 'conv-a', sessions)
    const restored = readStoredSessions('wf-1')

    // Assert
    const restoredMessage = restored.sessions[0].messages[0]
    expect(restoredMessage.retrievalMs).toBe(3953)
    expect(restoredMessage.totalMs).toBe(4696)
  })

  it('写入多段会话后可读回，保留 activeConversationId', () => {
    // Arrange
    const sessions = [entry('conv-a', '问 A', 1), entry('conv-b', '问 B', 2)]

    // Act
    writeStoredSessions('wf-1', 'conv-a', sessions)
    const restored = readStoredSessions('wf-1')

    // Assert
    expect(restored.activeConversationId).toBe('conv-a')
    expect(restored.sessions.map(item => item.conversationId).sort()).toEqual(['conv-a', 'conv-b'])
    expect(restored.sessions[0].messages[0].html).toContain('问 A')
  })

  it('空会话不落盘；没有可写会话时删 key', () => {
    writeStoredSessions('wf-1', 'conv-a', [])

    expect(storage.store.has(sessionsKey('wf-1'))).toBe(false)
    expect(readStoredSessions('wf-1')).toBeNull()
  })

  it('activeConversationId 指向不存在的会话时回落到最近一段', () => {
    writeStoredSessions('wf-1', 'conv-missing', [
      entry('conv-a', '问 A', 10),
      entry('conv-b', '问 B', 20)
    ])

    const restored = readStoredSessions('wf-1')

    expect(restored.activeConversationId).toBe('conv-b')
  })

  it('置顶与自定义标题随会话落盘，置顶排在最前', () => {
    // Arrange：较新的普通会话 + 较旧但置顶且重命名过的会话
    const pinned = { ...entry('conv-pinned', '旧问答', 5), title: '改名后的会话', pinned: true }

    // Act
    writeStoredSessions('wf-1', 'conv-new', [entry('conv-new', '新问答', 10), pinned])
    const restored = readStoredSessions('wf-1')

    // Assert：存储保留当前会话在前，展示时由排序函数把置顶顶到最前
    const pinnedEntry = restored.sessions.find(item => item.conversationId === 'conv-pinned')
    expect(pinnedEntry.title).toBe('改名后的会话')
    expect(pinnedEntry.pinned).toBe(true)
    expect(sortSessionsByRecent(restored.sessions)[0].conversationId).toBe('conv-pinned')
    expect(restored.sessions.find(item => item.conversationId === 'conv-new').title).toBeUndefined()
  })

  it('脏的 title / pinned 不恢复：title 只认非空字符串，pinned 只认 true', () => {
    // Arrange：直接写存储，绕过写侧的归一化，模拟被外部改过的 localStorage
    storage.setItem(sessionsKey('wf-1'), JSON.stringify({
      version: SESSIONS_VERSION,
      activeConversationId: 'conv-a',
      sessions: [{
        ...entry('conv-a', '问 A'),
        title: '   ',
        pinned: 'yes'
      }]
    }))

    // Act
    const restored = readStoredSessions('wf-1')

    // Assert
    expect(restored.sessions[0].title).toBeUndefined()
    expect(restored.sessions[0].pinned).toBeUndefined()
  })

  it('超过上限时丢最旧的，但当前会话永远保留', () => {
    // Arrange：最旧的那段就是当前会话
    const sessions = [entry('conv-active', '当前', 1)]
    for (let i = 0; i < SESSIONS_MAX_COUNT + 5; i++) {
      sessions.push(entry(`conv-${i}`, `问${i}`, 100 + i))
    }

    // Act
    writeStoredSessions('wf-1', 'conv-active', sessions)
    const restored = readStoredSessions('wf-1')

    // Assert
    expect(restored.sessions.length).toBe(SESSIONS_MAX_COUNT)
    expect(restored.sessions.some(item => item.conversationId === 'conv-active')).toBe(true)
    expect(restored.activeConversationId).toBe('conv-active')
  })

  it('每段会话最多存 SESSION_MAX_MESSAGES 条', () => {
    const messages = []
    for (let i = 0; i < SESSION_MAX_MESSAGES + 10; i++) {
      messages.push(message('user', `问${i}`))
    }
    writeStoredSessions('wf-1', 'conv-a', [{ conversationId: 'conv-a', savedAt: 1, messages }])

    const restored = readStoredSessions('wf-1')

    expect(restored.sessions[0].messages.length).toBe(SESSION_MAX_MESSAGES)
    expect(restored.sessions[0].messages[0].text).toBe('问10')
  })

  it('版本不符/JSON 损坏/结构不对都回 null（不白屏）', () => {
    storage.setItem(sessionsKey('wf-1'), JSON.stringify({
      version: SESSIONS_VERSION + 1, activeConversationId: 'x', sessions: []
    }))
    expect(readStoredSessions('wf-1')).toBeNull()

    storage.setItem(sessionsKey('wf-1'), '{不是 JSON')
    expect(readStoredSessions('wf-1')).toBeNull()

    storage.setItem(sessionsKey('wf-1'), JSON.stringify({
      version: SESSIONS_VERSION, activeConversationId: 'x', sessions: '不是数组'
    }))
    expect(readStoredSessions('wf-1')).toBeNull()
  })

  it('重复 conversationId 只保留第一条；坏条目丢弃', () => {
    storage.setItem(sessionsKey('wf-1'), JSON.stringify({
      version: SESSIONS_VERSION,
      activeConversationId: 'conv-a',
      sessions: [
        { conversationId: 'conv-a', savedAt: 2, messages: [{ role: 'user', text: '第一条' }] },
        { conversationId: 'conv-a', savedAt: 1, messages: [{ role: 'user', text: '重复' }] },
        { conversationId: '', savedAt: 1, messages: [{ role: 'user', text: '坏' }] },
        { conversationId: 'conv-empty', savedAt: 1, messages: [] }
      ]
    }))

    const restored = readStoredSessions('wf-1')

    expect(restored.sessions).toHaveLength(1)
    expect(restored.sessions[0].messages[0].text).toBe('第一条')
  })

  it('localStorage 抛异常时不抛出', () => {
    globalThis.window = {
      localStorage: {
        getItem: () => { throw new Error('SecurityError') },
        setItem: () => { throw new Error('QuotaExceededError') },
        removeItem: () => { throw new Error('SecurityError') }
      }
    }

    expect(readStoredSessions('wf-1')).toBeNull()
    expect(() => writeStoredSessions('wf-1', 'conv-a', [entry('conv-a', '问')])).not.toThrow()
    expect(() => clearStoredSessions('wf-1')).not.toThrow()
  })

  it('sortSessionsByRecent 不改原数组', () => {
    const sessions = [entry('a', 'A', 1), entry('b', 'B', 2)]

    const sorted = sortSessionsByRecent(sessions)

    expect(sorted.map(item => item.conversationId)).toEqual(['b', 'a'])
    expect(sessions.map(item => item.conversationId)).toEqual(['a', 'b'])
  })

  it('记住/读取上次选择的工作流；空值表示清除', () => {
    expect(readLastWorkflow()).toBe('')

    writeLastWorkflow('wf-graph')
    expect(readLastWorkflow()).toBe('wf-graph')
    expect(storage.store.get(LAST_WORKFLOW_STORAGE_KEY)).toBe('wf-graph')

    writeLastWorkflow('')
    expect(readLastWorkflow()).toBe('')
    expect(storage.store.has(LAST_WORKFLOW_STORAGE_KEY)).toBe(false)
  })

  it('上次工作流存储不可用时返回空串且不抛', () => {
    globalThis.window = { localStorage: {
      getItem: () => { throw new Error('SecurityError') },
      setItem: () => { throw new Error('QuotaExceededError') },
      removeItem: () => { throw new Error('SecurityError') }
    } }

    expect(readLastWorkflow()).toBe('')
    expect(() => writeLastWorkflow('wf')).not.toThrow()
  })

  it('清除只删当前工作流的会话键', () => {
    writeStoredSessions('wf-1', 'conv-a', [entry('conv-a', '问')])
    writeStoredSessions('wf-2', 'conv-b', [entry('conv-b', '问')])

    clearStoredSessions('wf-1')

    expect(storage.store.has(sessionsKey('wf-1'))).toBe(false)
    expect(storage.store.has(sessionsKey('wf-2'))).toBe(true)
  })
})

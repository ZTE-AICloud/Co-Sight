/**
 * 把界面消息整理成服务端要的 ``chat_history``（问答对）。
 *
 * 为什么前端传而不是只靠服务端进程内缓存：`chat_memory` 是单副本内存（TTL 10 分钟），
 * 刷新页面、换浏览器、服务重启都会丢；而完整的消息本来就在本地会话里。随请求带上
 * 最近 N 问 N 答后，多轮改写不再依赖服务端记住上一次。
 *
 * 口径（与服务端 ``query_rewrite`` 的消费方式对齐）：
 *   - 只取**成功**的问答对：失败气泡（error）不进历史，避免把错误文案当上下文；
 *   - 助手答案缺失（流中断/用户停止）时保留该问、答案置空 —— 服务端会用问句做
 *     「上一轮问题」补全，答案缺失不影响判定，凭空丢掉反而少了上下文；
 *   - 顺序保持对话顺序，最后再截最近 `limit` 对。
 */
import type { ChatMessage } from './session-storage'

/** 最多带多少轮（与后端 `default_max_multi_chat_limit` 一致；画布上的正数上限仍优先） */
export const CHAT_HISTORY_LIMIT = 8

export interface ChatHistoryPair {
  question: string
  answer: string
}

export function buildChatHistory (
  messages: readonly ChatMessage[],
  limit: number = CHAT_HISTORY_LIMIT
): ChatHistoryPair[] {
  if (!(limit > 0)) {
    return []
  }
  const pairs: ChatHistoryPair[] = []
  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i]
    if (msg.role !== 'user' || msg.error || !msg.text.trim()) {
      continue
    }
    const reply = messages[i + 1]
    // 这一轮助手明确失败：整对丢掉。把「工作流未发布」这类错误文案当上下文，
    // 下一轮改写只会被带偏；而缺答案的**未失败**轮（流中断/用户停止）仍保留问句。
    if (reply && reply.role === 'assistant' && reply.error) {
      continue
    }
    const answered = reply && reply.role === 'assistant'
    pairs.push({
      question: msg.text,
      answer: answered ? reply.text : ''
    })
  }
  return pairs.slice(-limit)
}

/** 会话标题：第一条用户消息截断；没有用户消息时返回空串（由视图给默认文案）。 */
export function sessionTitle (messages: readonly ChatMessage[], maxLength = 30): string {
  const first = messages.find(msg => msg.role === 'user' && !!msg.text.trim())
  if (!first) {
    return ''
  }
  const text = first.text.trim().replace(/\s+/g, ' ')
  return text.length > maxLength ? `${text.slice(0, maxLength).trimEnd()}…` : text
}

/**
 * 发送 / 流式收帧 / 停止生成 / 失败分类。
 *
 * DOM 相关的三件事（滚到底、只在贴底时跟随、收尾落盘）通过回调注入 —— 这样这一层
 * 只碰数据，视图层只碰 DOM，中间不互相伸手。
 */
import { reactive, ref, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { chatQueryStream } from '@/features/chat/api/chat'
import { buildChatHistory } from '@/features/chat/lib/chat-history'
import { errText, streamErrorMessage, type StreamResult } from '@/features/chat/lib/errors'
import { renderMarkdown } from '@/features/chat/lib/markdown'
import { splitReasoning } from '@/features/chat/lib/reasoning'
import { parseEvent } from '@/features/chat/lib/stream-frame'
import type { ChatMessage } from '@/features/chat/lib/session-storage'

export interface UseChatStreamOptions {
  /** 必传：不传会落到服务端的 default_workflow_id，而该默认检索不存在 */
  workflowId: Ref<string>
  /** 当前选中的知识检索名称；「未发布」报错用它代替服务端返回的内部 ID */
  workflowName?: Ref<string>
  conversationId: Ref<string>
  /** 对话消息（由 useChatSession 提供） */
  messages: Ref<ChatMessage[]>
  /** 输入框绑定；发送成功后被清空，所以必须传引用而不是当时的值 */
  question: Ref<string>
  /** 滚到底（nextTick 之后设 scrollTop） */
  scrollToBottom: () => void | Promise<void>
  /** 流式期间每帧调用；只在用户本来就贴着底部时才真的滚 */
  autoScroll: () => void
  /** 收尾立即落盘（不等节流定时器） */
  flushSession: () => void
}

export interface ChatStreamApi {
  /** 流式中（视图拿它切换「发送/停止」按钮） */
  sending: Ref<boolean>
  send: () => Promise<void>
  stopGenerating: () => void
}

/**
 * 渲染结果挂在 `msg.html` 上（而不是模板里每次求值调用函数）：Vue 每次重渲染都会
 * 重跑模板表达式，放函数里等于每一帧把**所有**历史消息重新解析一遍。
 */
function applyMarkdown (msg: ChatMessage): void {
  msg.html = renderMarkdown(msg.text)
}

export function useChatStream (options: UseChatStreamOptions): ChatStreamApi {
  const { t } = useI18n()

  const sending = ref(false)
  // : 流式进行中的中断句柄（「停止生成」）；非流式时有它也无害
  const abortController = ref<AbortController | null>(null)

  async function send (): Promise<void> {
    const text = options.question.value.trim()
    // 与视图上 `canSend` 同一套判据。输入框的 Enter 不经过按钮的 disabled，
    // 少了这道闸，流式期间再按一次 Enter 就会并发发出第二条。
    if (!text || !options.workflowId.value || sending.value) {
      return
    }

    // 必须在 push 本轮用户消息**之前**取：chat_history 是「前几轮」，本轮问题单独在
    // `question` 字段里；把本轮也塞进历史会让服务端把当前问句当成上一轮。
    const chatHistory = buildChatHistory(options.messages.value)

    // 用户输入与助手答案走同一套渲染：纯文本经 markdown 是安全的，观感也一致
    options.messages.value.push(reactive<ChatMessage>({
      role: 'user', text, html: renderMarkdown(text), thinking: '', pending: false, error: false, stopped: false
    }))
    options.question.value = ''
    sending.value = true

    // 用 reactive 包装后再 push：直接 push 普通对象的话，后面 mutate 它不会触发重渲染
    const startedAt = performance.now()
    const reply = reactive<ChatMessage>({
      role: 'assistant', text: '', html: '', thinking: '', pending: true, error: false, stopped: false,
      evidence: null,
      // 右侧「检索链路」面板的客户端耗时：retrievalMs/totalMs 随消息落盘（刷新后
      // 「生成回答/总耗时」仍能算），startedAt/firstTokenMs 只在本次会话内有效。
      startedAt,
      retrievalMs: undefined,
      firstTokenMs: undefined,
      totalMs: undefined
    })
    options.messages.value.push(reply)
    await options.scrollToBottom()

    const controller = new AbortController()
    abortController.value = controller
    let accumulated = ''

    try {
      const result = await chatQueryStream({
        question: text,
        conversation_id: options.conversationId.value,
        // 必传：不传会落到服务端的 default_workflow_id，而该默认工作流不存在
        workflow_id: options.workflowId.value,
        // 服务端 query_rewrite 用它做多轮改写（不再只依赖进程内 last_question）
        chat_history: chatHistory,
        stream: true,
        // 让服务端在正文之前补一帧「本轮检索依据」；老后端不认识该字段会忽略
        include_retrieval: true
      }, {
        signal: controller.signal,
        onEvent: ({ event, data }: { event: string, data: string }) => {
          const frame = parseEvent(event, data)
          if (frame.type === 'retrieval') {
            // 证据帧先于正文到达：先把依据挂到消息上，视图会显示「已召回 N 条，生成中」
            reply.evidence = frame.evidence
            reply.retrievalMs = performance.now() - startedAt
            options.autoScroll()
            return
          }
          if (frame.type !== 'text' || !frame.content) {
            return
          }
          const chunk = frame.content
          if (reply.firstTokenMs === undefined) {
            reply.firstTokenMs = performance.now() - startedAt
          }
          accumulated += chunk
          const parsed = splitReasoning(accumulated)
          reply.thinking = parsed.thinking
          reply.text = parsed.text
          // 注意：这里**每帧**重算 markdown（只算正在流式的这一条）。实测过一次真实
          // 流式回答（281 帧，marked + DOMPurify 全量解析消毒）：mean 0.84ms、
          // p95 1.4ms、max 6.7ms，整段流式期间 0 个 long task —— 离 16ms 的单帧
          // 预算还很远，因此**不做节流**（节流会引入合并窗口与「最后一帧」的兜底复杂度）。
          applyMarkdown(reply)
          options.autoScroll()
        }
      }) as StreamResult

      if (!result.ok) {
        // 没进入流式：服务端在出第一字节前就失败了（未发布的工作流、参数不合法…），
        // 拿到的是 HTTP problem+json 而不是 SSE 帧
        reply.error = true
        reply.text = streamErrorMessage(result, t('modules.chatTest.requestFailed'), {
          workflowName: options.workflowName?.value
        })
      } else if (result.errorEvent) {
        // 流中途失败：HTTP 已是 200，服务端用终态 `event: error` 报错
        reply.error = true
        reply.text = streamErrorMessage(result, t('modules.chatTest.requestFailed'), {
          workflowName: options.workflowName?.value
        })
      } else if (!reply.text && !reply.thinking) {
        reply.text = t('modules.chatTest.answerEmpty')
      }
    } catch (e: unknown) {
      if (e && (e as { name?: string }).name === 'AbortError') {
        reply.stopped = true
      } else {
        reply.error = true
        reply.text = errText(e, t('modules.chatTest.requestFailed'))
      }
    } finally {
      reply.pending = false
      reply.totalMs = performance.now() - startedAt
      sending.value = false
      abortController.value = null
      // 收尾：最后一帧一定会渲染（即便中途 abort），也会立刻落盘一次，
      // 不等节流——刷新/关页时丢的窗口越小越好
      applyMarkdown(reply)
      options.flushSession()
      await options.scrollToBottom()
    }
  }

  /** 「停止生成」：中断 fetch，已收到的部分原样留下并打上标记 */
  function stopGenerating (): void {
    const controller = abortController.value
    if (controller) {
      controller.abort()
    }
  }

  return { sending, send, stopGenerating }
}

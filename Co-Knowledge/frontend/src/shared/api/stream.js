import { buildRequestHeaders } from '@/shared/api/client'
import { hasUnauthorizedHandler, notifyUnauthorized } from '@/shared/api/unauthorized'

/**
 * POST + SSE 消费（标准 `event:` / `data:` 帧）。
 *
 * 为什么不用 axios：它默认走 XHR，浏览器端拿不到增量（`responseType: 'stream'` 只在 Node
 * 生效），而 `EventSource` 只支持 GET。所以这里用原生 `fetch` + `ReadableStream`。
 * 鉴权头复用 `base.js` 的 `buildRequestHeaders()`，两条路不会漂移。
 *
 * 服务端协议（编排 SSE 端点）：
 *   - `event: retrieval` → `{"conversation_id":…,"evidence":{…}}`
 *   - `event: token`     → `{"conversation_id":…,"content":"…"}`
 *   - `event: done`      → `{"conversation_id":…,"finish_reason":"stop"}`（终态）
 *   - `event: error`     → RFC 9457 problem（终态；HTTP 已经是 200，不能改状态）
 *   - 注释行（`: keep-alive`）是心跳，忽略。
 *
 * 出第一字节前的失败是普通 HTTP problem+json（4xx/5xx），`ok:false` + `errorEnvelope`。
 *
 * @param {string} url
 * @param {object} body
 * @param {object} [handlers]
 * @param {(frame: {event: string, data: string, id?: string}) => void} [handlers.onEvent]
 *   非终态事件（`retrieval` / `token` / 未来新增事件）
 * @param {() => void} [handlers.onOpen] 确认拿到 `text/event-stream` 之后回调
 * @param {AbortSignal} [handlers.signal]
 * @returns {Promise<{ok: boolean, status: number, contentType: string, done: boolean,
 *                    aborted: boolean, errorEnvelope: object|null,
 *                    errorEvent: object|null}>}
 */
export async function streamPost (url, body, { onEvent, onOpen, signal } = {}) {
  const response = await fetch(url, {
    method: 'POST',
    // 本地账号会话走 HttpOnly Cookie；fetch 的默认值是 same-origin，这里写死避免被
    // 将来的调用方改成 omit/cross-origin 时静默丢会话。
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      ...buildRequestHeaders()
    },
    body: JSON.stringify(body),
    signal
  })

  if (response.status === 401 && hasUnauthorizedHandler()) {
    notifyUnauthorized({ status: 401, code: 'unauthorized' })
  }

  const contentType = response.headers.get('content-type') || ''
  if (!response.ok || !contentType.includes('text/event-stream')) {
    const errorEnvelope = parseProblem(await response.text())
    return {
      ok: false,
      status: response.status,
      contentType,
      done: false,
      aborted: false,
      errorEnvelope,
      errorEvent: null
    }
  }

  if (onOpen) {
    onOpen()
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let errorEvent = null

  const dispatch = frameText => {
    const frame = parseSseFrame(frameText)
    if (!frame) {
      return null
    }
    if (frame.event === 'done') {
      return 'done'
    }
    if (frame.event === 'error') {
      errorEvent = parseProblem(frame.data) || { detail: frame.data }
      return 'error'
    }
    if (onEvent) {
      onEvent(frame)
    }
    return null
  }

  while (true) {
    const { value, done } = await reader.read()
    if (done) {
      break
    }
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split(/\r\n\r\n|\n\n|\r\r/)
    // 最后一段可能是不完整的帧，留到下一轮再拼
    buffer = frames.pop()
    for (const frame of frames) {
      const terminal = dispatch(frame)
      if (terminal) {
        // 终态之后主动收掉读端：否则长驻对话页每问一次都会漏一条连接。
        await reader.cancel()
        return {
          ok: true, status: response.status, contentType,
          done: terminal === 'done', aborted: false,
          errorEnvelope: null, errorEvent
        }
      }
    }
  }

  // 流自然结束（服务端没发 done/error）：残留帧也交付
  if (buffer) {
    const terminal = dispatch(buffer)
    if (terminal) {
      return {
        ok: true, status: response.status, contentType,
        done: terminal === 'done', aborted: false,
        errorEnvelope: null, errorEvent
      }
    }
  }
  return {
    ok: true, status: response.status, contentType,
    done: false, aborted: false, errorEnvelope: null, errorEvent
  }
}

/** 一帧 SSE 文本 → `{event, data, id}`；只有注释/空行时返回 null。 */
function parseSseFrame (raw) {
  let event = 'message'
  let id
  const data = []
  for (const line of raw.split(/\r\n|\n|\r/)) {
    if (!line || line.startsWith(':')) {
      continue // 心跳/注释
    }
    const separator = line.indexOf(':')
    const field = separator === -1 ? line : line.slice(0, separator)
    let value = separator === -1 ? '' : line.slice(separator + 1)
    if (value.startsWith(' ')) {
      value = value.slice(1) // 规范允许 `data:` 后跟 0 或 1 个空格
    }
    if (field === 'event') {
      event = value
    } else if (field === 'data') {
      data.push(value)
    } else if (field === 'id') {
      id = value
    }
  }
  if (!data.length) {
    return null
  }
  return { event, data: data.join('\n'), id }
}

function parseProblem (text) {
  if (typeof text !== 'string' || !text) {
    return null
  }
  try {
    const parsed = JSON.parse(text)
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch (e) {
    return null
  }
}

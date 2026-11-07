import { streamPost } from '@/shared/api/stream'

// `@/api/base` 在导入期就要读 window / localStorage / navigator（见 appState.js 与
// i18n.js），node 环境里根本 import 不进来；而且单测也不该碰真实鉴权状态。
// 这里把「共享鉴权头」换成固定值 —— 顺带验证 streamPost 确实复用了它。
vi.mock('@/shared/api/client', () => ({
  buildRequestHeaders: () => ({ 'X-Auth-Value': 'test-token' })
}))

// 测的是 `src/shared/api/stream.js` 的 **SSE 帧切分**：这是整条对话链里最容易出静默 bug 的地方
// （半帧、多帧挤在一个 chunk、done/error 之后还有数据、流自然结束……全都不报错，只是答案少一截）。
// 全程用假的 fetch + 真的 ReadableStream，不打网络。

const encoder = new TextEncoder()
const SSE_HEADERS = { 'content-type': 'text/event-stream' }

function eventFrame (event, data, { crlf = false } = {}) {
  const sep = crlf ? '\r\n' : '\n'
  return `event: ${event}${sep}data: ${data}${sep}${sep}`
}

/**
 * 造一个「按 pull 逐块吐出」的 SSE 响应。
 * 用 pull 而不是在 start 里一次性 enqueue，是为了让终态之后 reader.cancel()
 * 的行为可判定（还有排队数据时 cancel 才会真的触发底层 cancel 回调）。
 */
function sseResponse (chunks, onCancel) {
  const queue = chunks.slice()
  const body = new ReadableStream({
    pull (controller) {
      if (!queue.length) {
        controller.close()
        return
      }
      const next = queue.shift()
      controller.enqueue(typeof next === 'string' ? encoder.encode(next) : next)
    },
    cancel () {
      if (onCancel) onCancel()
    }
  })
  return new Response(body, { status: 200, headers: SSE_HEADERS })
}

/** 把 fetch 换成只回这一个响应的桩 */
function mockFetch (response) {
  const fetchMock = vi.fn(() => Promise.resolve(response))
  globalThis.fetch = fetchMock
  return fetchMock
}

describe('streamPost（具名 SSE 事件）', () => {
  let originalFetch

  beforeEach(() => {
    originalFetch = globalThis.fetch
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.restoreAllMocks()
  })

  describe('given_单个 token 事件_when_消费_then_事件名与 data 原样交付', () => {
    it('onEvent 拿到 event/data', async () => {
      mockFetch(sseResponse([eventFrame('token', '{"content":"你好"}')]))
      const frames = []

      const result = await streamPost('/api/query', { question: 'q' }, { onEvent: f => frames.push(f) })

      expect(frames).toEqual([{ event: 'token', data: '{"content":"你好"}', id: undefined }])
      expect(result.ok).toBe(true)
      expect(result.done).toBe(false)
      expect(result.aborted).toBe(false)
      expect(result.errorEvent).toBeNull()
    })
  })

  describe('given_一个帧被切成两个 chunk_when_消费_then_拼起来只交付一次', () => {
    it('半帧留在缓冲区，下一块拼上后再交付', async () => {
      const frame = eventFrame('token', '{"content":"半帧"}')
      const cut = frame.indexOf('content')
      mockFetch(sseResponse([frame.slice(0, cut), frame.slice(cut)]))
      const frames = []

      await streamPost('/api/query', {}, { onEvent: f => frames.push(f) })

      expect(frames.map(f => f.data)).toEqual(['{"content":"半帧"}'])
    })

    it('UTF-8 多字节字符被按字节切开时也不乱码（流式解码）', async () => {
      const frame = eventFrame('token', '{"content":"中文😀"}')
      const full = encoder.encode(frame)
      const prefixLen = encoder.encode('event: token\ndata: {"content":"').length
      mockFetch(sseResponse([full.slice(0, prefixLen + 1), full.slice(prefixLen + 1)]))
      const frames = []

      await streamPost('/api/query', {}, { onEvent: f => frames.push(f) })

      expect(frames.map(f => f.data)).toEqual(['{"content":"中文😀"}'])
    })
  })

  describe('given_一个 chunk 里有多个帧_when_消费_then_逐帧交付', () => {
    it('两帧挤在一个 chunk 里也要分别交付', async () => {
      mockFetch(sseResponse([
        eventFrame('token', 'A') + eventFrame('token', 'B')
      ]))
      const frames = []

      await streamPost('/api/query', {}, { onEvent: f => frames.push(f) })

      expect(frames.map(f => f.data)).toEqual(['A', 'B'])
    })
  })

  describe('given_一个帧里有多个 data 行_when_消费_then_按规范用换行拼接', () => {
    it('多行 data: 合成一个载荷', async () => {
      mockFetch(sseResponse(['event: token\ndata: line1\ndata: line2\n\n']))
      const frames = []

      await streamPost('/api/query', {}, { onEvent: f => frames.push(f) })

      expect(frames.map(f => f.data)).toEqual(['line1\nline2'])
    })
  })

  describe('given_注释行_when_消费_then_跳过且不产生事件', () => {
    it('心跳注释行被忽略', async () => {
      mockFetch(sseResponse([
        ': keep-alive\n\n' +
        eventFrame('token', '真帧') +
        ': keep-alive\n\n'
      ]))
      const frames = []

      await streamPost('/api/query', {}, { onEvent: f => frames.push(f) })

      expect(frames.map(f => f.data)).toEqual(['真帧'])
    })

    it('CRLF 结尾的帧也能解析', async () => {
      mockFetch(sseResponse([eventFrame('token', 'A', { crlf: true })]))
      const frames = []

      await streamPost('/api/query', {}, { onEvent: f => frames.push(f) })

      expect(frames.map(f => f.data)).toEqual(['A'])
    })
  })

  describe('given_遇到 done 事件_when_消费_then_立刻收流', () => {
    it('done=true，且 done 之后的事件不再交付', async () => {
      mockFetch(sseResponse([
        eventFrame('token', 'A') +
        eventFrame('done', '{"finish_reason":"stop"}') +
        eventFrame('token', 'B')
      ]))
      const frames = []

      const result = await streamPost('/api/query', {}, { onEvent: f => frames.push(f) })

      expect(frames.map(f => f.data)).toEqual(['A'])
      expect(result.done).toBe(true)
      expect(result.ok).toBe(true)
      expect(result.errorEvent).toBeNull()
    })

    it('见到 done 会取消读端（否则每次提问都漏一条连接）', async () => {
      let cancelled = false
      mockFetch(sseResponse([
        eventFrame('token', 'A') + eventFrame('done', '{}'),
        eventFrame('token', '不该再交付')
      ], () => { cancelled = true }))
      const frames = []

      const result = await streamPost('/api/query', {}, { onEvent: f => frames.push(f) })

      expect(cancelled).toBe(true)
      expect(frames.map(f => f.data)).toEqual(['A'])
      expect(result.done).toBe(true)
    })
  })

  describe('given_流中途 error 事件_when_消费_then_终态且带出 problem', () => {
    it('errorEvent 是可解析的 problem，done=false', async () => {
      const problem = {
        type: 'urn:ragstudio:problem:llm_unavailable',
        title: 'Llm unavailable',
        status: 502,
        detail: '模型挂了',
        code: 'llm_unavailable'
      }
      let cancelled = false
      mockFetch(sseResponse([
        eventFrame('token', '半句') + eventFrame('error', JSON.stringify(problem)),
        eventFrame('token', '不该再交付')
      ], () => { cancelled = true }))
      const frames = []

      const result = await streamPost('/api/query', {}, { onEvent: f => frames.push(f) })

      expect(cancelled).toBe(true)
      expect(frames.map(f => f.data)).toEqual(['半句'])
      expect(result.ok).toBe(true)
      expect(result.done).toBe(false)
      expect(result.errorEvent).toEqual(problem)
    })

    it('error 的 data 不是 JSON 时仍保留原文', async () => {
      mockFetch(sseResponse([eventFrame('error', 'gateway exploded')]))

      const result = await streamPost('/api/query', {}, {})

      expect(result.errorEvent).toEqual({ detail: 'gateway exploded' })
    })
  })

  describe('given_流自然结束且没有 done_when_消费_then_残留帧也交付', () => {
    it('末帧缺尾随空行时，缓冲区里的残留帧仍然交付', async () => {
      mockFetch(sseResponse([eventFrame('token', 'A') + 'event: token\ndata: B']))
      const frames = []

      const result = await streamPost('/api/query', {}, { onEvent: f => frames.push(f) })

      expect(frames.map(f => f.data)).toEqual(['A', 'B'])
      expect(result.done).toBe(false)
    })
  })

  describe('given_没进入流式_when_消费_then_按 problem/状态码归类', () => {
    it('4xx + application/problem+json：errorEnvelope 带出稳定 code 与 detail', async () => {
      const problem = {
        type: 'urn:ragstudio:problem:published_workflow_not_found',
        title: 'Published workflow not found',
        status: 404,
        detail: '工作流 xxx 没有已发布的版本',
        code: 'published_workflow_not_found'
      }
      mockFetch(new Response(JSON.stringify(problem), {
        status: 404, headers: { 'content-type': 'application/problem+json' }
      }))
      const frames = []

      const result = await streamPost('/api/query', {}, { onEvent: f => frames.push(f) })

      expect(result.ok).toBe(false)
      expect(result.status).toBe(404)
      expect(result.errorEnvelope).toEqual(problem)
      expect(frames).toEqual([])
    })

    it('HTTP 502 且响应体不是 JSON：errorEnvelope 为 null，状态码照实带出', async () => {
      mockFetch(new Response('<html>502 Bad Gateway</html>', {
        status: 502, headers: { 'content-type': 'text/html' }
      }))

      const result = await streamPost('/api/query', {}, {})

      expect(result.ok).toBe(false)
      expect(result.status).toBe(502)
      expect(result.errorEnvelope).toBeNull()
    })

    it('onOpen 只在确认 text/event-stream 之后调用', async () => {
      mockFetch(new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } }))
      const opened = []

      await streamPost('/api/query', {}, { onOpen: () => opened.push('json') })

      expect(opened).toEqual([])

      mockFetch(sseResponse([eventFrame('done', '{}')]))

      await streamPost('/api/query', {}, { onOpen: () => opened.push('sse') })

      expect(opened).toEqual(['sse'])
    })
  })

  describe('given_请求形状_when_发送_then_POST JSON 且带上共享鉴权头', () => {
    it('url/方法/Content-Type/body/鉴权头都对', async () => {
      const fetchMock = mockFetch(sseResponse([eventFrame('done', '{}')]))

      await streamPost('/api/co-knowledge/v1/query', { question: '你好', stream: true }, {})

      const [url, init] = fetchMock.mock.calls[0]
      expect(url).toBe('/api/co-knowledge/v1/query')
      expect(init.method).toBe('POST')
      expect(init.headers['Content-Type']).toBe('application/json')
      expect(init.headers['X-Auth-Value']).toBe('test-token')
      expect(JSON.parse(init.body)).toEqual({ question: '你好', stream: true })
    })
  })

  describe('given_中途中断_when_消费_then_AbortError 原样抛给调用方', () => {
    it('reader.read() 的 AbortError 不吞掉（调用方靠它标记「已停止生成」）', async () => {
      const controller = new AbortController()
      let streamController
      const body = new ReadableStream({
        start (c) {
          streamController = c
          c.enqueue(encoder.encode(eventFrame('token', '{"content":"半句"}')))
        },
        pull () { /* 不产出也不关闭 */ }
      })
      mockFetch(new Response(body, { status: 200, headers: SSE_HEADERS }))
      controller.signal.addEventListener('abort', () => {
        streamController.error(new DOMException('The operation was aborted.', 'AbortError'))
      })
      const frames = []

      const pending = streamPost('/api/query', {}, {
        signal: controller.signal, onEvent: f => frames.push(f)
      })
      setTimeout(() => controller.abort(), 0)

      await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
      expect(frames.map(f => f.data)).toEqual(['{"content":"半句"}'])
    })
  })
})

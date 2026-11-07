/**
 * fake-model-gateway：OpenAI 兼容的确定性模型替身。
 *
 * 为什么需要它：E2E 不能依赖真实 embedding/LLM（不稳定、要凭证、答案不可判定）。
 * 本服务让 CI 里的检索/编排/对话链路可重复断言。
 *
 * 实现的是最小子集：
 *   GET  /v1/models
 *   POST /v1/embeddings
 *   POST /v1/chat/completions   （支持 stream=true 的 SSE）
 *   POST /v1/rerank
 *   GET  /__mock__/health
 *   POST /__mock__/config       （delayMs / streamFrames / answerMarker / failNext）
 *   GET  /__mock__/requests     （请求日志，供断言“检索上下文进了 prompt”）
 *   POST /__mock__/reset
 *
 * 无第三方依赖，node:22-alpine 直接跑。
 */
import http from 'node:http'
import { randomUUID } from 'node:crypto'
import { embed, DEFAULT_DIMENSION, lexicalScore } from './embeddings.mjs'

const PORT = Number(process.env.MOCK_PORT || 8000)
const MAX_LOG = 500

const MODEL_IDS = (process.env.E2E_MOCK_MODELS || 'e2e-llm,e2e-embedding,e2e-reranker,e2e-path-llm')
  .split(',')
  .map(item => item.trim())
  .filter(Boolean)

let config = {
  delayMs: 0,
  streamFrames: 8,
  answerMarker: 'E2E_MOCK_ANSWER',
  reasoning: false,
  failNext: null,
  // 额外声明为“端点可服务”的模型名：发布校验会把画布里的 llm 名和 /models 清单比对，
  // 用例注册的自定义模型名不在固定清单里时用它补上。
  extraModels: [],
  // 持续失败（与 one-shot 的 failNext 区分）：抽图算子的 invoke_llm 会重试 20 次，
  // failNext 只失败第一次，重试就会成功，测不出“抽取失败可见”。
  failChat: null
}

let requestLog = []

function sleep (ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

function json (res, status, body) {
  const payload = JSON.stringify(body)
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(payload),
    'Access-Control-Allow-Origin': '*'
  })
  res.end(payload)
}

function text (res, status, body, contentType = 'text/plain; charset=utf-8') {
  res.writeHead(status, {
    'Content-Type': contentType,
    'Access-Control-Allow-Origin': '*'
  })
  res.end(body)
}

async function readBody (req) {
  const chunks = []
  let size = 0
  for await (const chunk of req) {
    size += chunk.length
    if (size > 10 * 1024 * 1024) throw new Error('request body too large')
    chunks.push(chunk)
  }
  const raw = Buffer.concat(chunks).toString('utf8')
  if (!raw) return {}
  return JSON.parse(raw)
}

function log (entry) {
  requestLog.push({ time: new Date().toISOString(), ...entry })
  if (requestLog.length > MAX_LOG) requestLog = requestLog.slice(-MAX_LOG)
}

/** 从 synthesizer 的 prompt 里提取检索上下文中的唯一标记。 */
function extractMarker (prompt) {
  const match = prompt.match(/E2E-[A-Za-z0-9-]{3,}/)
  return match ? match[0] : ''
}

function classifyPrompt (prompt) {
  if (prompt.includes('A list of documents is shown below')) return 'rerank'
  // 图谱抽取算子自己的提示词模板（graph_extract 模板）。
  if (
    prompt.includes('你是知识图谱抽取助手') ||
    prompt.includes('You are a knowledge graph extraction assistant')
  ) return 'graph'
  // 工作流模板按 `language-option` 落库；种子数据不带该头时会拿到英文模板，
  // 因此中英文两套提示词都要识别，否则改写节点会把答案文本当成 JSON 解析失败。
  if (
    prompt.includes('你是一个问题补全和重构的专家') ||
    prompt.includes('You are an expert in question completion and reconstruction')
  ) return 'rewrite'
  if (prompt.includes('Some choices are given below')) return 'select'
  return 'answer'
}

function buildChatContent (prompt) {
  const kind = classifyPrompt(prompt)

  if (kind === 'rewrite') {
    // 中文模板的行首是 `###￥`（全角￥），英文模板是 `###`；模板 JSON 里还带 4 空格
    // 缩进，所以 `###` 前不能只允许一个换行，必须把空白整体吃掉。
    const match = prompt.match(/(?:本轮问题|Current question):\s*###[^\n]*\n\s*([\s\S]*?)\s*\n\s*###/)
    const question = (match ? match[1] : prompt).trim().slice(0, 2000)
    return { kind, content: JSON.stringify({ question }) }
  }

  if (kind === 'rerank') {
    const numbers = [...new Set(
      [...prompt.matchAll(/Document\s+(\d+):/g)].map(match => Number(match[1]))
    )]
    const lines = numbers.slice(0, 10).map((number, index) =>
      `Doc: ${number}, Relevance: ${Math.max(1, 10 - index)}`
    )
    return { kind, content: lines.join('\n') || 'Doc: 1, Relevance: 10' }
  }

  if (kind === 'select') {
    return { kind, content: '1' }
  }

  if (kind === 'graph') {
    // graph_extract 模板要求：实体类型只能取 schema 里声明的值，关系两端必须在
    // entities 里。E2E schema 固定为 Person/Organization + Knows/WorksAt。
    return {
      kind,
      content: JSON.stringify({
        entities: [
          { entity_name: 'Alice', entity_type: 'Person', entity_description: 'Acme 公司的工程师' },
          { entity_name: 'Bob', entity_type: 'Person', entity_description: 'Alice 的同事' },
          { entity_name: 'Acme', entity_type: 'Organization', entity_description: '一家公司' }
        ],
        relationships: [
          {
            source_entity: 'Alice',
            target_entity: 'Acme',
            edge_type: 'WorksAt',
            relationship_description: 'Alice 在 Acme 工作'
          },
          {
            source_entity: 'Alice',
            target_entity: 'Bob',
            edge_type: 'Knows',
            relationship_description: 'Alice 与 Bob 是同事'
          }
        ]
      })
    }
  }

  const marker = extractMarker(prompt)
  const content = config.answerContent
    ? String(config.answerContent).replaceAll('{{marker}}', marker)
    : [
      config.answerMarker,
      marker ? `命中标记：${marker}` : '',
      '',
      '（E2E 确定性模型替身返回）'
    ].filter(Boolean).join('\n')
  return { kind, content }
}

function completionBody ({ id, model, content }) {
  return {
    id,
    object: 'chat.completion',
    created: Math.floor(Date.now() / 1000),
    model,
    choices: [{
      index: 0,
      message: { role: 'assistant', content },
      finish_reason: 'stop'
    }],
    usage: {
      prompt_tokens: 1,
      completion_tokens: content.length,
      total_tokens: content.length + 1
    }
  }
}

async function streamCompletion (res, { id, model, content }) {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-cache',
    Connection: 'keep-alive',
    'Access-Control-Allow-Origin': '*'
  })
  res.flushHeaders?.()

  const send = payload => res.write(`data: ${JSON.stringify(payload)}\n\n`)
  const chunk = delta => ({
    id,
    object: 'chat.completion.chunk',
    created: Math.floor(Date.now() / 1000),
    model,
    choices: [{ index: 0, delta, finish_reason: null }]
  })

  send(chunk({ role: 'assistant' }))

  if (config.reasoning) {
    send(chunk({ reasoning_content: 'E2E 思考中…' }))
  }

  const frames = Math.max(1, Number(config.streamFrames) || 1)
  const size = Math.max(1, Math.ceil(content.length / frames))
  for (let start = 0; start < content.length; start += size) {
    send(chunk({ content: content.slice(start, start + size) }))
    if (config.delayMs > 0) await sleep(config.delayMs)
  }

  send({
    id,
    object: 'chat.completion.chunk',
    created: Math.floor(Date.now() / 1000),
    model,
    choices: [{ index: 0, delta: {}, finish_reason: 'stop' }]
  })
  res.write('data: [DONE]\n\n')
  res.end()
}

async function handle (req, res) {
  const url = new URL(req.url, `http://127.0.0.1:${PORT}`)
  const path = url.pathname.replace(/\/+$/, '') || '/'

  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type,Authorization'
    })
    res.end()
    return
  }

  if (path === '/__mock__/health' || path === '/health') {
    json(res, 200, { ok: true })
    return
  }

  if (path === '/__mock__/reset' && req.method === 'POST') {
    config = {
      delayMs: 0,
      streamFrames: 8,
      answerMarker: 'E2E_MOCK_ANSWER',
      reasoning: false,
      failNext: null,
      failChat: null,
      extraModels: []
    }
    requestLog = []
    json(res, 200, { ok: true })
    return
  }

  if (path === '/__mock__/config' && req.method === 'POST') {
    const body = await readBody(req)
    config = { ...config, ...body }
    json(res, 200, { ok: true, config })
    return
  }

  if (path === '/__mock__/requests' && req.method === 'GET') {
    json(res, 200, requestLog)
    return
  }

  if (config.failNext) {
    const failure = config.failNext
    config.failNext = null
    json(res, Number(failure.status) || 500, {
      error: { message: failure.message || 'injected failure', type: 'mock_error' }
    })
    return
  }

  if (path.endsWith('/models')) {
    log({ path, kind: 'models', method: req.method })
    json(res, 200, {
      object: 'list',
      data: [...new Set([...MODEL_IDS, ...(config.extraModels || [])])]
        .map(id => ({ id, object: 'model', owned_by: 'e2e' }))
    })
    return
  }

  if (req.method !== 'POST') {
    json(res, 404, { error: { message: `not found: ${path}` } })
    return
  }

  const body = await readBody(req)

  if (path.endsWith('/embeddings')) {
    const inputs = Array.isArray(body.input) ? body.input : [body.input ?? '']
    const dimension = Number(body.dimensions) || DEFAULT_DIMENSION
    const data = inputs.map((input, index) => ({
      object: 'embedding',
      index,
      embedding: embed(String(input ?? ''), dimension)
    }))
    log({ path, kind: 'embeddings', count: inputs.length, model: body.model || '' })
    if (config.delayMs > 0) await sleep(config.delayMs)
    json(res, 200, {
      object: 'list',
      model: body.model || 'e2e-embedding',
      data,
      usage: { prompt_tokens: inputs.length, total_tokens: inputs.length }
    })
    return
  }

  if (path.endsWith('/chat/completions')) {
    if (config.failChat) {
      const failure = config.failChat
      log({ path, kind: 'chat', promptKind: 'injected-failure', stream: !!body.stream })
      json(res, Number(failure.status) || 500, {
        error: { message: failure.message || 'injected failure', type: 'mock_error' }
      })
      return
    }
    const messages = Array.isArray(body.messages) ? body.messages : []
    const userMessage = [...messages].reverse().find(message => message.role === 'user')
    const prompt = typeof userMessage?.content === 'string'
      ? userMessage.content
      : JSON.stringify(userMessage?.content ?? '')
    const { kind, content } = buildChatContent(prompt)
    const id = `chatcmpl-${randomUUID()}`
    const model = body.model || 'e2e-llm'

    log({
      path,
      kind: 'chat',
      promptKind: kind,
      stream: !!body.stream,
      model,
      marker: extractMarker(prompt),
      promptPreview: prompt.slice(0, 300),
      promptFull: prompt.slice(0, 6000)
    })

    if (body.stream) {
      await streamCompletion(res, { id, model, content })
    } else {
      if (config.delayMs > 0) await sleep(config.delayMs)
      json(res, 200, completionBody({ id, model, content }))
    }
    return
  }

  if (path.endsWith('/rerank')) {
    const query = String(body.query || '')
    const documents = Array.isArray(body.documents) ? body.documents : []
    const results = documents.map((document, index) => {
      const value = typeof document === 'string'
        ? document
        : (document.text || document.content || '')
      return { index, relevance_score: lexicalScore(query, String(value)) }
    }).sort((a, b) => b.relevance_score - a.relevance_score)

    log({ path, kind: 'rerank', count: documents.length, model: body.model || '' })
    if (config.delayMs > 0) await sleep(config.delayMs)
    json(res, 200, { model: body.model || 'e2e-reranker', results })
    return
  }

  json(res, 404, { error: { message: `not found: ${path}` } })
}

const server = http.createServer((req, res) => {
  handle(req, res).catch(error => {
    console.error('[fake-model-gateway]', error)
    if (!res.headersSent) {
      json(res, 500, { error: { message: error.message || 'internal error' } })
    } else {
      res.end()
    }
  })
})

server.listen(PORT, '0.0.0.0', () => {
  console.log(`[fake-model-gateway] listening on :${PORT} models=${MODEL_IDS.join(',')}`)
})

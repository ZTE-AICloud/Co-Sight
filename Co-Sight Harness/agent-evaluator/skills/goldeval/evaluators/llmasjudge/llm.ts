import { spawn } from 'child_process'

const CLI = 'claude'
const CLI_ARGS = ['-p', '--output-format', 'json', '--no-session-persistence']
const TIMEOUT_MS = 600000
const PREVIEW = 300

let reportedModel: string | undefined

export function getMainLoopModel(): string {
  return reportedModel ?? process.env.ANTHROPIC_MODEL ?? CLI
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function stripThinkTags(text: string): string {
  return text
    .replace(/<think[^>]*>[\s\S]*?<\/think>/gi, '')
    .replace(/<thinking[^>]*>[\s\S]*?<\/thinking>/gi, '')
    .trim()
}

function modelOf(payload: Record<string, unknown>): string | undefined {
  if (typeof payload.model === 'string' && payload.model) return payload.model
  const usage = payload.modelUsage
  if (isRecord(usage)) return Object.keys(usage)[0]
  return undefined
}

function parseCliOutput(stdout: string): Record<string, unknown> {
  const trimmed = stdout.trim()
  try {
    const value = JSON.parse(trimmed) as unknown
    if (isRecord(value)) return value
  } catch {
    // 整体不是单个 JSON，退化为逐行查找
  }
  for (const line of trimmed.split('\n')) {
    const text = line.trim()
    if (!text.startsWith('{')) continue
    try {
      const value = JSON.parse(text) as unknown
      if (isRecord(value) && (value.type === 'result' || 'result' in value)) {
        return value
      }
    } catch {
      // 该行不是 JSON，继续下一行
    }
  }
  throw new Error(`claude -p 输出无法解析为 JSON：${trimmed.slice(0, PREVIEW)}`)
}

interface CliRun {
  stdout: string
  stderr: string
  code: number | null
}

function runClaude(prompt: string): Promise<CliRun> {
  return new Promise((resolve, reject) => {
    const child = spawn(CLI, CLI_ARGS, { stdio: ['pipe', 'pipe', 'pipe'] })
    let stdout = ''
    let stderr = ''
    let settled = false
    let timer: NodeJS.Timeout | undefined

    const finish = (fn: () => void) => {
      if (settled) return
      settled = true
      if (timer) clearTimeout(timer)
      child.stdin.destroy()
      child.stdout.destroy()
      child.stderr.destroy()
      fn()
    }

    timer = setTimeout(() => {
      child.kill('SIGKILL')
      finish(() => reject(new Error(`claude -p 调用超时（${TIMEOUT_MS}ms）`)))
    }, TIMEOUT_MS)

    child.stdout.on('data', (chunk: Buffer) => {
      stdout += chunk.toString('utf-8')
    })
    child.stderr.on('data', (chunk: Buffer) => {
      stderr += chunk.toString('utf-8')
    })
    child.on('error', (error: Error) => {
      finish(() => reject(new Error(`无法启动 ${CLI}：${error.message}`)))
    })
    child.on('close', (code) => {
      finish(() => resolve({ stdout, stderr, code }))
    })
    child.stdin.on('error', (error: NodeJS.ErrnoException) => {
      // claude 提前退出导致的 EPIPE，由 close 分支的结果判定兜住
      if (error.code !== 'EPIPE') stderr += `stdin: ${error.message}\n`
    })
    child.stdin.end(prompt)
  })
}

export async function llmCall(prompt: string): Promise<string> {
  const run = await runClaude(prompt)
  const payload = parseCliOutput(run.stdout)
  const text = stripThinkTags(
    typeof payload.result === 'string' ? payload.result : '',
  )
  const detail = run.stderr.trim()
    ? ` | stderr: ${run.stderr.trim().slice(0, PREVIEW)}`
    : ''
  if (payload.is_error === true) {
    throw new Error(
      `claude -p 返回错误（${String(payload.subtype ?? 'unknown')}）：${
        text.slice(0, PREVIEW) || JSON.stringify(payload).slice(0, PREVIEW)
      }${detail}`,
    )
  }
  if (run.code !== 0) {
    throw new Error(`claude -p 退出码 ${String(run.code)}${detail}`)
  }
  if (!text) throw new Error(`claude -p 未返回文本${detail}`)

  const model = modelOf(payload)
  if (model) reportedModel = model
  return text
}

export function extractJson(text: string): unknown {
  const trimmed = text.trim()
  try {
    return JSON.parse(trimmed)
  } catch {
    // fall through to fence / brace extraction
  }
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/)
  if (fenced) {
    try {
      return JSON.parse(fenced[1].trim())
    } catch {
      // fall through
    }
  }
  const firstBrace = trimmed.indexOf('{')
  const lastBrace = trimmed.lastIndexOf('}')
  if (firstBrace !== -1 && lastBrace > firstBrace) {
    try {
      return JSON.parse(trimmed.slice(firstBrace, lastBrace + 1))
    } catch {
      // fall through
    }
  }
  throw new Error('无法从 LLM 输出中解析 JSON')
}

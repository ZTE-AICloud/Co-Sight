/**
 * hooks.mjs — run Claude `PreToolUse` command hooks on dsh's
 * `tools/pre-execute` seam.
 *
 * Why not `@deepseek-ai/dsh-hooks-claude-code`? Its `configPath` is a
 * per-instance setting, so one bridge instance can only serve one hooks.json,
 * and it would become a dependency of the installed profile. This layer runs
 * the same scripts with the same payload directly: no extra package, no peer
 * dependency coupling.
 *
 * Supported: `PreToolUse` + `type: 'command'` (the only kind the plugins in
 * this repo declare). Other events/kinds are reported once and skipped.
 * Decision mapping follows Claude Code:
 *   exit 2                                   -> deny (stderr is the reason)
 *   stdout JSON hookSpecificOutput
 *     .permissionDecision = deny|ask|allow   -> mapped; allow continues
 *   stdout JSON decision: 'block'            -> deny (legacy shape)
 *   other non-zero exit                      -> warn and allow (non-blocking)
 */
import { spawn } from 'node:child_process'
import fs from 'node:fs'

const MAX_CAPTURE_BYTES = 1024 * 1024
const DEFAULT_TIMEOUT_MS = 60_000

/** dsh tool name -> Claude Code PascalCase tool name. */
export const TOOL_NAME_ALIASES = {
  read: 'Read',
  write: 'Write',
  edit: 'Edit',
  bash: 'Bash',
  grep: 'Grep',
  glob: 'Glob',
  skill: 'Skill',
  task: 'Task',
  subagent: 'Task',
  ask_user_question: 'AskUserQuestion',
  todo_write: 'TodoWrite',
  web_fetch: 'WebFetch',
  web_search: 'WebSearch',
}

/** Return the Claude-facing name used in hook payloads and matchers. */
export function claudeToolName(name) {
  return TOOL_NAME_ALIASES[name] ?? name
}

/** Matchers containing regex metacharacters are treated as anchored regexes. */
function isRegexMatcher(part) {
  return /[.*+?^${}()|[\]\\]/.test(part)
}

/** Does one matcher select this tool name? */
export function matcherSelects(matcher, toolName) {
  if (matcher === undefined || matcher === null) return true
  const text = String(matcher).trim()
  if (text.length === 0 || text === '*') return true
  return text
    .split('|')
    .map((part) => part.trim())
    .filter((part) => part.length > 0)
    .some((part) => {
      if (isRegexMatcher(part)) {
        try {
          return new RegExp(`^(?:${part})$`).test(toolName)
        } catch {
          return false
        }
      }
      return part === toolName
    })
}

/**
 * Read one plugin's hooks.json into flat PreToolUse rules.
 * @returns {object[]} rules: {event, plugin, pluginRoot, matcher, command, timeoutMs}
 */
export function loadHookRules(plugin, log) {
  if (plugin.hooksFile === null) return []
  let parsed
  try {
    parsed = JSON.parse(fs.readFileSync(plugin.hooksFile, 'utf8'))
  } catch (error) {
    log.warn(`cosight-plugin-compat: cannot read ${plugin.hooksFile}: ${error?.message ?? error}`)
    return []
  }
  const events = parsed?.hooks
  if (events === undefined || events === null || typeof events !== 'object') return []

  const rules = []
  for (const [event, groups] of Object.entries(events)) {
    if (event !== 'PreToolUse') {
      log.warn(`cosight-plugin-compat: ${plugin.dir} declares unsupported hook event "${event}"; skipped`)
      continue
    }
    if (!Array.isArray(groups)) continue
    for (const group of groups) {
      if (group === null || typeof group !== 'object') continue
      const matcher = typeof group.matcher === 'string' ? group.matcher : undefined
      const handlers = Array.isArray(group.hooks) ? group.hooks : []
      for (const handler of handlers) {
        if (handler?.type !== 'command' || typeof handler.command !== 'string') {
          log.warn(`cosight-plugin-compat: ${plugin.dir} ${event} declares a non-command hook; skipped`)
          continue
        }
        rules.push({
          event,
          plugin: plugin.dir,
          pluginRoot: plugin.root,
          matcher,
          command: handler.command,
          timeoutMs: Number.isFinite(handler.timeout) && handler.timeout > 0
            ? handler.timeout
            : DEFAULT_TIMEOUT_MS,
        })
      }
    }
  }
  return rules
}

/** Inject the Claude tokens this bridge supports into one command string. */
export function expandHookCommand(command, { pluginRoot, projectDir }) {
  let out = String(command)
  if (typeof pluginRoot === 'string' && pluginRoot.length > 0) {
    out = out.replaceAll('${CLAUDE_PLUGIN_ROOT}', pluginRoot)
  }
  if (typeof projectDir === 'string' && projectDir.length > 0) {
    out = out.replaceAll('${CLAUDE_PROJECT_DIR}', projectDir)
  }
  return out
}

/** Run one command hook; resolves {code, stdout, stderr, timedOut}. */
function runCommand(command, { cwd, env, timeoutMs, payload }) {
  return new Promise((resolve) => {
    let stdout = ''
    let stderr = ''
    let settled = false
    let timer
    let child
    const finish = (value) => {
      if (settled) return
      settled = true
      if (timer !== undefined) clearTimeout(timer)
      resolve(value)
    }
    const append = (buffer, chunk) => {
      const next = buffer + chunk
      return next.length > MAX_CAPTURE_BYTES ? next.slice(0, MAX_CAPTURE_BYTES) : next
    }

    try {
      child = spawn('bash', ['-c', command], { cwd, env, stdio: ['pipe', 'pipe', 'pipe'] })
    } catch (error) {
      finish({ code: -1, stdout: '', stderr: `spawn failed: ${error?.message ?? error}`, timedOut: false })
      return
    }
    child.stdout.on('data', (chunk) => { stdout = append(stdout, String(chunk)) })
    child.stderr.on('data', (chunk) => { stderr = append(stderr, String(chunk)) })
    child.on('error', (error) => finish({ code: -1, stdout, stderr: `spawn failed: ${error.message}`, timedOut: false }))
    child.on('close', (code) => finish({ code: code ?? -1, stdout, stderr, timedOut: false }))
    timer = setTimeout(() => {
      try { child.kill('SIGKILL') } catch { /* already gone */ }
      finish({ code: -1, stdout, stderr: `${stderr}\n[timeout after ${timeoutMs}ms]`, timedOut: true })
    }, timeoutMs)

    try {
      child.stdin.write(`${JSON.stringify(payload)}\n`)
      child.stdin.end()
    } catch {
      // A hook that exits without reading stdin closes the pipe; the close
      // handler still reports its real exit code.
    }
  })
}

/** Normalize exec.arguments (may be a JSON string under programmatic calls). */
export function toArgs(argumentsValue) {
  if (argumentsValue === null || argumentsValue === undefined) return {}
  if (typeof argumentsValue === 'string') {
    try {
      return JSON.parse(argumentsValue)
    } catch {
      return {}
    }
  }
  return typeof argumentsValue === 'object' ? argumentsValue : {}
}

/** Resolve the directory a hook should run in (the session workspace). */
export async function resolveHookCwd(ctx, exec) {
  try {
    const workingDirectory = ctx.get('workingDirectory')
    if (workingDirectory !== undefined && workingDirectory !== null && exec.agent !== undefined) {
      const dir = await workingDirectory.get?.(exec.agent.session)
      if (typeof dir === 'string' && dir.length > 0) return dir
    }
  } catch { /* fall through to the session cwd */ }
  return exec.agent?.session?.header?.cwd || process.cwd()
}

/** Map a finished hook into a dsh pre-execute decision (or null to allow). */
export function decideFromResult(result, log, label) {
  const stdout = result.stdout.trim()
  let parsed
  if (stdout.startsWith('{')) {
    try { parsed = JSON.parse(stdout) } catch { parsed = undefined }
  }

  if (result.code === 2) {
    const reason = parsed?.hookSpecificOutput?.permissionDecisionReason
      ?? parsed?.reason
      ?? result.stderr.trim()
      ?? ''
    return { kind: 'deny', reason: reason.length > 0 ? reason : `${label} blocked this tool call` }
  }

  if (parsed !== undefined) {
    const specific = parsed.hookSpecificOutput
    if (specific?.permissionDecision === 'deny') {
      return { kind: 'deny', reason: specific.permissionDecisionReason || `${label} denied this tool call` }
    }
    if (specific?.permissionDecision === 'ask') {
      return { kind: 'ask', reason: specific.permissionDecisionReason || `${label} requires confirmation` }
    }
    if (specific?.permissionDecision === 'allow') return null
    if (parsed.decision === 'block') {
      return { kind: 'deny', reason: parsed.reason || `${label} blocked this tool call` }
    }
  }

  if (result.code !== 0) {
    log.warn(
      `cosight-plugin-compat: ${label} exited ${result.code}${result.timedOut ? ' (timeout)' : ''}: `
      + result.stderr.slice(0, 300),
    )
  }
  return null
}

/**
 * Build the `tools/pre-execute` listener.
 * @returns {(exec: object, next: Function) => Promise<object|undefined>}
 */
export function createPreExecuteHook(ctx, rules, config, log) {
  const configuredTimeout = Number.isFinite(config.hookTimeoutMs) && config.hookTimeoutMs > 0
    ? config.hookTimeoutMs
    : DEFAULT_TIMEOUT_MS

  return async (exec, next) => {
    const name = String(exec?.name ?? '')
    const toolName = claudeToolName(name)
    const matched = rules.filter((rule) => matcherSelects(rule.matcher, toolName))
    if (matched.length === 0) return next()

    const args = toArgs(exec.arguments)
    const cwd = await resolveHookCwd(ctx, exec)
    const payload = {
      session_id: exec.agent?.session?.header?.id ?? 'unknown',
      transcript_path: '',
      cwd,
      hook_event_name: 'PreToolUse',
      tool_name: toolName,
      tool_input: args,
      tool_use_id: exec.callId ?? '',
    }

    for (const rule of matched) {
      const command = expandHookCommand(rule.command, { pluginRoot: rule.pluginRoot, projectDir: cwd })
      const result = await runCommand(command, {
        cwd,
        env: {
          ...process.env,
          CLAUDE_PLUGIN_ROOT: rule.pluginRoot,
          CLAUDE_PROJECT_DIR: cwd,
          CLAUDE_CODE_REMOTE: 'false',
        },
        timeoutMs: Math.min(rule.timeoutMs, configuredTimeout),
        payload,
      })
      const decision = decideFromResult(result, log, `${rule.plugin} hook (${rule.command})`)
      if (decision !== null) return decision
    }

    return next()
  }
}

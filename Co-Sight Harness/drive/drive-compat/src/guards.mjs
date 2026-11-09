/**
 * guards.mjs — pre-execute wiring: tool-name normalization + drive Python guard
 * dispatch + HITL ask hook.
 *
 * Zero dsh-package imports: we only build Claude-shaped payloads and shell out
 * to the untouched drive Python guards. This is what makes the whole layer
 * loadable from a plain ESM file.
 */
import { spawn } from 'node:child_process'

/** dsh tool name -> Claude Code PascalCase tool name. */
export const NORMALIZE = {
  write: 'Write',
  edit: 'Edit',
  // MultiEdit has no dsh counterpart (only str_replace_editor); leave unmapped.
  bash: 'Bash',
  subagent: 'Task', // Claude: Task / Agent spawn tool
  skill: 'Skill',
}

/** Which drive guards run for each (normalized) tool name. */
const GUARDS_BY_TOOL = {
  Write: ['planning_write_guard.py', 'state_transition_guard.py'],
  Edit: ['planning_write_guard.py', 'state_transition_guard.py'],
  Bash: ['state_transition_guard.py', 'audit_events.py'],
  Task: ['audit_events.py'],
  Agent: ['audit_events.py'],
  Skill: ['audit_events.py'],
}

/** Known drive role ids for subagent_type back-fill. */
const ROLE_RE = /(analyzer|planner|executor|evaluator|code-reviewer|security-reviewer|gate-human)/

export function normalizeToolName(name) {
  return NORMALIZE[name] ?? name
}

/** Best-effort subagent_type from drive-style spawn arguments. */
export function backfillSubagentType(args) {
  if (!args || typeof args !== 'object') return 'unknown'
  if (typeof args.subagent_type === 'string' && args.subagent_type) return args.subagent_type
  const hunt = String(args.description ?? args.role ?? args.label ?? '')
  const hit = ROLE_RE.exec(hunt)
  if (hit) return hit[1]
  const prompt = String(args.prompt ?? '')
  const phit = ROLE_RE.exec(prompt)
  if (phit) return phit[1]
  return 'unknown'
}

/** Run one drive guard as a python subprocess; resolves {code, stderr}. */
export function runGuard(scriptPath, payload, cwd) {
  return new Promise((resolve) => {
    let stderr = ''
    let child
    try {
      child = spawn('python3', [scriptPath], { cwd, stdio: ['pipe', 'pipe', 'pipe'] })
    } catch (error) {
      resolve({ code: -1, stderr: String(error?.message ?? error) })
      return
    }
    child.stderr.on('data', (d) => { stderr += String(d) })
    child.on('error', (error) => resolve({ code: -1, stderr: `spawn failed: ${error.message}` }))
    child.on('exit', (code) => resolve({ code: code ?? -1, stderr: stderr.trim() }))
    child.stdin.write(JSON.stringify(payload))
    child.stdin.end()
  })
}

/** Resolve the working directory a drive guard should run in (finds .drive). */
export async function resolveGuardCwd(ctx, exec) {
  try {
    const wd = ctx.get('workingDirectory')
    if (wd && exec.agent) {
      const dir = await wd.get(exec.agent.session)
      if (dir) return dir
    }
  } catch { /* fall through */ }
  return (exec.agent && exec.agent.session && exec.agent.session.header?.cwd) || process.cwd()
}

/** Normalize exec.arguments to a plain object (PTC may hand us a string). */
export function toArgs(argumentsValue) {
  if (argumentsValue == null) return {}
  if (typeof argumentsValue === 'string') {
    try { return JSON.parse(argumentsValue) } catch { return {} }
  }
  return argumentsValue && typeof argumentsValue === 'object' ? argumentsValue : {}
}

/** HITL: should this tool call force a human approval? */
export function isConfirmCommand(normalizedName, args) {
  if (normalizedName !== 'Bash') return false
  const command = String(args?.command ?? '')
  return /confirm_stage\.py\b/.test(command)
      || /confirm-node\b/.test(command)
      || /state_cli(\.py)?\b[^]*\btransition\b/.test(command)
}

/**
 * Main pre-execute listener.
 * @returns a PreToolDecision-shaped object, or undefined to delegate (allow).
 */
export async function decide(ctx, exec, config, log) {
  const name = String(exec.name ?? '')
  const normalized = normalizeToolName(name)
  const args = toArgs(exec.arguments)

  // 1) HITL gate first (before guards, so an ask can never be short-circuited).
  if (config.hitl && isConfirmCommand(normalized, args)) {
    return {
      kind: 'ask',
      reason: `drive-compat(HITL): ${normalized} requires human confirmation (${args.command ?? name})`,
    }
  }

  // 2) Guard pipeline for tools drive actually watches.
  const scripts = config.hooks ? GUARDS_BY_TOOL[normalized] : undefined
  if (!scripts || scripts.length === 0) return undefined

  const driveRoot = config.driveRoot
  const cwd = await resolveGuardCwd(ctx, exec)
  const basePayload = {
    tool_name: normalized,
    session_id: exec.agent?.session?.header?.id ?? 'unknown',
    tool_use_id: exec.callId ?? '',
    cwd,
  }

  for (const script of scripts) {
    const payload = {
      ...basePayload,
      tool_input: normalized === 'Task' || normalized === 'Agent'
        ? { ...args, subagent_type: backfillSubagentType(args) }
        : args,
    }
    const { code, stderr } = await runGuard(
      `${driveRoot}/hooks/${script}`, payload, cwd,
    )
    if (code === 2) {
      return { kind: 'deny', reason: stderr || `blocked by drive guard ${script}` }
    }
    if (code !== 0) {
      // A guard that exits non-zero (but not 2) must not silently pass the
      // model: log it and keep the call allowed, matching audit-only reality.
      log.warn(`drive-compat: guard ${script} exited ${code}: ${stderr.slice(0, 300)}`)
    }
  }
  return undefined
}

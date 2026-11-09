/**
 * agents.mjs — make Claude `agents/*.md` role files usable inside dsh.
 *
 * dsh has no importer for Claude's markdown agent files: an agent is a preset
 * (a `@deepseek-ai/dsh-agent-preset` row listing its plugins), and a Claude
 * role becomes either a dedicated `@deepseek-ai/dsh-tool-subagent` instance
 * (persona + toolFilter) or just prompt text prepended to a spawn. This
 * bridge takes the second route: it re-registers the Claude spawn primitive
 * as a model tool (`Task`, plus `Agent` when that name is still free) and, on
 * each call, prepends the addressed role's markdown body to the task prompt
 * before handing it to a native dsh subagent.
 *
 * Tool-name collision policy: drive-compat already registers `Agent` in the
 * same profile. Registering a second same-name tool would throw, so a taken
 * name is skipped with a warning; `Task` is always attempted and is the
 * canonical entry point for these plugins.
 */
import path from 'node:path'
import fs from 'node:fs'
import {
  expandTokens,
  fieldList,
  fieldString,
  listMarkdown,
  parseFrontmatter,
} from './assets.mjs'

/** Provider preference order for spawns. */
const PROVIDER_ORDER = ['spawn', 'fork']

const EMPTY_OUTPUT = {
  schema: {
    type: 'object',
    additionalProperties: false,
    properties: { ok: { type: 'boolean', const: true } },
    required: ['ok'],
  },
  render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }],
}

/**
 * Index every agent markdown file under `<plugin>/agents`.
 * Keys are lower-cased so `skill-optimizer:Score-Analyzer` still resolves.
 * @returns {{byKey: Map<string, object>, agents: object[]}}
 */
export function collectAgents(plugins, log) {
  const byKey = new Map()
  const agents = []

  const addKey = (key, entry) => {
    const normalized = key.trim().toLowerCase()
    if (normalized.length === 0) return
    const holder = byKey.get(normalized)
    if (holder === undefined) byKey.set(normalized, entry)
    else if (holder !== entry) {
      log.warn(`cosight-plugin-compat: agent key "${key}" already maps to ${holder.plugin}:${holder.file}; ${entry.plugin}:${entry.file} keeps only its other keys`)
    }
  }

  for (const plugin of plugins) {
    for (const fileName of listMarkdown(plugin.agentsDir)) {
      const agentPath = path.join(plugin.agentsDir, fileName)
      let raw
      try {
        raw = fs.readFileSync(agentPath, 'utf8')
      } catch {
        continue
      }
      const { fields, body } = parseFrontmatter(raw)
      const stem = fileName.replace(/\.md$/, '')
      const declaredName = fieldString(fields, 'name') || stem
      const entry = {
        name: declaredName,
        stem,
        file: fileName,
        description: fieldString(fields, 'description'),
        tools: fieldList(fields, 'tools'),
        model: fieldString(fields, 'model'),
        body,
        path: agentPath,
        plugin: plugin.dir,
      }
      agents.push(entry)
      addKey(declaredName, entry)
      addKey(stem, entry)
      addKey(`${plugin.alias}:${declaredName}`, entry)
      addKey(`${plugin.dir}:${declaredName}`, entry)
      addKey(`${plugin.name}:${declaredName}`, entry)
      addKey(`${plugin.dir}/${declaredName}`, entry)
    }
  }

  return { byKey, agents }
}

/** Resolve a `subagent_type` string; undefined when no role matches. */
export function resolveAgent(index, subagentType) {
  if (subagentType === undefined || subagentType === null) return undefined
  const raw = String(subagentType).trim().toLowerCase()
  return raw.length === 0 ? undefined : index.get(raw)
}

/** Build the child prompt: role definition, then the task. */
export function buildAgentPrompt(agent, taskPrompt, pluginRoot) {
  const role = expandTokens(agent.body, { pluginRoot, skillDir: path.dirname(agent.path) })
  return [
    `<!-- cosight-plugin-compat: role "${agent.name}" from ${agent.plugin}/agents/${agent.file} -->`,
    role.trim(),
    '',
    '---',
    '',
    '# 任务',
    '',
    String(taskPrompt ?? ''),
  ].join('\n')
}

/** Pick the first provider the composition actually exposes. */
function pickProvider(subagents) {
  for (const name of PROVIDER_ORDER) {
    if (typeof subagents.getProvider !== 'function') return name
    if (subagents.getProvider(name) !== undefined) return name
  }
  return undefined
}

/** Register one tool, skipping (never throwing) when the name is taken. */
function registerTool(tools, definition, log) {
  const existing = typeof tools.get === 'function' ? tools.get(definition.name) : undefined
  if (existing !== undefined) {
    log.warn(`cosight-plugin-compat: tool "${definition.name}" is already registered by another plugin; the compat shim is skipped`)
    return false
  }
  try {
    tools.register(definition)
    return true
  } catch (error) {
    log.warn(`cosight-plugin-compat: could not register tool "${definition.name}": ${error?.message ?? error}`)
    return false
  }
}

/** The spawn tool shared by the `Task` and `Agent` names. */
function spawnToolDefinition({ ctx, index, name, log }) {
  return {
    name,
    description:
      'Spawn a subagent and wait for its final result. `subagent_type` names a role '
      + 'from the installed Claude plugins (e.g. "score-analyzer", '
      + '"skill-optimizer:skill-evaluator-agent" or "genesis:build-planner"); the role\'s '
      + 'markdown definition is prepended to the prompt. Unknown types run as a plain '
      + 'subagent. Equivalent to Claude Code Agent/Task with run_in_background=false.',
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        subagent_type: { type: 'string', description: 'Claude agent role id, optionally <plugin>:<name>.' },
        prompt: { type: 'string', description: 'Full task prompt for the subagent.' },
        description: { type: 'string', description: 'Short 3-5 word label.' },
        run_in_background: { type: 'boolean', description: 'Accepted for compatibility; this shim always waits.' },
        cwd: { type: 'string', description: 'Optional child working directory.' },
      },
      required: ['prompt'],
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          ok: { type: 'boolean' },
          subagentId: { type: 'string' },
          stopReason: { type: 'string' },
          agent: { type: 'string' },
          result: { type: 'string' },
        },
        required: ['ok', 'subagentId', 'stopReason', 'agent', 'result'],
      },
      render: (_args, value) => [{ type: 'text', text: value.result ?? JSON.stringify(value) }],
    },
    async execute(args, exec) {
      const subagents = ctx.get('subagents')
      if (subagents === undefined || subagents === null) {
        throw new Error(`${name} shim: ctx.subagents is unavailable in this composition; use the native \`subagent\` tool instead`)
      }
      if (exec?.agent === undefined) {
        throw new Error(`${name} shim: no live parent agent in this execution context`)
      }
      const agent = resolveAgent(index, args?.subagent_type)
      if (agent === undefined && args?.subagent_type) {
        log.warn(`cosight-plugin-compat: unknown subagent_type "${args.subagent_type}"; spawning without a role definition`)
      }
      const provider = pickProvider(subagents)
      if (provider === undefined) {
        throw new Error(`${name} shim: no subagent provider is registered (expected one of: ${PROVIDER_ORDER.join(', ')})`)
      }
      const text = agent === undefined
        ? String(args?.prompt ?? '')
        : buildAgentPrompt(agent, args?.prompt, path.resolve(agent.path, '..', '..'))
      let activation
      try {
        activation = await subagents.startActivation({
          provider,
          label: args?.description || agent?.name || args?.subagent_type || 'cosight-agent',
          request: {
            prompt: [{ type: 'text', text }],
            parent: exec.agent,
            ...(args?.cwd ? { cwd: args.cwd } : {}),
          },
          signal: exec.signal,
          delivery: 'caller',
        })
      } catch (error) {
        throw new Error(`${name} shim: could not start subagent on "${provider}": ${error?.message ?? error}`)
      }
      const result = await activation.result
      const output = (result.output ?? [])
        .filter((block) => block !== null && typeof block === 'object' && block.type === 'text')
        .map((block) => block.text)
        .join('\n')
      return {
        ok: result.stopReason === 'completed',
        subagentId: String(activation.childId ?? ''),
        stopReason: result.stopReason ?? 'unknown',
        agent: agent?.name ?? 'generic',
        result: output,
      }
    },
  }
}

/** TodoWrite — Claude progress bookkeeping; dsh persists its own todo state. */
function todoWriteDefinition() {
  return {
    name: 'TodoWrite',
    description: 'Record a Claude-style progress checklist (compatibility no-op; dsh tracks todos natively).',
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        todos: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              content: { type: 'string' },
              status: { type: 'string', enum: ['pending', 'in_progress', 'completed'] },
            },
            required: ['content', 'status'],
          },
        },
      },
      required: ['todos'],
    },
    output: EMPTY_OUTPUT,
    execute: async () => ({ ok: true }),
  }
}

/** AskUserQuestion — nudge the model to dsh's native, host-answered tool. */
function askUserQuestionDefinition() {
  return {
    name: 'AskUserQuestion',
    description:
      'Ask the user a question (compatibility shim). The native dsh tool is '
      + '`ask_user_question` (lowercase) with the same payload — call that one instead.',
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        questions: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              id: { type: 'string' },
              header: { type: 'string' },
              question: { type: 'string' },
              options: {
                type: 'array',
                items: {
                  type: 'object',
                  properties: { label: { type: 'string' }, description: { type: 'string' } },
                  required: ['label'],
                },
              },
            },
            required: ['id', 'question'],
          },
        },
      },
      required: ['questions'],
    },
    output: EMPTY_OUTPUT,
    execute: async () => {
      throw new Error('cosight-plugin-compat: use the native `ask_user_question` tool for this confirmation (same payload)')
    },
  }
}

/**
 * Register the shim tools.
 *
 * Only `Task` is registered by default. `Agent`, `TodoWrite` and
 * `AskUserQuestion` are already owned by drive-compat, which is installed
 * alongside this package; plugin fibers activate concurrently, so checking
 * `tools.get()` first is not enough — both sides could see the name free and
 * the loser's `register` throws, taking the whole plugin down. Registering a
 * disjoint set is the only race-free arrangement.
 *
 * `config.extraShims: true` opts into the other three for profiles that do
 * NOT install drive-compat (best effort: a taken name is skipped).
 *
 * @returns {{registered: string[], skipped: string[]}}
 */
export function registerShims(ctx, agentIndex, config, log) {
  const tools = ctx.get('tools') ?? ctx.tools
  if (tools === undefined || tools === null) {
    log.error('cosight-plugin-compat: ctx.tools is unavailable; agent shims are DISABLED')
    return { registered: [], skipped: [] }
  }
  if (config.shims === false) return { registered: [], skipped: [] }

  const registered = []
  const skipped = []
  const attempt = (definition) => {
    if (registerTool(tools, definition, log)) registered.push(definition.name)
    else skipped.push(definition.name)
  }

  attempt(spawnToolDefinition({ ctx, index: agentIndex, name: 'Task', log }))
  if (config.extraShims === true) {
    attempt(spawnToolDefinition({ ctx, index: agentIndex, name: 'Agent', log }))
    attempt(todoWriteDefinition())
    attempt(askUserQuestionDefinition())
  }
  return { registered, skipped }
}

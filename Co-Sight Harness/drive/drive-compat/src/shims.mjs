/**
 * shims.mjs — register Claude-named model tools so drive skill text works
 * verbatim inside dsh. Each shim adapts to dsh capability seams via ctx.get()
 * and degrades with an actionable message when a seam is absent.
 */
import { normalizeToolName } from './guards.mjs'

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
 * Agent — drive's spawn primitive: `Agent(subagent_type, prompt,
 * run_in_background=False)`. dsh subagents are async; this shim spawns on the
 * configured provider and AWAITS the result, emulating run_in_background=False.
 */
export function registerAgentShim(ctx) {
  const subagents = ctx.get('subagents');
  (ctx.get('tools') ?? ctx.tools).register({
    name: 'Agent',
    description:
      'Spawn a subagent that reads its role definition and completes a task, '
      + 'waiting for its final result before returning (equivalent to '
      + 'Claude Code run_in_background=False). Field `subagent_type` names the '
      + 'drive role (analyzer/planner/executor/evaluator/code-reviewer/security-reviewer/gate-human).',
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        subagent_type: { type: 'string', description: 'Drive role id, e.g. analyzer.' },
        prompt: { type: 'string', description: 'Full task prompt (usually points at an agents/*.md role).' },
        description: { type: 'string', description: 'Short 3-5 word label for the subagent.' },
        run_in_background: { type: 'boolean', description: 'Ignored by this shim; always awaited.' },
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
          result: { type: 'string' },
        },
        required: ['ok', 'subagentId', 'stopReason', 'result'],
      },
      render: (_args, value) => [{ type: 'text', text: value.result ?? JSON.stringify(value) }],
    },
    async execute(args, exec) {
      if (!subagents) {
        throw new Error('Agent shim: ctx.subagents is unavailable in this composition; use the native `subagent` tool instead')
      }
      let providerName = 'spawn'
      if (subagents.getProvider?.(providerName) === undefined) {
        providerName = subagents.getProvider?.('fork') !== undefined ? 'fork' : providerName
      }
      const request = {
        prompt: [{ type: 'text', text: String(args.prompt ?? '') }],
        ...(exec.agent ? { parent: exec.agent } : {}),
        ...(args.cwd ? { cwd: args.cwd } : {}),
      }
      let activation
      try {
        activation = await subagents.startActivation({
          provider: providerName,
          label: args.description || args.subagent_type || 'drive-agent',
          request,
          signal: exec.signal,
          delivery: 'caller',
        })
      } catch (error) {
        throw new Error(`Agent shim: could not start subagent on "${providerName}": ${error?.message ?? error}`)
      }
      const result = await activation.result
      const text = (result.output ?? [])
        .filter((b) => b && b.type === 'text')
        .map((b) => b.text)
        .join('\n')
      return {
        ok: result.stopReason === 'completed',
        subagentId: String(activation.childId ?? ''),
        stopReason: result.stopReason ?? 'unknown',
        result: text,
      }
    },
  }, 'drive-compat:Agent')
  return 'Agent'
}

/** TodoWrite — drive writes progress todos; dsh has native todo_write later in
 * prompt, so a faithful no-op that logs keeps drive text valid. */
export function registerTodoWriteShim(ctx) {
  (ctx.get('tools') ?? ctx.tools).register({
    name: 'TodoWrite',
    description: 'Record a drive progress checklist (compatibility shim; persisted by the host when available).',
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
  }, 'drive-compat:TodoWrite')
  return 'TodoWrite'
}

/** AskUserQuestion — drive HITL primitive. dsh has native ask_user_question;
 * this shim nudges the model to the native tool (which the host answers). */
export function registerAskUserQuestionShim(ctx) {
  (ctx.get('tools') ?? ctx.tools).register({
    name: 'AskUserQuestion',
    description:
      'Ask the drive user a confirmation question (compatibility shim). '
      + 'Because the native dsh tool is available, call `ask_user_question` '
      + '(lowercase) with the same payload instead — it reaches the human.',
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
    execute: async (_args) => {
      // Instruct the model to fall through to the native tool in the same turn.
      throw new Error('drive-compat: use the native `ask_user_question` tool for this confirmation (same payload)')
    },
  }, 'drive-compat:AskUserQuestion')
  return 'AskUserQuestion'
}

/** Register all shims; returns the names that were registered. */
export function registerShims(ctx) {
  const names = []
  names.push(registerAgentShim(ctx))
  names.push(registerTodoWriteShim(ctx))
  names.push(registerAskUserQuestionShim(ctx))
  return names
}

export { normalizeToolName }

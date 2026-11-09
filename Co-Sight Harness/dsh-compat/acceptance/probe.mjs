#!/usr/bin/env node
/**
 * probe.mjs — offline acceptance probe for cosight-plugin-compat.
 *
 * Runs with plain `node` (no dsh, no install, no build): it drives the
 * package's own modules through stub `ctx` objects that mimic the dsh
 * composition API, then executes the real agent-genesis guard script to prove
 * the hook bridge maps exit codes correctly.
 *
 *   node dsh-compat/acceptance/probe.mjs        # human summary
 *   node dsh-compat/acceptance/probe.mjs --json # machine summary
 *
 * Exit code 0 = every check passed, 1 = at least one failure.
 */
import assert from 'node:assert/strict'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { loadPlugins, resolvePluginsRoot } from '../src/assets.mjs'
import { collectAgents, resolveAgent } from '../src/agents.mjs'
import { fieldString, parseFrontmatter } from '../src/frontmatter.mjs'
import {
  claudeToolName,
  createPreExecuteHook,
  decideFromResult,
  loadHookRules,
  matcherSelects,
} from '../src/hooks.mjs'
import { compose } from '../src/index.mjs'
import { isValidName, normalizeName } from '../src/naming.mjs'
import { collectSkills } from '../src/skills.mjs'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const PKG_DIR = path.resolve(HERE, '..')
// Same precedence the plugin uses at mount time: packaged plugin-assets/ when
// present, otherwise the development layout (repo root above this package).
const { root: PLUGINS_ROOT, source: PLUGINS_ROOT_SOURCE } = resolvePluginsRoot({}, PKG_DIR)
const JSON_MODE = process.argv.includes('--json')

/** Collect log lines instead of printing them. */
function makeLogger() {
  const lines = []
  const push = (level) => (message) => lines.push({ level, message: String(message) })
  return { lines, info: push('info'), warn: push('warn'), error: push('error') }
}

/** Minimal composition stub: only the surfaces the package touches. */
function makeCtx({ seedTools = [] } = {}) {
  const logger = makeLogger()
  const registeredSkills = []
  const registeredTools = new Map()
  for (const name of seedTools) registeredTools.set(name, { name })
  const listeners = []

  const skills = {
    register(definition) {
      registeredSkills.push(definition)
    },
  }
  const tools = {
    get(name) {
      return registeredTools.get(name)
    },
    register(definition) {
      if (registeredTools.has(definition.name)) {
        throw new Error(`tool already registered: ${definition.name}`)
      }
      registeredTools.set(definition.name, definition)
    },
  }

  return {
    logger,
    skills,
    tools,
    listeners,
    registeredSkills,
    registeredTools,
    get(key) {
      if (key === 'skills') return skills
      if (key === 'tools') return tools
      return undefined
    },
    on(event, listener) {
      listeners.push({ event, listener })
    },
  }
}

const results = []

async function check(name, fn) {
  try {
    await fn()
    results.push({ name, ok: true })
  } catch (error) {
    results.push({ name, ok: false, error: String(error?.message ?? error) })
  }
}

// ---------------------------------------------------------------- frontmatter
await check('frontmatter: folded description and flow sequence', () => {
  const { fields, body, hasFrontmatter } = parseFrontmatter(
    '---\nname: demo\ndescription: >\n  first line\n  second line\ntools: [Read, Write]\n---\nbody text\n',
  )
  assert.equal(hasFrontmatter, true)
  assert.equal(fieldString(fields, 'name'), 'demo')
  assert.equal(fieldString(fields, 'description'), 'first line second line')
  assert.deepEqual(fields.tools, ['Read', 'Write'])
  assert.equal(body.trim(), 'body text')
})

// --------------------------------------------------------------------- naming
await check('naming: CJK and underscore names become valid dsh ids', () => {
  assert.equal(normalizeName('编码原则', 'fallback'), 'coding-principles')
  assert.equal(normalizeName('skill_optimize', 'fallback'), 'skill-optimize')
  assert.equal(normalizeName('dev-off', 'fallback'), 'dev-off')
  assert.ok(isValidName('goldeval-e2e-test-runner'))
})

// ------------------------------------------------------------------- plugins
const logger = makeLogger()
const plugins = loadPlugins(PLUGINS_ROOT, undefined, logger)
const genesis = plugins.find((plugin) => plugin.dir === 'agent-genesis')

await check('plugins: all four payloads load from the repo root', () => {
  assert.deepEqual(plugins.map((plugin) => plugin.dir).sort(), [
    'agent-evaluator',
    'agent-genesis',
    'cosight-bot',
    'skill-optimizer',
  ])
})

await check('plugins: agent-genesis exposes its PreToolUse hook file', () => {
  assert.ok(genesis !== undefined)
  assert.ok(genesis.hooksFile !== null)
  assert.ok(genesis.hooksFile.endsWith(path.join('hooks', 'hooks.json')))
})

// -------------------------------------------------------------------- skills
const collected = collectSkills(plugins, logger)

await check('skills: every mounted name satisfies the dsh grammar', () => {
  const names = [...collected.skills, ...collected.commands].map((entry) => entry.name)
  assert.ok(names.length > 0)
  for (const name of names) assert.ok(isValidName(name), `invalid name: ${name}`)
})

await check('skills: duplicate e2e-test-runner is renamed, not dropped', () => {
  const names = new Set(collected.skills.map((entry) => entry.name))
  assert.ok(names.has('e2e-test-runner'), 'agent-genesis keeps the plain name')
  assert.ok(names.has('goldeval-e2e-test-runner'), 'agent-evaluator survivor is prefixed')
})

await check('skills: CJK skill is mounted under its documented alias', () => {
  assert.ok(collected.skills.some((entry) => entry.name === 'coding-principles'))
})

await check('skills: cosight-bot payload mounts its PKM/SOC skills', () => {
  const names = new Set(collected.skills.map((entry) => entry.name))
  for (const expected of ['pkm-expert', 'soc-expert', 'cosightbot-retrieve']) {
    assert.ok(names.has(expected), `${expected} missing`)
  }
})

await check('skills: all eleven Claude commands become user-invocable skills', () => {
  const commandNames = collected.commands.map((entry) => entry.name).sort()
  assert.deepEqual(commandNames, [
    'dev',
    'dev-off',
    // harness-create 命令与同名技能冲突，命令侧按「先到先得」前缀改名
    'genesis-harness-create',
    'pkm',
    'retrieve',
    'selftest',
    'skill-create',
    'skill-evolve',
    'skill-optimize',
    'soc',
    'soc-pipeline',
  ])
  for (const command of collected.commands) {
    assert.equal(command.invocation.modelInvocable, false)
    assert.equal(command.invocation.userInvocable, true)
  }
})

await check('skills: plugin-root tokens are expanded before mounting', () => {
  const all = [...collected.skills, ...collected.commands]
  for (const entry of all) {
    assert.ok(!entry.content.includes('${CLAUDE_PLUGIN_ROOT}'), `${entry.name} kept CLAUDE_PLUGIN_ROOT`)
    assert.ok(!entry.content.includes('${PLUGIN_ROOT}'), `${entry.name} kept PLUGIN_ROOT`)
    assert.ok(!entry.content.includes('$CLAUDE_PLUGIN_ROOT'), `${entry.name} kept $CLAUDE_PLUGIN_ROOT`)
  }
})

// -------------------------------------------------------------------- agents
const agentIndex = collectAgents(plugins, logger)

await check('agents: every declared role resolves by name and by plugin prefix', () => {
  assert.ok(agentIndex.agents.length > 0)
  for (const agent of agentIndex.agents) {
    assert.equal(resolveAgent(agentIndex.byKey, agent.name), agent, `bare name: ${agent.name}`)
    assert.equal(
      resolveAgent(agentIndex.byKey, `${agent.plugin}:${agent.name}`),
      agent,
      `prefixed name: ${agent.plugin}:${agent.name}`,
    )
  }
})

await check('agents: lookup is case-insensitive and rejects unknown types', () => {
  const sample = agentIndex.agents[0]
  assert.equal(resolveAgent(agentIndex.byKey, sample.name.toUpperCase()), sample)
  assert.equal(resolveAgent(agentIndex.byKey, 'no-such-role-xyz'), undefined)
  assert.equal(resolveAgent(agentIndex.byKey, undefined), undefined)
})

// --------------------------------------------------------------------- hooks
const rules = plugins.flatMap((plugin) => loadHookRules(plugin, logger))

await check('hooks: one command rule is discovered (agent-genesis)', () => {
  assert.equal(rules.length, 1)
  assert.equal(rules[0].matcher, 'Write|Edit')
  assert.ok(rules[0].command.includes('guard-self-modify.py'))
  assert.equal(rules[0].timeoutMs, 60_000)
})

await check('hooks: Claude matcher is case-sensitive and pipe-aware', () => {
  assert.equal(matcherSelects('Write|Edit', 'Write'), true)
  assert.equal(matcherSelects('Write|Edit', 'Edit'), true)
  assert.equal(matcherSelects('Write|Edit', 'Bash'), false)
  assert.equal(matcherSelects('write|edit', 'Write'), false)
  assert.equal(matcherSelects(undefined, 'Anything'), true)
  assert.equal(matcherSelects('Bash', 'Bash'), true)
})

await check('hooks: dsh tool names map to Claude tool names', () => {
  assert.equal(claudeToolName('write'), 'Write')
  assert.equal(claudeToolName('edit'), 'Edit')
  assert.equal(claudeToolName('bash'), 'Bash')
  assert.equal(claudeToolName('Skill'), 'Skill')
})

await check('hooks: decision mapping covers exit 2, allow, ask and legacy block', () => {
  const quiet = makeLogger()
  assert.equal(decideFromResult({ code: 0, stdout: '', stderr: '' }, quiet, 'probe'), null)
  assert.equal(decideFromResult({ code: 2, stdout: '', stderr: 'nope' }, quiet, 'probe').kind, 'deny')
  assert.equal(
    decideFromResult({ code: 0, stdout: JSON.stringify({ hookSpecificOutput: { permissionDecision: 'allow' } }), stderr: '' }, quiet, 'probe'),
    null,
  )
  assert.equal(
    decideFromResult({ code: 0, stdout: JSON.stringify({ hookSpecificOutput: { permissionDecision: 'ask' } }), stderr: '' }, quiet, 'probe').kind,
    'ask',
  )
  assert.equal(
    decideFromResult({ code: 0, stdout: JSON.stringify({ decision: 'block', reason: 'no' }), stderr: '' }, quiet, 'probe').kind,
    'deny',
  )
})

// Real hook script: a write inside the plugin root must be denied.
await check('hooks: real guard denies a self-modifying write', async () => {
  const ctx = makeCtx()
  const listener = createPreExecuteHook(ctx, rules, {}, makeLogger())
  const SENTINEL = { kind: 'sentinel' }
  const decision = await listener(
    {
      name: 'write',
      arguments: { file_path: path.join(genesis.root, 'agents', 'probe-guard.md') },
      callId: 'probe-1',
      agent: { session: { header: { id: 'probe-session', cwd: PLUGINS_ROOT } } },
    },
    () => SENTINEL,
  )
  assert.equal(decision?.kind, 'deny')
  assert.match(String(decision.reason), /BLOCKED|受保护/)
})

await check('hooks: real guard allows a write outside the plugin root', async () => {
  const ctx = makeCtx()
  const listener = createPreExecuteHook(ctx, rules, {}, makeLogger())
  const SENTINEL = { kind: 'sentinel' }
  const decision = await listener(
    {
      name: 'write',
      arguments: { file_path: path.join(HERE, 'scratch.md') },
      callId: 'probe-2',
      agent: { session: { header: { id: 'probe-session', cwd: PKG_DIR } } },
    },
    () => SENTINEL,
  )
  assert.equal(decision, SENTINEL)
})

// --------------------------------------------------------------------- apply
await check('apply: full composition mounts skills, shims and the hook layer', async () => {
  const ctx = makeCtx()
  const report = await compose(ctx, { pluginsRoot: PLUGINS_ROOT, hooks: true, skills: true, shims: true })
  assert.equal(report.plugins.length, 4)
  assert.equal(report.skills, collected.skills.length)
  assert.equal(report.commands, collected.commands.length)
  assert.equal(ctx.registeredSkills.length, collected.skills.length + collected.commands.length)
  assert.deepEqual(report.shims.registered, ['Task'])
  assert.equal(report.hooks.active, true)
  assert.equal(report.hooks.rules, 1)
  assert.equal(ctx.listeners.filter((entry) => entry.event === 'tools/pre-execute').length, 1)
  assert.equal(report.skipped.length, 0)
})

await check('apply: default shims do not contend with drive-compat tool names', async () => {
  const ctx = makeCtx({ seedTools: ['Agent', 'TodoWrite', 'AskUserQuestion'] })
  const report = await compose(ctx, { pluginsRoot: PLUGINS_ROOT, hooks: false, skills: false, shims: true })
  assert.deepEqual(report.shims.registered, ['Task'])
  assert.deepEqual(report.shims.skipped, [])
  assert.equal(ctx.listeners.length, 0)
})

await check('apply: extraShims registers the remaining Claude tool names', async () => {
  const ctx = makeCtx()
  const report = await compose(ctx, { pluginsRoot: PLUGINS_ROOT, hooks: false, skills: false, shims: true, extraShims: true })
  assert.deepEqual(report.shims.registered.slice().sort(), ['Agent', 'AskUserQuestion', 'Task', 'TodoWrite'])
})

await check('apply: extraShims skips a name that is already taken', async () => {
  const ctx = makeCtx({ seedTools: ['Agent'] })
  const report = await compose(ctx, { pluginsRoot: PLUGINS_ROOT, hooks: false, skills: false, shims: true, extraShims: true })
  assert.deepEqual(report.shims.skipped, ['Agent'])
  assert.ok(report.shims.registered.includes('Task'))
})

await check('apply: a missing plugins root fails loud and mounts nothing', async () => {
  const ctx = makeCtx()
  const report = await compose(ctx, { pluginsRoot: path.join(PKG_DIR, 'no-such-dir'), hooks: true, skills: true, shims: true })
  assert.equal(report.plugins.length, 0)
  assert.equal(ctx.registeredSkills.length, 0)
  assert.ok(ctx.logger.lines.some((line) => line.level === 'error'))
})

// -------------------------------------------------------------------- report
const failed = results.filter((result) => !result.ok)

if (JSON_MODE) {
  process.stdout.write(`${JSON.stringify({
    ok: failed.length === 0,
    total: results.length,
    failed: failed.length,
    results,
  }, null, 2)}\n`)
} else {
  for (const result of results) {
    process.stdout.write(`${result.ok ? 'PASS' : 'FAIL'}  ${result.name}\n`)
    if (!result.ok) process.stdout.write(`      ${result.error}\n`)
  }
  const warnings = logger.lines.filter((line) => line.level === 'warn')
  if (warnings.length > 0) {
    process.stdout.write(`\n${warnings.length} loader warning(s):\n`)
    for (const warning of warnings.slice(0, 10)) process.stdout.write(`  - ${warning.message}\n`)
  }
  process.stdout.write(`\n${results.length - failed.length}/${results.length} checks passed\n`)
}

process.exit(failed.length === 0 ? 0 : 1)

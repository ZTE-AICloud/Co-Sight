/**
 * index.mjs — cosight-plugin-compat entry.
 *
 * Mounts the four Claude Code plugins that ship next to this package
 * (agent-genesis, agent-evaluator/goldeval, skill-optimizer, cosight-bot)
 * inside
 * DeepSeek Harness, without modifying a single file of theirs:
 *
 *   skills/<name>/SKILL.md   -> dsh skill           (model + user invocable)
 *   commands/<name>.md       -> dsh skill           (user invocable, `/name`)
 *   agents/<name>.md         -> `Task`/`Agent` shim (role body + spawn)
 *   hooks/hooks.json         -> tools/pre-execute   (PreToolUse command hooks)
 *
 * Zero imports from dsh packages: everything arrives through `ctx` and the
 * profile `config`, so the file loads as plain ESM with no build step.
 * drive-compat (which mounts drive itself) is a sibling, not a dependency;
 * both register `Agent`/`TodoWrite`/`AskUserQuestion`, and this package skips
 * any tool name already taken instead of throwing.
 */
import path from 'node:path'
import { loadPlugins, resolvePluginsRoot } from './assets.mjs'
import { collectAgents, registerShims } from './agents.mjs'
import { createPreExecuteHook, loadHookRules } from './hooks.mjs'
import { collectSkills, mountSkills } from './skills.mjs'

export const name = 'cosight-plugin-compat'
export const inject = ['tools']

/** Readable summary of what the layers did, returned for logs and probes. */
function emptyReport(root, source) {
  return {
    pluginsRoot: root,
    pluginsRootSource: source,
    plugins: [],
    skills: 0,
    commands: 0,
    shims: { registered: [], skipped: [] },
    hooks: { rules: 0, active: false },
    skipped: [],
  }
}

/**
 * Fail loud, never silently: an un-paired or relocated package must be
 * visible in the host log instead of quietly mounting nothing.
 */
function validatePlugins(ctx, plugins, root) {
  if (plugins.length > 0) return true
  ctx.logger.error(
    `cosight-plugin-compat: no plugin payload found under ${root}. `
    + 'Expected agent-genesis/, agent-evaluator/, skill-optimizer/ and '
    + 'cosight-bot/ (or the packaged plugin-assets/) to sit there. '
    + 'Skills, commands, agents and '
    + 'hooks are DISABLED. Fix config.pluginsRoot, COSIGHT_COMPAT_PLUGINS_ROOT, '
    + 'or re-run the installer.',
  )
  return false
}

/**
 * Mount every layer and return a report describing what happened.
 * Exported separately from `apply` so the acceptance probe can inspect the
 * result: cordis treats `apply`'s return value as an effect, so it may only
 * be a disposer (returning a plain object fails with `TypeError: Invalid
 * effect`).
 */
export async function compose(ctx, config = {}) {
  const pkgDir = path.resolve(import.meta.dirname, '..')
  const { root, source } = resolvePluginsRoot(config, pkgDir)
  const report = emptyReport(root, source)

  const plugins = loadPlugins(root, config.plugins, ctx.logger)
  report.plugins = plugins.map((plugin) => ({
    dir: plugin.dir,
    name: plugin.name,
    version: plugin.version,
  }))
  const valid = validatePlugins(ctx, plugins, root)

  const want = {
    skills: config.skills !== false,
    shims: config.shims !== false,
    hooks: config.hooks !== false,
  }
  ctx.logger.info(
    `cosight-plugin-compat: mounting (root=${root} via ${source}, `
    + `plugins=${plugins.map((plugin) => plugin.dir).join(',') || 'none'}, `
    + `valid=${valid}, ${JSON.stringify(want)})`,
  )
  if (!valid) return report

  // 1) skills + commands: dsh runtime skills, tokens expanded at mount time.
  if (want.skills) {
    const skillsCtx = ctx.get('skills') ?? ctx.skills
    if (skillsCtx === undefined || skillsCtx === null) {
      ctx.logger.warn('cosight-plugin-compat: skills requested but ctx.skills is absent; skipped')
    } else {
      const collected = collectSkills(plugins, ctx.logger)
      const mounted = mountSkills(ctx, [...collected.skills, ...collected.commands], ctx.logger)
      report.skills = collected.skills.length
      report.commands = collected.commands.length
      report.skipped = collected.skipped
      ctx.logger.info(
        `cosight-plugin-compat: mounted ${mounted.mounted} skills/commands `
        + `(${collected.skills.length} skills, ${collected.commands.length} commands, `
        + `${mounted.failed.length} failed, ${collected.skipped.length} skipped)`,
      )
    }
  }

  // 2) agent shims: `Task`/`Agent` resolving Claude agent roles.
  if (want.shims) {
    const agentIndex = collectAgents(plugins, ctx.logger)
    report.shims = registerShims(ctx, agentIndex.byKey, config, ctx.logger)
    ctx.logger.info(
      `cosight-plugin-compat: agent roles=${agentIndex.agents.length}, `
      + `shims registered=[${report.shims.registered.join(', ')}], `
      + `skipped=[${report.shims.skipped.join(', ')}]`,
    )
  }

  // 3) PreToolUse command hooks on the pre-execute waterfall.
  if (want.hooks) {
    const rules = plugins.flatMap((plugin) => loadHookRules(plugin, ctx.logger))
    report.hooks = { rules: rules.length, active: rules.length > 0 }
    if (rules.length > 0) {
      ctx.on('tools/pre-execute', createPreExecuteHook(ctx, rules, config, ctx.logger))
      ctx.logger.info(
        `cosight-plugin-compat: ${rules.length} PreToolUse hook rule(s) active: `
        + rules.map((rule) => `${rule.plugin}[${rule.matcher ?? '*'}]`).join(', '),
      )
    }
  }

  return report
}

/**
 * cordis entry point. The return value must be `void` or a disposer; all
 * registrations above are ctx-scoped and disposed with the owning fiber.
 */
export async function apply(ctx, config = {}) {
  await compose(ctx, config)
  return () => {}
}

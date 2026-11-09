/**
 * index.mjs — drive-compat plugin entry.
 *
 * Zero runtime imports from dsh packages: the plugin receives everything it
 * needs through the cordis `ctx` and the `config` its profile patch provides.
 * This keeps it loadable from a plain ESM file (no install, no build).
 */
import fs from 'node:fs'
import path from 'node:path'
import { decide } from './guards.mjs'
import { mountSkills } from './skills.mjs'
import { registerShims } from './shims.mjs'

export const name = 'drive-compat'
export const inject = ['tools']

/**
 * Resolve the drive assets root (a directory holding hooks/ + skills/).
 *
 * Precedence:
 *   1. explicit config.driveRoot (unless the 'AUTO' sentinel — see below)
 *   2. env DRIVE_COMPAT_DRIVE_ROOT
 *   3. self-contained published bundle: <pkg>/drive-assets (pack.sh embeds
 *      drive's hooks/skills/agents here, so a third party needs no drive repo)
 *   4. development layout: <drive>/drive-compat/src  ->  <drive>
 *
 * 'AUTO' is written by install.sh for a published package: skip the external
 * override and let the plugin prefer its in-package drive-assets.
 */
export function resolveDriveRoot(config) {
  const explicit = config.driveRoot
  if (explicit && explicit !== 'AUTO') return explicit
  if (process.env.DRIVE_COMPAT_DRIVE_ROOT) return process.env.DRIVE_COMPAT_DRIVE_ROOT
  const inPackage = path.resolve(import.meta.dirname, '..', 'drive-assets')
  if (pathExists(path.join(inPackage, 'hooks'))) return inPackage
  return path.resolve(import.meta.dirname, '..', '..')
}

function pathExists(p) {
  try { fs.statSync(p); return true } catch { return false }
}

/**
 * Fail loud, never silently: if the resolved drive root does not actually hold
 * the drive payload (hooks/ + skills/), log a clear error so an un-paired or
 * relocated plugin is discovered instead of quietly disabling guards.
 */
export function validateDriveRoot(ctx, driveRoot) {
  const hasHooks = ['hooks.json', 'planning_write_guard.py', 'state_transition_guard.py', 'audit_events.py', 'subagent_report_guard.py']
    .some((f) => pathExists(path.join(driveRoot, 'hooks', f)))
  const hasSkills = pathExists(path.join(driveRoot, 'skills'))
  if (!hasHooks || !hasSkills) {
    ctx.logger.error(
      `drive-compat: resolved driveRoot ${driveRoot} is missing the drive payload `
      + `(hooks=${hasHooks}, skills=${hasSkills}). Guards and skills are DISABLED. `
      + `Expected one of: an installed published bundle (drive-assets inside the `
      + `package), a drive repo layout (<drive>/drive-compat/src), an explicit `
      + `config.driveRoot, or DRIVE_COMPAT_DRIVE_ROOT.`,
    )
    return false
  }
  return true
}

export async function apply(ctx, config = {}) {
  const driveRoot = resolveDriveRoot(config)
  const valid = validateDriveRoot(ctx, driveRoot)
  const want = {
    hooks: config.hooks !== false,
    hitl: config.hitl !== false,
    skills: config.skills !== false,
    shims: config.shims !== false,
  }
  ctx.logger.info(`drive-compat: mounting (driveRoot=${driveRoot}, valid=${valid}, ${JSON.stringify(want)})`)

  // If the drive payload is not paired, disable the layers that need it.
  // (Agent shim runs off ctx.subagents and stays available regardless.)
  const effective = {
    hooks: valid && want.hooks,
    hitl: valid && want.hitl,
    skills: valid && want.skills,
    shims: want.shims,
  }

  // 1) pre-execute waterfall: normalization + drive guards + HITL ask.
  if (effective.hooks || effective.hitl) {
    ctx.on('tools/pre-execute', async (exec, next) => {
      const decision = await decide(
        ctx, exec,
        { driveRoot, hooks: effective.hooks, hitl: effective.hitl },
        ctx.logger,
      )
      return decision ?? next()
    })
  }

  // 2) skills: mount drive/skills/* with ${CLAUDE_*} expansion.
  const skills = ctx.get('skills') ?? ctx.skills
  if (effective.skills && skills) {
    const n = await mountSkills(ctx, driveRoot)
    ctx.logger.info(`drive-compat: mounted ${n} drive skills`)
  } else if (want.skills && !skills) {
    ctx.logger.warn('drive-compat: skills requested but ctx.skills is absent; skipped')
  }

  // 3) shims: Claude-named model tools.
  const tools = ctx.get('tools') ?? ctx.tools
  if (effective.shims && tools) {
    const names = registerShims(ctx)
    ctx.logger.info(`drive-compat: registered shim tools: ${names.join(', ')}`)
  }

  return () => { /* registrations are ctx.effect-scoped; explicit disposer optional */ }
}

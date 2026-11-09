/**
 * assets.mjs — locate the Claude plugin trees this bridge mounts and expand
 * the Claude-only path tokens inside their text.
 *
 * Zero dsh imports: everything is filesystem + string work so the module can
 * be loaded by a plain ESM package or exercised by the offline probe.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fieldList, fieldString, parseFrontmatter } from './frontmatter.mjs'

/**
 * The plugins this bridge knows how to mount. `dir` is the repository
 * directory, `alias` is the short prefix used for collision renames and
 * `<alias>:<agent>` references, and `kind` is the human label used in logs.
 */
export const PLUGIN_DEFS = [
  { dir: 'agent-genesis', alias: 'genesis', kind: 'AgentGenesis' },
  { dir: 'agent-evaluator', alias: 'goldeval', kind: 'goldeval' },
  { dir: 'skill-optimizer', alias: 'skillx', kind: 'Skill Optimizer' },
  { dir: 'cosight-bot', alias: 'cosightbot', kind: 'CoSightBot' },
]

const TOKEN_CLAUDE_ROOT = '${CLAUDE_PLUGIN_ROOT}'
const TOKEN_PLUGIN_ROOT = '${PLUGIN_ROOT}'
const TOKEN_CLAUDE_SKILL_DIR = '${CLAUDE_SKILL_DIR}'
const TOKEN_CLAUDE_PROJECT_DIR = '${CLAUDE_PROJECT_DIR}'

/** Whether a path exists (any type). */
export function pathExists(target) {
  try {
    fs.statSync(target)
    return true
  } catch {
    return false
  }
}

function isDirectory(target) {
  try {
    return fs.statSync(target).isDirectory()
  } catch {
    return false
  }
}

function isFile(target) {
  try {
    return fs.statSync(target).isFile()
  } catch {
    return false
  }
}

/**
 * Resolve the directory that holds the plugin trees.
 *
 * Precedence:
 *   1. `config.pluginsRoot` (unless 'AUTO' — the sentinel install-dsh.sh writes
 *      for a self-contained package)
 *   2. env COSIGHT_COMPAT_PLUGINS_ROOT
 *   3. <package>/plugin-assets  (assets embedded by pack.sh)
 *   4. <package>/..             (development layout: repo/dsh-compat)
 *
 * @returns {{ root: string, source: string }}
 */
export function resolvePluginsRoot(config, pkgDir) {
  const explicit = config?.pluginsRoot
  if (typeof explicit === 'string' && explicit.length > 0 && explicit !== 'AUTO') {
    return { root: path.resolve(explicit), source: 'config.pluginsRoot' }
  }
  const fromEnv = process.env.COSIGHT_COMPAT_PLUGINS_ROOT
  if (explicit !== 'AUTO' && typeof fromEnv === 'string' && fromEnv.length > 0) {
    return { root: path.resolve(fromEnv), source: 'COSIGHT_COMPAT_PLUGINS_ROOT' }
  }
  const inPackage = path.resolve(pkgDir, 'plugin-assets')
  if (isDirectory(inPackage)) return { root: inPackage, source: 'package plugin-assets' }
  return { root: path.resolve(pkgDir, '..'), source: 'development layout' }
}

/** Read a plugin manifest; returns {} when absent or unreadable. */
function readManifest(pluginDir) {
  const manifestPath = path.join(pluginDir, '.claude-plugin', 'plugin.json')
  try {
    const parsed = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
    return parsed !== null && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

/**
 * Load one plugin tree.
 * @returns {object | null} null when the directory or its payload is missing.
 */
export function loadPlugin(root, def) {
  const pluginDir = path.join(root, def.dir)
  if (!isDirectory(pluginDir)) return null
  const manifest = readManifest(pluginDir)
  const skillsDir = path.join(pluginDir, 'skills')
  const agentsDir = path.join(pluginDir, 'agents')
  const commandsDir = path.join(pluginDir, 'commands')
  const hooksFile = path.join(pluginDir, 'hooks', 'hooks.json')
  const hasPayload = [skillsDir, agentsDir, commandsDir].some(isDirectory)
    || isFile(hooksFile)
  if (!hasPayload) return null
  return {
    dir: def.dir,
    alias: def.alias,
    kind: def.kind,
    name: typeof manifest.name === 'string' && manifest.name.length > 0 ? manifest.name : def.dir,
    version: typeof manifest.version === 'string' ? manifest.version : '',
    root: pluginDir,
    skillsDir: isDirectory(skillsDir) ? skillsDir : null,
    agentsDir: isDirectory(agentsDir) ? agentsDir : null,
    commandsDir: isDirectory(commandsDir) ? commandsDir : null,
    hooksFile: isFile(hooksFile) ? hooksFile : null,
    manifest,
  }
}

/** Load every requested plugin, reporting the ones that are absent. */
export function loadPlugins(root, requested, log) {
  const wanted = Array.isArray(requested) && requested.length > 0
    ? requested
    : PLUGIN_DEFS.map((def) => def.dir)
  const loaded = []
  for (const dir of wanted) {
    const def = PLUGIN_DEFS.find((candidate) => candidate.dir === dir)
    if (def === undefined) {
      log.warn(`cosight-plugin-compat: unknown plugin "${dir}" (known: ${PLUGIN_DEFS.map((d) => d.dir).join(', ')})`)
      continue
    }
    const plugin = loadPlugin(root, def)
    if (plugin === null) {
      log.warn(`cosight-plugin-compat: ${dir} payload not found under ${root}; skipped`)
      continue
    }
    loaded.push(plugin)
  }
  return loaded
}

/**
 * Expand Claude-only tokens in skill/command/agent text.
 * `${CLAUDE_PROJECT_DIR}` is intentionally left alone: it depends on the live
 * session directory, which does not exist at mount time.
 */
export function expandTokens(text, { pluginRoot, skillDir, projectDir } = {}) {
  let out = String(text)
  if (typeof skillDir === 'string' && skillDir.length > 0) {
    out = out.replaceAll(TOKEN_CLAUDE_SKILL_DIR, skillDir)
  }
  if (typeof pluginRoot === 'string' && pluginRoot.length > 0) {
    out = out
      .replaceAll(TOKEN_CLAUDE_ROOT, pluginRoot)
      .replaceAll(TOKEN_PLUGIN_ROOT, pluginRoot)
      .replaceAll('$CLAUDE_PLUGIN_ROOT', pluginRoot)
      .replaceAll('$PLUGIN_ROOT', pluginRoot)
  }
  if (typeof projectDir === 'string' && projectDir.length > 0) {
    out = out.replaceAll(TOKEN_CLAUDE_PROJECT_DIR, projectDir)
  }
  return out
}

/** List immediate subdirectories, sorted, dot-dirs excluded. */
export function listDirectories(parent) {
  if (parent === null) return []
  try {
    return fs.readdirSync(parent, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && !entry.name.startsWith('.'))
      .map((entry) => entry.name)
      .sort()
  } catch {
    return []
  }
}

/** List `*.md` files in a directory, sorted. */
export function listMarkdown(parent) {
  if (parent === null) return []
  try {
    return fs.readdirSync(parent, { withFileTypes: true })
      .filter((entry) => entry.isFile() && entry.name.endsWith('.md'))
      .map((entry) => entry.name)
      .sort()
  } catch {
    return []
  }
}

export { parseFrontmatter, fieldString, fieldList }

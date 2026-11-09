/**
 * naming.mjs — turn Claude asset names into names dsh accepts.
 *
 * dsh validates skill/command identifiers with `^[a-z0-9]+(?:-[a-z0-9]+)*$`
 * (see @deepseek-ai/dsh-skill `SKILL_NAME`). Claude plugins are looser:
 * `skill_optimize.md` (underscore) and `编码原则` (CJK) both appear in the
 * plugins this bridge mounts.
 *
 * Policy, in order:
 *   1. already valid          -> unchanged
 *   2. explicit override      -> mapped, deterministic, documented
 *   3. mechanical slug        -> lower-case, `_`/space/`.` -> `-`
 *   4. per-asset fallback     -> `<plugin alias>-<kind>-<n>` (never silently dropped)
 */

const SKILL_NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/

/**
 * Names that cannot be recovered mechanically. Keep this list small and
 * explicit: every entry is a user-visible rename.
 */
export const NAME_OVERRIDES = {
  编码原则: 'coding-principles',
  编码skill: 'coding-skill',
  编码技能: 'coding-skill',
}

/** Whether a name satisfies dsh's skill-name grammar. */
export function isValidName(name) {
  return SKILL_NAME.test(name)
}

/** Lower-case, dash-separated ASCII slug; '' when nothing survives. */
export function slugify(raw) {
  return String(raw)
    .trim()
    .toLowerCase()
    .replace(/[_./\\\s]+/g, '-')
    .replace(/[^a-z0-9-]/g, '')
    .replace(/-+/g, '-')
    .replace(/^-+|-+$/g, '')
}

/**
 * Normalize one asset name.
 * @param {string} raw - the name from frontmatter or the file/dir name.
 * @param {string} fallback - stable fallback stem (usually `<alias>-<kind>`).
 * @returns {string} a valid dsh name.
 */
export function normalizeName(raw, fallback) {
  const text = String(raw ?? '').trim()
  if (isValidName(text)) return text
  if (NAME_OVERRIDES[text] !== undefined) return NAME_OVERRIDES[text]

  const slug = slugify(text)
  if (isValidName(slug)) return slug

  const base = slugify(fallback) || 'plugin'
  return isValidName(base) ? base : `plugin-${base}`
}

/**
 * First-wins name registry with deterministic collision renames.
 * A collision renames the newcomer to `<alias>-<name>`; a second collision
 * returns null so the caller can skip the asset loudly.
 */
export class NameRegistry {
  constructor() {
    this.used = new Map()
  }

  /**
   * @param {string} name - desired dsh name.
   * @param {{ plugin: string, alias: string, kind: string }} owner
   * @returns {{ name: string, renamed: boolean } | { name: null, conflictWith: string }}
   */
  claim(name, owner) {
    const holder = this.used.get(name)
    if (holder === undefined) {
      this.used.set(name, owner)
      return { name, renamed: false }
    }
    const alternate = normalizeName(`${owner.alias}-${name}`, `${owner.alias}-${name}`)
    if (!this.used.has(alternate)) {
      this.used.set(alternate, owner)
      return { name: alternate, renamed: true }
    }
    return { name: null, conflictWith: `${holder.plugin}:${holder.kind}:${name}` }
  }
}

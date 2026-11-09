// skills.mjs — mount drive/skills/*/SKILL.md via ctx.skills.register,
// expanding Claude env tokens to absolute paths (drive files untouched).
import { readdir, readFile } from 'node:fs/promises'
import path from 'node:path'

/** Parse a minimal frontmatter block: returns { name, description, userInvocable, body }. */
export function parseFrontmatter(raw) {
  const m = /^\ufeff?---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(raw)
  if (!m) return null
  const fields = {}
  for (const line of m[1].split(/\r?\n/)) {
    const kv = /^([A-Za-z0-9-]+):\s*(.*)$/.exec(line.trim())
    if (!kv) continue
    let value = kv[2].trim()
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1)
    }
    fields[kv[1]] = value
  }
  if (!fields.name || !fields.description) return null
  return {
    name: fields.name,
    description: fields.description,
    userInvocable: fields['user-invocable'] !== 'false',
    body: raw.slice(m[0].length),
  }
}

/** Expand ${CLAUDE_SKILL_DIR} / ${CLAUDE_PLUGIN_ROOT} in skill body text. */
export function expandSkillBody(body, skillDir, driveRoot) {
  return body
    .replaceAll('${CLAUDE_SKILL_DIR}', skillDir)
    .replaceAll('${CLAUDE_PLUGIN_ROOT}', driveRoot)
}

/** Mount every skill under <driveRoot>/skills that has a SKILL.md. */
export async function mountSkills(ctx, driveRoot) {
  const skills = ctx.get('skills') ?? ctx.skills
  if (!skills) return 0
  const skillsRoot = path.join(driveRoot, 'skills')
  let entries
  try {
    entries = await readdir(skillsRoot, { withFileTypes: true })
  } catch (error) {
    ctx.logger.warn(`drive-compat: cannot read skills root ${skillsRoot}: ${error.message}`)
    return 0
  }
  const dirs = entries.filter((e) => e.isDirectory())
  // .drive is a skill subdir only in the lab copy; skip dotdirs.
  const candidates = dirs.filter((d) => !d.name.startsWith('.'))
  let mounted = 0
  await Promise.all(candidates.map(async (dir) => {
    const skillDir = path.join(skillsRoot, dir.name)
    const skillPath = path.join(skillDir, 'SKILL.md')
    const raw = await readFile(skillPath, 'utf8').catch(() => null)
    if (raw == null) return
    const fm = parseFrontmatter(raw)
    if (!fm) {
      ctx.logger.warn(`drive-compat: ${skillPath} has no drive frontmatter; skipped`)
      return
    }
    const content = expandSkillBody(fm.body, skillDir, driveRoot)
    skills.register({
      name: fm.name,
      description: fm.description,
      content,
      invocation: { modelInvocable: true, userInvocable: fm.userInvocable },
    })
    mounted += 1
  }).map((p) => p.catch((error) => {
    ctx.logger.warn(`drive-compat: skill mount failed: ${error.message}`)
  })))
  return mounted
}

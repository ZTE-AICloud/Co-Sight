/**
 * skills.mjs — mount Claude skills and slash commands as dsh runtime skills.
 *
 * Mapping:
 *   skills/<name>/SKILL.md  -> skill  (model + user invocable, like Claude)
 *   commands/<name>.md      -> skill  (user invocable only; dsh renders a
 *                                     user-invocable skill as `/name`, which
 *                                     is the closest equivalent of a Claude
 *                                     slash command — its body is a prompt
 *                                     template, not a program)
 *
 * Files on disk are never modified: token expansion happens on the string we
 * register, not on the source.
 */
import path from 'node:path'
import fs from 'node:fs'
import {
  expandTokens,
  fieldString,
  listDirectories,
  listMarkdown,
  parseFrontmatter,
} from './assets.mjs'
import { NameRegistry, normalizeName } from './naming.mjs'

/** Header prepended to command-derived skills so the model knows the contract. */
function commandHeader({ commandName, plugin, argumentHint, allowedTools }) {
  const lines = [
    `> **dsh 兼容层说明**：本命令由 Claude Code 插件 \`${plugin.dir}\` 的 \`commands/${commandName}.md\` 映射而来，`,
    '> 以 user-invocable skill 的形式提供。在 dsh 中，`/` 后的同一行文本就是参数',
    '> （等价于 Claude Code 的 `$ARGUMENTS`），宿主会把本文件内容作为指令注入当前步骤。',
    `> 插件根目录：\`${plugin.root}\`（文中相对路径均相对该目录解析）。`,
  ]
  if (argumentHint) lines.push(`> 参数提示：\`${argumentHint}\``)
  if (allowedTools) {
    lines.push(`> 原命令声明 \`allowed-tools: ${allowedTools}\`；dsh 没有按命令收窄工具权限的机制，此声明仅作提示。`)
  }
  return `${lines.join('\n')}\n\n`
}

/**
 * Collect skills and commands from every loaded plugin.
 * @returns {{skills: object[], commands: object[], skipped: object[]}}
 */
export function collectSkills(plugins, log) {
  const registry = new NameRegistry()
  const skills = []
  const commands = []
  const skipped = []

  for (const plugin of plugins) {
    for (const dirName of listDirectories(plugin.skillsDir)) {
      const skillDir = path.join(plugin.skillsDir, dirName)
      const skillPath = path.join(skillDir, 'SKILL.md')
      let raw
      try {
        raw = fs.readFileSync(skillPath, 'utf8')
      } catch {
        continue // a resource-only directory under skills/ is not an error
      }
      const { fields, body } = parseFrontmatter(raw)
      const declaredName = fieldString(fields, 'name') || dirName
      const description = fieldString(fields, 'description')
      if (description.length === 0) {
        skipped.push({ plugin: plugin.dir, kind: 'skill', path: skillPath, reason: 'missing description' })
        continue
      }
      const normalized = normalizeName(declaredName, `${plugin.alias}-skill`)
      const claim = registry.claim(normalized, { plugin: plugin.dir, alias: plugin.alias, kind: 'skill' })
      if (claim.name === null) {
        skipped.push({ plugin: plugin.dir, kind: 'skill', path: skillPath, reason: `name collision with ${claim.conflictWith}` })
        continue
      }
      if (claim.renamed) {
        log.warn(`cosight-plugin-compat: skill "${declaredName}" from ${plugin.dir} collides; mounted as "${claim.name}"`)
      }
      skills.push({
        name: claim.name,
        originalName: declaredName,
        description,
        whenToUse: fieldString(fields, 'when_to_use') || undefined,
        content: expandTokens(body, { pluginRoot: plugin.root, skillDir }),
        path: skillPath,
        resourceBase: { kind: 'directory', path: skillDir },
        invocation: {
          modelInvocable: true,
          userInvocable: fieldString(fields, 'user-invocable') !== 'false',
        },
        plugin: plugin.dir,
      })
    }

    for (const fileName of listMarkdown(plugin.commandsDir)) {
      const commandPath = path.join(plugin.commandsDir, fileName)
      const stem = fileName.replace(/\.md$/, '')
      let raw
      try {
        raw = fs.readFileSync(commandPath, 'utf8')
      } catch {
        continue
      }
      const { fields, body } = parseFrontmatter(raw)
      const declaredName = fieldString(fields, 'name') || stem
      const description = fieldString(fields, 'description')
      if (description.length === 0) {
        skipped.push({ plugin: plugin.dir, kind: 'command', path: commandPath, reason: 'missing description' })
        continue
      }
      const normalized = normalizeName(declaredName, `${plugin.alias}-${stem}`)
      const claim = registry.claim(normalized, { plugin: plugin.dir, alias: plugin.alias, kind: 'command' })
      if (claim.name === null) {
        skipped.push({ plugin: plugin.dir, kind: 'command', path: commandPath, reason: `name collision with ${claim.conflictWith}` })
        continue
      }
      if (claim.renamed) {
        log.warn(`cosight-plugin-compat: command "${declaredName}" from ${plugin.dir} collides; mounted as "/${claim.name}"`)
      }
      const argumentHint = fieldString(fields, 'argument-hint')
      const allowedTools = fieldString(fields, 'allowed-tools')
      const header = commandHeader({
        commandName: stem,
        plugin,
        argumentHint,
        allowedTools,
      })
      commands.push({
        name: claim.name,
        originalName: declaredName,
        description: argumentHint
          ? `${description}（参数：${argumentHint}）`
          : description,
        content: header + expandTokens(body, { pluginRoot: plugin.root, skillDir: path.dirname(commandPath) }),
        path: commandPath,
        resourceBase: { kind: 'directory', path: plugin.root },
        invocation: { modelInvocable: false, userInvocable: true },
        plugin: plugin.dir,
      })
    }
  }

  return { skills, commands, skipped }
}

/**
 * Register collected entries on the dsh skills registry.
 * @returns {{mounted: number, failed: object[]}}
 */
export function mountSkills(ctx, entries, log) {
  const skills = ctx.get('skills') ?? ctx.skills
  if (skills === undefined || skills === null) {
    log.error('cosight-plugin-compat: ctx.skills is unavailable; skills and commands are DISABLED')
    return { mounted: 0, failed: entries.map((entry) => ({ name: entry.name, reason: 'ctx.skills unavailable' })) }
  }
  let mounted = 0
  const failed = []
  for (const entry of entries) {
    try {
      skills.register({
        name: entry.name,
        description: entry.description,
        ...(entry.whenToUse === undefined ? {} : { whenToUse: entry.whenToUse }),
        content: entry.content,
        path: entry.path,
        source: 'runtime',
        resourceBase: entry.resourceBase,
        invocation: entry.invocation,
      })
      mounted += 1
    } catch (error) {
      failed.push({ name: entry.name, reason: String(error?.message ?? error) })
      log.warn(`cosight-plugin-compat: could not mount "${entry.name}" from ${entry.plugin}: ${error?.message ?? error}`)
    }
  }
  return { mounted, failed }
}

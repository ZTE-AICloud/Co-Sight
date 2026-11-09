/**
 * frontmatter.mjs — minimal, dependency-free parser for the YAML frontmatter
 * that Claude Code plugins put at the top of SKILL.md / agents/*.md /
 * commands/*.md.
 *
 * It deliberately does NOT implement YAML. It understands exactly the shapes
 * those files use:
 *   key: inline value            (plain, "quoted", 'quoted')
 *   key: [a, b, c]               (single-line flow sequence)
 *   key: >                       (folded block scalar)
 *   key: |                       (literal block scalar)
 *   key:                         (nested map -> ignored)
 *
 * Anything else is skipped rather than guessed at, so a malformed asset can
 * never be silently reinterpreted as a different field.
 */

const KEY_RE = /^([A-Za-z0-9_-]+):(.*)$/

/** Strip a matching pair of surrounding quotes. */
function unquote(value) {
  const text = value.trim()
  if (text.length >= 2) {
    const first = text[0]
    const last = text[text.length - 1]
    if ((first === '"' && last === '"') || (first === "'" && last === "'")) {
      return text.slice(1, -1)
    }
  }
  return text
}

/** Parse one inline scalar or flow sequence. */
function parseScalar(raw) {
  const text = raw.trim()
  if (text.length === 0) return ''
  if (text.startsWith('[') && text.endsWith(']')) {
    return text
      .slice(1, -1)
      .split(',')
      .map((item) => unquote(item))
      .filter((item) => item.length > 0)
  }
  return unquote(text)
}

/**
 * Parse a frontmatter block.
 * @param {string} raw - full file text.
 * @returns {{fields: Record<string, string | string[]>, body: string, hasFrontmatter: boolean}}
 */
export function parseFrontmatter(raw) {
  const text = String(raw).replace(/^﻿/, '')
  const match = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/.exec(text)
  if (match === null) return { fields: {}, body: text, hasFrontmatter: false }

  const lines = match[1].split(/\r?\n/)
  const fields = {}

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    // Indented lines belong to the previous key's block scalar or nested map.
    if (/^\s/.test(line)) continue
    const keyMatch = KEY_RE.exec(line)
    if (keyMatch === null) continue

    const key = keyMatch[1]
    const inline = keyMatch[2].trim()

    if (/^[>|][+-]?$/.test(inline)) {
      const folded = inline.startsWith('>')
      const collected = []
      let cursor = index + 1
      for (; cursor < lines.length; cursor += 1) {
        const next = lines[cursor]
        if (next.trim().length === 0) {
          collected.push('')
          continue
        }
        if (!/^\s/.test(next)) break
        collected.push(next.replace(/^ {1,4}/, ''))
      }
      index = cursor - 1
      fields[key] = folded
        ? collected.join(' ').replace(/[ \t]+/g, ' ').trim()
        : collected.join('\n').trim()
      continue
    }

    if (inline.length === 0) {
      // Nested map (e.g. `metadata:`) — this parser does not model it.
      continue
    }

    fields[key] = parseScalar(inline)
  }

  return { fields, body: text.slice(match[0].length), hasFrontmatter: true }
}

/** Return a field as a trimmed string, or '' when absent/non-string. */
export function fieldString(fields, key) {
  const value = fields[key]
  return typeof value === 'string' ? value.trim() : ''
}

/** Return a field as an array of strings (flow sequence or comma list). */
export function fieldList(fields, key) {
  const value = fields[key]
  if (Array.isArray(value)) return value
  if (typeof value === 'string' && value.trim().length > 0) {
    return value.split(',').map((item) => item.trim()).filter((item) => item.length > 0)
  }
  return []
}

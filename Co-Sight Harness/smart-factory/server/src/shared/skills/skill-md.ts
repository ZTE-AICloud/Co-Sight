import { closeSync, openSync, readSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

/**
 * SKILL.md 头部解析。
 *
 * 消费者：技能库扫描（`modules/skill/skill.service.ts`）与智能体技能装配
 * （`modules/agent/agent-skill.service.ts`）。两处必须同一套口径 ——
 * 扫描显示的名字与装配落盘的目录名来自同一个 frontmatter 解析。
 *
 * 不追求完整 YAML：只认单行纯文本与块标量（`>` / `|`，可带 `-` / `+` 修饰符）。
 */

/** SKILL.md 只读头部 8KB：frontmatter 都在最前面，整个文件可能很大。 */
const SKILL_MD_HEAD_BYTES = 8 * 1024;

export interface SkillFrontmatter {
  /** frontmatter `name`；缺失或解析失败为 undefined，调用方回落到目录名 */
  name?: string;
  description?: string;
  /** 产品里的技能常写 `version: "1.0"`；库技能以目录 `vN` 为准，这里只读不解释 */
  version?: string;
  /**
   * frontmatter `user-invocable`：缺省 = true（引擎默认）；显式 `false` 的技能只给模型
   * 或上游技能内部调用，不进 `/` 菜单。只认 `true` / `false` 两个字面量，别的不解释。
   */
  userInvocable?: boolean;
}

/** 剥成对引号：`"x"` / `'x'` → `x`；不成对原样保留。 */
function stripQuotes(value: string): string {
  if (value.length >= 2 && ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'")))) {
    return value.slice(1, -1);
  }
  return value;
}

/**
 * 块标量（`>` / `|`）的值：先去块内公共缩进，再按指示符折行。
 *
 * `>` 折叠：普通换行变空格，空行保留为段落分隔（YAML 的 folded 语义）；
 * `|` 字面量：换行原样保留。首尾空白一律去掉 —— 这是简介，不是文档正文。
 */
function foldBlock(lines: string[], literal: boolean): string {
  const indents = lines
    .filter((line) => line.trim() !== '')
    .map((line) => /^[ \t]*/u.exec(line)![0].length);
  const indent = indents.length === 0 ? 0 : Math.min(...indents);
  const dedented = lines.map((line) => (line.trim() === '' ? '' : line.slice(indent)));

  if (literal) return dedented.join('\n').trim();

  let text = '';
  for (const line of dedented) {
    if (line === '') {
      text += '\n';
      continue;
    }
    // 折行变空格；紧跟在空行后面的那一行是段落开头，不再补空格
    text += text === '' || text.endsWith('\n') ? line.trim() : ` ${line.trim()}`;
  }
  return text.trim();
}

/**
 * 解析 SKILL.md 头部：frontmatter 以 `---` 起止，`name` / `description` / `version` /
 * `user-invocable` 各取首次命中行。块标量是 Anthropic Skill 里写长 description 的常见写法
 * （`description: >-` 换行缩进），不认的话取到的就是 `>-` 这两个字符。
 */
export function parseSkillFrontmatter(raw: string): SkillFrontmatter {
  const lines = raw.split(/\r?\n/);
  if (lines[0]?.trim() !== '---') return {};
  let end = -1;
  for (let i = 1; i < lines.length; i += 1) {
    if (lines[i]?.trim() === '---') {
      end = i;
      break;
    }
  }
  if (end === -1) return {};

  const result: SkillFrontmatter = {};
  const body = lines.slice(1, end);
  for (let index = 0; index < body.length; index += 1) {
    const match = /^(name|description|version|user-invocable)\s*:\s*(.*)$/.exec(body[index]!.trim());
    if (!match) continue;
    // 布尔字段单独解析：`true` / `false` 之外的值（含 YAML 的 `yes`）不猜，留给引擎默认 true
    if (match[1] === 'user-invocable') {
      if (result.userInvocable !== undefined) continue;
      const value = stripQuotes(match[2]!.trim()).toLowerCase();
      if (value === 'true' || value === 'false') result.userInvocable = value === 'true';
      continue;
    }
    const key = match[1] as 'name' | 'description' | 'version';
    if (result[key] !== undefined) continue;

    const inline = stripQuotes(match[2]!.trim());
    if (!/^[>|][+-]?$/.test(inline)) {
      result[key] = inline;
      continue;
    }

    // 块标量：值在后续的缩进行里，直到下一个不缩进的行（下一个字段 / 结束行）
    const blockLines: string[] = [];
    let next = index + 1;
    for (; next < body.length; next += 1) {
      const line = body[next]!;
      if (line.trim() !== '' && !/^[ \t]/u.test(line)) break;
      blockLines.push(line);
    }
    result[key] = foldBlock(blockLines, inline.startsWith('|'));
    index = next - 1;
  }
  return result;
}

/** 读 SKILL.md 头部 8KB；文件不存在 / 读失败都返回 null（单文件问题不拖垮扫描）。 */
export function readSkillMdHead(skillMdPath: string): string | null {
  let fd: number;
  try {
    fd = openSync(skillMdPath, 'r');
  } catch {
    return null;
  }
  try {
    const buffer = Buffer.alloc(SKILL_MD_HEAD_BYTES);
    const bytes = readSync(fd, buffer, 0, SKILL_MD_HEAD_BYTES, 0);
    return buffer.subarray(0, bytes).toString('utf8');
  } catch {
    return null;
  } finally {
    closeSync(fd);
  }
}

/** 目录内 `v<数字>` 子目录按数字取最大（`v10` > `v1`，不按字典序）；没有则空串。 */
export function detectSkillVersion(skillDir: string): string {
  let entries;
  try {
    entries = readdirSync(skillDir, { withFileTypes: true });
  } catch {
    return '';
  }
  let best = -1;
  for (const entry of entries) {
    const match = /^v(\d+)$/.exec(entry.name);
    if (!match || !entry.isDirectory()) continue;
    best = Math.max(best, Number(match[1]));
  }
  return best >= 0 ? `v${best}` : '';
}

/**
 * 读技能目录的 frontmatter：SKILL.md 固定在版本目录里（`<name>/<vN>/SKILL.md`）；
 * 版本目录里没有时回落技能目录本身。`version` 传空串表示来源没有版本子目录。
 */
export function readSkillFrontmatter(skillDir: string, version: string): SkillFrontmatter {
  const head =
    readSkillMdHead(join(skillDir, version === '' ? 'SKILL.md' : join(version, 'SKILL.md'))) ??
    (version === '' ? null : readSkillMdHead(join(skillDir, 'SKILL.md')));
  return head === null ? {} : parseSkillFrontmatter(head);
}

/** 技能目录的 mtime（ISO 串）；stat 失败返回 null，调用方决定是否跳过该项。 */
export function skillMtime(skillDir: string): string | null {
  try {
    return statSync(skillDir).mtime.toISOString();
  } catch {
    return null;
  }
}

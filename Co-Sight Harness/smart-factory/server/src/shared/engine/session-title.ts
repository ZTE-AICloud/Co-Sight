/**
 * 读 Claude Code 会话标题：`/rename` 的自定义名优先，其次自动摘要。
 *
 * 直接读 `~/.claude/projects/<project>/<sessionId>.jsonl`，不发起模型调用。
 * 不按 cwd 反推 project 目录名（各版本对路径的转义规则不完全一致），
 * 而是按 sessionId 扫一层目录——会话 id 是 UUID，足够唯一，目录数量也很小。
 */

import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

const SESSION_ID = /^[A-Za-z0-9._-]+$/;

/** 在一条 JSONL 记录里找字段；只下钻两层，避免把工具结果里的同名字段当成标题。 */
function findString(value: unknown, key: string, depth = 0): string | undefined {
  if (depth > 2 || value === null || typeof value !== 'object') return undefined;
  if (Array.isArray(value)) {
    for (const item of value) {
      const hit = findString(item, key, depth + 1);
      if (hit !== undefined) return hit;
    }
    return undefined;
  }
  const record = value as Record<string, unknown>;
  const direct = record[key];
  if (typeof direct === 'string' && direct.trim() !== '') return direct.trim();
  for (const child of Object.values(record)) {
    const hit = findString(child, key, depth + 1);
    if (hit !== undefined) return hit;
  }
  return undefined;
}

function readTitle(file: string): string | null {
  let text: string;
  try {
    text = readFileSync(file, 'utf8');
  } catch {
    return null;
  }

  let customTitle: string | undefined;
  let summary: string | undefined;
  for (const line of text.split('\n')) {
    if (line.trim() === '') continue;
    let record: unknown;
    try {
      record = JSON.parse(line);
    } catch {
      continue;
    }
    customTitle = findString(record, 'customTitle') ?? customTitle;
    if ((record as { type?: unknown }).type === 'summary') {
      summary = findString(record, 'summary') ?? summary;
    }
  }
  return customTitle ?? summary ?? null;
}

/** 会话文件不存在 / 尚无标题时返回 null；`_cwd` 留给调用方语义，不参与定位。 */
export async function readSessionTitle(sessionId: string, _cwd: string): Promise<string | null> {
  const id = sessionId.endsWith('.jsonl') ? sessionId.slice(0, -'.jsonl'.length) : sessionId;
  if (!SESSION_ID.test(id) || id.includes('..')) return null;

  const configDir = (process.env.CLAUDE_CONFIG_DIR ?? '').trim() || join(homedir(), '.claude');
  const projectsDir = join(configDir, 'projects');
  if (!existsSync(projectsDir)) return null;

  const fileName = `${id}.jsonl`;
  // 兼容两种布局：projects/<id>.jsonl 与 projects/<project>/<id>.jsonl。
  const direct = join(projectsDir, fileName);
  if (existsSync(direct)) return readTitle(direct);

  let entries: string[];
  try {
    entries = readdirSync(projectsDir, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name);
  } catch {
    return null;
  }
  for (const project of entries) {
    const candidate = join(projectsDir, project, fileName);
    if (existsSync(candidate)) return readTitle(candidate);
  }
  return null;
}

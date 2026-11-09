/**
 * 对话里的「文件引用」：哪些行内代码是真文件、点开时落到哪个绝对路径。
 *
 * 纯函数，不碰 React —— 匹配规则能单独讲清楚，也就该能单独验。
 *
 * 核心一条（见 `docs/file-preview-plan.md` §2.1）：**不用正则猜「这串像不像文件名」**。
 * 判定依据是这一轮真正写过的文件集合（`producedPathsOf`），行内代码只在
 * 精确命中 / 后缀命中 / basename 唯一命中时才变成按钮。两个同名文件导致歧义时
 * 宁可不做链接 —— 误把普通代码变成可点按钮，比少一个链接更烦人。
 *
 * 局限（有意不覆盖）：`Bash` 里 `> out.html` 这类写出来的文件收不到；
 * 要覆盖得解析 shell 命令，不做。
 */

import { fileNameOf } from './file-name';
import type { ConversationTurn, TurnEntry } from './components/Conversation/types';

/** 会产生文件写入的工具；只有它们的结果能进「本轮产物集合」 */
const WRITE_TOOLS = new Set(['Write', 'Edit', 'MultiEdit', 'NotebookEdit']);

/** 工具入参里可能承载路径的字段（Read / Write / Notebook 的命名不完全一致） */
const PATH_KEYS = ['file_path', 'path', 'notebook_path'] as const;

/** 从工具入参里取一个路径字符串；没有就 undefined */
export function pathOfToolInput(input: unknown): string | undefined {
  if (input === null || typeof input !== 'object') return undefined;
  const record = input as Record<string, unknown>;
  for (const key of PATH_KEYS) {
    const value = record[key];
    if (typeof value === 'string' && value.trim() !== '') return value;
  }
  return undefined;
}

/**
 * 本轮写过的文件（绝对路径，已去重）。
 *
 * 数据来自 `ConversationMessage.entries` 里的工具条目：投影层（map-message）把
 * `tool_use` 的 `input` 原样留着，`tool_result` 的 `isError` 落成 `status`，
 * 所以这里不需要改数据模型。
 *
 * 只认 `status === 'done'`：失败的 Write 没有产生文件，不该变成可点链接。
 */
export function producedPathsOf(turn: ConversationTurn): string[] {
  const produced = new Set<string>();

  for (const reply of turn.replies) {
    for (const entry of reply.entries ?? []) {
      if (entry.kind !== 'tool') continue;
      if (entry.status !== 'done') continue;
      if (!WRITE_TOOLS.has(entry.toolName)) continue;

      const path = writtenPathOf(entry);
      if (path !== undefined) produced.add(path);
    }
  }

  return [...produced];
}

function writtenPathOf(entry: TurnEntry): string | undefined {
  if (entry.kind !== 'tool') return undefined;
  return pathOfToolInput(entry.input);
}

/** 去掉 `file://`、`./`，解一次百分号编码；解不开就按原样用 */
function normalize(value: string): string {
  let text = value.trim();
  if (text === '') return '';
  try {
    text = decodeURIComponent(text);
  } catch {
    // 不是合法的百分号编码：保留原文，交给后端 400 / 404
  }
  text = text.replace(/^file:\/\//iu, '');
  return text.replace(/^\.\//u, '');
}

function baseNameOf(path: string): string {
  const parts = path.split('/');
  return parts[parts.length - 1] ?? path;
}

/**
 * 行内代码 → 目标绝对路径。返回 `undefined` 表示「保持纯文本」。
 *
 * 优先级：
 *   1. 精确命中本轮产物；
 *   2. 后缀命中（正文常写相对片段 `output/agents/x/v1/SKILL.md`，工具给的是绝对路径）；
 *   3. basename 唯一命中；
 *   4. 其余一律不做链接（0 个或多个同名文件都不猜）。
 */
export function resolveMention(value: string, produced: readonly string[]): string | undefined {
  const target = normalize(value);
  if (target === '' || produced.length === 0) return undefined;

  const exact = produced.find((path) => path === target);
  if (exact !== undefined) return exact;

  const bySuffix = produced.filter((path) => path.endsWith(`/${target}`));
  if (bySuffix.length === 1) return bySuffix[0];
  // 多个后缀命中就是有歧义（`a/x.ts` 与 `b/x.ts` 都写正文里的 `x.ts`）：不猜
  if (bySuffix.length > 1) return undefined;

  const name = baseNameOf(target);
  if (name === '') return undefined;
  const byName = produced.filter((path) => fileNameOf(path) === name);
  return byName.length === 1 ? byName[0] : undefined;
}

/**
 * 点击时把正文里的写法解析成绝对路径。
 *
 * - 绝对路径原样返回（`~` 也原样交给后端展开，主目录只有服务端知道）；
 * - 相对路径拼 `baseDir`（会话 cwd = `<agentDir>/<stage>`）；
 * - `baseDir` 为空时给不出确定答案，返回空串由调用方放弃打开。
 */
export function resolveToAbsolute(raw: string, baseDir: string): string {
  const value = raw.trim().replace(/^file:\/\//iu, '');
  if (value === '') return '';
  if (value === '~' || value.startsWith('~/')) return value;
  if (value.startsWith('/')) return collapseSlashes(value);

  if (baseDir === '') return '';
  return collapseSlashes(`${baseDir.replace(/\/+$/u, '')}/${value.replace(/^\.\/+/u, '')}`);
}

/** 拼路径后可能出现 `//`；保留开头的根，其余收成一个 */
function collapseSlashes(path: string): string {
  return path.replace(/\/{2,}/gu, '/');
}

/**
 * 输入框里的字符串 → 能提交的值（外加一条待翻译的问题）。
 *
 * 为什么每个函数同时返回 value 与 issue，而不是抛异常或返回 `null`：
 * "空串"是**合法**的（模型配置里它表示"不设置"，代理配置里它表示"用默认值"），
 * 而"填了 abc"是**非法**的。两者都不能解析出数字，用一个 `null` 表达会把它们
 * 混成一件事，于是"没填"会被报成"请填一个数字"。
 *
 * 输入一律 trim 后再解析：这几个字段用户多半是从别处粘贴过来的，尾部空格是复制
 * 带来的噪声而不是有意义的字符。
 */

import type { FieldIssue } from './issues';

export interface ParsedNumber {
  /** 解析结果；`undefined` 表示这一栏是空的。 */
  value: number | undefined;
  /** `null` 表示没问题。 */
  issue: FieldIssue | null;
}

const EMPTY: ParsedNumber = { value: undefined, issue: null };

/**
 * 小数（温度、Top P）。
 *
 * 上下限在这里一并校验，而不是留给服务端：契约里 `.min(0).max(2)` 越界会返回 422
 * "请求参数校验未通过"，用户拿着这句话既不知道是哪个字段、也不知道该填多少。
 */
export function parseDecimal(raw: string, min: number, max: number): ParsedNumber {
  const text = raw.trim();
  if (text === '') {
    return EMPTY;
  }
  const value = Number(text);
  if (!Number.isFinite(value)) {
    return { value: undefined, issue: { kind: 'number' } };
  }
  if (value < min || value > max) {
    return { value: undefined, issue: { kind: 'range', min, max } };
  }
  return { value, issue: null };
}

/**
 * 正整数（迭代步数、并行度、超时、Token 上限）。
 *
 * `Number.isInteger` 而不是 `Number.isFinite` + 取整：`1.5` 应当报错，不该被悄悄
 * 变成 1 或 2——用户敲下去的数和存下来的数必须是同一个。
 * `max` 不给表示契约里没有上限（如 `maxOutputTokens`）。
 */
export function parsePositiveInteger(raw: string, max?: number): ParsedNumber {
  const text = raw.trim();
  if (text === '') {
    return EMPTY;
  }
  const value = Number(text);
  if (!Number.isInteger(value) || value <= 0) {
    return { value: undefined, issue: { kind: 'positiveInteger' } };
  }
  if (max !== undefined && value > max) {
    return { value: undefined, issue: { kind: 'range', min: 1, max } };
  }
  return { value, issue: null };
}

/**
 * 是否是服务端会接受的地址（`httpUrlSchema` 的同一条规则）。
 *
 * 用 `new URL` 解析而不是写正则：地址的合法形状（IPv6 字面量、端口、国际化域名、
 * 结尾斜杠）只有解析器清楚，正则想否掉的其实只是"协议不对"这一类，却很容易顺手
 * 误伤别的写法。`ftp://x` 在 `new URL` 下是合法的，所以协议必须单独再判一次——
 * 这也正是服务端用 `z.url({ protocol: /^https?$/ })` 而不是 `z.url()` 的原因。
 */
export function isHttpUrl(raw: string): boolean {
  try {
    const url = new URL(raw);
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch {
    // 解析不了就是非法地址。这里不需要区分"哪一段不对"：文案只有一句。
    return false;
  }
}

export interface ParsedUrl {
  /** 空串 → `null`（契约里 null 表示"不设置"，如"用供应商官方地址"）。 */
  value: string | null;
  issue: FieldIssue | null;
}

/**
 * 可留空的地址字段。
 *
 * 空串单独走一条分支，是为了让"没填地址"与"填了个坏地址"分开：前者返回 `null`
 * 表示不设置，后者才报错。这里也是唯一会 trim 地址的地方——服务端对地址没有
 * `.trim()`，原样存下去的话，尾巴上一个空格会让它变成一个和用户以为的不一样的值。
 */
export function parseHttpUrl(raw: string): ParsedUrl {
  const text = raw.trim();
  if (text === '') {
    return { value: null, issue: null };
  }
  return isHttpUrl(text) ? { value: text, issue: null } : { value: null, issue: { kind: 'url' } };
}

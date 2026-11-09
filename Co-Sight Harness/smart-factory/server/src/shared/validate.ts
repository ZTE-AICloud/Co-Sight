import { BadRequestError } from './errors.js';

/** 分页与 limit 的上限，避免一次拉爆。 */
const PAGE_SIZE_DEFAULT = 20;
const PAGE_SIZE_MAX = 200;
export const MESSAGE_LIMIT_DEFAULT = 50;

/** 消息分页上限；订阅补发挂起帧也用它兜住条数。 */
export const MESSAGE_LIMIT_MAX = 200;

export function requireString(value: unknown, name: string): string {
  if (typeof value !== 'string' || value.trim() === '') {
    throw new BadRequestError(`${name} 必填`, 'error.bad_request.required', { name });
  }
  return value;
}

export function optionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value !== '' ? value : undefined;
}

/** 框架工作区 id 的形态。只在入参边界校验，不解析内容。 */
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** 工作区 id：必填、trim 后须是 uuid。多个模块共用同一份形态口径（agents / skills 列表）。 */
export function readWorkspaceId(value: unknown): string {
  if (typeof value !== 'string' || value.trim() === '') throw new BadRequestError('workspaceId 必填', 'error.bad_request.required', { name: 'workspaceId' });
  const workspaceId = value.trim();
  if (!UUID_PATTERN.test(workspaceId)) {
    throw new BadRequestError(`workspaceId 不是合法的 uuid：${JSON.stringify(workspaceId)}`);
  }
  return workspaceId;
}

/** 逗号分隔的字符串查询参数：去空白、去空项；没有有效值返回 undefined。 */
export function csvStrings(value: unknown): string[] | undefined {
  const text = optionalString(value);
  if (!text) return undefined;
  const items = text
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item !== '');
  return items.length > 0 ? items : undefined;
}

export function requireEnum<T extends string>(value: unknown, allowed: readonly T[], name: string, fallback?: T): T {
  if (value === undefined || value === '') {
    if (fallback !== undefined) return fallback;
    throw new BadRequestError(`${name} 必填`, 'error.bad_request.required', { name });
  }
  if (typeof value !== 'string' || !allowed.includes(value as T)) {
    throw new BadRequestError(
      `${name} 取值非法：${JSON.stringify(value)}（可选：${allowed.join(' / ')}）`,
      'error.bad_request.invalid_value',
      { name, value: JSON.stringify(value), allowed: allowed.join(' / ') },
    );
  }
  return value as T;
}

function positiveInt(value: unknown, fallback: number): number {
  if (value === undefined || value === '') return fallback;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

export function pageParams(page: unknown, pageSize: unknown): { page: number; pageSize: number } {
  return {
    page: positiveInt(page, 1),
    pageSize: Math.min(positiveInt(pageSize, PAGE_SIZE_DEFAULT), PAGE_SIZE_MAX),
  };
}

export function limitParam(limit: unknown, fallback = MESSAGE_LIMIT_DEFAULT): number {
  return Math.min(positiveInt(limit, fallback), MESSAGE_LIMIT_MAX);
}

/**
 * 交互问询的应答：形状为 `{ 问题原文: [选项] }`，每个值必须是字符串数组。
 *
 * 空对象表示用户未作答；值类型不对必须当场拒绝，否则后面拼请求载荷时会炸。
 */
export function answersParam(value: unknown): Record<string, string[]> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new BadRequestError(
      'answers 必填，形状为 { 问题原文: [选项] }',
      'error.bad_request.answers_required',
    );
  }
  for (const [question, choices] of Object.entries(value)) {
    if (!Array.isArray(choices) || choices.some((choice) => typeof choice !== 'string')) {
      throw new BadRequestError(
        `answers 的「${question}」必须是选项字符串数组，形状为 { 问题原文: [选项] }`,
        'error.bad_request.answer_shape',
        { question },
      );
    }
  }
  return value as Record<string, string[]>;
}

export function optionalInt(value: unknown): number | undefined {
  if (value === undefined || value === '') return undefined;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : undefined;
}

/** 历史消息的翻页游标：afterSeq 往前、beforeSeq 往后，两个方向互斥。 */
export interface MessageCursor {
  afterSeq?: number;
  beforeSeq?: number;
}

export function messageCursor(afterSeq: unknown, beforeSeq: unknown): MessageCursor {
  const after = optionalInt(afterSeq);
  const before = optionalInt(beforeSeq);
  if (after !== undefined && before !== undefined) {
    throw new BadRequestError(
      'afterSeq 与 beforeSeq 只能给一个',
      'error.bad_request.cursor_exclusive',
    );
  }
  return { afterSeq: after, beforeSeq: before };
}

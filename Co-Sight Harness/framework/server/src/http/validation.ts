/**
 * 校验错误到 `FieldIssue[]` 的转换。
 *
 * 前端的表单需要"哪个字段、错在哪、用哪个 i18n 键"三件事，而 zod 与 fastify
 * 给出的原始 issue 只有机器码，所以这里统一补上点分路径与 i18n 键。
 */

import type { FieldIssue } from 'harness-shared';

/** 与校验错误码一一对应的 i18n 键前缀。 */
const MESSAGE_KEY_PREFIX = 'validation';

export interface RawValidationIssue {
  /** 契约层的点分路径，如 `tags.0`；根级错误为空串。 */
  path: string;
  code: string;
  message: string;
}

export function toFieldIssues(issues: readonly RawValidationIssue[]): FieldIssue[] {
  return issues.map((issue) => ({
    path: issue.path,
    code: issue.code,
    messageKey: `${MESSAGE_KEY_PREFIX}.${issue.code}`,
    message: issue.message,
  }));
}

/**
 * 把 JSON Pointer 形式的 `instancePath`（如 `/tags/0`、`/`）还原成
 * 契约层的点分路径（`tags.0`、``）。
 *
 * 注意 `~1`/`~0` 转义：JSON Pointer 用 `~1` 表示 `/`、`~0` 表示 `~`，
 * 不还原的话形如 `a/b` 的字段名会被错拆成两层路径。
 */
export function pointerToPath(instancePath: string | undefined): string {
  if (instancePath === undefined || instancePath === '' || instancePath === '/') {
    return '';
  }
  return instancePath
    .replace(/^\//, '')
    .split('/')
    .map((segment) => segment.replace(/~1/g, '/').replace(/~0/g, '~'))
    .join('.');
}

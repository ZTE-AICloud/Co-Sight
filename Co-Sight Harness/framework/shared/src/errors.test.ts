import { describe, expect, test } from 'vitest';

import { API_ERROR_CODES, AppError, ERROR_HTTP_STATUS, toApiError } from './errors';

describe('AppError', () => {
  test('notFound 带上资源名的 i18n 键', () => {
    const error = AppError.notFound('expert', 'abc');
    expect(error.code).toBe('NOT_FOUND');
    expect(error.messageKey).toBe('error.not_found.expert');
    expect(error.message).toContain('abc');
  });

  test('toApiError 注入 traceId 且保留 details', () => {
    const error = AppError.validation([
      { path: 'name', code: 'too_small', messageKey: 'k', message: 'm' },
    ]);
    const api = error.toApiError('trace-9');
    expect(api.traceId).toBe('trace-9');
    expect(api.details).toHaveLength(1);
    expect(api.code).toBe('VALIDATION_FAILED');
  });
});

describe('toApiError', () => {
  test('普通 Error 折叠为 INTERNAL，且不外泄原始 message', () => {
    const api = toApiError(new Error('SQLITE_ERROR: no such table: experts'));
    expect(api.code).toBe('INTERNAL');
    expect(api.message).toBe('服务内部错误');
    expect(api.message).not.toContain('SQLITE_ERROR');
  });

  test('非 Error 值同样折叠为 INTERNAL', () => {
    expect(toApiError('boom').code).toBe('INTERNAL');
  });

  test('AppError 原样透出', () => {
    expect(toApiError(AppError.notFound('workspace')).code).toBe('NOT_FOUND');
  });
});

describe('错误码表', () => {
  test('每个错误码都有 HTTP 状态映射', () => {
    for (const code of API_ERROR_CODES) {
      expect(ERROR_HTTP_STATUS[code]).toBeGreaterThanOrEqual(400);
    }
  });
});

import { describe, expect, test } from 'vitest';

import { buildPageMeta, fail, ok } from './envelope';

describe('buildPageMeta', () => {
  test('空结果集的总页数为 0 且无更多', () => {
    expect(buildPageMeta(0, 1, 30)).toEqual({
      page: 1,
      pageSize: 30,
      total: 0,
      totalPages: 0,
      hasMore: false,
    });
  });

  test('整除时最后一页没有更多', () => {
    const meta = buildPageMeta(60, 2, 30);
    expect(meta.totalPages).toBe(2);
    expect(meta.hasMore).toBe(false);
  });

  test('有余数时未到最后一页则还有更多', () => {
    const meta = buildPageMeta(61, 2, 30);
    expect(meta.totalPages).toBe(3);
    expect(meta.hasMore).toBe(true);
  });

  test('非法的 pageSize 会被夹到至少 1，避免除零', () => {
    expect(buildPageMeta(5, 1, 0).pageSize).toBe(1);
  });
});

describe('响应信封', () => {
  test('成功响应的 error 为 null、meta 缺省为 null', () => {
    expect(ok({ id: 'a' })).toEqual({ success: true, data: { id: 'a' }, error: null, meta: null });
  });

  test('失败响应的 data 为 null', () => {
    const response = fail({
      code: 'NOT_FOUND',
      messageKey: 'error.not_found.expert',
      message: '未找到 expert',
      details: null,
      traceId: 't-1',
    });
    expect(response.success).toBe(false);
    expect(response.data).toBeNull();
    expect(response.error.code).toBe('NOT_FOUND');
  });
});

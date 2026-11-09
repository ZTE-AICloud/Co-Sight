import { describe, expect, test } from 'vitest';

import {
  EXPERT_ACTIONS,
  EXPERT_ACTION_KIND,
  EXPERT_FILTERS,
  expertListQuerySchema,
} from './expert';

describe('expertListQuerySchema', () => {
  test('空查询落到 全部 / 第 1 页 / 30 条', () => {
    const query = expertListQuerySchema.parse({});
    expect(query.filter).toBe('all');
    expect(query.page).toBe(1);
    expect(query.pageSize).toBe(30);
    expect(query.q).toBeUndefined();
  });

  test('URL 上的字符串分页参数被强制转成数字', () => {
    const query = expertListQuerySchema.parse({ page: '3', pageSize: '15' });
    expect(query.page).toBe(3);
    expect(query.pageSize).toBe(15);
  });

  test('空串搜索等价于不搜索', () => {
    expect(expertListQuerySchema.parse({ q: '   ' }).q).toBeUndefined();
  });

  test('超出上限的 pageSize 被拒，避免一次拉全库', () => {
    expect(expertListQuerySchema.safeParse({ pageSize: 500 }).success).toBe(false);
  });

  test('未知的 filter 被拒', () => {
    expect(expertListQuerySchema.safeParse({ filter: 'cheapest' }).success).toBe(false);
  });

  test('四个筛选项与需求 4.3 一致（含 D13 追加的 预置）', () => {
    expect([...EXPERT_FILTERS]).toEqual(['all', 'hot', 'new', 'preset']);
  });
});

describe('EXPERT_ACTION_KIND', () => {
  test('使用 走会话，设计/评估/优化 走 Agent 开发（需求 4.5）', () => {
    expect(EXPERT_ACTION_KIND.use).toBe('conversation');
    expect(EXPERT_ACTION_KIND.design).toBe('agent-dev');
    expect(EXPERT_ACTION_KIND.evaluate).toBe('agent-dev');
    expect(EXPERT_ACTION_KIND.optimize).toBe('agent-dev');
  });

  test('四个动作全部有归属', () => {
    for (const action of EXPERT_ACTIONS) {
      expect(EXPERT_ACTION_KIND[action]).toBeDefined();
    }
  });
});

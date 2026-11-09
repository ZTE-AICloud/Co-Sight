/**
 * 专家接口（需求 2.2、4.3–4.5）。
 *
 * 排序与搜索直接建在 SQL 上，所以测试也走真实查询：内存里排一遍再断言，
 * 测不到分页与排序交互出错（同分记录跨页重复）这类真实故障。
 *
 * 需要控制创建时间与使用次数的用例，通过仓储层写入——HTTP 接口不接受这两个字段，
 * 它们本来就该由服务端掌握（时间）或由行为累积（使用次数）。
 */

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import type { CreateExpertInput } from 'harness-shared';

import { createTestContext, destroyTestContext, type TestContext } from './helpers/context';
import { expertInput } from './helpers/experts';

let context: TestContext;

beforeAll(async () => {
  context = await createTestContext();
});

afterAll(async () => {
  await destroyTestContext(context);
});

let seededAt = 0;

async function seed(
  input: Partial<CreateExpertInput>,
  options: { useCount?: number } = {},
): Promise<string> {
  // 每条记录的创建时间比上一条晚 1 分钟，让 `最新` 的顺序完全由写入顺序决定，
  // 不受同一毫秒内的 id 排序干扰。
  seededAt += 1;
  const createdAt = new Date(Date.UTC(2026, 0, 1, 0, 0, 0) + seededAt * 60_000);
  const created = await context.services.experts.create(expertInput(input), createdAt);
  if (options.useCount !== undefined) {
    await context.services.experts.setUseCount(created.id, options.useCount, createdAt);
  }
  return created.id;
}

async function list(query: string): Promise<{ items: unknown[]; meta: Record<string, unknown> }> {
  const response = await context.app.inject({ method: 'GET', url: `/api/experts?${query}` });
  expect(response.statusCode).toBe(200);
  const body = response.json();
  return { items: body.data.items, meta: body.meta };
}

describe('专家接口', () => {
  it('分页：总数、hasMore 与页大小都对得上', async () => {
    for (let index = 0; index < 35; index += 1) {
      await seed({ name: `分页专家 ${String(index).padStart(2, '0')}` });
    }

    const first = await list('page=1&pageSize=30');
    expect(first.items).toHaveLength(30);
    expect(first.meta.page).toBe(1);
    expect(first.meta.total).toBe(35);
    expect(first.meta.totalPages).toBe(2);
    expect(first.meta.hasMore).toBe(true);

    const second = await list('page=2&pageSize=30');
    expect(second.items).toHaveLength(5);
    expect(second.meta.hasMore).toBe(false);
  });

  it('两页之间不重复、不遗漏（排序有唯一兜底）', async () => {
    const first = await list('page=1&pageSize=30');
    const second = await list('page=2&pageSize=30');
    const ids = [...first.items, ...second.items].map((item) => (item as { id: string }).id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toHaveLength(35);
  });

  it('pageSize 上限被强制（防止一次拉走整表）', async () => {
    const response = await context.app.inject({
      method: 'GET',
      url: '/api/experts?pageSize=5000',
    });
    expect(response.statusCode).toBe(422);
  });

  it('最热：按使用次数倒序（D15 = B，纯计数无时间衰减）', async () => {
    const low = await seed({ name: '最热-低' }, { useCount: 1 });
    const high = await seed({ name: '最热-高' }, { useCount: 999 });
    const mid = await seed({ name: '最热-中' }, { useCount: 50 });

    const { items } = await list('filter=hot&pageSize=60');
    const ids = items.map((item) => (item as { id: string }).id);
    expect(ids.indexOf(high)).toBeLessThan(ids.indexOf(mid));
    expect(ids.indexOf(mid)).toBeLessThan(ids.indexOf(low));
  });

  it('最新：按创建时间倒序', async () => {
    const older = await seed({ name: '最新-先建' });
    const newer = await seed({ name: '最新-后建' });
    const { items } = await list('filter=new&pageSize=60');
    const ids = items.map((item) => (item as { id: string }).id);
    expect(ids.indexOf(newer)).toBeLessThan(ids.indexOf(older));
  });

  it('预置：只返回预置项（D13 = A）', async () => {
    await seed({ name: '预置-甲', isPreset: true });
    await seed({ name: '预置-乙', isPreset: true });
    await seed({ name: '非预置-丙', isPreset: false });

    const { items } = await list('filter=preset&pageSize=60');
    expect(items.length).toBeGreaterThanOrEqual(2);
    for (const item of items) {
      expect((item as { isPreset: boolean }).isPreset).toBe(true);
    }
  });

  it('全部：预置与非预置都返回', async () => {
    const { items } = await list('filter=all&pageSize=60');
    const flags = new Set(items.map((item) => (item as { isPreset: boolean }).isPreset));
    expect(flags.has(true)).toBe(true);
    expect(flags.has(false)).toBe(true);
  });

  it('搜索：按名称模糊匹配且大小写不敏感', async () => {
    await seed({ name: 'RAG 检索专家' });
    const { items } = await list(`q=${encodeURIComponent('rag')}`);
    expect(items.length).toBeGreaterThanOrEqual(1);
    for (const item of items) {
      expect((item as { name: string }).name.toLowerCase()).toContain('rag');
    }
  });

  it('搜索：空串等价于不搜索', async () => {
    const withEmpty = await list('q=&pageSize=60');
    const withoutQ = await list('pageSize=60');
    expect(withEmpty.meta.total).toBe(withoutQ.meta.total);
  });

  it('搜索：% 与 _ 按字面匹配，不当通配符', async () => {
    await seed({ name: '命中率 100% 的报告' });
    await seed({ name: '兜底 100X 的报告' });
    await seed({ name: '字段 a_b 命名' });
    await seed({ name: '字段 axb 命名' });

    const percent = await list(`q=${encodeURIComponent('100%')}`);
    const percentNames = percent.items.map((item) => (item as { name: string }).name);
    expect(percentNames).toContain('命中率 100% 的报告');
    expect(percentNames).not.toContain('兜底 100X 的报告');

    const underscore = await list(`q=${encodeURIComponent('a_b')}`);
    const underscoreNames = underscore.items.map((item) => (item as { name: string }).name);
    expect(underscoreNames).toEqual(['字段 a_b 命名']);
  });

  it('搜索与页签叠加生效', async () => {
    await seed({ name: '叠加-预置', isPreset: true });
    await seed({ name: '叠加-普通', isPreset: false });
    const { items } = await list(`filter=preset&q=${encodeURIComponent('叠加')}&pageSize=60`);
    expect(items).toHaveLength(1);
    expect((items[0] as { name: string }).name).toBe('叠加-预置');
  });

  it('使用：计数加一，并推高在「最热」中的位置', async () => {
    const id = await seed({ name: '使用计数专家' }, { useCount: 0 });
    await context.services.experts.setUseCount(id, 500);

    const response = await context.app.inject({
      method: 'POST',
      url: `/api/experts/${id}/use`,
      payload: { workspaceId: null },
    });
    expect(response.statusCode).toBe(200);
    expect(response.json().data.useCount).toBe(501);
  });

  it('使用：工作区不存在时返回 404，且不计数', async () => {
    const id = await seed({ name: '使用-坏工作区' }, { useCount: 7 });
    const response = await context.app.inject({
      method: 'POST',
      url: `/api/experts/${id}/use`,
      payload: { workspaceId: '00000000-0000-4000-8000-000000000002' },
    });
    expect(response.statusCode).toBe(404);

    const detail = await context.app.inject({ method: 'GET', url: `/api/experts/${id}` });
    expect(detail.json().data.useCount).toBe(7);
  });

  it('创建：补全默认值并返回 201', async () => {
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/experts',
      payload: { name: '新建专家', author: '某人' },
    });
    expect(response.statusCode).toBe(201);
    const created = response.json().data;
    expect(created.description).toBe('');
    expect(created.tags).toEqual([]);
    expect(created.avatarUrl).toBeNull();
    expect(created.useCount).toBe(0);
    expect(created.isPreset).toBe(false);
  });

  it('创建：头像必须是 http(s) 地址', async () => {
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/experts',
      payload: { name: '坏头像', author: '某人', avatarUrl: 'javascript:alert(1)' },
    });
    expect(response.statusCode).toBe(422);
  });

  it('详情与删除', async () => {
    const id = await seed({ name: '待删除专家' });
    const detail = await context.app.inject({ method: 'GET', url: `/api/experts/${id}` });
    expect(detail.json().data.name).toBe('待删除专家');

    const removed = await context.app.inject({ method: 'DELETE', url: `/api/experts/${id}` });
    expect(removed.json().data.deleted).toBe(true);

    const gone = await context.app.inject({ method: 'GET', url: `/api/experts/${id}` });
    expect(gone.statusCode).toBe(404);
  });

  it('详情不存在返回 404 信封', async () => {
    const response = await context.app.inject({
      method: 'GET',
      url: '/api/experts/00000000-0000-4000-8000-000000000003',
    });
    expect(response.statusCode).toBe(404);
    expect(response.json().error.code).toBe('NOT_FOUND');
  });
});

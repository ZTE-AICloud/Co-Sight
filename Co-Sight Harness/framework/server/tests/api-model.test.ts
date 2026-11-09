/**
 * 模型配置接口（需求 2.3）。
 *
 * 最重要的一条断言是**明文密钥绝不出现在任何响应里**——包括创建响应本身。
 * 很多实现只保证"列表不回明文"，却在创建时把入参原样回显。这里对完整响应体
 * 做字符串包含检查，把这类疏漏钉死。
 */

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { createTestContext, destroyTestContext, type TestContext } from './helpers/context';

const API_KEY = 'sk-live-do-not-leak-0123456789';

let context: TestContext;

beforeAll(async () => {
  context = await createTestContext();
});

afterAll(async () => {
  await destroyTestContext(context);
});

async function createModel(payload: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
  const response = await context.app.inject({
    method: 'POST',
    url: '/api/models',
    payload: {
      provider: 'openai',
      label: '主模型',
      modelName: 'gpt-5',
      apiKey: API_KEY,
      ...payload,
    },
  });
  expect(response.statusCode).toBe(201);
  return response.json().data as Record<string, unknown>;
}

describe('模型配置接口', () => {
  it('创建：补全默认参数', async () => {
    const created = await createModel();
    expect(created.temperature).toBe(0.7);
    expect(created.topP).toBe(1);
    expect(created.timeoutSeconds).toBe(120);
    expect(created.isActive).toBe(false);
  });

  it('创建响应只回掩码，不含明文密钥', async () => {
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/models',
      payload: { provider: 'openai', label: '掩码检查', modelName: 'gpt-5', apiKey: API_KEY },
    });
    expect(response.body).not.toContain(API_KEY);
    const data = response.json().data;
    expect(data.hasApiKey).toBe(true);
    expect(data.apiKeyMasked).toBe('**********');
  });

  it('密钥确实写进了密钥文件，且库里只存引用', async () => {
    const created = await createModel({ label: '落盘检查' });
    const ref = `model:${String(created.id)}`;
    expect(context.services.credentials.read(ref)).toBe(API_KEY);
    // 数据库里不含明文——把整库文件读成字符串来验证，而不是查某一列。
    const dbBytes = await import('node:fs').then((fs) =>
      fs.readFileSync(`${context.home}/test.sqlite`),
    );
    expect(dbBytes.includes(API_KEY)).toBe(false);
  });

  it('列表只回掩码', async () => {
    const response = await context.app.inject({ method: 'GET', url: '/api/models' });
    expect(response.body).not.toContain(API_KEY);
    const items = response.json().data as { apiKeyMasked: string | null }[];
    expect(items.length).toBeGreaterThan(0);
    for (const item of items) {
      expect(item.apiKeyMasked === null || item.apiKeyMasked === '**********').toBe(true);
    }
  });

  /*
   * 详情是**最容易漏掉明文断言**的一条：创建/列表/更新都断言过，
   * 唯独「按 id 取单条」在很长一段时间里没被覆盖——而那正好是前端编辑表单
   * 打开时走的接口。这条补上，让四个读写路径对明文的断言成一套。
   */
  it('详情只回掩码，不含明文密钥，也不含 apiKey 字段', async () => {
    const created = await createModel({ label: '详情掩码' });
    const response = await context.app.inject({
      method: 'GET',
      url: `/api/models/${String(created.id)}`,
    });
    expect(response.statusCode).toBe(200);
    expect(response.body).not.toContain(API_KEY);

    const data = response.json().data as Record<string, unknown>;
    expect(data.apiKeyMasked).toBe('**********');
    // 字段本身都不该存在——只判"值不是明文"的话，一个恒为 null 的 apiKey
    // 字段能骗过检查，而它一旦被填上就是泄漏。
    expect('apiKey' in data).toBe(false);
  });

  it('不提供密钥时 hasApiKey 为 false', async () => {
    const created = await createModel({ label: '无密钥', apiKey: null });
    expect(created.hasApiKey).toBe(false);
    expect(created.apiKeyMasked).toBeNull();
  });

  it('更新密钥会覆盖旧值', async () => {
    const created = await createModel({ label: '覆盖密钥' });
    const response = await context.app.inject({
      method: 'PATCH',
      url: `/api/models/${String(created.id)}`,
      payload: { apiKey: 'sk-rotated-value' },
    });
    expect(response.statusCode).toBe(200);
    expect(response.body).not.toContain('sk-rotated-value');
    expect(context.services.credentials.read(`model:${String(created.id)}`)).toBe(
      'sk-rotated-value',
    );
  });

  it('更新：每个可编辑字段都能单独落库（设置页逐项保存）', async () => {
    const created = await createModel({ label: '逐字段更新' });
    const response = await context.app.inject({
      method: 'PATCH',
      url: `/api/models/${String(created.id)}`,
      payload: {
        provider: 'anthropic',
        label: '改名后',
        baseUrl: 'http://gateway.internal:8080',
        modelName: 'claude-opus-5-5',
        temperature: 0.2,
        topP: 0.9,
        maxOutputTokens: 8192,
        contextWindow: 200000,
        timeoutSeconds: 45,
      },
    });
    expect(response.statusCode).toBe(200);
    const data = response.json().data;
    // 逐个断言：漏掉一列映射（复制粘贴改错列）只有逐项比对才定位得到。
    expect(data.provider).toBe('anthropic');
    expect(data.label).toBe('改名后');
    expect(data.baseUrl).toBe('http://gateway.internal:8080');
    expect(data.modelName).toBe('claude-opus-5-5');
    expect(data.temperature).toBe(0.2);
    expect(data.topP).toBe(0.9);
    expect(data.maxOutputTokens).toBe(8192);
    expect(data.contextWindow).toBe(200000);
    expect(data.timeoutSeconds).toBe(45);
    // 未提及的密钥不受影响，仍然只以掩码出现。
    expect(data.hasApiKey).toBe(true);
    expect(response.body).not.toContain(API_KEY);
  });

  it('更新：可以解除激活标记（isActive: false）', async () => {
    const created = await createModel({ label: '解除激活' });
    const id = String(created.id);
    await context.app.inject({ method: 'POST', url: `/api/models/${id}/activate` });

    const response = await context.app.inject({
      method: 'PATCH',
      url: `/api/models/${id}`,
      payload: { isActive: false },
    });
    expect(response.json().data.isActive).toBe(false);

    // "没有激活项"是 200 + data: null，不是 404 —— 首次启动就是这个状态，
    // 它不是错误，所以 /active 与 /:id 的错误语义刻意不同。
    // 本文件的用例共用一个库，不能断言一定是 null，要断言的是"不再是这一条"。
    const active = await context.app.inject({ method: 'GET', url: '/api/models/active' });
    expect(active.statusCode).toBe(200);
    const current = active.json().data;
    expect(current === null || current.id !== id).toBe(true);
  });

  it('显式传 null 清除密钥', async () => {
    const created = await createModel({ label: '清除密钥' });
    const response = await context.app.inject({
      method: 'PATCH',
      url: `/api/models/${String(created.id)}`,
      payload: { apiKey: null },
    });
    expect(response.json().data.hasApiKey).toBe(false);
    expect(context.services.credentials.read(`model:${String(created.id)}`)).toBeNull();
  });

  it('删除配置会连带删掉密钥，不留孤儿', async () => {
    const created = await createModel({ label: '删除检查' });
    const ref = `model:${String(created.id)}`;
    expect(context.services.credentials.has(ref)).toBe(true);

    await context.app.inject({ method: 'DELETE', url: `/api/models/${String(created.id)}` });
    expect(context.services.credentials.has(ref)).toBe(false);
  });

  it('激活是排他的：同时只有一条 isActive', async () => {
    const first = await createModel({ label: '激活 A' });
    const second = await createModel({ label: '激活 B' });

    await context.app.inject({ method: 'POST', url: `/api/models/${String(first.id)}/activate` });
    await context.app.inject({ method: 'POST', url: `/api/models/${String(second.id)}/activate` });

    const active = await context.app.inject({ method: 'GET', url: '/api/models/active' });
    expect(active.json().data.id).toBe(second.id);

    const list = await context.app.inject({ method: 'GET', url: '/api/models' });
    const actives = (list.json().data as { isActive: boolean }[]).filter((item) => item.isActive);
    expect(actives).toHaveLength(1);
  });

  it('创建时带 isActive 也会清掉上一条的激活标记', async () => {
    const existing = await context.app.inject({ method: 'GET', url: '/api/models/active' });
    const previousId = existing.json().data?.id as string | undefined;

    const created = await createModel({ label: '创建即激活', isActive: true });
    expect(created.isActive).toBe(true);

    if (previousId !== undefined) {
      const previous = await context.app.inject({ method: 'GET', url: `/api/models/${previousId}` });
      expect(previous.json().data.isActive).toBe(false);
    }
  });

  it('校验：baseUrl 只接受 http(s)，temperature 有边界', async () => {
    const badUrl = await context.app.inject({
      method: 'POST',
      url: '/api/models',
      payload: {
        provider: 'openai',
        label: 'x',
        modelName: 'y',
        baseUrl: 'file:///etc/passwd',
      },
    });
    expect(badUrl.statusCode).toBe(422);

    const badTemp = await context.app.inject({
      method: 'POST',
      url: '/api/models',
      payload: { provider: 'openai', label: 'x', modelName: 'y', temperature: 5 },
    });
    expect(badTemp.statusCode).toBe(422);
  });

  it('未知 provider 被拒绝', async () => {
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/models',
      payload: { provider: 'not-a-provider', label: 'x', modelName: 'y' },
    });
    expect(response.statusCode).toBe(422);
  });

  it('连通性探测如实返回未实现（D21 = C）', async () => {
    const created = await createModel({ label: '探测' });
    const response = await context.app.inject({
      method: 'POST',
      url: `/api/models/${String(created.id)}/probe`,
    });
    expect(response.statusCode).toBe(501);
    expect(response.json().error.code).toBe('NOT_IMPLEMENTED');
  });

  it('更新与删除不存在的配置返回 404', async () => {
    const missing = '00000000-0000-4000-8000-00000000000a';
    const patched = await context.app.inject({
      method: 'PATCH',
      url: `/api/models/${missing}`,
      payload: { label: 'x' },
    });
    expect(patched.statusCode).toBe(404);

    const removed = await context.app.inject({ method: 'DELETE', url: `/api/models/${missing}` });
    expect(removed.statusCode).toBe(404);
  });
});

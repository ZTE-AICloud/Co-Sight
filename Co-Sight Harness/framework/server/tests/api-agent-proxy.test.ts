/**
 * Agent 代理配置接口（需求 2.3-1：配置与显示）。
 *
 * "显示"这一半是重点：前端要能把配置渲染回表单，所以除令牌外的字段必须原样返回。
 * 令牌与模型密钥同规则——只回掩码，明文只进密钥文件。
 */

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { createTestContext, destroyTestContext, type TestContext } from './helpers/context';

const TOKEN = 'proxy-token-abcdefghijklmnop';

let context: TestContext;

beforeAll(async () => {
  context = await createTestContext();
});

afterAll(async () => {
  await destroyTestContext(context);
});

async function createProxy(payload: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
  const response = await context.app.inject({
    method: 'POST',
    url: '/api/agent-proxies',
    payload: {
      name: '本地代理',
      agentType: 'openhands',
      endpoint: 'http://127.0.0.1:3000',
      token: TOKEN,
      ...payload,
    },
  });
  expect(response.statusCode).toBe(201);
  return response.json().data as Record<string, unknown>;
}

describe('Agent 代理配置接口', () => {
  it('创建：补全默认值', async () => {
    const created = await createProxy();
    expect(created.maxIterations).toBe(50);
    expect(created.parallelism).toBe(4);
    expect(created.timeoutSeconds).toBe(600);
    expect(created.memoryEnabled).toBe(true);
    expect(created.condensationEnabled).toBe(true);
    expect(created.securityAnalyzer).toBe('none');
    expect(created.enabled).toBe(true);
    expect(created.extra).toEqual({});
  });

  it('令牌只回掩码，响应体不含明文', async () => {
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/agent-proxies',
      payload: { name: '掩码检查', agentType: 'custom', token: TOKEN },
    });
    expect(response.body).not.toContain(TOKEN);
    expect(response.json().data.hasToken).toBe(true);
    expect(response.json().data.tokenMasked).toBe('**********');
  });

  it('令牌写入密钥文件', async () => {
    const created = await createProxy({ name: '落盘检查' });
    expect(context.services.credentials.read(`agent-proxy:${String(created.id)}`)).toBe(TOKEN);
  });

  it('显示：可编辑字段原样返回，供前端渲染表单', async () => {
    const created = await createProxy({
      name: '完整配置',
      description: '用于渲染测试',
      maxIterations: 12,
      parallelism: 2,
      securityAnalyzer: 'invariant',
      extra: { workspaceRoot: '/srv/x' },
    });
    const detail = await context.app.inject({
      method: 'GET',
      url: `/api/agent-proxies/${String(created.id)}`,
    });
    const data = detail.json().data;
    expect(data.description).toBe('用于渲染测试');
    expect(data.maxIterations).toBe(12);
    expect(data.parallelism).toBe(2);
    expect(data.securityAnalyzer).toBe('invariant');
    expect(data.extra).toEqual({ workspaceRoot: '/srv/x' });
  });

  it('未提供令牌时 hasToken 为 false', async () => {
    expect((await createProxy({ name: '无令牌', token: null })).hasToken).toBe(false);
  });

  it('更新：部分字段更新不影响其它字段', async () => {
    const created = await createProxy({ name: '更新检查' });
    const response = await context.app.inject({
      method: 'PATCH',
      url: `/api/agent-proxies/${String(created.id)}`,
      payload: { parallelism: 8 },
    });
    const data = response.json().data;
    expect(data.parallelism).toBe(8);
    expect(data.maxIterations).toBe(50);
    expect(data.name).toBe('更新检查');
    expect(data.hasToken).toBe(true);
  });

  it('更新：每个可编辑字段都能单独落库（设置页逐项保存）', async () => {
    const created = await createProxy({ name: '逐字段更新' });
    const id = String(created.id);
    const response = await context.app.inject({
      method: 'PATCH',
      url: `/api/agent-proxies/${id}`,
      payload: {
        name: '改名后',
        description: '新描述',
        agentType: 'custom',
        endpoint: 'http://127.0.0.1:4000',
        enabled: false,
        maxIterations: 7,
        parallelism: 1,
        timeoutSeconds: 30,
        memoryEnabled: false,
        condensationEnabled: false,
        securityAnalyzer: 'invariant',
        extra: { workspaceRoot: '/srv/y' },
      },
    });
    expect(response.statusCode).toBe(200);
    const data = response.json().data;
    // 逐个字段断言而不是整体比对：漏掉一个字段的映射（比如复制粘贴时改错了列）
    // 只有逐项断言才能定位到是哪个字段。
    expect(data.name).toBe('改名后');
    expect(data.description).toBe('新描述');
    expect(data.agentType).toBe('custom');
    expect(data.endpoint).toBe('http://127.0.0.1:4000');
    expect(data.enabled).toBe(false);
    expect(data.maxIterations).toBe(7);
    expect(data.parallelism).toBe(1);
    expect(data.timeoutSeconds).toBe(30);
    expect(data.memoryEnabled).toBe(false);
    expect(data.condensationEnabled).toBe(false);
    expect(data.securityAnalyzer).toBe('invariant');
    expect(data.extra).toEqual({ workspaceRoot: '/srv/y' });
    // 未提及的令牌不受影响。
    expect(data.hasToken).toBe(true);
  });

  it('更新：显式 null 清空描述，undefined 不动它', async () => {
    const created = await createProxy({ name: '清描述', description: '原描述' });
    const id = String(created.id);

    // 只想清空 description：其它字段一概不传。若把 undefined 与 null 合并处理，
    // 每次保存表单都会顺手把没碰过的字段清掉。
    const cleared = await context.app.inject({
      method: 'PATCH',
      url: `/api/agent-proxies/${id}`,
      payload: { description: null },
    });
    expect(cleared.json().data.description).toBeNull();
    expect(cleared.json().data.name).toBe('清描述');
  });

  it('更新：rotation 换令牌后旧明文不再留在密钥文件里', async () => {
    const created = await createProxy({ name: '换令牌' });
    const id = String(created.id);
    await context.app.inject({
      method: 'PATCH',
      url: `/api/agent-proxies/${id}`,
      payload: { token: 'rotated-token-zyxwvutsrq' },
    });
    expect(context.services.credentials.read(`agent-proxy:${id}`)).toBe('rotated-token-zyxwvutsrq');
  });

  it('更新：isDefault 传 false 会解除默认标记', async () => {
    const created = await createProxy({ name: '取消默认' });
    const id = String(created.id);
    await context.app.inject({ method: 'POST', url: `/api/agent-proxies/${id}/default` });

    const response = await context.app.inject({
      method: 'PATCH',
      url: `/api/agent-proxies/${id}`,
      payload: { isDefault: false },
    });
    expect(response.json().data.isDefault).toBe(false);

    // "没有默认项"是 200 + data: null，不是 404——它不是错误。
    // 本文件的用例共用一个库，不能断言一定是 null，要断言的是"不再是这一条"。
    const current = await context.app.inject({ method: 'GET', url: '/api/agent-proxies/default' });
    expect(current.statusCode).toBe(200);
    const data = current.json().data;
    expect(data === null || data.id !== id).toBe(true);
  });

  it('更新不存在的配置返回 404', async () => {
    const missing = '00000000-0000-4000-8000-00000000000c';
    const response = await context.app.inject({
      method: 'PATCH',
      url: `/api/agent-proxies/${missing}`,
      payload: { name: '无' },
    });
    expect(response.statusCode).toBe(404);
  });

  it('显式传 null 清除令牌', async () => {
    const created = await createProxy({ name: '清令牌' });
    await context.app.inject({
      method: 'PATCH',
      url: `/api/agent-proxies/${String(created.id)}`,
      payload: { token: null },
    });
    expect(context.services.credentials.read(`agent-proxy:${String(created.id)}`)).toBeNull();
  });

  it('默认配置是排他的', async () => {
    const first = await createProxy({ name: '默认 A' });
    const second = await createProxy({ name: '默认 B' });

    await context.app.inject({ method: 'POST', url: `/api/agent-proxies/${String(first.id)}/default` });
    await context.app.inject({
      method: 'POST',
      url: `/api/agent-proxies/${String(second.id)}/default`,
    });

    const current = await context.app.inject({ method: 'GET', url: '/api/agent-proxies/default' });
    expect(current.json().data.id).toBe(second.id);
  });

  it('删除配置会连带删掉令牌', async () => {
    const created = await createProxy({ name: '删除检查' });
    const ref = `agent-proxy:${String(created.id)}`;
    expect(context.services.credentials.has(ref)).toBe(true);

    await context.app.inject({
      method: 'DELETE',
      url: `/api/agent-proxies/${String(created.id)}`,
    });
    expect(context.services.credentials.has(ref)).toBe(false);
  });

  it('校验：endpoint 只接受 http(s)，安全分析器取枚举值', async () => {
    const badEndpoint = await context.app.inject({
      method: 'POST',
      url: '/api/agent-proxies',
      payload: { name: 'x', agentType: 'custom', endpoint: 'ftp://x.test' },
    });
    expect(badEndpoint.statusCode).toBe(422);

    const badAnalyzer = await context.app.inject({
      method: 'POST',
      url: '/api/agent-proxies',
      payload: { name: 'x', agentType: 'custom', securityAnalyzer: 'magic' },
    });
    expect(badAnalyzer.statusCode).toBe(422);
  });

  it('不存在的配置返回 404', async () => {
    const missing = '00000000-0000-4000-8000-00000000000b';
    expect((await context.app.inject({ method: 'GET', url: `/api/agent-proxies/${missing}` })).statusCode).toBe(404);
    expect(
      (await context.app.inject({ method: 'DELETE', url: `/api/agent-proxies/${missing}` })).statusCode,
    ).toBe(404);
  });
});

/**
 * 模块面 RAG 知识库接口（`/api/framework/v1/rag-knowledge`）。
 *
 * 这里测两件事，缺一不可：
 *
 * 1. **门禁确实继承到了新子树**。它不在 `module-rag-knowledge.ts` 里，而在父上下文
 *    `module-face.ts` 的 `onRequest` 上——"新子树忘了挂门禁"不会报错，只会安静地
 *    对全世界开放，所以必须有断言钉住（无令牌 / 带 `Origin` / 非回环 Host 三种）。
 * 2. **这一面只读**。`POST` / `PATCH` / `DELETE` 一律 404；少一个写入口就是少一分
 *    泄漏令牌的杀伤面。
 */

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import {
  createTestContext,
  destroyTestContext,
  withContext,
  type TestContext,
} from './helpers/context';

const BASE_PATH = '/api/framework/v1/rag-knowledge';

let context: TestContext;
let token: string;

function callModule(pathname = '', init: Record<string, unknown> = {}) {
  return context.app.inject({
    method: 'GET',
    url: `${BASE_PATH}${pathname}`,
    headers: { authorization: `Bearer ${token}` },
    ...init,
  });
}

beforeAll(async () => {
  context = await createTestContext();
  token = context.services.moduleToken.read() ?? '';
  expect(token).not.toBe('');

  await context.services.ragKnowledge.create({
    name: '生效知识库',
    routeUrl: 'https://kb.example.com/live',
    username: 'kb-admin',
    password: 'live-pass',
    apiKey: 'live-key',
    description: null,
    isActive: true,
  });
  await context.services.ragKnowledge.create({
    name: '备用知识库',
    routeUrl: 'https://kb.example.com/standby',
    description: null,
    isActive: false,
  });
});

afterAll(async () => {
  await destroyTestContext(context);
});

describe('模块面 RAG 知识库门禁', () => {
  it('没有令牌 → 401', async () => {
    const response = await context.app.inject({ method: 'GET', url: `${BASE_PATH}/active` });
    expect(response.statusCode).toBe(401);
  });

  it('带 Origin 的浏览器请求 → 403', async () => {
    const response = await callModule('/active', {
      headers: { authorization: `Bearer ${token}`, origin: 'http://127.0.0.1:4830' },
    });
    expect(response.statusCode).toBe(403);
  });

  it('非回环 Host → 403', async () => {
    const response = await callModule('/active', {
      headers: { authorization: `Bearer ${token}`, host: 'evil.example' },
    });
    expect(response.statusCode).toBe(403);
  });
});

describe('模块面 RAG 知识库读取', () => {
  it('列表返回全部记录', async () => {
    const response = await callModule();
    expect(response.statusCode).toBe(200);
    const names = (response.json().data as Record<string, unknown>[]).map((item) => item.name);
    expect(names).toContain('生效知识库');
    expect(names).toContain('备用知识库');
  });

  it('/active 返回当前生效的那条', async () => {
    const response = await callModule('/active');
    expect(response.statusCode).toBe(200);
    expect(response.json().data.name).toBe('生效知识库');
  });

  /*
   * 两面的分工在这里最容易被改坏：列表**不含**明文，只有 `/active` 含。
   * 少了这条断言，某天有人"顺手"让列表也返回密码，CI 不会有任何反应。
   */
  it('明文密码与 API Key 只从 /active 出去，列表只给 hasX', async () => {
    const list = (await callModule()).json().data as Record<string, unknown>[];
    const live = list.find((item) => item.name === '生效知识库');
    expect(live?.hasPassword).toBe(true);
    expect(live?.hasApiKey).toBe(true);
    expect(live).not.toHaveProperty('password');
    expect(live).not.toHaveProperty('passwordMasked');
    expect(live).not.toHaveProperty('apiKey');
    expect(live).not.toHaveProperty('apiKeyMasked');

    const active = (await callModule('/active')).json().data as Record<string, unknown>;
    expect(active.username).toBe('kb-admin');
    expect(active.password).toBe('live-pass');
    expect(active.apiKey).toBe('live-key');
    // 掩码是浏览器面的东西，模块面直接给生效的明文（或 null）。
    expect(active).not.toHaveProperty('passwordMasked');
    expect(active).not.toHaveProperty('apiKeyMasked');
  });

  it('没配密码的生效项，password 是 null 而不是缺键', async () => {
    await context.services.ragKnowledge.create({
      name: '无密码知识库',
      routeUrl: 'https://kb.example.com/open',
      description: null,
      isActive: true,
    });

    const active = (await callModule('/active')).json().data as Record<string, unknown>;
    expect(active.name).toBe('无密码知识库');
    expect(active.hasPassword).toBe(false);
    expect(active.password).toBeNull();
    expect(active.hasApiKey).toBe(false);
    // 这个上下文没设默认密钥，所以必须原样是 null——默认层另有专门的用例。
    expect(active.apiKey).toBeNull();
  });
});

/**
 * API Key 的两层：路由自己配的优先，没配时回落到服务端默认。
 *
 * 默认值只存在于服务端内存（环境变量 `CO_KNOWLEDGE_API_KEY`），所以必须用一个
 * **单独设了该变量**的上下文来测。文件级那个上下文没设，上面那些"没配就是 null"
 * 的断言才立得住。
 */
describe('模块面 API Key 的默认层', () => {
  it(
    '路由没配 Key 时用 CO_KNOWLEDGE_API_KEY，自己配了则用自己的',
    withContext(
      async (ctx) => {
        const moduleToken = ctx.services.moduleToken.read() ?? '';

        // 浏览器面只该知道"有默认"，值本身不能出现在响应里。
        const defaults = await ctx.app.inject({
          method: 'GET',
          url: '/api/rag-knowledge/defaults',
        });
        expect(defaults.json().data).toEqual({ hasDefaultApiKey: true });
        expect(JSON.stringify(defaults.json())).not.toContain('ragk_default');

        await ctx.services.ragKnowledge.create({
          name: '用默认密钥',
          routeUrl: 'https://kb.example.com/default',
          description: null,
          isActive: true,
        });

        const fallback = await ctx.app.inject({
          method: 'GET',
          url: `${BASE_PATH}/active`,
          headers: { authorization: `Bearer ${moduleToken}` },
        });
        expect(fallback.json().data.apiKey).toBe('ragk_default');

        await ctx.services.ragKnowledge.create({
          name: '用自己的密钥',
          routeUrl: 'https://kb.example.com/own',
          apiKey: 'ragk_own',
          description: null,
          isActive: true,
        });

        const own = await ctx.app.inject({
          method: 'GET',
          url: `${BASE_PATH}/active`,
          headers: { authorization: `Bearer ${moduleToken}` },
        });
        // 自己的那一枚优先——默认只是兜底，不是覆盖。
        expect(own.json().data.apiKey).toBe('ragk_own');
      },
      { CO_KNOWLEDGE_API_KEY: 'ragk_default' },
    ),
  );
});

describe('模块面 RAG 知识库只读', () => {
  it('写方法一律 404', async () => {
    const requests = [
      { method: 'POST' as const, url: BASE_PATH, payload: { name: 'x', routeUrl: 'https://x.example/' } },
      { method: 'PATCH' as const, url: `${BASE_PATH}/active`, payload: { name: 'x' } },
      { method: 'DELETE' as const, url: `${BASE_PATH}/active` },
    ];
    for (const request of requests) {
      const response = await context.app.inject({
        ...request,
        headers: { authorization: `Bearer ${token}` },
      });
      expect(response.statusCode).toBe(404);
    }
  });
});

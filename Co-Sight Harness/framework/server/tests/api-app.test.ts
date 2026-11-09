/**
 * 应用级行为：信封一致性、404、校验失败、文档页。
 *
 * "每个响应都是同一套信封"是前端最依赖的约定——只要有一条路径漏了信封，
 * 前端的统一解包逻辑就要加分支。所以这里逐条钉住，包括 404 这种容易被忽略的路径。
 */

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { createTestContext, destroyTestContext, type TestContext } from './helpers/context';

let context: TestContext;

beforeAll(async () => {
  context = await createTestContext();
});

afterAll(async () => {
  await destroyTestContext(context);
});

describe('应用级行为', () => {
  it('健康检查返回已验证的信封与数据目录', async () => {
    const response = await context.app.inject({ method: 'GET', url: '/api/health' });
    expect(response.statusCode).toBe(200);
    const body = response.json();
    expect(body.success).toBe(true);
    expect(body.error).toBeNull();
    expect(body.meta).toBeNull();
    expect(body.data.status).toBe('ok');
    expect(body.data.cosightHome).toBe(context.home);
  });

  it('未知路由返回 404 信封而不是 HTML', async () => {
    const response = await context.app.inject({ method: 'GET', url: '/api/nope' });
    expect(response.statusCode).toBe(404);
    const body = response.json();
    expect(body.success).toBe(false);
    expect(body.data).toBeNull();
    expect(body.error.code).toBe('NOT_FOUND');
    expect(body.error.traceId).not.toBeNull();
  });

  it('请求体校验失败返回 422 与字段级明细', async () => {
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/workspaces',
      payload: { name: '' },
    });
    expect(response.statusCode).toBe(422);
    const body = response.json();
    expect(body.error.code).toBe('VALIDATION_FAILED');
    expect(body.error.details.length).toBeGreaterThan(0);
    const issue = body.error.details[0];
    expect(issue.path).toBe('name');
    expect(issue.messageKey).toMatch(/^validation\./);
  });

  it('校验失败时未提供的字段也会被报告（提示缺失字段）', async () => {
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/experts',
      payload: { name: 'x' },
    });
    expect(response.statusCode).toBe(422);
    const paths = response.json().error.details.map((i: { path: string }) => i.path);
    expect(paths).toContain('author');
  });

  it('查询参数校验失败走同一条校验错误路径', async () => {
    const response = await context.app.inject({
      method: 'GET',
      url: '/api/experts?page=0',
    });
    expect(response.statusCode).toBe(422);
    expect(response.json().error.code).toBe('VALIDATION_FAILED');
  });

  it('非法的 uuid 路径参数被入口挡下', async () => {
    const response = await context.app.inject({
      method: 'GET',
      url: '/api/experts/..%2Fetc%2Fpasswd',
    });
    // 要么被参数校验拦下(422)，要么被路由判为不存在(404)，都不能是 200 或 500。
    expect([404, 422]).toContain(response.statusCode);
  });

  it('不存在路由上的非 GET 方法同样走信封', async () => {
    const response = await context.app.inject({ method: 'DELETE', url: '/api/nope' });
    expect(response.statusCode).toBe(404);
    expect(response.json().success).toBe(false);
  });

  it('OpenAPI 文档页可用，且所有资源都进了文档', async () => {
    const response = await context.app.inject({ method: 'GET', url: '/api/docs/json' });
    expect(response.statusCode).toBe(200);
    const document = response.json();
    expect(document.openapi).toBeDefined();

    const paths = Object.keys(document.paths);
    // 集合路由注册在 prefix 的 '/' 上，文档里会带尾斜杠。
    expect(paths).toContain('/api/workspaces/');
    expect(paths).toContain('/api/experts/');
    expect(paths).toContain('/api/models/');
    expect(paths).toContain('/api/agent-proxies/');
    expect(paths).toContain('/api/bridge/exchange');
    // 模块面（对外，含明文密钥）也必须进文档——它是最需要被文档说清楚的接口。
    expect(paths).toContain('/api/framework/v1/models/');
    expect(paths).toContain('/api/framework/v1/models/active');
    expect(paths).toContain('/api/framework/v1/models/{id}');
  });

  it('每个接口都归到分组，不散落在 default 下', async () => {
    const response = await context.app.inject({ method: 'GET', url: '/api/docs/json' });
    const document = response.json();
    // 没有 schema.tags 的接口会在文档里挤成一堆，分组是文档可用的前提。
    for (const [path, methods] of Object.entries(document.paths)) {
      for (const [method, operation] of Object.entries(methods as Record<string, unknown>)) {
        const tags = (operation as { tags?: string[] }).tags;
        expect(tags, `${method.toUpperCase()} ${path} 缺少 tags`).toBeDefined();
        expect(tags?.length).toBeGreaterThan(0);
      }
    }
  });

  it('请求侧 schema 被翻译成 JSON Schema（zod 契约进了文档）', async () => {
    const response = await context.app.inject({ method: 'GET', url: '/api/docs/json' });
    const document = response.json();
    const list = document.paths['/api/experts/'].get;
    // pageSize 的上限 60 是契约里的约束，必须体现在文档里。
    expect(JSON.stringify(list.parameters)).toContain('60');
  });
});

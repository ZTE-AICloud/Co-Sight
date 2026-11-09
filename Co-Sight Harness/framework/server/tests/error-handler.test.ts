/**
 * 错误处理器。
 *
 * 这里最要紧的一条是**5xx 不外泄原始 message**：异常文本常带文件路径、SQL 片段
 * 或密钥，而 Fastify 默认会把 message 原样返回。这条靠集成测试（真实路由抛出
 * 真实异常）来验，单元测断言不出"实际响应体里没有敏感串"。
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import fastifyStatic from '@fastify/static';
import Fastify, { type FastifyError, type FastifyInstance } from 'fastify';
import { serializerCompiler, validatorCompiler } from 'fastify-type-provider-zod';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { installErrorHandler } from '../src/plugins/error-handler';

/** 一段"如果泄漏了就很难看"的文本，用来验证 5xx 把它吞掉。 */
const SENSITIVE = '/home/user/.cosight-harness/.credentials.yaml 含 sk-live-abcdef';

let app: FastifyInstance;

async function buildTestApp(options: { serveSpa?: boolean; staticRoot?: string }): Promise<void> {
  app = Fastify({ logger: false });
  app.setValidatorCompiler(validatorCompiler);
  app.setSerializerCompiler(serializerCompiler);
  installErrorHandler(
    app,
    options.serveSpa === undefined ? {} : { serveSpa: options.serveSpa },
  );

  app.get('/boom', () => {
    throw new Error(SENSITIVE);
  });

  app.get('/teapot', () => {
    const error = new Error('我是茶壶') as FastifyError;
    error.statusCode = 418;
    throw error;
  });

  if (options.staticRoot !== undefined) {
    await app.register(fastifyStatic, { root: options.staticRoot, wildcard: false });
  }

  await app.ready();
}

afterEach(async () => {
  await app.close();
});

describe('错误处理器', () => {
  beforeEach(async () => {
    await buildTestApp({});
  });

  it('未捕获的异常返回 500 信封，且不泄漏原始 message', async () => {
    const response = await app.inject({ method: 'GET', url: '/boom' });
    expect(response.statusCode).toBe(500);
    expect(response.body).not.toContain(SENSITIVE);
    expect(response.body).not.toContain('sk-live-abcdef');
    expect(response.body).not.toContain('.credentials.yaml');

    const body = response.json();
    expect(body.success).toBe(false);
    expect(body.error.code).toBe('INTERNAL');
    expect(body.error.message).toBe('服务内部错误');
    expect(body.error.traceId).not.toBeNull();
  });

  it('未列入映射表的状态码回落到 INTERNAL，且对外只报契约里有的状态码', async () => {
    const response = await app.inject({ method: 'GET', url: '/teapot' });
    // 内部异常带了 418，但响应状态由错误码映射得出（ERROR_HTTP_STATUS），
    // 所以对外是 500 —— 前端永远只需要处理契约里定义过的那几个状态码，
    // 不会被某个库随手抛出的奇怪状态码打乱。
    expect(response.statusCode).toBe(500);
    expect(response.json().error.code).toBe('INTERNAL');
  });

  it('未知路由返回 404 信封', async () => {
    const response = await app.inject({ method: 'GET', url: '/nothing-here' });
    expect(response.statusCode).toBe(404);
    expect(response.json().error.code).toBe('NOT_FOUND');
  });
});

describe('错误处理器：单页应用回退', () => {
  let webRoot: string;

  beforeEach(async () => {
    webRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-web-'));
    fs.writeFileSync(path.join(webRoot, 'index.html'), '<!doctype html><title>框架首页</title>');
    // 静态文件必须在注册前就位：`wildcard: false` 是"为每个已存在的文件建一条路由"，
    // 注册之后再写文件不会自动出现在路由表里。生产态 dist 是构建完成的，不受影响。
    fs.writeFileSync(path.join(webRoot, 'app.js'), 'console.log(1)');
    await buildTestApp({ serveSpa: true, staticRoot: webRoot });
  });

  afterEach(() => {
    fs.rmSync(webRoot, { recursive: true, force: true });
  });

  it('前端路由（GET 非 /api）回退到首页，刷新页面不白屏', async () => {
    const response = await app.inject({ method: 'GET', url: '/experts' });
    expect(response.statusCode).toBe(200);
    expect(response.body).toContain('框架首页');
  });

  it('未知的 API 路径仍然返回 404 信封，不回退成首页', async () => {
    const response = await app.inject({ method: 'GET', url: '/api/definitely-not-here' });
    expect(response.statusCode).toBe(404);
    // 若这里返回 HTML，前端的统一解包逻辑会被一个 200 + HTML 打乱。
    expect(response.json().error.code).toBe('NOT_FOUND');
  });

  it('非 GET 请求不回退到首页', async () => {
    const response = await app.inject({ method: 'POST', url: '/experts' });
    expect(response.statusCode).toBe(404);
  });

  it('真实存在的静态文件优先于首页回退', async () => {
    const response = await app.inject({ method: 'GET', url: '/app.js' });
    expect(response.statusCode).toBe(200);
    expect(response.body).toBe('console.log(1)');
  });

  it('缺失的带扩展名资源返回 404 信封，而不是回退成 HTML', async () => {
    // 浏览器脚本请求不带 Accept: text/html，但断言不依赖这一点：
    // 只要路径带扩展名，就按"缺资源"处理。
    const response = await app.inject({
      method: 'GET',
      url: '/assets/index-KENmPXQz.js',
      headers: { accept: '*/*' },
    });
    expect(response.statusCode).toBe(404);
    expect(response.json().error.code).toBe('NOT_FOUND');
    // 回退成 200 + text/html 会让浏览器按 MIME 拒收，表现为整页白屏（D49）。
    expect(response.headers['content-type']).toContain('application/json');
  });
});

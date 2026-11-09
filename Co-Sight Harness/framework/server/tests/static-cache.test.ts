/**
 * 产物静态资源的缓存头。
 *
 * 打包把文件 mtime 统一成 1970，静态插件默认的 ETag 是「字节数 + mtime」。
 * 新旧两版 index.html 只要字节数相同，ETag 就完全相同：升级后浏览器带着旧 ETag
 * 回源，服务端回 304，浏览器继续使用指向旧 bundle 的缓存页面，而旧资源已经被删掉，
 * 结果就是整页白屏且控制台只有 404。这里钉住"不做基于 mtime 的协商缓存"。
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import type { FastifyInstance } from 'fastify';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { buildApp } from '../src/app';
import { loadConfig } from '../src/config/env';
import { closeServices, createServices, type Services } from '../src/services/container';

/** 与产物里 index.html 的字节数一致；两版同大小正是撞 ETag 的条件。 */
const INDEX_BYTES = 493;

let home: string;
let webRoot: string;
let services: Services;
let app: FastifyInstance;

beforeEach(async () => {
  home = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-static-home-'));
  webRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-static-web-'));
  fs.mkdirSync(path.join(webRoot, 'assets'));
  fs.writeFileSync(path.join(webRoot, 'index.html'), 'a'.repeat(INDEX_BYTES));
  fs.writeFileSync(path.join(webRoot, 'assets', 'index-abc123.js'), 'console.info(1)');

  const config = loadConfig({
    COSIGHT_HOME: home,
    COSIGHT_DATABASE_URL: `file:${path.join(home, 'test.sqlite')}`,
    COSIGHT_WEB_DIST: webRoot,
    NODE_ENV: 'test',
  });
  services = await createServices({ config });
  app = await buildApp({ services, logger: false });
  await app.ready();
});

afterEach(async () => {
  await app.close();
  await closeServices(services);
  fs.rmSync(home, { recursive: true, force: true });
  fs.rmSync(webRoot, { recursive: true, force: true });
});

describe('静态资源缓存', () => {
  it('index.html 不走 mtime ETag：旧 ETag 不会换来 304', async () => {
    const first = await app.inject({ method: 'GET', url: '/' });
    expect(first.statusCode).toBe(200);
    expect(first.headers['cache-control']).toBe('no-cache');
    expect(first.headers.etag).toBeUndefined();

    // 模拟升级前留下的浏览器：带着旧 ETag 回源，必须重新拿到当前页面。
    const conditional = await app.inject({
      method: 'GET',
      url: '/',
      headers: { 'if-none-match': 'W/"1ed-0"' },
    });
    expect(conditional.statusCode).toBe(200);
    expect(conditional.body).toHaveLength(INDEX_BYTES);
  });

  it('assets 下的哈希文件长期缓存，且不依赖条件请求', async () => {
    const response = await app.inject({ method: 'GET', url: '/assets/index-abc123.js' });
    expect(response.statusCode).toBe(200);
    expect(response.headers['cache-control']).toContain('immutable');
    expect(response.headers.etag).toBeUndefined();
  });

  it('SPA 深链接仍回退到首页，并沿用同样的缓存策略', async () => {
    const response = await app.inject({ method: 'GET', url: '/experts' });
    expect(response.statusCode).toBe(200);
    expect(response.headers['cache-control']).toBe('no-cache');
  });
});

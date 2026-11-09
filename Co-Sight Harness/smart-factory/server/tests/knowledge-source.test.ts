/**
 * 知识服务参数的来源优先级：框架「知识库路由设置」优先，环境变量兜底。
 *
 * 框架模块面用本地桩（校验 Bearer、可随时切换生效路由与状态码），
 * 不依赖本机真的在跑框架。真实契约见 framework/docs/rag-knowledge-api.md。
 */
import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createServer, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import { join } from 'node:path';
import { prepareTestEnv } from './helpers/test-db.js';

const env = prepareTestEnv('knowledge-source');

type Mode = 'ok' | 'error';
let mode: Mode = 'ok';
let active: Record<string, unknown> | null = null;
let seenAuthorization: string | undefined;

function send(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(JSON.stringify(body));
}

function ok(data: unknown): unknown {
  return { success: true, data, error: null, meta: null };
}

const token = readFileSync(join(env.home, '.module-token'), 'utf8').trim();

const stub = createServer((req, res) => {
  seenAuthorization = req.headers.authorization;

  if (req.url !== '/api/framework/v1/rag-knowledge/active') {
    send(res, 404, { success: false, data: null, error: { code: 'NOT_FOUND', message: '接口不存在' }, meta: null });
    return;
  }
  if (mode === 'error') {
    send(res, 500, { success: false, data: null, error: { code: 'INTERNAL', message: '数据目录不可写' }, meta: null });
    return;
  }
  if (req.headers.authorization !== `Bearer ${token}`) {
    send(res, 401, { success: false, data: null, error: { code: 'UNAUTHORIZED', message: '模块令牌无效' }, meta: null });
    return;
  }
  send(res, 200, ok(active));
});

let source: typeof import('../src/modules/knowledge/knowledge-source.js');

before(async () => {
  await new Promise<void>((resolve) => stub.listen(0, '127.0.0.1', resolve));
  const port = (stub.address() as AddressInfo).port;

  // 必须在 import src 之前设好：config 在 import 时读环境
  process.env.FRAMEWORK_BASE_URL = `http://127.0.0.1:${port}`;
  process.env.CO_KNOWLEDGE_BASE_URL = 'http://env.example.com';
  process.env.CO_KNOWLEDGE_API_KEY = 'ragk_env';

  source = await import('../src/modules/knowledge/knowledge-source.js');
});

after(async () => {
  await new Promise<void>((resolve) => stub.close(() => resolve()));
});

test('routeUrl 只取 origin：路径、查询串、hash 都丢掉', () => {
  const { baseUrlFromRouteUrl } = source;

  assert.equal(baseUrlFromRouteUrl('http://rag-studio.example.com/#/login?redirect=/kb'), 'http://rag-studio.example.com');
  assert.equal(baseUrlFromRouteUrl('https://kb.example.com/kb/42?x=1'), 'https://kb.example.com');
  assert.equal(baseUrlFromRouteUrl('https://kb.example.com:8443/a/b'), 'https://kb.example.com:8443');
  // 非 http(s) 与解析失败都交给环境变量兜底
  assert.equal(baseUrlFromRouteUrl('ftp://kb.example.com'), null);
  assert.equal(baseUrlFromRouteUrl('不是地址'), null);
});

test('框架有生效路由时，基址与 Key 都优先用框架的', async () => {
  mode = 'ok';
  active = { routeUrl: 'http://kb.framework:9000/#/login', apiKey: 'ragk_framework', isActive: true };

  assert.deepEqual(await source.resolveKnowledgeSource(), {
    baseUrl: 'http://kb.framework:9000',
    apiKey: 'ragk_framework',
  });
  assert.equal(seenAuthorization, `Bearer ${token}`);
});

test('框架没有生效路由（data: null）时整组回落 env', async () => {
  mode = 'ok';
  active = null;

  assert.deepEqual(await source.resolveKnowledgeSource(), {
    baseUrl: 'http://env.example.com',
    apiKey: 'ragk_env',
  });
});

test('框架给了路由但 Key 为 null：基址用框架的，Key 回落 env', async () => {
  mode = 'ok';
  active = { routeUrl: 'http://kb.framework:9000', apiKey: null, isActive: true };

  assert.deepEqual(await source.resolveKnowledgeSource(), {
    baseUrl: 'http://kb.framework:9000',
    apiKey: 'ragk_env',
  });
});

test('routeUrl 不合法时基址回落 env，但框架的 Key 照用', async () => {
  mode = 'ok';
  active = { routeUrl: 'ftp://kb.framework', apiKey: 'ragk_framework', isActive: true };

  assert.deepEqual(await source.resolveKnowledgeSource(), {
    baseUrl: 'http://env.example.com',
    apiKey: 'ragk_framework',
  });
});

test('框架不可用（500）时静默回落 env，不把故障抛给调用方', async () => {
  mode = 'error';

  assert.deepEqual(await source.resolveKnowledgeSource(), {
    baseUrl: 'http://env.example.com',
    apiKey: 'ragk_env',
  });
});

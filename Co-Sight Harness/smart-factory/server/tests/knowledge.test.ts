/**
 * 知识检索列表代理：认证头、只列已发布、字段映射与上游失败的翻译。
 *
 * 上游用本地桩，不依赖真实 RAG Studio；真实响应形状见 4.15-知识库.md。
 */
import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import type { AddressInfo } from 'node:net';
import { prepareTestEnv } from './helpers/test-db.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

const env = prepareTestEnv('knowledge');

type Mode = 'ok' | 'unauthorized' | 'html';
let mode: Mode = 'ok';
const seen: { url: string | undefined; apiKey: string | undefined; authorization: string | undefined }[] = [];

/** 照真实响应裁剪：混合草稿、非法 id、缺 id 三种脏数据（防御性过滤的回归）。 */
const RAG_ITEMS = [
  { workFlowId: 'RAG_Workflow_780f', name: 'test1', description: '示例工作流', publishType: 1 },
  { workFlowId: 'RAG_Workflow_89f4', name: '顺序检索', description: '', publishType: 1 },
  { workFlowId: 'RAG_Workflow_1035', name: 'test456', description: '', publishType: 0 },
  { workFlowId: 'bad id!', name: '非法 id', description: '', publishType: 1 },
  { name: '缺 id', description: '', publishType: 1 },
];

const ragStub = createServer((req, res) => {
  seen.push({
    url: req.url,
    apiKey: req.headers['x-api-key'] as string | undefined,
    authorization: req.headers.authorization,
  });

  if (mode === 'unauthorized') {
    res.writeHead(401, { 'content-type': 'application/json' });
    res.end('{"code":"unauthorized"}');
    return;
  }
  if (mode === 'html') {
    res.writeHead(200, { 'content-type': 'text/html' });
    res.end('<html>RAG Studio</html>');
    return;
  }

  res.writeHead(200, { 'content-type': 'application/json' });
  res.end(JSON.stringify({ items: RAG_ITEMS, total: 8, page: 1, pageSize: 500 }));
});

let api: TestApi;
let knowledge: typeof import('../src/modules/knowledge/knowledge.service.js');

before(async () => {
  await new Promise<void>((resolve) => ragStub.listen(0, '127.0.0.1', resolve));
  const port = (ragStub.address() as AddressInfo).port;

  // 必须在 import src 之前设好：config 在 import 时读环境（与其它用例同一约定）
  process.env.CO_KNOWLEDGE_BASE_URL = `http://127.0.0.1:${port}`;
  process.env.CO_KNOWLEDGE_API_KEY = 'ragk_test-key';
  // 本用例只测环境变量这一条路：把框架指到没人监听的端口，让解析必定回落到 env
  // （否则开发机上真在跑框架时会读到设置里的路由，用例随环境飘）。
  process.env.FRAMEWORK_BASE_URL = 'http://127.0.0.1:1';
  delete process.env.CO_KNOWLEDGE_AUTH_MODE;
  delete process.env.CO_KNOWLEDGE_SESSION_COOKIE;

  knowledge = await import('../src/modules/knowledge/knowledge.service.js');
  api = await startTestApi();
});

after(async () => {
  await api?.close();
  await new Promise<void>((resolve) => ragStub.close(() => resolve()));
});

test('只列已发布：草稿、非法 id、缺 id 都被过滤，workFlowId 映射成 id', async () => {
  mode = 'ok';
  seen.length = 0;

  const { status, body } = await api.get(`${API}/knowledge/workflows/list`);
  assert.equal(status, 200);
  assert.equal(body.total, 8);
  assert.deepEqual(body.items, [
    { id: 'RAG_Workflow_780f', name: 'test1', description: '示例工作流' },
    { id: 'RAG_Workflow_89f4', name: '顺序检索', description: '' },
  ]);

  // 请求形状：走 Agent API，一页拉全量，只带 X-API-Key
  assert.equal(seen.length, 1);
  assert.equal(seen[0]!.url, '/api/co-knowledge/v1/agent/workflows?page=1&size=500&publishType=1');
  assert.equal(seen[0]!.apiKey, 'ragk_test-key');
  assert.equal(seen[0]!.authorization, undefined);
});

test('401 翻译成「检查 CO_KNOWLEDGE_API_KEY」的人话，不降级成空列表', async () => {
  mode = 'unauthorized';
  const { status, body } = await api.get(`${API}/knowledge/workflows/list`);
  assert.equal(status, 502);
  assert.match(body.message, /HTTP 401/);
  assert.match(body.message, /CO_KNOWLEDGE_API_KEY/);
});

test('上游吐 HTML 时明确说「不是合法 JSON」', async () => {
  mode = 'html';
  const { status, body } = await api.get(`${API}/knowledge/workflows/list`);
  assert.equal(status, 502);
  assert.match(body.message, /不是合法 JSON/);
});

test('响应缺 items 时 502（不把结构漂移当成空列表）', () => {
  assert.throws(
    () => knowledge.normalizeWorkflowList({ total: 0 }),
    /缺少 items/,
  );
});

test('空列表是合法结果', () => {
  assert.deepEqual(knowledge.normalizeWorkflowList({ items: [], total: 0 }), { items: [], total: 0 });
});

test('认证头：缺 key 时直接指出该设哪个变量', () => {
  assert.deepEqual(knowledge.buildAuthHeaders('ragk_test'), { 'x-api-key': 'ragk_test' });
  assert.throws(() => knowledge.buildAuthHeaders(''), /CO_KNOWLEDGE_API_KEY/);
});

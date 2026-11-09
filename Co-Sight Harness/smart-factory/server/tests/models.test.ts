/**
 * 模型列表代理：读令牌 → 请求框架模块面 → 只透出不含密钥的列表。
 *
 * 权威：`Cosight-Harness-开源/model-config-api.md`（基址、令牌、四道门、信封、字段表）。
 */
import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import type { AddressInfo } from 'node:net';
import { join } from 'node:path';
import { prepareTestEnv } from './helpers/test-db.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

const env = prepareTestEnv('models');

const MODULE_TOKEN = 'test-module-token';
const COSIGHT_HOME = join(env.home, 'cosight-home');
const TOKEN_FILE = join(COSIGHT_HOME, '.module-token');
mkdirSync(COSIGHT_HOME, { recursive: true });
writeFileSync(TOKEN_FILE, `${MODULE_TOKEN}\n`);

/** 框架桩：`GET /api/framework/v1/models`。响应形状照 model-config-api.md §4.1。 */
const MODELS = [
  {
    id: 'a7cf0154-020b-4f97-b2bc-5ab8eb3bf0b5',
    provider: 'anthropic',
    protocol: 'anthropic',
    label: 'deepseek-v4-flash',
    modelName: 'deepseek-v4-flash',
    baseUrl: 'https://api.deepseek.com/anthropic',
    hasApiKey: true,
    isActive: true,
    createdAt: '2026-10-15T06:10:13.679Z',
    updatedAt: '2026-10-15T06:10:19.275Z',
    // 框架列表本来就没有密钥；这里故意塞一个，验证代理不会把它透出去
    apiKey: 'sk-should-never-reach-the-browser',
  },
  {
    id: '2168b0c5-6f3b-4f2f-9d6b-2f5b4f7f8a11',
    provider: 'openai-compatible',
    protocol: 'openai',
    label: 'GLM-4.6',
    modelName: 'glm-4.6',
    baseUrl: null,
    hasApiKey: false,
    isActive: false,
    createdAt: '2026-10-15T06:11:00.000Z',
    updatedAt: '2026-10-15T06:11:00.000Z',
  },
];

type Mode = 'ok' | 'unauthorized' | 'bad-protocol';
let mode: Mode = 'ok';
const seen: { authorization: string; origin?: string }[] = [];

const frameworkStub = createServer((req, res) => {
  seen.push({ authorization: req.headers.authorization ?? '', origin: req.headers.origin });

  if (req.url !== '/api/framework/v1/models') {
    res.statusCode = 404;
    res.end('{}');
    return;
  }

  res.setHeader('content-type', 'application/json');
  if (mode === 'unauthorized') {
    res.statusCode = 401;
    res.end(JSON.stringify({ success: false, data: null, error: { code: 'UNAUTHORIZED', message: '缺少模块面令牌' }, meta: null }));
    return;
  }

  const items =
    mode === 'bad-protocol' ? [{ ...MODELS[0], protocol: 'grpc' }] : MODELS;
  res.end(JSON.stringify({ success: true, data: { items, activeId: MODELS[0].id }, error: null, meta: null }));
});

await new Promise<void>((resolve) => frameworkStub.listen(0, '127.0.0.1', resolve));

// 必须在 import 任何 src 模块之前设置：config 在 import 时读环境
process.env.COSIGHT_HOME = COSIGHT_HOME;
process.env.FRAMEWORK_BASE_URL = `http://127.0.0.1:${(frameworkStub.address() as AddressInfo).port}`;

let api: TestApi;

before(async () => {
  api = await startTestApi();
});

after(async () => {
  await api.close();
  await new Promise<void>((resolve) => frameworkStub.close(() => resolve()));
});

test('GET /models/list 透出框架列表与 activeId，不带 apiKey', async () => {
  mode = 'ok';
  seen.length = 0;

  const { status, body } = await api.get(`${API}/models/list`);

  assert.equal(status, 200);
  assert.equal(body.activeId, MODELS[0].id);
  assert.equal(body.items.length, 2);

  const first = body.items[0];
  assert.equal(first.id, MODELS[0].id);
  assert.equal(first.label, 'deepseek-v4-flash');
  assert.equal(first.protocol, 'anthropic');
  assert.equal(first.isActive, true);
  assert.equal(first.hasApiKey, true);
  assert.equal('apiKey' in first, false, '代理不得把密钥透给前端');

  const second = body.items[1];
  assert.equal(second.protocol, 'openai');
  assert.equal(second.baseUrl, null, 'null 表示用官方地址，不能自己推导');

  // 令牌经 Authorization 头、且不带 Origin（框架的四道门）
  assert.deepEqual(seen, [{ authorization: `Bearer ${MODULE_TOKEN}`, origin: undefined }]);
});

test('框架 401 → 502 且提示检查令牌文件', async () => {
  mode = 'unauthorized';

  const { status, body } = await api.get(`${API}/models/list`);

  assert.equal(status, 502);
  assert.equal(body.error, 'FRAMEWORK_UNAVAILABLE');
  assert.match(body.message, /401/);
  assert.match(body.message, /\.module-token/);
});

test('协议不在白名单 → 502，不把会静默用错 SDK 的模型放出去', async () => {
  mode = 'bad-protocol';

  const { status, body } = await api.get(`${API}/models/list`);

  assert.equal(status, 502);
  assert.equal(body.error, 'FRAMEWORK_UNAVAILABLE');
  assert.match(body.message, /grpc/);
});

test('令牌文件缺失 → 502 且不阻塞成 500', async () => {
  mode = 'ok';
  rmSync(TOKEN_FILE, { force: true });

  const { status, body } = await api.get(`${API}/models/list`);

  assert.equal(status, 502);
  assert.equal(body.error, 'FRAMEWORK_UNAVAILABLE');
  assert.match(body.message, /模块令牌/);

  // 还原，避免影响后续用例（当前文件内已无，但保持环境干净）
  writeFileSync(TOKEN_FILE, `${MODULE_TOKEN}\n`);
});

test('令牌文件内容含换行 / 非法字符 → 502，且响应不回显写入的内容', async () => {
  mode = 'ok';
  const marker = 'TOKEN-LEAK-MARKER';
  // 换行与 ASCII 控制字符都过不了 HTTP 头校验；绝不能把文件内容带进错误消息
  const contents = [`${marker}\nsecond-line\n`, `${marker}\u0001tail\n`];

  try {
    for (const content of contents) {
      writeFileSync(TOKEN_FILE, content);

      const { status, body } = await api.get(`${API}/models/list`);
      assert.equal(status, 502, JSON.stringify(body));
      assert.equal(body.error, 'FRAMEWORK_UNAVAILABLE');
      assert.match(body.message, /令牌/);

      const serialized = JSON.stringify(body);
      assert.equal(serialized.includes(marker), false, '响应不得回显令牌文件内容');
      assert.equal(serialized.includes('second-line'), false, '响应不得回显令牌文件内容');
    }
  } finally {
    writeFileSync(TOKEN_FILE, `${MODULE_TOKEN}\n`);
  }
});

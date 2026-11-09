/**
 * 观测端可监控目录清单：`GET /workspaces/directories/list`。
 *
 * 覆盖：框架工作区原样带 directory、内置目录条目指向 `{COSIGHT_HOME}/smart-factory`、
 * 前缀能覆盖内置专家 / 技能工坊 / 自由对话三类 cwd、`/workspaces/list` 的契约不变、
 * 框架不可达时与 `/workspaces/list` 同口径 `502`。权威：4.01-接口总览.md §4.6、cosight-viewer-对接清单.md §9.6。
 */
import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { mkdirSync, readFileSync, realpathSync } from 'node:fs';
import { prepareTestEnv } from './helpers/test-db.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';
import { startFrameworkStub, type StubWorkspace } from './helpers/framework-stub.js';

const env = prepareTestEnv('workspace-directories');

/** smart-factory 数据根：内置专家、技能工坊、自由对话的 cwd 都在它下面。 */
const FACTORY_ROOT = join(env.home, 'smart-factory');

const WS_MAIN = '8b1f0c2d-4e5a-4b6c-9d7e-1f2a3b4c5d6e';
const WS_UNBOUND = '1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f';
const TIMESTAMP = '2026-01-01T00:00:00.000Z';
const MODEL_ID = 'a7cf0154-020b-4f97-b2bc-5ab8eb3bf0b5';

function workspace(id: string, name: string, directory: string | null, defaultModelId: string | null = null): StubWorkspace {
  return { id, name, directory, defaultModelId, defaultAgentId: null, createdAt: TIMESTAMP, updatedAt: TIMESTAMP };
}

const TOKEN = readFileSync(join(env.home, '.module-token'), 'utf8').trim();
const stub = await startFrameworkStub({
  token: TOKEN,
  workspaces: [workspace(WS_MAIN, '主工作区', env.workspaceDir, MODEL_ID), workspace(WS_UNBOUND, '未绑目录', null)],
  activeWorkspaceId: WS_MAIN,
});
process.env.FRAMEWORK_BASE_URL = stub.url;

let api: TestApi;

before(async () => {
  // 生产布局：boot 会建 skills 根、seed 会登记内置专家；测试只需要目录在盘上。
  mkdirSync(join(FACTORY_ROOT, 'builtin-agents', 'example-builtin-agent'), { recursive: true });
  mkdirSync(join(FACTORY_ROOT, 'skill-workshop', 'output', 'skills'), { recursive: true });
  mkdirSync(join(FACTORY_ROOT, 'chat'), { recursive: true });
  api = await startTestApi();
});

after(async () => {
  await api.close();
  await stub.close();
});

test('清单：框架工作区带 directory / defaultModelId，末尾补一条内置与技能开发目录', async () => {
  const res = await api.get(`${API}/workspaces/directories/list`);
  assert.equal(res.status, 200);
  assert.equal(res.body.activeId, WS_MAIN);

  const main = res.body.items.find((item: any) => item.id === WS_MAIN);
  assert.deepEqual(main, {
    id: WS_MAIN,
    name: '主工作区',
    directory: env.workspaceDir,
    defaultModelId: MODEL_ID,
    kind: 'workspace',
  });

  const unbound = res.body.items.find((item: any) => item.id === WS_UNBOUND);
  assert.equal(unbound.directory, null, '未绑目录的工作区原样下发，由观测端自行跳过');
  assert.equal(unbound.kind, 'workspace');

  assert.deepEqual(res.body.items.at(-1), {
    id: 'default',
    // 展示名与框架真实工作区「默认工作区」区分开；id / kind 才是观测端的判别依据
    name: '内置与技能开发目录',
    directory: realpathSync(FACTORY_ROOT),
    defaultModelId: null,
    kind: 'default',
  });
});

test('内置目录条目的前缀覆盖内置专家、技能开发与自由对话三类 cwd', async () => {
  const res = await api.get(`${API}/workspaces/directories/list`);
  const root = res.body.items.find((item: any) => item.kind === 'default').directory;

  const cwds = [
    join(FACTORY_ROOT, 'builtin-agents', 'example-builtin-agent'),
    join(FACTORY_ROOT, 'skill-workshop'),
    join(FACTORY_ROOT, 'chat'),
  ];
  for (const cwd of cwds) {
    assert.ok(`${realpathSync(cwd)}/`.startsWith(`${root}/`), `${cwd} 应被内置目录条目覆盖`);
  }
});

test('既有 /workspaces/list 契约不变：仍不下发 directory', async () => {
  const res = await api.get(`${API}/workspaces/list`);
  assert.equal(res.status, 200);
  assert.deepEqual(res.body.items.find((item: any) => item.id === WS_MAIN), {
    id: WS_MAIN,
    name: '主工作区',
    defaultModelId: MODEL_ID,
  });
  assert.ok(!res.body.items.some((item: any) => item.kind !== undefined), '内置目录条目不进 Web 用的工作区列表');
});

test('框架不可达：与 /workspaces/list 同口径返回 502，不做降级', async () => {
  stub.workspacesStatus = 500;
  try {
    const res = await api.get(`${API}/workspaces/directories/list`);
    assert.equal(res.status, 502);
    assert.equal(res.body.error, 'BAD_GATEWAY');
  } finally {
    stub.workspacesStatus = 200;
  }
});

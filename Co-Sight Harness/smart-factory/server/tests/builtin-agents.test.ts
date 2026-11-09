/**
 * 内置智能体：boot seed（登记 / 幂等 / 漂移刷新 / 清理）、列表混入、只读守卫、
 * 仅 runtime 的阶段门禁、定义目录即 cwd、产物浏览与评估的 409、/fs 白名单。
 *
 * 权威：server/docs/99-adr/0003-builtin-agents.md、server/docs/03-architecture/08-agent.md（内置专节）
 */
import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { prepareTestEnv } from './helpers/test-db.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';
import { startFrameworkStub, type StubModel, type StubWorkspace } from './helpers/framework-stub.js';

const env = prepareTestEnv('builtin-agents');

/** 定义根在测试 COSIGHT_HOME 下，与生产布局逐字一致。 */
const BUILTIN_ROOT = join(env.home, 'smart-factory', 'builtin-agents');

const WS_ID = '8b1f0c2d-4e5a-4b6c-9d7e-1f2a3b4c5d6e';
const TIMESTAMP = '2026-01-01T00:00:00.000Z';

const MODEL_ID = 'a7cf0154-020b-4f97-b2bc-5ab8eb3bf0b5';
const MODELS: StubModel[] = [
  {
    id: MODEL_ID,
    provider: 'anthropic',
    protocol: 'anthropic',
    label: 'test-sonnet',
    modelName: 'test-sonnet',
    baseUrl: null,
    hasApiKey: true,
    isActive: true,
    createdAt: TIMESTAMP,
    updatedAt: TIMESTAMP,
    apiKey: 'sk-should-never-reach-the-browser',
    temperature: 1,
    topP: 1,
    maxOutputTokens: null,
    contextWindow: null,
    timeoutSeconds: 60,
  },
];

function workspace(id: string, name: string, directory: string | null): StubWorkspace {
  return { id, name, directory, defaultAgentId: null, createdAt: TIMESTAMP, updatedAt: TIMESTAMP };
}

const TOKEN = readFileSync(join(env.home, '.module-token'), 'utf8').trim();
const stub = await startFrameworkStub({
  token: TOKEN,
  workspaces: [workspace(WS_ID, '主工作区', env.workspaceDir)],
  activeWorkspaceId: WS_ID,
  activeModelId: MODEL_ID,
  models: MODELS,
});
process.env.FRAMEWORK_BASE_URL = stub.url;

const { prisma } = await import('../src/shared/prisma/client.js');
const { agentService } = await import('../src/modules/agent/agent.service.js');

/** 写一个定义目录：agent.json + 假装是专家目录的入口文件。 */
function writeBuiltinDir(id: string, manifest: Record<string, unknown>): string {
  const dir = join(BUILTIN_ROOT, id);
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, 'agent.json'), JSON.stringify(manifest));
  writeFileSync(join(dir, 'CLAUDE.md'), `# ${id}\n`);
  return dir;
}

const BUILTIN_A = {
  name: 'Example built-in agent A',
  description: 'Generic built-in agent test fixture',
  tags: [],
  icon: '',
};

let api: TestApi;
let stubClosed = false;

before(async () => {
  api = await startTestApi();
  writeBuiltinDir('example-builtin-a', BUILTIN_A);
  writeBuiltinDir('example-builtin-b', { name: 'Example built-in agent B', description: 'Secondary test fixture' });
  // 脏清单目录：seed 必须跳过它而不挡启动
  writeBuiltinDir('bad-agent', { description: '缺 name 的清单' });
  writeBuiltinDir('.hidden', { name: '隐藏目录' });
});

after(async () => {
  await api.close();
  if (!stubClosed) await stub.close();
  await prisma.$disconnect();
});

/* ---------- seed：登记 / 幂等 / 漂移 ---------- */

test('seed：合法清单登记为内置行（status=completed、workspaceId=null、source=builtin、tags 不含来源）；脏清单与隐藏目录跳过', async () => {
  const seeded = await agentService.seedBuiltinAgents();
  assert.equal(seeded, 2);

  const office = await agentService.getAgent('example-builtin-a');
  assert.equal(office.source, 'builtin');
  assert.equal(office.workspaceId, null);
  assert.equal(office.status, 'completed', '内置智能体开箱即用：没有生产流程（/production 对它们 409），状态恒为 completed');
  assert.deepEqual(office.tags, [], '来源不进 tags：清单没写标签，行里就是一个空数组');
  assert.equal(office.dir, join(BUILTIN_ROOT, 'example-builtin-a'));
  assert.equal(office.runtimeDir, office.dir, '内置智能体的 runtime cwd 就是定义目录本身');

  const soc = await agentService.getAgent('example-builtin-b');
  assert.deepEqual(soc.tags, []);

  const bad = await api.get(`${API}/agents/bad-agent`);
  assert.equal(bad.status, 404, '脏清单目录不登记，boot 也不因此失败');
});

test('seed：幂等——重跑不重复登记、无漂移不刷新 updatedAt', async () => {
  const before = await agentService.getAgent('example-builtin-a');
  const seeded = await agentService.seedBuiltinAgents();
  assert.equal(seeded, 0);
  const after = await agentService.getAgent('example-builtin-a');
  assert.equal(after.updatedAt, before.updatedAt);
});

test('seed：清单漂移 → 按清单刷新行', async () => {
  writeBuiltinDir('example-builtin-a', { ...BUILTIN_A, description: '新描述' });
  await agentService.seedBuiltinAgents();
  const office = await agentService.getAgent('example-builtin-a');
  assert.equal(office.description, '新描述');
  // 还原，免得影响后面的用例
  writeBuiltinDir('example-builtin-a', BUILTIN_A);
  await agentService.seedBuiltinAgents();
});

/* ---------- 列表混入 ---------- */

test('list：按工作区筛选的查询也返回内置行；source/keyword 过滤对内置行生效', async () => {
  const user = await api.post(`${API}/agents`, { workspaceId: WS_ID, name: '用户智能体' });
  assert.equal(user.status, 200);
  assert.equal(user.body.source, 'user');

  const mixed = await api.get(`${API}/agents?workspaceId=${WS_ID}`);
  assert.equal(mixed.status, 200);
  const ids = mixed.body.items.map((row: any) => row.id);
  assert.ok(ids.includes('example-builtin-a'), '内置行必须混进工作区列表');
  assert.ok(ids.includes(user.body.id));

  const builtinOnly = await api.get(`${API}/agents?workspaceId=${WS_ID}&source=builtin`);
  assert.deepEqual(builtinOnly.body.items.map((row: any) => row.id).sort(), ['example-builtin-a', 'example-builtin-b']);

  const userOnly = await api.get(`${API}/agents?workspaceId=${WS_ID}&source=user`);
  assert.deepEqual(userOnly.body.items.map((row: any) => row.id), [user.body.id], '来源筛选不混入内置行');

  const byKeyword = await api.get(`${API}/agents?keyword=example-builtin`);
  assert.ok(byKeyword.body.items.length >= 2, '内置 id（目录名）参与 keyword 匹配');

  // dir 的解析不依赖工作区：内置行自带定义目录
  const row = mixed.body.items.find((item: any) => item.id === 'example-builtin-a');
  assert.equal(row.dir, join(BUILTIN_ROOT, 'example-builtin-a'));
  assert.equal(row.runtimeDir, row.dir);
  assert.equal(row.status, 'completed', '内置行开箱即用：列表里的状态也恒为 completed');

  // 来源不是标签：标签下拉里不该再出现「内置」
  const tags = await api.get(`${API}/agents/tags?workspaceId=${WS_ID}`);
  assert.ok(!tags.body.items.some((item: any) => item.tag === '内置'), '来源不进标签词表');
});

test('seed：清单里的保留标签被剥掉，其余标签原样落库', async () => {
  const dir = writeBuiltinDir('legacy-tag', { name: '旧写法', tags: ['内置', '办公'] });
  assert.equal(await agentService.seedBuiltinAgents(), 1);

  const agent = await agentService.getAgent('legacy-tag');
  assert.equal(agent.source, 'builtin');
  assert.deepEqual(agent.tags, ['办公'], '来源不进 tags，清单里的普通标签保留');

  // 收尾：删目录再 seed，让这一行随定义目录一起清掉
  rmSync(dir, { recursive: true, force: true });
  await agentService.seedBuiltinAgents();
});

/* ---------- 只读守卫 ---------- */

test('update / delete / production：内置行一律 409，行与盘原样', async () => {
  const updated = await api.post(`${API}/agents/example-builtin-a/update`, { description: '改不动' });
  assert.equal(updated.status, 409);

  const emptyPatch = await api.post(`${API}/agents/example-builtin-a/update`, {});
  assert.equal(emptyPatch.status, 409, '只读守卫先于「空请求」400');

  const removed = await api.post(`${API}/agents/example-builtin-a/delete`);
  assert.equal(removed.status, 409);
  assert.equal(existsSync(join(BUILTIN_ROOT, 'example-builtin-a')), true, '删除守卫不碰盘');

  const production = await api.get(`${API}/agents/example-builtin-a/production`);
  assert.equal(production.status, 409);
});

/* ---------- 会话：仅 runtime ---------- */

test('sessions/create：内置智能体非 runtime（含缺省 development）→ 409；runtime → 200', async () => {
  for (const stage of ['development', 'preview', 'evaluation', undefined]) {
    const res = await api.post(`${API}/sessions/create`, {
      agentId: 'example-builtin-a',
      modelId: MODEL_ID,
      ...(stage === undefined ? {} : { stage }),
    });
    assert.equal(res.status, 409, `stage=${String(stage)} 应被 409 拦截`);
  }

  const ok = await api.post(`${API}/sessions/create`, { agentId: 'example-builtin-a', stage: 'runtime', modelId: MODEL_ID });
  assert.equal(ok.status, 200);
  assert.equal(ok.body.instance.stage, 'runtime');
});

test('内置 runtime 会话：send 起跑成功（cwd=定义目录的链路无产物门禁）', async () => {
  const created = await api.post(`${API}/sessions/create`, { agentId: 'example-builtin-a', stage: 'runtime', modelId: MODEL_ID });
  const sent = await api.post(`${API}/messages/send`, { sessionId: created.body.id, prompt: '你好' });
  assert.equal(sent.status, 200, JSON.stringify(sent.body));
  assert.equal(sent.body.instanceId, created.body.instance.id);
  const run = await api.waitTerminal(sent.body.runId);
  assert.equal(run.status, 'succeeded');
});

/* ---------- 产物浏览 / 评估 ---------- */

test('artifacts：内置 runtime 浏览根=定义目录（能看到 agent.json）；非 runtime 409', async () => {
  const runtime = await api.get(`${API}/artifacts/list?agentId=example-builtin-a&stage=runtime`);
  assert.equal(runtime.status, 200);
  const names = runtime.body.items.map((item: any) => item.name);
  assert.ok(names.includes('agent.json'), `应列出定义目录内容：${JSON.stringify(names)}`);

  const development = await api.get(`${API}/artifacts/list?agentId=example-builtin-a&stage=development`);
  assert.equal(development.status, 409);
});

test('evaluations/list：内置智能体 409', async () => {
  const res = await api.get(`${API}/evaluations/list?agentId=example-builtin-a`);
  assert.equal(res.status, 409);
});

/* ---------- /fs 白名单 ---------- */

test('/fs/roots：内置定义根在白名单里', async () => {
  const res = await api.get(`${API}/fs/roots`);
  assert.equal(res.status, 200);
  assert.ok(res.body.items.some((item: any) => item.path === BUILTIN_ROOT), JSON.stringify(res.body.items));
});

/* ---------- id 冲突与清理 ---------- */

test('seed：id 被非内置行占用 → 告警跳过，用户行原样', async () => {
  writeBuiltinDir('collide', { name: '撞位内置', description: '' });
  // 直接落一行非内置行占住 id（模拟存量用户智能体先占了目录名）
  await prisma.agent.create({
    data: { id: 'collide', workspaceId: WS_ID, source: 'user', name: '用户占位', description: '', tags: '[]', icon: '' },
  });

  const seeded = await agentService.seedBuiltinAgents();
  assert.equal(seeded, 0, '占位场景不产生新登记');

  const row = await prisma.agent.findUnique({ where: { id: 'collide' } });
  assert.equal(row?.source, 'user', '用户行原样');
  assert.equal(row?.name, '用户占位');

  // 收尾：删掉用户行与目录，恢复内置定义的干净状态
  await prisma.agent.deleteMany({ where: { id: 'collide' } });
  rmSync(join(BUILTIN_ROOT, 'collide'), { recursive: true, force: true });
  await agentService.seedBuiltinAgents();
});

test('seed：定义目录消失 → 内置行连带清理', async () => {
  rmSync(join(BUILTIN_ROOT, 'example-builtin-b'), { recursive: true, force: true });
  await agentService.seedBuiltinAgents();
  const detail = await api.get(`${API}/agents/example-builtin-b`);
  assert.equal(detail.status, 404);
});

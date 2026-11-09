/**
 * 智能体资源：六个端点、工作区归属、形态与重名、盘库两侧的副作用、启动收养。
 *
 * 权威：server/docs/05-openapi/5.01-agent-openapi.yaml（接口形状）
 *       server/docs/03-architecture/08-agent.md（目录与 id、盘库顺序、收养）
 */
import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { prepareTestEnv } from './helpers/test-db.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';
import { startFrameworkStub, type StubModel, type StubWorkspace } from './helpers/framework-stub.js';
import { TEST_MODEL_NO_KEY_ID, TEST_MODEL_OPENAI_ID } from './helpers/workspace-stub.js';

const env = prepareTestEnv('agents');

const WS_ID = '8b1f0c2d-4e5a-4b6c-9d7e-1f2a3b4c5d6e';
const WS_OTHER = '1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d';
const WS_NO_DIR = '2b3c4d5e-6f70-4a8b-9c0d-1e2f3a4b5c6d';
const WS_UNKNOWN = 'ffffffff-ffff-4fff-8fff-ffffffffffff';

const OTHER_DIR = join(env.home, 'workspace-other');
mkdirSync(OTHER_DIR, { recursive: true });

const TIMESTAMP = '2026-01-01T00:00:00.000Z';

function workspace(
  id: string,
  name: string,
  directory: string | null,
  defaultModelId: string | null = null,
): StubWorkspace {
  return { id, name, directory, defaultModelId, defaultAgentId: null, createdAt: TIMESTAMP, updatedAt: TIMESTAMP };
}

/** init.modelId 的存在性校验要问模型管理；这里给一条能用、一条不在列表里的 id 作对照。 */
const MODEL_ID = 'a7cf0154-020b-4f97-b2bc-5ab8eb3bf0b5';
const ABSENT_MODEL_ID = '00000000-0000-4000-8000-000000000000';
const MODELS: StubModel[] = [
  {
    id: MODEL_ID,
    provider: 'anthropic',
    protocol: 'anthropic',
    label: 'deepseek-v4-flash',
    modelName: 'deepseek-v4-flash',
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
  {
    id: TEST_MODEL_OPENAI_ID,
    provider: 'openai-compatible',
    protocol: 'openai',
    label: '测试 OpenAI',
    modelName: 'test-gpt',
    baseUrl: null,
    hasApiKey: true,
    isActive: false,
    createdAt: TIMESTAMP,
    updatedAt: TIMESTAMP,
    apiKey: 'sk-test-openai-key',
    temperature: 1,
    topP: 1,
    maxOutputTokens: null,
    contextWindow: null,
    timeoutSeconds: 60,
  },
  {
    id: TEST_MODEL_NO_KEY_ID,
    provider: 'anthropic',
    protocol: 'anthropic',
    label: '测试无密钥',
    modelName: 'test-no-key',
    baseUrl: null,
    hasApiKey: false,
    isActive: false,
    createdAt: TIMESTAMP,
    updatedAt: TIMESTAMP,
    apiKey: null,
    temperature: 1,
    topP: 1,
    maxOutputTokens: null,
    contextWindow: null,
    timeoutSeconds: 60,
  },
];

// 测试令牌由本进程写入临时目录，再交给框架桩校验；生产代码只从 COSIGHT_HOME 现读。
const TOKEN = readFileSync(join(env.home, '.module-token'), 'utf8').trim();
const stub = await startFrameworkStub({
  token: TOKEN,
  workspaces: [
    workspace(WS_ID, '主工作区', env.workspaceDir),
    workspace(WS_OTHER, '另一个工作区', OTHER_DIR, MODEL_ID),
    workspace(WS_NO_DIR, '未绑定工作区', null),
  ],
  activeWorkspaceId: WS_ID,
  // send 在建 run 之前解析模型：没有生效模型会在发送时 502
  activeModelId: MODEL_ID,
  models: MODELS,
});
process.env.FRAMEWORK_BASE_URL = stub.url;

const { prisma } = await import('../src/shared/prisma/client.js');
const { agentService } = await import('../src/modules/agent/agent.service.js');
const { instancesRepo } = await import('../src/shared/store/instances.repo.js');
const { sessionsRepo } = await import('../src/shared/store/sessions.repo.js');
const { FAKE_TRIGGER } = await import('../src/shared/engine/fake-adapter.js');

let api: TestApi;
let stubClosed = false;

/**
 * 一个「形态合法、库里没有」的 agentId。
 *
 * **不能拿中文当不存在的 id**：pattern 是 `^[a-z0-9][a-z0-9._-]{0,63}$`，
 * 非 ASCII 一律先被判成形态非法（400），到不了存在性判定（404）。
 */
const ABSENT = 'agt_00000000-0000-4000-8000-000000000000';

const TIMESTAMP_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;

/** 封面图是一个地址，不是图标名；空串才是「没有封面」。 */
const COVER = 'https://cdn.example.com/covers/weather.png';

/** agentRoot = <workspace.directory>/.smart-factory/agents/{id}；测试里只按约定拼，不猜。 */
const agentRoot = (id: string, workspaceDir = env.workspaceDir): string =>
  join(workspaceDir, '.smart-factory', 'agents', id);

const agentsRoot = (workspaceDir = env.workspaceDir): string => join(workspaceDir, '.smart-factory', 'agents');

async function createAgent(body: Record<string, unknown>): Promise<any> {
  const res = await api.post(`${API}/agents`, { workspaceId: WS_ID, ...body });
  assert.equal(res.status, 200, JSON.stringify(res.body));
  return res.body;
}

before(async () => {
  api = await startTestApi();
  mkdirSync(agentsRoot(), { recursive: true });
  mkdirSync(agentsRoot(OTHER_DIR), { recursive: true });
});

after(async () => {
  await api.close();
  if (!stubClosed) await stub.close();
  await prisma.$disconnect();
});

/* ---------- create：工作区归属 ---------- */

test('create：workspaceId 必填且须是 uuid；其余字段非法时先返回 400，不解析工作区', async () => {
  for (const [body, message] of [
    [{}, 'workspaceId 必填'],
    [{ name: '没有工作区' }, 'workspaceId 必填'],
    [{ workspaceId: 'not-a-uuid', name: '非法工作区' }, /workspaceId.*uuid/],
    [{ workspaceId: WS_ID }, 'name 必填'],
    [{ workspaceId: WS_ID, name: '   ' }, 'name 必填'],
    [{ workspaceId: WS_ID, name: 'x'.repeat(41) }, 'name 不能超过 40 字'],
  ] as const) {
    const res = await api.post(`${API}/agents`, body);
    assert.equal(res.status, 400, JSON.stringify(body));
    assert.equal(res.body.error, 'BAD_REQUEST');
    if (typeof message === 'string') assert.equal(res.body.message, message);
    else assert.match(res.body.message, message);
  }
});

test('create：工作区不存在或未绑定目录 → 502，且不建行、不建目录', async () => {
  const before = readdirSync(agentsRoot()).length;
  const unknown = await api.post(`${API}/agents`, { workspaceId: WS_UNKNOWN, name: '未知工作区智能体' });
  assert.equal(unknown.status, 502);
  assert.equal(unknown.body.error, 'BAD_GATEWAY');
  assert.equal(unknown.body.message, `工作区 ${WS_UNKNOWN} 不存在`);

  const unbound = await api.post(`${API}/agents`, { workspaceId: WS_NO_DIR, name: '未绑定智能体' });
  assert.equal(unbound.status, 502);
  assert.equal(unbound.body.error, 'BAD_GATEWAY');
  assert.equal(unbound.body.message, `工作区 ${WS_NO_DIR} 未绑定目录`);

  assert.equal(await prisma.agent.count(), 0);
  assert.equal(readdirSync(agentsRoot()).length, before, '解析失败时不建目录');
});

test('create：id 由服务端发（agt_ 前缀），status 派生为 not_started，workspaceId 回显，dir 按工作区现算', async () => {
  const agent = await createAgent({ name: '天气智能体', description: '查询实时天气', icon: COVER });

  assert.match(agent.id, /^agt_/);
  assert.equal(agent.workspaceId, WS_ID);
  assert.equal(agent.name, '天气智能体');
  assert.equal(agent.description, '查询实时天气');
  assert.equal(agent.icon, COVER);
  // 空目录 + 无状态文件 → 与 /production 同源的 not_started
  assert.equal(agent.status, 'not_started');
  // 绝对路径、恒为 <workspace.directory>/.smart-factory/agents/{id}，且它就是目录名
  assert.equal(agent.dir, agentRoot(agent.id));
  // 刚建出来还没有产物：runtime 起不了，runtimeDir 表达为 null
  assert.equal(agent.runtimeDir, null);
  assert.match(agent.createdAt, TIMESTAMP_PATTERN);
  assert.equal(agent.createdAt, agent.updatedAt);

  // 先落行、后建目录：行回得来时 development 目录已在
  assert.ok(existsSync(join(agentRoot(agent.id), 'development')));
  // 不再在 COSIGHT_HOME 下猜一个 agents 目录
  assert.ok(!existsSync(join(env.home, 'agents')));
});

test('create：description / icon / tags 都有缺省；多余字段（agentId、status）按忽略处理', async () => {
  const agent = await createAgent({
    workspaceId: WS_OTHER,
    name: '只给名字',
    agentId: 'agt_客户端瞎编的',
    status: 'ready',
  });

  assert.equal(agent.workspaceId, WS_OTHER);
  assert.equal(agent.source, 'user', '用户建的智能体来源恒为 user，不接受请求体指定');
  assert.equal(agent.description, '');
  assert.deepEqual(agent.tags, [], '没有标签是空数组，不是 null');
  assert.equal(agent.icon, '');
  // status 不接受请求体指定，也不落库（派生值）；agentId 不进 body，服务端自己发
  assert.equal(agent.status, 'not_started');
  assert.notEqual(agent.id, 'agt_客户端瞎编的');
  assert.equal(agent.dir, agentRoot(agent.id, OTHER_DIR));
});

test('create：name 缺失 / 超长 → 400，且不留下任何行与目录', async () => {
  const before = readdirSync(agentsRoot()).length;

  for (const [body, message] of [
    [{ workspaceId: WS_ID }, 'name 必填'],
    [{ workspaceId: WS_ID, name: '   ' }, 'name 必填'],
    [{ workspaceId: WS_ID, name: 'x'.repeat(41) }, 'name 不能超过 40 字'],
  ] as const) {
    const res = await api.post(`${API}/agents`, body);
    assert.equal(res.status, 400, JSON.stringify(res.body));
    assert.equal(res.body.error, 'BAD_REQUEST');
    assert.equal(res.body.message, message);
  }

  assert.equal(readdirSync(agentsRoot()).length, before);
});

test('create：description / icon 超长 → 400', async () => {
  const long = await api.post(`${API}/agents`, { workspaceId: WS_ID, name: '描述太长', description: '字'.repeat(121) });
  assert.equal(long.status, 400);
  assert.equal(long.body.message, 'description 不能超过 120 字');

  // 上限 512：它是一条地址，不是展示文本，所以这里比 name / description 宽得多
  const wide = await api.post(`${API}/agents`, { workspaceId: WS_ID, name: '封面地址太长', icon: `https://a/${'i'.repeat(512)}` });
  assert.equal(wide.status, 400);
  assert.equal(wide.body.message, 'icon 不能超过 512 字');
});

test('create：重名按工作区隔离；同一工作区内 409 且不自动加后缀；唯一性按字节精确', async () => {
  await createAgent({ name: '重名候选' });

  const dup = await api.post(`${API}/agents`, { workspaceId: WS_ID, name: '重名候选' });
  assert.equal(dup.status, 409);
  assert.equal(dup.body.error, 'CONFLICT');
  assert.equal(dup.body.message, '该工作区已有同名智能体「重名候选」');

  // 只有一条「重名候选」
  assert.equal(await prisma.agent.count({ where: { name: '重名候选' } }), 1);

  // 前后空格只是 trim，仍是重名
  assert.equal((await api.post(`${API}/agents`, { workspaceId: WS_ID, name: '  重名候选  ' })).status, 409);
  // 大小写不同是两个名字
  assert.equal((await api.post(`${API}/agents`, { workspaceId: WS_ID, name: 'CaseKey' })).status, 200);
  assert.equal((await api.post(`${API}/agents`, { workspaceId: WS_ID, name: 'casekey' })).status, 200);
  // 不同工作区可以同名
  assert.equal((await api.post(`${API}/agents`, { workspaceId: WS_OTHER, name: '重名候选' })).status, 200);
});

/* ---------- detail ---------- */

test('detail：形状 = create 的响应 + 可执行技能 / 命令；不存在 404；形态非法 400', async () => {
  const created = await createAgent({ name: '详情样本' });

  const got = await api.get(`${API}/agents/${created.id}`);
  assert.equal(got.status, 200);
  // 刚建出来没有产物：可执行清单是空数组（不是缺字段）
  assert.deepEqual(got.body, { ...created, skills: [], commands: [], knowledgeInjected: false });

  // 形态合法但查不到 → 404（中文等非 ASCII 的 id 过不了 pattern，那是 400，不是 404）
  const missing = await api.get(`${API}/agents/${ABSENT}`);
  assert.equal(missing.status, 404);
  assert.equal(missing.body.error, 'NOT_FOUND');
  assert.equal(missing.body.message, `智能体 ${ABSENT} 不存在`);

  // 形态非法：路径段过不了 ^[a-z0-9][a-z0-9._-]{0,63}$
  for (const bad of ['-evil', '.hidden']) {
    const res = await api.get(`${API}/agents/${bad}`);
    assert.equal(res.status, 400, bad);
    assert.equal(res.body.error, 'BAD_REQUEST');
    assert.match(res.body.message, /agentId 形态非法/);
  }
});

/* ---------- list ---------- */

test('list：updatedAt 降序、total 是过滤后的全量、分页按 page/pageSize 切', async () => {
  await prisma.agent.deleteMany();
  const rows = [
    { id: 'sort-old', name: '旧的', updatedAt: '2026-10-01T00:00:00.000Z' },
    { id: 'sort-new', name: '新的', updatedAt: '2026-10-09T00:00:00.000Z' },
    { id: 'sort-mid', name: '中间的', updatedAt: '2026-10-05T00:00:00.000Z' },
  ];
  for (const row of rows) {
    await prisma.agent.create({ data: { ...row, workspaceId: WS_ID, description: '', icon: '' } });
  }

  const all = await api.get(`${API}/agents`);
  assert.equal(all.status, 200);
  assert.deepEqual(all.body.items.map((a: any) => a.id), ['sort-new', 'sort-mid', 'sort-old']);
  assert.equal(all.body.total, 3);
  assert.equal(all.body.items[0].workspaceId, WS_ID);
  assert.equal(all.body.items[0].dir, agentRoot('sort-new'));

  const firstPage = await api.get(`${API}/agents?page=1&pageSize=2`);
  assert.equal(firstPage.body.items.length, 2);
  assert.equal(firstPage.body.total, 3, 'total 是过滤后的全量，不是本页条数');

  const secondPage = await api.get(`${API}/agents?page=2&pageSize=2`);
  assert.deepEqual(secondPage.body.items.map((a: any) => a.id), ['sort-old']);

  const beyond = await api.get(`${API}/agents?page=9&pageSize=2`);
  assert.deepEqual(beyond.body.items, []);
  assert.equal(beyond.body.total, 3);
});

test('list：page / pageSize 非正值静默回落（不报错）；pageSize 超出按 200 截断', async () => {
  const fallback = await api.get(`${API}/agents?page=0&pageSize=-3`);
  assert.equal(fallback.status, 200);
  assert.equal(fallback.body.items.length, 3, 'page=0 → 1、pageSize 非法 → 20');

  const capped = await api.get(`${API}/agents?pageSize=999`);
  assert.equal(capped.status, 200);
  assert.equal(capped.body.items.length, 3);
});

test('list：workspaceId 精确过滤；空串视为未传；非法 uuid 400', async () => {
  await prisma.agent.deleteMany();
  await prisma.agent.createMany({
    data: [
      { id: 'in-main', workspaceId: WS_ID, name: '主工作区里的', description: '', icon: '' },
      { id: 'in-other', workspaceId: WS_OTHER, name: '另一个工作区里的', description: '', icon: '' },
    ],
  });

  const main = await api.get(`${API}/agents?workspaceId=${WS_ID}`);
  assert.deepEqual(main.body.items.map((a: any) => a.id), ['in-main']);
  assert.equal(main.body.total, 1);

  const other = await api.get(`${API}/agents?workspaceId=${WS_OTHER}`);
  assert.deepEqual(other.body.items.map((a: any) => a.id), ['in-other']);
  assert.equal(other.body.items[0].dir, agentRoot('in-other', OTHER_DIR));

  assert.equal((await api.get(`${API}/agents?workspaceId=`)).body.total, 2);

  const illegal = await api.get(`${API}/agents?workspaceId=nope`);
  assert.equal(illegal.status, 400);
  assert.equal(illegal.body.error, 'BAD_REQUEST');
  assert.match(illegal.body.message, /workspaceId.*uuid/);
});

test('list：keyword 子串匹配 name / id / description 任一，ASCII 大小写不敏感，空串视为未传', async () => {
  await prisma.agent.deleteMany();
  await prisma.agent.createMany({
    data: [
      { id: 'weather-agent', workspaceId: WS_ID, name: '天气智能体', description: '实时天气', icon: 'https://cdn.example.com/covers/weather.png' },
      { id: 'code-reviewer', workspaceId: WS_ID, name: '代码审查', description: '扫描仓库找 BUG', icon: 'https://cdn.example.com/covers/review.png' },
      { id: 'misc', workspaceId: WS_ID, name: '杂项', description: '什么也不做', icon: '' },
    ],
  });

  const hitName = await api.get(`${API}/agents?keyword=天气`);
  assert.deepEqual(hitName.body.items.map((a: any) => a.id), ['weather-agent']);

  const hitId = await api.get(`${API}/agents?keyword=code-rev`);
  assert.deepEqual(hitId.body.items.map((a: any) => a.id), ['code-reviewer']);

  const hitDescription = await api.get(`${API}/agents?keyword=仓库`);
  assert.deepEqual(hitDescription.body.items.map((a: any) => a.id), ['code-reviewer']);

  // ASCII 大小写不敏感（name / id / description 三处都验一遍）
  for (const keyword of ['BUG', 'bug', 'CODE-REV', 'WEATHER']) {
    const res = await api.get(`${API}/agents?keyword=${keyword}`);
    assert.equal(res.body.total, 1, keyword);
  }

  // 空串视为未传
  assert.equal((await api.get(`${API}/agents?keyword=`)).body.total, 3);
});

test('list / detail：status 与 /production 同源；?status= 只认枚举值', async () => {
  const listed = await api.get(`${API}/agents`);
  assert.equal(listed.body.total, 3);
  assert.deepEqual(
    new Set(listed.body.items.map((a: any) => a.status)),
    new Set(['not_started']),
    '没有状态文件与产物 → 与 /production 同源的 not_started',
  );

  const detail = await api.get(`${API}/agents/weather-agent`);
  assert.equal(detail.body.status, 'not_started');

  // 枚举外取值 400，不静默退化成「全部」（与 source 同口径）；空串才是未传
  const illegal = await api.get(`${API}/agents?status=published`);
  assert.equal(illegal.status, 400);
  assert.equal(illegal.body.error, 'BAD_REQUEST');
  assert.match(illegal.body.message, /status.*取值非法/);

  // `null` 那个降级值不是可查询的取值，同样 400
  const nullish = await api.get(`${API}/agents?status=null`);
  assert.equal(nullish.status, 400);

  assert.equal((await api.get(`${API}/agents?status=`)).body.total, 3);
});

test('list：产物状态按实例批量判定，一个在跑不能把整页标成 building', async () => {
  const instance = await instancesRepo.getOrCreate('code-reviewer', 'development');
  await prisma.run.create({
    data: {
      id: 'run_agents_batch',
      sessionId: 'sess_agents_batch',
      instanceId: instance.id,
      stage: 'development',
      status: 'running',
    },
  });
  try {
    const listed = await api.get(`${API}/agents`);
    assert.equal(listed.status, 200);
    const byId = new Map(listed.body.items.map((agent: any) => [agent.id, agent.status]));
    assert.equal(byId.get('code-reviewer'), 'building', '有活跃 run 的那一行是 building');
    assert.equal(byId.get('weather-agent'), 'not_started', '同页其它行不受影响');
    assert.equal(byId.get('misc'), 'not_started');
  } finally {
    await prisma.run.deleteMany({ where: { instanceId: instance.id } });
    await prisma.instance.delete({ where: { id: instance.id } });
  }
});

test('list：?status= 按现算状态筛选，total 是过滤后的全量，分页在过滤之后切', async () => {
  await prisma.agent.deleteMany();
  await prisma.agent.createMany({
    data: [
      { id: 'st-fresh', workspaceId: WS_ID, name: '还没开始', description: '', icon: '' },
      { id: 'st-running', workspaceId: WS_ID, name: '正在生成', description: '', icon: '' },
      { id: 'st-done', workspaceId: WS_ID, name: '已经就绪', description: '', icon: '' },
    ],
  });
  // 内置行：不属于任何工作区（混进每个列表），状态恒为 completed，会跟着 completed 一起被筛出来
  await prisma.agent.create({
    data: { id: 'st-builtin', workspaceId: null, source: 'builtin', name: '内置的就绪', description: '', icon: '' },
  });

  // st-running：development 实例上有一个活跃 run → building
  const instance = await instancesRepo.getOrCreate('st-running', 'development');
  await prisma.run.create({
    data: { id: 'run_st_status', sessionId: 'sess_st_status', instanceId: instance.id, stage: 'development', status: 'running' },
  });

  // st-done：按 AgentGenesis 的落盘布局补状态、门禁与产物 → completed（同 production 端点用例的夹具）
  const root = agentRoot('st-done');
  const work = join(root, 'development', '.agent-genesis', 'work', 'demo');
  mkdirSync(join(work, 'gate-results'), { recursive: true });
  writeFileSync(
    join(work, 'orchestrator-state.yaml'),
    'pipeline: agent-creation\npipeline_status: COMPLETED\ncurrent_step: step-5-readiness-verification\nsteps:\n  - step_id: step-4-implementation\n',
  );
  writeFileSync(join(work, 'gate-results', 'step-4-implementation.json'), JSON.stringify({ verdict: 'PASS', concerns: [] }));
  mkdirSync(join(root, 'development', 'output', 'agents', 'demo', 'v1'), { recursive: true });

  try {
    const building = await api.get(`${API}/agents?status=building`);
    assert.deepEqual(building.body.items.map((a: any) => a.id), ['st-running']);
    assert.equal(building.body.total, 1);

    const completed = await api.get(`${API}/agents?status=completed`);
    assert.deepEqual(new Set(completed.body.items.map((a: any) => a.id)), new Set(['st-done', 'st-builtin']));
    assert.equal(completed.body.total, 2);

    const fresh = await api.get(`${API}/agents?status=not_started`);
    assert.deepEqual(fresh.body.items.map((a: any) => a.id), ['st-fresh']);
    assert.equal(fresh.body.total, 1);

    // 与其余筛选是 AND 关系；内置行照旧混进每个工作区的查询
    assert.deepEqual(
      (await api.get(`${API}/agents?status=completed&source=user`)).body.items.map((a: any) => a.id),
      ['st-done'],
    );
    assert.deepEqual(
      (await api.get(`${API}/agents?status=completed&workspaceId=${WS_OTHER}`)).body.items.map((a: any) => a.id),
      ['st-builtin'],
    );
    assert.equal((await api.get(`${API}/agents?status=not_started&workspaceId=${WS_OTHER}`)).body.total, 0);

    // 分页在过滤之后切：total 是过滤后的全量，两页各一条且不重复
    const firstPage = await api.get(`${API}/agents?status=completed&pageSize=1&page=1`);
    const secondPage = await api.get(`${API}/agents?status=completed&pageSize=1&page=2`);
    assert.equal(secondPage.body.total, 2);
    assert.equal(secondPage.body.items.length, 1);
    assert.notEqual(secondPage.body.items[0].id, firstPage.body.items[0].id);

    // 没有命中的状态是空页，不是 404
    const none = await api.get(`${API}/agents?status=blocked`);
    assert.equal(none.status, 200);
    assert.deepEqual(none.body.items, []);
    assert.equal(none.body.total, 0);
  } finally {
    await prisma.run.deleteMany({ where: { instanceId: instance.id } });
    await prisma.instance.delete({ where: { id: instance.id } });
  }
});

/* ---------- 标签 ---------- */

test('tags：新建时给 → 逐项 trim、去重、保序；库里存成一列 JSON 数组串', async () => {
  // 「  天气  」trim 后与「天气」是同一个标签 → 去重，且保留首次出现的顺序
  const agent = await createAgent({ name: '带标签', tags: ['  天气  ', '代码', '天气', '代码'] });
  assert.deepEqual(agent.tags, ['天气', '代码']);

  const row = await prisma.agent.findUnique({ where: { id: agent.id } });
  assert.equal(row?.tags, '["天气","代码"]', '一列 JSON 串，不是关联表');
});

test('tags：不是数组 / 空项 / 超长 / 禁用字符 / 超数量 一律 400', async () => {
  const tooMany = Array.from({ length: 11 }, (_, index) => `t${index}`);
  const cases: Array<[unknown, string]> = [
    ['天气', 'tags 必须是字符串数组'],
    [[1], 'tags[0] 必须是字符串'],
    [['天气', '   '], 'tags[1] 不能为空'],
    [['x'.repeat(11)], `tags[0] 不能超过 10 字：${'x'.repeat(11)}`],
    [tooMany, 'tags 不能超过 10 个（去重后 11 个）'],
    [['天"气'], 'tags[0] 不能含 " \\ % _ 这四个字符：天"气'],
  ];

  for (const [index, [tags, message]] of cases.entries()) {
    const res = await api.post(`${API}/agents`, { workspaceId: WS_ID, name: `非法标签 ${index}`, tags });
    assert.equal(res.status, 400, JSON.stringify(tags));
    assert.equal(res.body.message, message);
  }

  // 去重发生在数量上限之前：11 项里有 2 个重复 → 9 个唯一，放行
  const deduped = await api.post(`${API}/agents`, {
    workspaceId: WS_ID,
    name: '去重后刚好九个',
    tags: [...Array.from({ length: 9 }, (_, index) => `t${index}`), 't0', 't1'],
  });
  assert.equal(deduped.status, 200);
  assert.equal(deduped.body.tags.length, 9);
});

test('tags：来源是保留字，不能当普通标签写入（create / update 都 400）', async () => {
  const created = await api.post(`${API}/agents`, {
    workspaceId: WS_ID,
    name: '来源标签',
    tags: ['自定义'],
  });
  assert.equal(created.status, 400);
  assert.equal(created.body.message, 'tags[0] 不能使用保留标签「自定义」');

  const agent = await createAgent({ name: '来源标签占位' });
  const updated = await api.post(`${API}/agents/${agent.id}/update`, { tags: ['内置'] });
  assert.equal(updated.status, 400);
  assert.equal(updated.body.message, 'tags[0] 不能使用保留标签「内置」');
});

test('list：source 只认 user / builtin，空串视为未传，非法值 400', async () => {
  await prisma.agent.deleteMany();
  await createAgent({ name: '来源甲' });
  await createAgent({ name: '来源乙' });

  const users = await api.get(`${API}/agents?source=user`);
  assert.deepEqual(users.body.items.map((a: any) => a.name).sort(), ['来源乙', '来源甲']);
  assert.equal(users.body.items.every((a: any) => a.source === 'user'), true);

  const builtins = await api.get(`${API}/agents?source=builtin`);
  assert.equal(builtins.body.total, 0);

  assert.equal((await api.get(`${API}/agents?source=`)).body.total, 2);

  const illegal = await api.get(`${API}/agents?source=system`);
  assert.equal(illegal.status, 400);
  assert.equal(illegal.body.message, 'source 取值非法："system"（可选：user / builtin）');
});

test('tags：update 传 [] 是清空、不传才是不改；只给 tags 也算给了字段', async () => {
  const created = await createAgent({ name: '改标签', tags: ['天气'] });

  const kept = await api.post(`${API}/agents/${created.id}/update`, { name: '只改名' });
  assert.deepEqual(kept.body.tags, ['天气'], '没传 tags，标签原样');

  const changed = await api.post(`${API}/agents/${created.id}/update`, { tags: ['代码', '审查'] });
  assert.deepEqual(changed.body.tags, ['代码', '审查']);
  assert.equal(changed.body.name, '只改名');

  const cleared = await api.post(`${API}/agents/${created.id}/update`, { tags: [] });
  assert.deepEqual(cleared.body.tags, []);
});

test('list：tag 是精确匹配（不是子串），空串视为未传', async () => {
  await prisma.agent.deleteMany();
  // 名字要跟别处的用例不撞车（同一工作区内 name 唯一，撞了是 409 而不是这里要测的东西）
  await createAgent({ name: '标签甲', tags: ['天气'] });
  await createAgent({ name: '标签乙', tags: ['天气2', '代码'] });
  await createAgent({ name: '标签丙', tags: ['代码'] });
  await createAgent({ name: '标签丁' });

  const weather = await api.get(`${API}/agents?tag=${encodeURIComponent('天气')}`);
  assert.deepEqual(weather.body.items.map((a: any) => a.name), ['标签甲'], '「天气」不该命中「天气2」');

  const code = await api.get(`${API}/agents?tag=${encodeURIComponent('代码')}`);
  assert.deepEqual(code.body.items.map((a: any) => a.name).sort(), ['标签丙', '标签乙']);
  assert.equal(code.body.total, 2);

  // 没有这个标签是空页，不是报错
  assert.deepEqual((await api.get(`${API}/agents?tag=${encodeURIComponent('查无此标签')}`)).body, {
    items: [],
    total: 0,
    page: 1,
    pageSize: 20,
  });

  // 空串视为未传
  assert.equal((await api.get(`${API}/agents?tag=`)).body.total, 4);

  // 形态非法按 400，与请求体里的 tags 同一套判定
  const illegal = await api.get(`${API}/agents?tag=${encodeURIComponent('天_气')}`);
  assert.equal(illegal.status, 400);
  assert.equal(illegal.body.message, 'tag 不能含 " \\ % _ 这四个字符：天_气');
});

test('tags 清单：去重计数、无标签不产生条目、count 降序后 tag 升序', async () => {
  await prisma.agent.deleteMany();
  await createAgent({ name: '清单甲', tags: ['common', 'code'] });
  await createAgent({ name: '清单乙', tags: ['common', 'weather'] });
  await createAgent({ name: '清单丙', tags: ['common'] });
  await createAgent({ name: '清单丁' });

  const res = await api.get(`${API}/agents/tags`);
  assert.equal(res.status, 200);
  assert.deepEqual(res.body, {
    items: [
      { tag: 'common', count: 3 },
      { tag: 'code', count: 1 },
      { tag: 'weather', count: 1 },
    ],
  });
});

test('tags 清单：空库返回 items: []，且不会被 /agents/:agentId 吞成 404', async () => {
  await prisma.agent.deleteMany();

  const res = await api.get(`${API}/agents/tags`);
  assert.equal(res.status, 200, '静态子路径必须先于 /agents/:agentId 注册');
  assert.deepEqual(res.body, { items: [] });
  assert.equal(res.body.id, undefined, '响应是标签清单，不是某个智能体');
});

test('tags 清单：workspaceId 精确过滤；空串视为未传；非法 uuid 400', async () => {
  await prisma.agent.deleteMany();
  await createAgent({ name: '主区甲', tags: ['main-a', 'shared'] });
  const other = await api.post(`${API}/agents`, {
    workspaceId: WS_OTHER,
    name: '他区甲',
    tags: ['other-a', 'shared'],
  });
  assert.equal(other.status, 200, JSON.stringify(other.body));

  const main = await api.get(`${API}/agents/tags?workspaceId=${WS_ID}`);
  assert.deepEqual(main.body, {
    items: [
      { tag: 'main-a', count: 1 },
      { tag: 'shared', count: 1 },
    ],
  });

  const another = await api.get(`${API}/agents/tags?workspaceId=${WS_OTHER}`);
  assert.deepEqual(another.body, {
    items: [
      { tag: 'other-a', count: 1 },
      { tag: 'shared', count: 1 },
    ],
  });

  // 不传 / 空串：全库口径，跨工作区的同名标签合并计数
  assert.deepEqual((await api.get(`${API}/agents/tags`)).body, {
    items: [
      { tag: 'shared', count: 2 },
      { tag: 'main-a', count: 1 },
      { tag: 'other-a', count: 1 },
    ],
  });
  assert.deepEqual((await api.get(`${API}/agents/tags?workspaceId=`)).body, {
    items: [
      { tag: 'shared', count: 2 },
      { tag: 'main-a', count: 1 },
      { tag: 'other-a', count: 1 },
    ],
  });

  const illegal = await api.get(`${API}/agents/tags?workspaceId=nope`);
  assert.equal(illegal.status, 400);
  assert.match(illegal.body.message, /workspaceId.*uuid/);
});

/* ---------- update ---------- */

test('update：只改传了的字段，workspaceId 不可改且不算可改字段', async () => {
  const created = await createAgent({ name: '待更新', description: '原描述', icon: COVER });
  const before = created.updatedAt;

  const renamed = await api.post(`${API}/agents/${created.id}/update`, { name: '更新后', workspaceId: WS_OTHER });
  assert.equal(renamed.status, 200);
  assert.equal(renamed.body.name, '更新后');
  assert.equal(renamed.body.workspaceId, WS_ID, 'workspaceId 建后不可改，传了按多余字段忽略');
  assert.equal(renamed.body.dir, agentRoot(created.id), '目录不随 update 搬家');
  assert.equal(renamed.body.description, '原描述', '没传的字段原样');
  assert.equal(renamed.body.icon, COVER);
  assert.equal(renamed.body.status, 'not_started');
  assert.equal(renamed.body.id, created.id, 'id 不可改');
  assert.notEqual(renamed.body.updatedAt, before);

  // 只给 workspaceId 等于一个可改字段都没给
  const nothing = await api.post(`${API}/agents/${created.id}/update`, { workspaceId: WS_OTHER });
  assert.equal(nothing.status, 400);
  assert.equal(nothing.body.message, 'update 至少要给一个字段：name / description / tags / icon / knowledgeWorkflowId');

  // 新记录落在列表最前
  const listed = await api.get(`${API}/agents`);
  assert.equal(listed.body.items[0].id, created.id);
});

test('update：description / icon 传空串是清空，不传才是不改', async () => {
  const created = await createAgent({ name: '清空描述', description: '要被清掉的', icon: COVER });

  const kept = await api.post(`${API}/agents/${created.id}/update`, { name: '改名不动描述' });
  assert.equal(kept.body.description, '要被清掉的');
  assert.equal(kept.body.icon, COVER, '没传 icon，封面原样');

  const cleared = await api.post(`${API}/agents/${created.id}/update`, { description: '', icon: '' });
  assert.equal(cleared.body.description, '');
  assert.equal(cleared.body.icon, '', '空串是有意义的取值：没有封面，前端落名称首字');
  assert.equal(cleared.body.name, '改名不动描述');
});

test('update：五个字段一个都没给 → 400（空请求只刷新 updatedAt 是看不见的副作用）', async () => {
  const created = await createAgent({ name: '空更新' });

  for (const body of [{}, { agentId: created.id }, { unknownField: 1 }]) {
    const res = await api.post(`${API}/agents/${created.id}/update`, body);
    assert.equal(res.status, 400, JSON.stringify(body));
    assert.equal(res.body.message, 'update 至少要给一个字段：name / description / tags / icon / knowledgeWorkflowId');
  }

  // 一次都没落盘：updatedAt 没被顶过
  const row = await prisma.agent.findUnique({ where: { id: created.id } });
  assert.equal(row?.updatedAt.toISOString(), created.updatedAt);
});

test('update：status 不在可改字段里，单独传按「一个字段都没给」处理', async () => {
  const created = await createAgent({ name: '状态样本' });

  const only = await api.post(`${API}/agents/${created.id}/update`, { status: 'archived' });
  assert.equal(only.status, 400);
  assert.equal(only.body.message, 'update 至少要给一个字段：name / description / tags / icon / knowledgeWorkflowId');

  // 和别的字段一起传也不生效：status 是派生值，不是可写列
  const renamed = await api.post(`${API}/agents/${created.id}/update`, { name: '状态样本改名', status: 'archived' });
  assert.equal(renamed.status, 200);
  assert.equal(renamed.body.status, 'not_started');
});

test('update：重名按工作区隔离；同工作区 409，跨工作区同名不算冲突', async () => {
  const a = await createAgent({ name: '甲' });
  const b = await createAgent({ name: '乙' });
  const other = await createAgent({ workspaceId: WS_OTHER, name: '另一个工作区的丙' });

  const missing = await api.post(`${API}/agents/${ABSENT}/update`, { name: '随便' });
  assert.equal(missing.status, 404);

  const taken = await api.post(`${API}/agents/${a.id}/update`, { name: '乙' });
  assert.equal(taken.status, 409);
  assert.equal(taken.body.message, '该工作区已有同名智能体「乙」');

  // 改成另一个工作区里已存在的名字：不冲突
  const crossWorkspace = await api.post(`${API}/agents/${a.id}/update`, { name: '另一个工作区的丙' });
  assert.equal(crossWorkspace.status, 200);

  // 值没变，不该撞唯一性
  const same = await api.post(`${API}/agents/${a.id}/update`, { name: '另一个工作区的丙', icon: COVER });
  assert.equal(same.status, 200);
  assert.equal(same.body.icon, COVER);
  assert.equal(b.name, '乙');
  assert.equal(other.name, '另一个工作区的丙');
});

/* ---------- delete ---------- */

test('delete：删整棵 agentRoot（development / preview / .state 全在），返回空对象；不幂等', async () => {
  const created = await createAgent({ name: '待删除' });
  mkdirSync(join(agentRoot(created.id), 'preview'), { recursive: true });
  mkdirSync(join(agentRoot(created.id), '.state'), { recursive: true });
  writeFileSync(join(agentRoot(created.id), 'preview', 'a.txt'), 'x');
  assert.ok(existsSync(join(agentRoot(created.id), 'development')));

  const removed = await api.post(`${API}/agents/${created.id}/delete`);
  assert.equal(removed.status, 200);
  assert.deepEqual(removed.body, {});

  assert.equal(await prisma.agent.count({ where: { id: created.id } }), 0);
  assert.ok(!existsSync(agentRoot(created.id)), '整棵智能体根目录应一并删掉');

  const again = await api.post(`${API}/agents/${created.id}/delete`);
  assert.equal(again.status, 404);
  assert.equal(again.body.message, `智能体 ${created.id} 不存在`);
});

test('delete：工作区未绑定目录 / 不存在 → 502，且不动库、不动盘', async () => {
  await prisma.agent.deleteMany();
  const unbound = 'unbound-agent';
  const unknown = 'unknown-agent';
  await prisma.agent.create({
    data: { id: unbound, workspaceId: WS_NO_DIR, name: unbound, description: '', icon: '' },
  });
  await prisma.agent.create({
    data: { id: unknown, workspaceId: WS_UNKNOWN, name: unknown, description: '', icon: '' },
  });

  const first = await api.post(`${API}/agents/${unbound}/delete`);
  assert.equal(first.status, 502);
  assert.equal(first.body.message, `工作区 ${WS_NO_DIR} 未绑定目录`);

  const second = await api.post(`${API}/agents/${unknown}/delete`);
  assert.equal(second.status, 502);
  assert.equal(second.body.message, `工作区 ${WS_UNKNOWN} 不存在`);

  assert.equal(await prisma.agent.count(), 2, '解析失败时不删库');
});

test('delete：级联清掉该智能体名下全部实例的会话、运行与消息', async () => {
  const created = await createAgent({ name: '级联样本' });

  const production = await api.post(`${API}/sessions/create`, { agentId: created.id, modelId: MODEL_ID });
  const preview = await api.post(`${API}/sessions/create`, { agentId: created.id, stage: 'preview', modelId: MODEL_ID });
  assert.equal(production.status, 200);
  assert.equal(preview.status, 200);

  const sent = await api.post(`${API}/messages/send`, { sessionId: production.body.id, prompt: '你好' });
  await api.waitTerminal(sent.body.run.id);

  const instanceIds = [production.body.instance.id, preview.body.instance.id];
  const sessionIds = [production.body.id, preview.body.id];
  assert.ok(await prisma.run.count({ where: { sessionId: { in: sessionIds } } }) > 0);

  assert.equal((await api.post(`${API}/agents/${created.id}/delete`)).status, 200);

  assert.equal(await prisma.instance.count({ where: { id: { in: instanceIds } } }), 0);
  assert.equal(await prisma.session.count({ where: { id: { in: sessionIds } } }), 0);
  assert.equal(await prisma.run.count({ where: { sessionId: { in: sessionIds } } }), 0);
  assert.equal(await prisma.message.count({ where: { sessionId: { in: sessionIds } } }), 0);
});

test('delete：有活跃 run → 先停掉运行的会话再删，不再 409', async () => {
  const created = await createAgent({ name: '忙碌样本' });
  const session = await api.post(`${API}/sessions/create`, { agentId: created.id, modelId: MODEL_ID });
  // 桩适配器遇到「需要审批」会挂起等应答，run 停在活跃态
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.body.id, prompt: FAKE_TRIGGER.approval });
  assert.equal(sent.body.status, 'running');
  assert.equal(sent.body.run.status, 'running');

  const removed = await api.post(`${API}/agents/${created.id}/delete`);
  assert.equal(removed.status, 200);
  assert.deepEqual(removed.body, {});

  assert.equal(await prisma.agent.count({ where: { id: created.id } }), 0);
  assert.equal(await prisma.instance.count({ where: { id: session.body.instance.id } }), 0);
  assert.equal(await prisma.session.count({ where: { id: session.body.id } }), 0);
  assert.equal(await prisma.run.count({ where: { id: sent.body.run.id } }), 0);
  assert.ok(!existsSync(agentRoot(created.id)));
});

/* ---------- 与会话域的接缝 ---------- */

test('sessions/create：未知 agentId 404（agents 表是智能体存在的唯一权威）', async () => {
  const res = await api.post(`${API}/sessions/create`, { agentId: ABSENT, modelId: MODEL_ID });
  assert.equal(res.status, 404);
  assert.equal(res.body.error, 'NOT_FOUND');
  assert.equal(res.body.message, `智能体 ${ABSENT} 不存在`);

  // 形态非法仍走 400，先于存在性判定
  const malformed = await api.post(`${API}/sessions/create`, { agentId: '../evil', modelId: MODEL_ID });
  assert.equal(malformed.status, 400);
  assert.match(malformed.body.message, /agentId 形态非法/);

  // 没建出实例：拒绝得干干净净
  assert.equal(await prisma.instance.count({ where: { agentId: ABSENT } }), 0);
});

/* ---------- 产物状态 ---------- */

test('GET /agents/{id}/production：未开始时 200 + not_started，完成后 ready=true', async () => {
  const agent = await createAgent({ name: '产物状态智能体' });
  const root = agentRoot(agent.id);

  const initial = await api.get(`${API}/agents/${agent.id}/production`);
  assert.equal(initial.status, 200);
  assert.equal(initial.body.agentId, agent.id);
  assert.equal(initial.body.status, 'not_started');
  assert.equal(initial.body.ready, false);
  assert.deepEqual(initial.body.reasons, ['尚未开始生成智能体']);

  // 按 AgentGenesis 的落盘布局补状态、门禁与产物
  const work = join(root, 'development', '.agent-genesis', 'work', 'demo');
  mkdirSync(join(work, 'gate-results'), { recursive: true });
  writeFileSync(
    join(work, 'orchestrator-state.yaml'),
    'pipeline: agent-creation\npipeline_status: COMPLETED\ncurrent_step: step-5-readiness-verification\nsteps:\n  - step_id: step-4-implementation\n',
  );
  writeFileSync(join(work, 'gate-results', 'step-4-implementation.json'), JSON.stringify({ verdict: 'PASS', concerns: [] }));
  const produced = join(root, 'development', 'output', 'agents', 'demo', 'v1');
  mkdirSync(produced, { recursive: true });
  writeFileSync(join(produced, 'CLAUDE.md'), '# demo\n');

  const ready = await api.get(`${API}/agents/${agent.id}/production`);
  assert.equal(ready.status, 200);
  assert.equal(ready.body.status, 'completed');
  assert.equal(ready.body.ready, true);
  assert.equal(ready.body.lane, 'full');
  assert.equal(ready.body.delivery.verdict, 'PASS');
  assert.equal(ready.body.product.path, 'output/agents/demo/v1');
  assert.deepEqual(ready.body.reasons, []);
});

test('runtimeDir / status：detail / list 现算产物最新版本目录与状态，门禁未过或未生成时为 null；内置行等于 dir', async () => {
  const agent = await createAgent({ name: '运行目录智能体' });
  const root = agentRoot(agent.id);

  // 未生成：null（上面 create 用例已钉一次，这里钉 detail / list 两条路径）
  const fresh = await api.get(`${API}/agents/${agent.id}`);
  assert.equal(fresh.body.runtimeDir, null);
  assert.equal(fresh.body.status, 'not_started');
  const listed = await api.get(`${API}/agents?keyword=运行目录`);
  assert.equal(listed.body.items[0].runtimeDir, null);
  assert.equal(listed.body.items[0].status, 'not_started');

  // 按 AgentGenesis 的落盘布局补状态、门禁与产物（同 production 端点用例的夹具）
  const work = join(root, 'development', '.agent-genesis', 'work', 'demo');
  mkdirSync(join(work, 'gate-results'), { recursive: true });
  writeFileSync(
    join(work, 'orchestrator-state.yaml'),
    'pipeline: agent-creation\npipeline_status: COMPLETED\ncurrent_step: step-5-readiness-verification\nsteps:\n  - step_id: step-4-implementation\n',
  );
  writeFileSync(join(work, 'gate-results', 'step-4-implementation.json'), JSON.stringify({ verdict: 'PASS', concerns: [] }));
  const produced = join(root, 'development', 'output', 'agents', 'demo', 'v1');
  mkdirSync(produced, { recursive: true });
  writeFileSync(join(produced, 'CLAUDE.md'), '# demo\n');

  const ready = await api.get(`${API}/agents/${agent.id}`);
  assert.equal(ready.body.runtimeDir, produced, 'runtime cwd = 产物最新版本目录');
  assert.equal(ready.body.status, 'completed');
  const readyListed = await api.get(`${API}/agents?keyword=运行目录`);
  assert.equal(readyListed.body.items[0].runtimeDir, produced);
  assert.equal(readyListed.body.items[0].status, 'completed');

  // 门禁翻转 FAIL：runtime 起不了跑，runtimeDir 跟着回 null（与起跑门禁同源）
  writeFileSync(join(work, 'gate-results', 'step-4-implementation.json'), JSON.stringify({ verdict: 'FAIL', concerns: [] }));
  const gated = await api.get(`${API}/agents/${agent.id}`);
  assert.equal(gated.body.runtimeDir, null);
  assert.equal(gated.body.status, 'failed');
});

test('detail.knowledgeInjected：产物里真有 rag-knowledge-search 技能才为 true', async () => {
  const agent = await createAgent({ name: '知识注入产物' });
  assert.equal((await api.get(`${API}/agents/${agent.id}`)).body.knowledgeInjected, false, '还没产物');

  // 按 AgentGenesis 的落盘布局补状态、门禁与产物（同上面的夹具）
  const root = agentRoot(agent.id);
  const work = join(root, 'development', '.agent-genesis', 'work', 'demo');
  mkdirSync(join(work, 'gate-results'), { recursive: true });
  writeFileSync(
    join(work, 'orchestrator-state.yaml'),
    'pipeline: agent-creation\npipeline_status: COMPLETED\ncurrent_step: step-5-readiness-verification\nsteps:\n  - step_id: step-4-implementation\n',
  );
  writeFileSync(join(work, 'gate-results', 'step-4-implementation.json'), JSON.stringify({ verdict: 'PASS', concerns: [] }));
  const produced = join(root, 'development', 'output', 'agents', 'demo', 'v1');
  const skill = join(produced, '.claude', 'skills', 'rag-knowledge-search');
  mkdirSync(skill, { recursive: true });
  writeFileSync(join(produced, 'CLAUDE.md'), '# demo\n');
  writeFileSync(join(skill, 'SKILL.md'), '---\nname: rag-knowledge-search\ndescription: 检索\n---\n');

  const detail = await api.get(`${API}/agents/${agent.id}`);
  assert.equal(detail.body.knowledgeInjected, true);
  assert.ok(detail.body.skills.some((skillItem: { name: string }) => skillItem.name === 'rag-knowledge-search'));

  // 重建移除技能后，detail 的派生值跟着变（配置与产物是两件事，这里只看产物）
  rmSync(skill, { recursive: true, force: true });
  assert.equal((await api.get(`${API}/agents/${agent.id}`)).body.knowledgeInjected, false);
});

test('GET /agents/{id}/production：未知智能体 404、形态非法 400', async () => {
  const absent = await api.get(`${API}/agents/${ABSENT}/production`);
  assert.equal(absent.status, 404);
  assert.equal(absent.body.error, 'NOT_FOUND');

  // 大写不合 agentId 形态 → 400（先于存在性判定）
  const malformed = await api.get(`${API}/agents/BAD_ID/production`);
  assert.equal(malformed.status, 400);
});

/* ---------- 启动收养 ---------- */

/** 清空两个工作区的智能体目录，让「有几颗目录该被收」是确定的。 */
function resetAgentsRoots(): void {
  for (const dir of [agentsRoot(), agentsRoot(OTHER_DIR)]) {
    rmSync(dir, { recursive: true, force: true });
    mkdirSync(dir, { recursive: true });
  }
}

test('收养：按工作区扫描盘上已有、表里没有的目录，补登记时带上 workspaceId，且幂等', async () => {
  await prisma.agent.deleteMany();
  resetAgentsRoots();
  mkdirSync(join(agentsRoot(), 'legacy-agent'), { recursive: true });
  mkdirSync(join(agentsRoot(OTHER_DIR), 'other-agent'), { recursive: true });

  assert.equal(await agentService.adoptExistingDirs(), 2);

  const legacy = await prisma.agent.findUnique({ where: { id: 'legacy-agent' } });
  assert.equal(legacy?.workspaceId, WS_ID);
  assert.equal(legacy?.name, 'legacy-agent', 'name 只能拿目录名凑');
  assert.equal(legacy?.description, '');
  assert.equal(legacy?.icon, '', '收养来的行没有封面：前端落名称首字');

  const other = await prisma.agent.findUnique({ where: { id: 'other-agent' } });
  assert.equal(other?.workspaceId, WS_OTHER);

  // 幂等：重复启动不重复插入
  assert.equal(await agentService.adoptExistingDirs(), 0);
  assert.equal(await prisma.agent.count(), 2);
});

test('收养：跳过非目录、隐藏目录与过不了形态校验的目录名；表里有行、盘上没有时不动', async () => {
  await prisma.agent.deleteMany();
  resetAgentsRoots();
  mkdirSync(join(agentsRoot(), '我的笔记'), { recursive: true });
  mkdirSync(join(agentsRoot(), '.hidden'), { recursive: true });
  mkdirSync(join(agentsRoot(), 'tmp dir'), { recursive: true });
  // Windows 上无法创建保留名/结尾点目录，这两个用例只在非 Windows 落盘；判定本身跨平台一致
  if (process.platform !== 'win32') {
    mkdirSync(join(agentsRoot(), 'con'), { recursive: true });
    mkdirSync(join(agentsRoot(), 'trail.'), { recursive: true });
  }
  mkdirSync(join(agentsRoot(), 'keep-me'), { recursive: true });
  await prisma.agent.create({
    data: { id: 'orphan-row', workspaceId: WS_ID, name: 'orphan-row', description: '', icon: '' },
  });

  assert.equal(await agentService.adoptExistingDirs(), 1, '只有 keep-me 够格');

  const ids = (await prisma.agent.findMany({ select: { id: true } })).map((row) => row.id).sort();
  assert.deepEqual(ids, ['keep-me', 'orphan-row']);
  // 盘上没有目录的行留着：宁留空壳，不误删数据
  assert.ok(!existsSync(join(agentsRoot(), 'orphan-row')));
});

test('收养：目录名与同一工作区内已有的展示名撞了 → 跳过，不让 boot 起不来', async () => {
  await prisma.agent.deleteMany();
  resetAgentsRoots();
  await prisma.agent.create({
    data: { id: 'taken-id', workspaceId: WS_ID, name: 'takeout', description: '', icon: '' },
  });
  mkdirSync(join(agentsRoot(), 'takeout'), { recursive: true });
  // 另一个工作区里同名不冲突
  mkdirSync(join(agentsRoot(OTHER_DIR), 'takeout'), { recursive: true });

  assert.equal(await agentService.adoptExistingDirs(), 1, '另一个工作区的 takeout 可以收');
  assert.equal(await prisma.agent.count(), 2);
  assert.equal((await prisma.agent.findUnique({ where: { id: 'takeout' } }))?.workspaceId, WS_OTHER);
});

/* ---------- create 的 init：初始化 development 会话 ---------- */

/** 某智能体名下的会话（经公开接口查，顺带验证 agentId 过滤可用）。 */
async function sessionsOf(agentId: string): Promise<any[]> {
  const { body } = await api.get(`${API}/sessions/list?agentId=${agentId}&stage=development`);
  return body.items;
}

test('create：不带 init 保持旧行为 - 不建实例、不建会话、响应里没有 initSessionId', async () => {
  const agent = await createAgent({ name: '无初始化' });

  assert.equal('initSessionId' in agent, false);
  assert.equal(agent.initialInput, '', '没有 init 就没有创建时的原话');
  assert.deepEqual(await sessionsOf(agent.id), []);
  assert.equal(await prisma.instance.count({ where: { agentId: agent.id } }), 0);
});

test('create：init.modelId 建 development 会话，模型原样落库，不起 run，回带 initSessionId', async () => {
  const agent = await createAgent({ name: '只初始化模型', init: { modelId: MODEL_ID } });

  assert.match(agent.initSessionId, /^sess_/);
  const session = await prisma.session.findUnique({ where: { id: agent.initSessionId } });
  assert.equal(session?.modelId, MODEL_ID);

  const instance = await prisma.instance.findUnique({ where: { id: session!.instanceId } });
  assert.equal(instance?.agentId, agent.id);
  assert.equal(instance?.stage, 'development');

  // 没有 input 就只建会话：不起 run、不落消息
  assert.equal(await prisma.run.count({ where: { sessionId: session!.id } }), 0);
  assert.equal(await prisma.message.count({ where: { sessionId: session!.id } }), 0);

  // 响应除 initSessionId 外与 detail 完全一致（detail 多两项可执行清单，此时都为空）
  const detail = await api.get(`${API}/agents/${agent.id}`);
  const { initSessionId: _initSessionId, ...rest } = agent;
  assert.deepEqual(detail.body, { ...rest, skills: [], commands: [], knowledgeInjected: false });
});

test('create：init.input 原文落库（前端路由 state 丢失后仍可恢复），但不落消息、不起 run', async () => {
  const INPUT = '我要做一个天气智能体，支持查询任意城市的实时天气和未来 7 天预报。';
  const agent = await createAgent({ name: '带初始化输入', description: '卡片摘要', init: { input: INPUT, modelId: MODEL_ID } });
  assert.equal(agent.description, '卡片摘要', 'input 与 description 语义不同，不能混存');
  assert.equal(agent.initialInput, INPUT, '响应里带回原文');

  // 原文是智能体元数据的一部分：落库、detail 可读回，不是一次性的请求参数
  assert.equal((await prisma.agent.findUnique({ where: { id: agent.id } }))?.initialInput, INPUT);
  assert.equal((await api.get(`${API}/agents/${agent.id}`)).body.initialInput, INPUT);

  // 仍然只是「记下来」：首轮由前端在设计页触发，这里不落消息、不起 run
  const session = await prisma.session.findUnique({ where: { id: agent.initSessionId } });
  assert.equal(await prisma.message.count({ where: { sessionId: session!.id } }), 0);
  assert.equal(await prisma.run.count({ where: { sessionId: session!.id } }), 0);
});

test('create：init.input 里的知识检索参数落成 Agent.knowledgeWorkflowId，可改可取消', async () => {
  const INPUT =
    '/agent-genesis:harness-create --knowledge-workflow-id RAG_Workflow_780f 做一个会议纪要助手，从速记里提取待办';
  const agent = await createAgent({ name: '带知识检索', init: { input: INPUT, modelId: MODEL_ID } });
  assert.equal(agent.knowledgeWorkflowId, 'RAG_Workflow_780f', '响应里带回解析出的 id');
  assert.equal(
    (await prisma.agent.findUnique({ where: { id: agent.id } }))?.knowledgeWorkflowId,
    'RAG_Workflow_780f',
  );
  assert.equal((await api.get(`${API}/agents/${agent.id}`)).body.knowledgeWorkflowId, 'RAG_Workflow_780f');

  // 没带参数 = 明确「没有」：落空串（不是 NULL，NULL 留给存量行做推导）
  const plain = await createAgent({ name: '不带知识检索', init: { input: '做一个助手', modelId: MODEL_ID } });
  assert.equal(plain.knowledgeWorkflowId, '');
  assert.equal((await prisma.agent.findUnique({ where: { id: plain.id } }))?.knowledgeWorkflowId, '');

  // 改
  const changed = await api.post(`${API}/agents/${agent.id}/update`, {
    knowledgeWorkflowId: 'RAG_Workflow_other',
  });
  assert.equal(changed.status, 200, JSON.stringify(changed.body));
  assert.equal(changed.body.knowledgeWorkflowId, 'RAG_Workflow_other');

  // 取消：传空串，落库也是空串
  const cleared = await api.post(`${API}/agents/${agent.id}/update`, { knowledgeWorkflowId: '' });
  assert.equal(cleared.status, 200, JSON.stringify(cleared.body));
  assert.equal(cleared.body.knowledgeWorkflowId, '');
  assert.equal((await prisma.agent.findUnique({ where: { id: agent.id } }))?.knowledgeWorkflowId, '');

  // 不传 / 传 null 都是「不改」（null 与空串必须能分开）
  for (const patch of [{}, { knowledgeWorkflowId: null }]) {
    const kept = await api.post(`${API}/agents/${agent.id}/update`, { ...patch, description: '新摘要' });
    assert.equal(kept.status, 200, JSON.stringify(kept.body));
    assert.equal(kept.body.knowledgeWorkflowId, '', JSON.stringify(patch));
  }

  // 形态非法 400，且不改库
  const bad = await api.post(`${API}/agents/${agent.id}/update`, { knowledgeWorkflowId: 'bad id!' });
  assert.equal(bad.status, 400, JSON.stringify(bad.body));
  assert.match(bad.body.message, /knowledgeWorkflowId/);
});

test('存量行：knowledge_workflow_id 为 NULL 时按 initialInput 现推，写过之后固化', async () => {
  const legacyId = 'legacy-knowledge';
  mkdirSync(join(agentsRoot(), legacyId), { recursive: true });
  await prisma.agent.create({
    data: {
      id: legacyId,
      workspaceId: WS_ID,
      source: 'user',
      name: '存量知识检索',
      description: '',
      initialInput: '/agent-genesis:harness-create --knowledge-workflow-id RAG_Workflow_legacy 需求',
      knowledgeWorkflowId: null,
    },
  });

  try {
    const detail = await api.get(`${API}/agents/${legacyId}`);
    assert.equal(detail.status, 200, JSON.stringify(detail.body));
    assert.equal(detail.body.knowledgeWorkflowId, 'RAG_Workflow_legacy', '存量行按创建原话推导');

    // 取消之后不再从原文推 —— 否则「取消」每次重开都会被 history 复活
    await api.post(`${API}/agents/${legacyId}/update`, { knowledgeWorkflowId: '' });
    assert.equal((await api.get(`${API}/agents/${legacyId}`)).body.knowledgeWorkflowId, '');
  } finally {
    await prisma.agent.delete({ where: { id: legacyId } });
    rmSync(join(agentsRoot(), legacyId), { recursive: true, force: true });
  }
});

test('create：init.attachments 落库（真实路径、去重、保序），但不落消息、不起 run', async () => {
  const NOTES = join(env.workspaceDir, 'init-notes.md');
  const SPEC_DIR = join(env.workspaceDir, 'init-spec');
  const SPEC = join(SPEC_DIR, 'api.yaml');
  mkdirSync(SPEC_DIR, { recursive: true });
  writeFileSync(NOTES, '# 笔记\n');
  writeFileSync(SPEC, 'openapi: 3.0.0\n');

  // 裸字符串与 { path } 两种形态都收（与 messages/send 同一套）；重复项只留一份
  const agent = await createAgent({
    name: '带附件',
    init: { modelId: MODEL_ID, attachments: [NOTES, { path: SPEC }, NOTES] },
  });

  assert.deepEqual(agent.initialAttachments, [NOTES, SPEC], '解析后的真实绝对路径、去重保序');
  assert.equal(agent.initialInput, '', '只有附件也可以，原文保持空串');

  // 与 initialInput 一样是元数据：落库、detail 可读回
  const row = await prisma.agent.findUnique({ where: { id: agent.id } });
  assert.equal(row?.initialAttachments, JSON.stringify([NOTES, SPEC]));
  assert.deepEqual((await api.get(`${API}/agents/${agent.id}`)).body.initialAttachments, [NOTES, SPEC]);

  // 首轮仍由前端触发：不落消息、不起 run
  const session = await prisma.session.findUnique({ where: { id: agent.initSessionId } });
  assert.equal(await prisma.message.count({ where: { sessionId: session!.id } }), 0);
  assert.equal(await prisma.run.count({ where: { sessionId: session!.id } }), 0);
});

test('create：不带 init / init 不带 attachments 时 initialAttachments 恒为空数组', async () => {
  const plain = await createAgent({ name: '没有附件' });
  assert.deepEqual(plain.initialAttachments, [], '没有 init 也是 []，不是 null');

  const withInput = await createAgent({ name: '只有原文', init: { modelId: MODEL_ID, input: '原话' } });
  assert.deepEqual(withInput.initialAttachments, []);

  assert.equal(await prisma.agent.count({ where: { name: { in: ['没有附件', '只有原文'] } } }), 2);
});

test('create：init.attachments 形态 / 路径非法时 400 / 404，且不落行、不建目录、不建实例', async () => {
  const beforeDirs = readdirSync(agentsRoot()).length;
  const beforeInstances = await prisma.instance.count();
  const NOTES = join(env.workspaceDir, 'init-valid.md');
  writeFileSync(NOTES, 'x\n');
  const DIR = join(env.workspaceDir, 'init-dir');
  mkdirSync(DIR, { recursive: true });

  const cases: Array<[string, unknown, number, RegExp]> = [
    ['不是数组', NOTES, 400, /init\.attachments 必须是数组/],
    ['null', null, 400, /init\.attachments 必须是数组/],
    ['项不是字符串', [1], 400, /path 必填/],
    ['相对路径', ['relative/path.md'], 400, /必须是绝对路径/],
    ['不存在', [join(env.workspaceDir, 'nope.md')], 404, /不存在/],
    ['是目录不是文件', [DIR], 400, /不是文件/],
    ['超过 20 项', Array.from({ length: 21 }, () => NOTES), 400, /最多 20 项/],
  ];

  for (const [index, [name, attachments, status, message]] of cases.entries()) {
    const agentName = `非法附件 ${index}`;
    const res = await api.post(`${API}/agents`, {
      workspaceId: WS_ID,
      name: agentName,
      init: { modelId: MODEL_ID, attachments },
    });
    assert.equal(res.status, status, `${name}: ${JSON.stringify(res.body)}`);
    assert.match(res.body.message, message, name);
    assert.equal(await prisma.agent.count({ where: { name: agentName } }), 0, `${name} 不得落行`);
  }

  assert.equal(readdirSync(agentsRoot()).length, beforeDirs, '校验失败不建目录');
  assert.equal(await prisma.instance.count(), beforeInstances, '校验失败不建实例');
});

test('update：initialInput / initialAttachments 不可改 - 创建时的原话与附件不是可编辑字段，传了按多余字段忽略', async () => {
  const NOTES = join(env.workspaceDir, 'immutable-notes.md');
  writeFileSync(NOTES, 'x\n');
  const agent = await createAgent({ name: '原话不可改', init: { input: '原话', modelId: MODEL_ID, attachments: [NOTES] } });

  const res = await api.post(`${API}/agents/${agent.id}/update`, {
    initialInput: '改掉',
    initialAttachments: ['/etc/hosts'],
    description: '新摘要',
  });
  assert.equal(res.status, 200, JSON.stringify(res.body));
  assert.equal(res.body.description, '新摘要');
  assert.equal(res.body.initialInput, '原话');
  assert.deepEqual(res.body.initialAttachments, [NOTES]);
  assert.equal((await prisma.agent.findUnique({ where: { id: agent.id } }))?.initialInput, '原话');
});

test('create：init 缺 modelId / 空串 modelId 一律 400，不落行、不建目录、不建实例', async () => {
  const beforeDirs = readdirSync(agentsRoot()).length;
  const beforeInstances = await prisma.instance.count();

  const cases: Array<[string, Record<string, unknown>]> = [
    ['空 init', {}],
    ['空串 modelId', { modelId: '' }],
    ['只有 input', { input: '' }],
  ];

  for (const [name, init] of cases) {
    const res = await api.post(`${API}/agents`, { workspaceId: WS_ID, name, init });
    assert.equal(res.status, 400, `${name}: ${JSON.stringify(res.body)}`);
    assert.equal(res.body.error, 'BAD_REQUEST');
    assert.match(res.body.message, /init\.modelId/);
    assert.equal(await prisma.agent.count({ where: { name } }), 0);
  }

  assert.equal(readdirSync(agentsRoot()).length, beforeDirs, '校验失败不建目录');
  assert.equal(await prisma.instance.count(), beforeInstances, '校验失败不建实例');
});

test('create：init.input 为空或空白仍建会话，只是不落消息、不起 run', async () => {
  for (const [name, init] of [
    ['空串 input', { modelId: MODEL_ID, input: '' }],
    ['空白 input', { modelId: MODEL_ID, input: '   ' }],
  ] as const) {
    const agent = await createAgent({ name, init });
    assert.match(agent.initSessionId, /^sess_/);
    assert.equal(agent.initialInput, '', '空白原文等同于没写');

    const session = await prisma.session.findUnique({ where: { id: agent.initSessionId } });
    assert.equal(session?.modelId, MODEL_ID);
    assert.equal(await prisma.run.count({ where: { sessionId: session!.id } }), 0);
    assert.equal(await prisma.message.count({ where: { sessionId: session!.id } }), 0);
  }
});

test('create：init 形态非法一律 400，且不落行、不建目录、不建实例', async () => {
  const beforeDirs = readdirSync(agentsRoot()).length;
  const beforeInstances = await prisma.instance.count();

  const cases: Array<[unknown, string]> = [
    ['不是对象', 'init 必须是对象'],
    [[], 'init 必须是对象'],
    [{ foo: 1 }, 'init 含未知字段：foo（只支持 input / modelId / attachments）'],
    [{ input: 1 }, 'init.input 必须是字符串'],
    [{ input: null }, 'init.input 必须是字符串'],
    [{ modelId: 1 }, 'init.modelId 必须是字符串'],
    [{ modelId: null }, 'init.modelId 必须是字符串'],
  ];

  for (const [index, [init, message]] of cases.entries()) {
    const name = `非法 init ${index}`;
    const res = await api.post(`${API}/agents`, { workspaceId: WS_ID, name, init });
    assert.equal(res.status, 400, JSON.stringify(init));
    assert.equal(res.body.error, 'BAD_REQUEST');
    assert.equal(res.body.message, message);
    assert.equal(await prisma.agent.count({ where: { name } }), 0);
  }

  assert.equal(readdirSync(agentsRoot()).length, beforeDirs, '校验失败不建目录');
  assert.equal(await prisma.instance.count(), beforeInstances, '校验失败不建实例');
});

test('create：init.modelId 不存在 → 400；模型管理不可用 → 502；都不落行', async () => {
  const absent = await api.post(`${API}/agents`, {
    workspaceId: WS_ID,
    name: '模型不存在',
    init: { modelId: ABSENT_MODEL_ID },
  });
  assert.equal(absent.status, 400);
  // 具体原因必须带自己的 messageKey：只给 bad_request.default 时前端会显示「请求格式不正确」
  assert.equal(absent.body.messageKey, 'error.bad_request.model_not_found');
  assert.equal(absent.body.message, '所选模型不存在或已删除，请重新选择模型');
  assert.ok(!absent.body.message.includes(ABSENT_MODEL_ID), '模型 id 不得出现在给人看的文案里');
  assert.equal(await prisma.agent.count({ where: { name: '模型不存在' } }), 0);

  stub.modelsStatus = 503;
  try {
    const down = await api.post(`${API}/agents`, {
      workspaceId: WS_ID,
      name: '模型管理不可用',
      init: { modelId: MODEL_ID },
    });
    assert.equal(down.status, 502);
    assert.equal(down.body.error, 'FRAMEWORK_UNAVAILABLE');
    assert.equal(await prisma.agent.count({ where: { name: '模型管理不可用' } }), 0);
  } finally {
    stub.modelsStatus = 200;
  }
});

test('create：init.modelId 指向 openai 协议或无密钥模型 → 400，且不落行', async () => {
  const beforeDirs = readdirSync(agentsRoot()).length;
  const cases: Array<[string, string, RegExp, string]> = [
    ['OpenAI 协议模型', TEST_MODEL_OPENAI_ID, /协议/, 'error.bad_request.model_protocol'],
    ['无密钥模型', TEST_MODEL_NO_KEY_ID, /(密钥|API ?Key)/i, 'error.bad_request.model_no_key'],
  ];

  for (const [name, modelId, reason, messageKey] of cases) {
    const res = await api.post(`${API}/agents`, { workspaceId: WS_ID, name, init: { modelId } });
    assert.equal(res.status, 400, `${name}: ${JSON.stringify(res.body)}`);
    assert.equal(res.body.error, 'BAD_REQUEST');
    assert.equal(res.body.messageKey, messageKey);
    assert.match(res.body.message, /模型/);
    assert.match(res.body.message, reason);
    assert.equal(await prisma.agent.count({ where: { name } }), 0, `${name} 不得落行`);
  }

  assert.equal(readdirSync(agentsRoot()).length, beforeDirs, '校验失败不建目录');
});

test('create：初始化会话失败 → 回滚刚建的 agent 行与目录，不留半成品', async () => {
  const beforeDirs = readdirSync(agentsRoot()).length;
  const beforeInstances = await prisma.instance.count();
  const original = sessionsRepo.create;
  // 走到建会话这一步才失败：用来验证「有 agent、没有会话」的半成品会被清掉
  sessionsRepo.create = async () => {
    throw new Error('模拟初始化失败');
  };
  try {
    const res = await api.post(`${API}/agents`, {
      workspaceId: WS_ID,
      name: '回滚样本',
      init: { modelId: MODEL_ID },
    });
    assert.equal(res.status, 500);
  } finally {
    sessionsRepo.create = original;
  }

  assert.equal(await prisma.agent.count({ where: { name: '回滚样本' } }), 0);
  assert.equal(await prisma.instance.count(), beforeInstances, '实例随级联一起回滚');
  assert.equal(readdirSync(agentsRoot()).length, beforeDirs, '目录也一并删掉');
});

/* ---------- 工作区列表代理 ---------- */

test('workspaces/list：只透出 id / name / defaultModelId 与 activeId，不下发 directory', async () => {
  const res = await api.get(`${API}/workspaces/list`);
  assert.equal(res.status, 200);
  assert.deepEqual(res.body, {
    items: [
      { id: WS_ID, name: '主工作区', defaultModelId: null },
      { id: WS_OTHER, name: '另一个工作区', defaultModelId: MODEL_ID },
      { id: WS_NO_DIR, name: '未绑定工作区', defaultModelId: null },
    ],
    activeId: WS_ID,
  });
  for (const item of res.body.items) {
    assert.deepEqual(Object.keys(item).sort(), ['defaultModelId', 'id', 'name']);
  }
});

test('workspaces/list：框架不可达 → 502，message 保留上游原因', async () => {
  await stub.close();
  stubClosed = true;

  // 换一个从未被请求过的端口更贴近真实断连；这里直接复用已停止的桩地址即可
  const res = await api.get(`${API}/workspaces/list`);
  assert.equal(res.status, 502);
  assert.equal(res.body.error, 'BAD_GATEWAY');
  assert.match(res.body.message, /框架请求失败/);
});

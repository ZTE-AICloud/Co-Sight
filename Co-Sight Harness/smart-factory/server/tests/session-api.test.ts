import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync } from 'node:fs';
import { prepareTestEnv } from './helpers/test-db.js';
import { agentRootIn, seedAgents, seedDevelopmentDir, seedPipelineState } from './helpers/agents.js';
import { startWorkspaceStub, TEST_MODEL_ALT_ID, TEST_MODEL_BASE_URL, TEST_MODEL_ID } from './helpers/workspace-stub.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

const env = prepareTestEnv('session-api');
const stub = await startWorkspaceStub(env);

const { prisma } = await import('../src/shared/prisma/client.js');
const { instancesRepo } = await import('../src/shared/store/instances.repo.js');
const { sessionsRepo } = await import('../src/shared/store/sessions.repo.js');
const { messagesRepo } = await import('../src/shared/store/messages.repo.js');
const { runsRepo } = await import('../src/shared/store/runs.repo.js');
const { liveHub } = await import('../src/shared/live/live-hub.js');
const { FakeAdapter, FAKE_TRIGGER } = await import('../src/shared/engine/fake-adapter.js');
const { sessionService } = await import('../src/modules/session/session.service.js');

let api: TestApi;

/** 轮询 run 直到停在挂起（审批/交互）上；用例需要「活跃窗口」时用它，不依赖 fake 的流式节奏。 */
async function waitRunWaiting(runId: string): Promise<void> {
  for (let i = 0; i < 100; i += 1) {
    const { body } = await api.get(`${API}/runs/detail?runId=${runId}`);
    if (body.waiting) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`run ${runId} 未在 5s 内停在挂起上`);
}

before(async () => {
  // 会话挂在智能体上：agents 表是存在的唯一权威，本文件用到的 agentId 先建行
  await seedAgents(
    'api-flow',
    'api-evaluate',
    'api-preview',
    'api-preview-blocked',
    'api-conflict',
    'api-orphan-guard',
    'api-abort',
    'api-runs',
    'api-delete',
    'api-instance-busy',
    'api-revive',
    'api-delete-busy',
    'api-abort-race',
    'api-abort-pre-engine',
    'api-abort-terminal-window',
    'api-validate',
    'api-runtime-send',
    'api-runtime-reuse',
    'api-runtime-model',
    'api-runtime-race',
    'api-runtime-concurrent',
    'api-runtime-guard',
    'api-derived',
    'api-switch',
    'api-resume',
    'api-resume-lookup',
    'api-named-by-engine',
    'api-resolve-fail',
    'api-send-null',
  );
  for (const agentId of [
    'api-flow',
    'api-evaluate',
    'api-preview',
    'api-preview-blocked',
    'api-conflict',
    'api-orphan-guard',
    'api-abort',
    'api-abort-race',
    'api-abort-pre-engine',
    'api-abort-terminal-window',
    'api-runs',
    'api-delete',
    'api-instance-busy',
    'api-revive',
    'api-delete-busy',
    'api-validate',
    'api-runtime-send',
    'api-runtime-reuse',
    'api-runtime-model',
    'api-runtime-race',
    'api-runtime-concurrent',
    'api-runtime-guard',
    'api-derived',
    'api-switch',
    'api-resume',
    'api-named-by-engine',
    'api-resolve-fail',
  ]) {
    seedDevelopmentDir(env.workspaceDir, agentId);
  }
  api = await startTestApi();
});

after(async () => {
  await api.close();
  await stub.close();
  await prisma.$disconnect();
});

test('探活在新前缀下：GET /api/smart-factory/v1/health', async () => {
  const { status, body } = await api.get(`${API}/health`);
  assert.equal(status, 200);
  assert.equal(body.status, 'ok');
});

test('建会话 → 发消息 → fake 跑完 → 读历史（完整的 run 链路）', async () => {
  const created = await api.post(`${API}/sessions/create`, { agentId: 'api-flow', modelId: TEST_MODEL_ID });
  assert.equal(created.status, 200);
  assert.equal(created.body.instance.stage, 'development');
  assert.equal(created.body.instance.agentId, 'api-flow');
  assert.equal(created.body.instance.engine, 'fake');

  const sent = await api.post(`${API}/messages/send`, { sessionId: created.body.id, prompt: '你好' });
  assert.equal(sent.status, 200);
  assert.equal(sent.body.message.role, 'user');
  assert.equal(sent.body.message.seq, 1);
  assert.equal(sent.body.status, 'running');
  assert.equal(sent.body.run.status, 'running');
  assert.ok(sent.body.run.startedAt, 'running run 必须带 startedAt');
  assert.equal(sent.body.effort, 'high');
  assert.equal(sent.body.modelId, TEST_MODEL_ID, '起跑条件解析在响应前完成，模型随响应返回');
  assert.equal(sent.body.modelName, 'test-sonnet');
  assert.equal(sent.body.modelFellBack, false);
  assert.equal(sent.body.sessionId, created.body.id);
  assert.equal(sent.body.runId, sent.body.run.id);
  assert.equal(sent.body.instanceId, created.body.instance.id);

  const run = await api.waitTerminal(sent.body.run.id);
  assert.equal(run.status, 'succeeded');
  assert.equal(run.error, null);
  assert.equal(run.waiting, null);

  const messages = await api.get(`${API}/messages/list?sessionId=${created.body.id}`);
  assert.equal(messages.status, 200);
  assert.deepEqual(
    messages.body.items.map((m: any) => [m.seq, m.role, m.type]),
    [
      [1, 'user', 'text'],
      [2, 'assistant', 'text'],
    ],
  );
  assert.deepEqual(messages.body.items[1].content, { text: '收到：你好' });
  assert.equal(messages.body.nextAfterSeq, null);

  const session = await api.get(`${API}/sessions/detail?sessionId=${created.body.id}`);
  assert.equal(session.body.status, 'completed');
  assert.equal(session.body.messageCount, 2);
  assert.equal(session.body.lastMessage, null, 'detail 不填充 lastMessage');
  assert.equal(session.body.firstUserMessage, null, 'detail 不填充 firstUserMessage');

  const listed = await api.get(`${API}/sessions/list?agentId=api-flow&stage=development`);
  const row = listed.body.items.find((item: any) => item.id === created.body.id);
  assert.equal(row.messageCount, 2);
  assert.equal(row.lastMessage, '收到：你好');
});

test('stage=evaluation：create 不物化，run 前从产物物化评估目录，且与开发实例不同', async () => {
  const { mkdirSync, writeFileSync } = await import('node:fs');
  const { instancesRepo: repo } = await import('../src/shared/store/instances.repo.js');

  const agentRoot = agentRootIn(env.workspaceDir, 'api-evaluate');
  const produced = `${agentRoot}/development/output/agents/demo/v1`;
  mkdirSync(produced, { recursive: true });
  writeFileSync(`${produced}/from-development.txt`, 'v1');
  seedPipelineState(agentRoot, 'demo');

  const created = await api.post(`${API}/sessions/create`, {
    agentId: 'api-evaluate',
    stage: 'evaluation',
    modelId: TEST_MODEL_ID,
  });
  assert.equal(created.status, 200);
  assert.equal(created.body.instance.stage, 'evaluation');
  assert.ok(!existsSync(`${agentRoot}/evaluation`), 'create 不物化');

  const sent = await api.post(`${API}/messages/send`, { sessionId: created.body.id, prompt: '你好' });
  assert.equal((await api.waitTerminal(sent.body.run.id)).status, 'succeeded');
  assert.equal(existsSync(`${agentRoot}/evaluation/agent/from-development.txt`), true);

  const developmentInstance = await repo.getOrCreate('api-evaluate', 'development');
  assert.notEqual(developmentInstance.id, created.body.instance.id);
});

test('stage=preview：create 不物化，run 前从最新 vN 产物物化，且与开发实例不同', async () => {
  const { mkdirSync, writeFileSync } = await import('node:fs');
  const { instancesRepo: repo } = await import('../src/shared/store/instances.repo.js');

  const agentRoot = agentRootIn(env.workspaceDir, 'api-preview');
  const produced = `${agentRoot}/development/output/agents/demo/v2`;
  mkdirSync(produced, { recursive: true });
  writeFileSync(`${produced}/from-development.txt`, 'v2');
  seedPipelineState(agentRoot, 'demo');

  const created = await api.post(`${API}/sessions/create`, {
    agentId: 'api-preview',
    stage: 'preview',
    modelId: TEST_MODEL_ID,
  });
  assert.equal(created.status, 200);
  assert.equal(created.body.instance.stage, 'preview');
  assert.ok(!existsSync(`${agentRoot}/preview`), 'create 不物化');

  const sent = await api.post(`${API}/messages/send`, { sessionId: created.body.id, prompt: '你好' });
  assert.equal((await api.waitTerminal(sent.body.run.id)).status, 'succeeded');
  assert.equal(existsSync(`${agentRoot}/preview/from-development.txt`), true);

  const developmentInstance = await repo.getOrCreate('api-preview', 'development');
  assert.notEqual(developmentInstance.id, created.body.instance.id);
});

test('preview：产物未生成时 send 被拒，补齐产物 + 状态 + 门禁后才放行', async () => {
  const { writeFileSync } = await import('node:fs');
  const agentRoot = agentRootIn(env.workspaceDir, 'api-preview-blocked');

  // create 本身不碰磁盘，允许先建会话
  const created = await api.post(`${API}/sessions/create`, {
    agentId: 'api-preview-blocked',
    stage: 'preview',
    modelId: TEST_MODEL_ID,
  });
  assert.equal(created.status, 200);

  const blocked = await api.post(`${API}/messages/send`, { sessionId: created.body.id, prompt: '你好' });
  assert.equal(blocked.status, 404, JSON.stringify(blocked.body));
  assert.match(blocked.body.message, /output\/agents/);

  // 被拒时不留 run、不留用户消息
  assert.equal((await api.get(`${API}/runs/list?sessionId=${created.body.id}`)).body.total, 0);
  assert.equal((await api.get(`${API}/messages/list?sessionId=${created.body.id}`)).body.items.length, 0);

  const produced = `${agentRoot}/development/output/agents/demo/v1`;
  mkdirSync(produced, { recursive: true });
  writeFileSync(`${produced}/CLAUDE.md`, '# demo\n');
  seedPipelineState(agentRoot, 'demo');

  const sent = await api.post(`${API}/messages/send`, { sessionId: created.body.id, prompt: '你好' });
  assert.equal(sent.status, 200);
  assert.equal((await api.waitTerminal(sent.body.run.id)).status, 'succeeded');
});

test('同一会话已有活跃 run 时再发消息返回 409', async () => {
  const { body: session } = await api.post(`${API}/sessions/create`, {
    agentId: 'api-conflict',
    modelId: TEST_MODEL_ID,
  });
  // 停在审批上，确保第一条 run 在第二次 send 时仍然活跃
  const first = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: FAKE_TRIGGER.approval });
  assert.equal(first.status, 200);

  const second = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: '再来一条' });
  assert.equal(second.status, 409);
  assert.equal(second.body.error, 'CONFLICT');

  const aborted = await api.post(`${API}/runs/abort`, { runId: first.body.run.id });
  assert.equal(aborted.status, 200);
  await api.waitTerminal(first.body.run.id);
});

test('同实例的其它会话在跑时，messages/send 返回 409 且不落任何消息', async () => {
  const { body: busy } = await api.post(`${API}/sessions/create`, {
    agentId: 'api-orphan-guard',
    modelId: TEST_MODEL_ID,
  });
  const { body: idle } = await api.post(`${API}/sessions/create`, {
    agentId: 'api-orphan-guard',
    modelId: TEST_MODEL_ID,
  });

  // idle 先跑完一轮，留下可对比的消息基线
  const first = await api.post(`${API}/messages/send`, { sessionId: idle.id, prompt: '先跑一轮' });
  assert.equal(first.status, 200);
  await api.waitTerminal(first.body.run.id);
  const before = await api.get(`${API}/messages/list?sessionId=${idle.id}`);
  assert.deepEqual(before.body.items.map((m: any) => [m.seq, m.role]), [[1, 'user'], [2, 'assistant']]);

  // busy 的 run 停在审批上，占住实例名额
  const parked = await api.post(`${API}/messages/send`, { sessionId: busy.id, prompt: `${FAKE_TRIGGER.approval}` });
  assert.equal(parked.status, 200);

  const blocked = await api.post(`${API}/messages/send`, { sessionId: idle.id, prompt: '不该落库' });
  assert.equal(blocked.status, 409);
  assert.equal(blocked.body.error, 'CONFLICT');

  const after = await api.get(`${API}/messages/list?sessionId=${idle.id}`);
  assert.deepEqual(after.body.items.map((m: any) => [m.seq, m.role]), [[1, 'user'], [2, 'assistant']]);
  assert.equal((await api.get(`${API}/sessions/detail?sessionId=${idle.id}`)).body.status, 'completed');

  const aborted = await api.post(`${API}/runs/abort`, { runId: parked.body.run.id });
  assert.equal(aborted.status, 200);
});

test('中止运行：run 落 aborted，会话收口', async () => {
  const { body: session } = await api.post(`${API}/sessions/create`, {
    agentId: 'api-abort',
    modelId: TEST_MODEL_ID,
  });
  // 停在审批上再中止：不依赖 fake adapter 的流式节奏，避免 run 先跑完导致 409
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: FAKE_TRIGGER.approval });
  assert.equal(sent.status, 200);

  const aborted = await api.post(`${API}/runs/abort`, { runId: sent.body.run.id });
  assert.equal(aborted.status, 200);
  assert.equal(aborted.body.status, 'aborted');

  const detail = await api.get(`${API}/runs/detail?runId=${sent.body.run.id}`);
  assert.equal(detail.body.status, 'aborted');

  const again = await api.post(`${API}/runs/abort`, { runId: sent.body.run.id });
  assert.equal(again.status, 409);
});

test('send 返回后中止的竞态：引擎启动被拦住，run 仍收口为 aborted，终态之后不再发 run.started', async () => {
  const { FakeAdapter } = await import('../src/shared/engine/fake-adapter.js');
  const { body: session } = await api.post(`${API}/sessions/create`, {
    agentId: 'api-abort-race',
    modelId: TEST_MODEL_ID,
  });

  const events: any[] = [];
  const subscriber = {
    send: (envelope: any): boolean => {
      events.push(envelope);
      return true;
    },
  };
  liveHub.subscribe(session.id, subscriber);

  // 卡住引擎启动：send 已返回，适配器还没真正开跑，中止必须能命中
  const originalRun = FakeAdapter.prototype.run;
  let releaseEngine!: () => void;
  const engineGate = new Promise<void>((resolve) => {
    releaseEngine = resolve;
  });
  let engineEntered!: () => void;
  const entered = new Promise<void>((resolve) => {
    engineEntered = resolve;
  });
  let engineObservedAborted: boolean | null = null;
  FakeAdapter.prototype.run = async function (ctx: Parameters<typeof originalRun>[0]) {
    engineEntered();
    await engineGate;
    engineObservedAborted = ctx.signal.aborted;
    return originalRun.call(this, ctx);
  };

  try {
    const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: '你好' });
    assert.equal(sent.status, 200);
    assert.equal(sent.body.status, 'running');
    await entered;

    // run.started 在 send 返回前已广播；中止落在引擎启动窗口内
    assert.deepEqual(
      events.filter((e) => e.method === 'run.started').map((e) => e.payload.status),
      ['running'],
    );
    const aborted = await api.post(`${API}/runs/abort`, { runId: sent.body.run.id });
    assert.equal(aborted.status, 200);
    assert.equal(aborted.body.status, 'aborted');

    releaseEngine();
    const run = await api.waitTerminal(sent.body.run.id);
    assert.equal(run.status, 'aborted');
    assert.ok(run.finishedAt);
    // 等驱动链收尾（closeRun 的广播）
    await new Promise((resolve) => setTimeout(resolve, 300));

    assert.equal(engineObservedAborted, true, '中止后已进入的引擎必须观察到 signal.aborted');

    // 4.06 §5.2：run.started 的 status 恒为 running；终态之后不得再补发
    const terminalIndex = events.findIndex(
      (e) => e.method === 'run.status' && e.payload.id === sent.body.run.id && e.payload.status === 'aborted',
    );
    assert.ok(terminalIndex >= 0, '中止终态必须广播');
    assert.deepEqual(
      events.slice(terminalIndex + 1).filter((e) => e.method === 'run.started'),
      [],
      '终态之后不得再发 run.started',
    );
    assert.equal((await api.get(`${API}/sessions/detail?sessionId=${session.id}`)).body.status, 'completed');
  } finally {
    releaseEngine();
    FakeAdapter.prototype.run = originalRun;
    liveHub.unsubscribe(session.id, subscriber);
  }
});

test('send 返回前中止：跳过 run.started 与引擎启动，run 由 closeRun 收口', async () => {
  const { FakeAdapter } = await import('../src/shared/engine/fake-adapter.js');
  const { body: session } = await api.post(`${API}/sessions/create`, {
    agentId: 'api-abort-pre-engine',
    modelId: TEST_MODEL_ID,
  });

  const events: any[] = [];
  const subscriber = {
    send: (envelope: any): boolean => {
      events.push(envelope);
      return true;
    },
  };
  liveHub.subscribe(session.id, subscriber);

  // 卡在会话置 in_progress：此时 run 已建、中止句柄已注册，响应尚未返回
  const originalMarkInProgress = sessionsRepo.markInProgress;
  let releaseMark!: () => void;
  const markGate = new Promise<void>((resolve) => {
    releaseMark = resolve;
  });
  let markEntered!: () => void;
  const markHeld = new Promise<void>((resolve) => {
    markEntered = resolve;
  });
  sessionsRepo.markInProgress = async (id: string) => {
    markEntered();
    await markGate;
    return originalMarkInProgress.call(sessionsRepo, id);
  };

  const originalRun = FakeAdapter.prototype.run;
  let adapterCalls = 0;
  FakeAdapter.prototype.run = async function (ctx: Parameters<typeof originalRun>[0]) {
    adapterCalls += 1;
    return originalRun.call(this, ctx);
  };

  let sent: any;
  try {
    const sending = api.post(`${API}/messages/send`, { sessionId: session.id, prompt: '你好' });
    await markHeld;
    // 响应还没回来，客户端还不知道 runId；按会话中止
    const aborted = await api.post(`${API}/sessions/abort`, { sessionId: session.id });
    assert.equal(aborted.status, 200);
    assert.equal(aborted.body.status, 'aborted');
    releaseMark();
    sent = await sending;
  } finally {
    releaseMark();
    sessionsRepo.markInProgress = originalMarkInProgress;
    FakeAdapter.prototype.run = originalRun;
  }

  assert.equal(sent.status, 200);
  assert.equal(sent.body.run.status, 'running', '响应是建 run 时的快照');

  const run = await api.waitTerminal(sent.body.runId);
  assert.equal(run.status, 'aborted');
  assert.equal(adapterCalls, 0, '中止先于引擎启动时不得实例化适配器');

  await new Promise((resolve) => setTimeout(resolve, 200));
  assert.deepEqual(
    events.filter((event) => event.method === 'run.started'),
    [],
    '中止先于 run.started 广播时不得补发起跑事件',
  );
  liveHub.unsubscribe(session.id, subscriber);
  assert.equal((await api.get(`${API}/sessions/detail?sessionId=${session.id}`)).body.status, 'completed');
});

test('起跑前模型解析失败：400、不建 run、不落消息、不改会话状态', async () => {
  // 会话里的模型 id 在框架详情面不存在：resolveRunModel 在建 run 之前失败（详情 404 -> 400）
  const development = await instancesRepo.getOrCreate('api-resolve-fail', 'development');
  const session = await sessionsRepo.create({ instanceId: development.id, modelId: 'mdl_missing_for_send' });

  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: '你好' });
  assert.equal(sent.status, 400, JSON.stringify(sent.body));
  assert.equal(sent.body.error, 'BAD_REQUEST');
  // 会话里的模型被删是「可修复状态」，与「刚选了一个不存在的模型」分开
  assert.equal(sent.body.messageKey, 'error.bad_request.session_model_missing');
  assert.match(sent.body.message, /已被删除/);
  assert.doesNotMatch(sent.body.message, /mdl_missing_for_send/, '模型 id 不得出现在给人看的文案里');

  assert.equal(await prisma.run.count({ where: { sessionId: session.id } }), 0, '解析失败不得留下 run');
  assert.equal(await prisma.message.count({ where: { sessionId: session.id } }), 0, '解析失败不得落下用户消息');
  assert.equal((await api.get(`${API}/sessions/detail?sessionId=${session.id}`)).body.status, 'not_started');

  // 首帧按 agentId 新建的会话同样在解析失败后删除，实例上不多出空会话
  const runtimeRoot = agentRootIn(env.workspaceDir, 'api-resolve-fail');
  mkdirSync(`${runtimeRoot}/development/output/agents/demo/v1`, { recursive: true });
  seedPipelineState(runtimeRoot, 'demo');
  await assert.rejects(
    () => sessionService.sendMessage({ agentId: 'api-resolve-fail', prompt: '你好', modelId: 'mdl_missing_for_send' }),
    (error: any) => error.status === 400,
  );
  const runtime = await instancesRepo.getOrCreate('api-resolve-fail', 'runtime');
  assert.equal(await prisma.session.count({ where: { instanceId: runtime.id } }), 0, '解析失败的新建会话必须被清理');
});

test('终态窗口内重复中止：run 已落 succeeded、句柄未摘，也稳定 409', async () => {
  const originalFinish = runsRepo.finish;
  let releaseFinish!: () => void;
  const finishGate = new Promise<void>((resolve) => {
    releaseFinish = resolve;
  });
  let markFinished!: () => void;
  const finished = new Promise<void>((resolve) => {
    markFinished = resolve;
  });

  // 撑开「已落终态、驱动链还没摘句柄」的窗口
  runsRepo.finish = async (id: string, status: 'succeeded' | 'failed' | 'aborted', error?: string) => {
    const ok = await originalFinish.call(runsRepo, id, status, error);
    if (status === 'succeeded') {
      markFinished();
      await finishGate;
    }
    return ok;
  };

  const { body: session } = await api.post(`${API}/sessions/create`, {
    agentId: 'api-abort-terminal-window',
    modelId: TEST_MODEL_ID,
  });
  let runId = '';
  try {
    const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: '你好' });
    assert.equal(sent.status, 200);
    runId = sent.body.run.id;
    await finished;

    const again = await api.post(`${API}/runs/abort`, { runId });
    assert.equal(again.status, 409);
    assert.equal(again.body.error, 'CONFLICT');
  } finally {
    runsRepo.finish = originalFinish;
    releaseFinish();
  }

  assert.equal((await api.waitTerminal(runId)).status, 'succeeded');
});

test('已删会话不能再起 run：createActiveRun 必须拒绝', async () => {
  const instance = await instancesRepo.getOrCreate('api-orphan-run', 'development');
  const session = await sessionsRepo.create({ instanceId: instance.id, modelId: TEST_MODEL_ID });
  await sessionsRepo.deleteCascade(session.id);

  await assert.rejects(() => runsRepo.createActiveRun({ sessionId: session.id, instanceId: instance.id }), /会话/);
  assert.equal(await prisma.run.count({ where: { sessionId: session.id } }), 0);
});

test('运行记录列表按会话过滤', async () => {
  const { body: session } = await api.post(`${API}/sessions/create`, {
    agentId: 'api-runs',
    modelId: TEST_MODEL_ID,
  });
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: 'hi' });
  await api.waitTerminal(sent.body.run.id);

  const list = await api.get(`${API}/runs/list?sessionId=${session.id}`);
  assert.equal(list.status, 200);
  assert.equal(list.body.total, 1);
  assert.equal(list.body.items[0].status, 'succeeded');
});

test('删会话：连带清掉消息与运行，之后再查 404', async () => {
  const { body: session } = await api.post(`${API}/sessions/create`, {
    agentId: 'api-delete',
    modelId: TEST_MODEL_ID,
  });
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: 'hi' });
  await api.waitTerminal(sent.body.run.id);

  const removed = await api.post(`${API}/sessions/delete`, { sessionId: session.id });
  assert.equal(removed.status, 200);

  assert.equal((await api.get(`${API}/sessions/detail?sessionId=${session.id}`)).status, 404);
  assert.equal(await prisma.message.count({ where: { sessionId: session.id } }), 0);
  assert.equal(await prisma.run.count({ where: { sessionId: session.id } }), 0);
});

test('参数与错误码：agentId 形态非法 400、缺 id 400、未知路由 404', async () => {
  assert.equal(
    (await api.post(`${API}/sessions/create`, { agentId: '../evil', modelId: TEST_MODEL_ID })).status,
    400,
  );
  assert.equal((await api.post(`${API}/sessions/create`, {})).status, 400);
  assert.equal((await api.get(`${API}/sessions/detail`)).status, 400);
  assert.equal((await api.get(`${API}/messages/list?sessionId=s&runId=r`)).status, 400);
  assert.equal((await api.post(`${API}/messages/send`, {})).status, 400);
  assert.equal((await api.get(`${API}/nope`)).status, 404);
});

test('REST messages/send：sessionId 分支带显式 null 的新建参数同样 400', async () => {
  const { body: session } = await api.post(`${API}/sessions/create`, { agentId: 'api-send-null', modelId: TEST_MODEL_ID });
  for (const extra of [{ modelId: null }, { mode: null }, { effort: null }]) {
    const res = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: 'hi', ...extra });
    assert.equal(res.status, 400, JSON.stringify(extra));
    assert.equal(res.body.error, 'BAD_REQUEST');
    assert.match(res.body.message, /不接受/);
  }
  assert.equal(await prisma.message.count({ where: { sessionId: session.id } }), 0);
  assert.equal(await prisma.run.count({ where: { sessionId: session.id } }), 0);
});

test('非 runtime 阶段：实例已有活跃 run 时再建会话返回 409；sessions/abort 可中止它', async () => {
  const first = await api.post(`${API}/sessions/create`, {
    agentId: 'api-instance-busy',
    modelId: TEST_MODEL_ID,
  });
  const sent = await api.post(`${API}/messages/send`, { sessionId: first.body.id, prompt: `${FAKE_TRIGGER.approval}` });
  assert.equal(sent.status, 200);

  const blocked = await api.post(`${API}/sessions/create`, {
    agentId: 'api-instance-busy',
    modelId: TEST_MODEL_ID,
  });
  assert.equal(blocked.status, 409);
  assert.equal(blocked.body.error, 'CONFLICT');

  const aborted = await api.post(`${API}/sessions/abort`, { sessionId: first.body.id });
  assert.equal(aborted.status, 200);
  assert.equal(aborted.body.status, 'aborted');

  assert.equal((await api.post(`${API}/sessions/abort`, { sessionId: first.body.id })).status, 409);

  const created = await api.post(`${API}/sessions/create`, {
    agentId: 'api-instance-busy',
    modelId: TEST_MODEL_ID,
  });
  assert.equal(created.status, 200);
});

test('列表接口：sessions/list 支持 agentId 过滤与分页', async () => {
  const list = await api.get(`${API}/sessions/list?agentId=api-flow&stage=development&page=1&pageSize=5`);
  assert.equal(list.status, 200);
  assert.equal(list.body.total, 1);
  assert.equal(list.body.items[0].instance.agentId, 'api-flow');
});

test('直接调用 store 造数据后，sessions/list 能内联 instance', async () => {
  const instance = await instancesRepo.getOrCreate('api-inline', 'development');
  await sessionsRepo.create({ instanceId: instance.id, name: '直连', modelId: TEST_MODEL_ID });

  const list = await api.get(`${API}/sessions/list?agentId=api-inline&stage=development`);
  assert.equal(list.body.items[0].instance.id, instance.id);
  assert.equal(list.body.items[0].name, '直连');
});

test('sessions/list 的 createdFrom / createdTo 只收 ISO 日期时间', async () => {
  for (const [name, value] of [
    ['createdFrom', '1'],
    ['createdFrom', '2026/10/20'],
    ['createdFrom', '2026-10-20'],
    ['createdTo', '2026-10-20T00:00:00'],
    ['createdTo', '2026-02-30T00:00:00Z'],
    ['createdFrom', '2026-10-20T24:00:00Z'],
  ] as const) {
    const invalid = await api.get(`${API}/sessions/list?${name}=${encodeURIComponent(value)}`);
    assert.equal(invalid.status, 400, `${name}=${value} 应 400`);
    assert.equal(invalid.body.message, `${name} 不是合法的日期时间`);
  }

  const valid = await api.get(
    `${API}/sessions/list?createdFrom=${encodeURIComponent('2026-01-01T00:00:00Z')}&createdTo=${encodeURIComponent(
      '2026-12-31T23:59:59.999+08:00',
    )}`,
  );
  assert.equal(valid.status, 200);
});

test('completed 会话再发消息即复活，seq 续增且 run 再次收口', async () => {
  const { body: session } = await api.post(`${API}/sessions/create`, {
    agentId: 'api-revive',
    modelId: TEST_MODEL_ID,
  });

  const first = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: '第一轮' });
  assert.equal(first.status, 200);
  assert.equal(first.body.message.seq, 1);
  assert.equal((await api.waitTerminal(first.body.run.id)).status, 'succeeded');
  assert.equal((await api.get(`${API}/sessions/detail?sessionId=${session.id}`)).body.status, 'completed');

  // 订阅 alive 事件：复活必须真的把会话置回 in_progress，而不只是响应里恒为 running
  const events: any[] = [];
  const subscriber = {
    send: (envelope: any): boolean => {
      events.push(envelope);
      return true;
    },
  };
  liveHub.subscribe(session.id, subscriber);
  let second: any;
  try {
    second = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: '第二轮' });
  } finally {
    liveHub.unsubscribe(session.id, subscriber);
  }
  assert.equal(second.status, 200);
  assert.equal(second.body.message.seq, 3);
  assert.ok(
    events.some(
      (event) => event.method === 'session.status' && event.payload.sessionId === session.id && event.payload.status === 'in_progress',
    ),
    'completed 会话再次发送必须广播 session.status=in_progress',
  );
  assert.equal((await api.waitTerminal(second.body.run.id)).status, 'succeeded');

  const messages = await api.get(`${API}/messages/list?sessionId=${session.id}`);
  assert.equal(messages.status, 200);
  assert.deepEqual(
    messages.body.items.map((m: any) => [m.seq, m.role]),
    [
      [1, 'user'],
      [2, 'assistant'],
      [3, 'user'],
      [4, 'assistant'],
    ],
  );
  assert.deepEqual(messages.body.items[3].content, { text: '收到：第二轮' });
  assert.equal((await api.get(`${API}/sessions/detail?sessionId=${session.id}`)).body.status, 'completed');
});

test('send { agentId }：每次新建 runtime 会话，首轮使用请求的 modelId / mode / effort', async () => {
  const runtimeRoot = agentRootIn(env.workspaceDir, 'api-runtime-send');
  mkdirSync(`${runtimeRoot}/development/output/agents/demo/v1`, { recursive: true });
  seedPipelineState(runtimeRoot, 'demo');

  const resolved: string[] = [];
  const sent = await sessionService.sendMessage({
    agentId: 'api-runtime-send',
    prompt: '你好',
    modelId: TEST_MODEL_ID,
    mode: 'read_only',
    effort: 'low',
    onSessionResolved: (sessionId) => resolved.push(sessionId),
  });

  assert.deepEqual(resolved, [sent.sessionId]);
  assert.equal(sent.runId, sent.run.id);
  assert.equal(sent.instanceId, sent.run.instanceId);
  assert.equal(sent.status, 'running');
  assert.equal(sent.run.status, 'running');
  assert.equal(sent.modelId, TEST_MODEL_ID);
  assert.equal(sent.modelName, 'test-sonnet');
  assert.equal(sent.effort, 'low');
  assert.equal(sent.modelFellBack, false);
  assert.equal('created' in sent, false, 'send 响应没有 created 字段');

  // 请求的三个字段都落在新会话上
  const session = await sessionsRepo.findById(sent.sessionId);
  assert.equal(session?.instanceId, sent.instanceId);
  assert.equal(session?.modelId, TEST_MODEL_ID);
  assert.equal(session?.approvalMode, 'read_only');
  assert.equal(session?.effort, 'low');
  assert.equal(session?.resumeSessionId, null);

  assert.equal((await api.waitTerminal(sent.runId)).status, 'succeeded');
  assert.equal(FakeAdapter.lastModel?.modelName, 'test-sonnet');
  assert.equal(FakeAdapter.lastMode, 'read_only');
  assert.equal(FakeAdapter.lastEffort, 'low');

  const instance = await instancesRepo.findById(sent.instanceId);
  assert.equal(instance?.agentId, 'api-runtime-send');
  assert.equal(instance?.stage, 'runtime');
});

test('send 只给未知 agentId：404，且不留实例或会话行', async () => {
  const agentId = 'agt_00000000-0000-4000-8000-000000000000';
  const instancesBefore = await prisma.instance.count();
  const sessionsBefore = await prisma.session.count();

  await assert.rejects(
    () => sessionService.sendMessage({ agentId, prompt: '你好', modelId: TEST_MODEL_ID }),
    (error: any) => error.status === 404 && error.message === `智能体 ${agentId} 不存在`,
  );

  assert.equal(await prisma.instance.count({ where: { agentId } }), 0);
  assert.equal(await prisma.instance.count(), instancesBefore);
  assert.equal(await prisma.session.count(), sessionsBefore);
});

test('send { agentId } 不复用：两次发送得到两条会话，各自保留自己的设置', async () => {
  const runtimeRoot = agentRootIn(env.workspaceDir, 'api-runtime-reuse');
  mkdirSync(`${runtimeRoot}/development/output/agents/demo/v1`, { recursive: true });
  seedPipelineState(runtimeRoot, 'demo');

  const first = await sessionService.sendMessage({
    agentId: 'api-runtime-reuse',
    prompt: '第一轮',
    modelId: TEST_MODEL_ID,
    mode: 'workspace_write',
    effort: 'high',
  });
  assert.equal((await api.waitTerminal(first.runId)).status, 'succeeded');
  assert.equal((await sessionsRepo.findById(first.sessionId))?.status, 'completed');

  // 第一条会话跑完后，用不同的模型与设置再发一次：必须新建会话
  const second = await sessionService.sendMessage({
    agentId: 'api-runtime-reuse',
    prompt: '第二轮',
    modelId: TEST_MODEL_ALT_ID,
    mode: 'read_only',
    effort: 'low',
  });

  assert.notEqual(second.sessionId, first.sessionId);
  assert.equal(second.instanceId, first.instanceId);
  assert.notEqual(second.runId, first.runId);
  assert.equal(await prisma.session.count({ where: { instanceId: first.instanceId } }), 2);

  const kept = await sessionsRepo.findById(first.sessionId);
  assert.equal(kept?.modelId, TEST_MODEL_ID);
  assert.equal(kept?.approvalMode, 'workspace_write');
  assert.equal(kept?.effort, 'high');

  const secondRow = await sessionsRepo.findById(second.sessionId);
  assert.equal(secondRow?.modelId, TEST_MODEL_ALT_ID);
  assert.equal(secondRow?.approvalMode, 'read_only');
  assert.equal(secondRow?.effort, 'low');
  assert.equal(secondRow?.resumeSessionId, null, '新会话不继承旧会话的引擎接续标识');
  assert.equal((await api.waitTerminal(second.runId)).status, 'succeeded');
});

test('手工建的 runtime 会话不参与 send { agentId }；缺 modelId 一律 400', async () => {
  const runtimeRoot = agentRootIn(env.workspaceDir, 'api-runtime-model');
  mkdirSync(`${runtimeRoot}/development/output/agents/demo/v1`, { recursive: true });
  seedPipelineState(runtimeRoot, 'demo');

  // REST 手工建的 runtime 会话不会被 send { agentId } 复用
  const manual = await api.post(`${API}/sessions/create`, {
    agentId: 'api-runtime-model',
    stage: 'runtime',
    modelId: TEST_MODEL_ID,
  });
  assert.equal(manual.status, 200);

  const first = await sessionService.sendMessage({
    agentId: 'api-runtime-model',
    prompt: '首轮',
    modelId: TEST_MODEL_ALT_ID,
  });
  assert.notEqual(first.sessionId, manual.body.id);
  assert.equal(first.modelId, TEST_MODEL_ALT_ID, '请求的模型在本轮生效');
  assert.equal(first.modelName, 'test-opus');
  assert.equal((await sessionsRepo.findById(first.sessionId))?.modelId, TEST_MODEL_ALT_ID);
  assert.equal((await api.waitTerminal(first.runId)).status, 'succeeded');

  const instance = await instancesRepo.getOrCreate('api-runtime-model', 'runtime');
  const sessionsBefore = await prisma.session.count({ where: { instanceId: instance.id } });
  const missing = await api.post(`${API}/messages/send`, { agentId: 'api-runtime-model', prompt: '第三轮' });
  assert.equal(missing.status, 400);
  assert.equal(missing.body.error, 'BAD_REQUEST');
  assert.equal(missing.body.message, 'modelId 必填');
  assert.equal(await prisma.session.count({ where: { instanceId: instance.id } }), sessionsBefore, '缺 modelId 不得建会话');
});

test('REST messages/send 透传 agentId / modelId / mode / effort', async () => {
  const sent = await api.post(`${API}/messages/send`, {
    agentId: 'api-runtime-send',
    modelId: TEST_MODEL_ALT_ID,
    mode: 'full_access',
    effort: 'xhigh',
    prompt: 'REST 透传',
  });
  assert.equal(sent.status, 200, JSON.stringify(sent.body));
  assert.equal(sent.body.modelId, TEST_MODEL_ALT_ID);
  assert.equal(sent.body.modelName, 'test-opus');
  assert.equal(sent.body.effort, 'xhigh');
  assert.equal(sent.body.modelFellBack, false);
  assert.equal('created' in sent.body, false);

  const row = await sessionsRepo.findById(sent.body.sessionId);
  assert.equal(row?.modelId, TEST_MODEL_ALT_ID);
  assert.equal(row?.approvalMode, 'full_access');
  assert.equal(row?.effort, 'xhigh');

  assert.equal((await api.waitTerminal(sent.body.run.id)).status, 'succeeded');
  assert.equal(FakeAdapter.lastModel?.modelName, 'test-opus');
  assert.equal(FakeAdapter.lastMode, 'full_access');
  assert.equal(FakeAdapter.lastEffort, 'xhigh');
});

test('并发首帧：同一 runtime 实例下两条都成功，各自新建会话与 run', async () => {
  const runtimeRoot = agentRootIn(env.workspaceDir, 'api-runtime-race');
  mkdirSync(`${runtimeRoot}/development/output/agents/demo/v1`, { recursive: true });
  seedPipelineState(runtimeRoot, 'demo');

  // 第一条停在审批上撑开活跃窗口，第二条普通 prompt 自行跑完：并发下两条都必须落成
  const [parked, normal] = await Promise.all([
    sessionService.sendMessage({
      agentId: 'api-runtime-race',
      prompt: FAKE_TRIGGER.approval,
      modelId: TEST_MODEL_ID,
    }),
    sessionService.sendMessage({ agentId: 'api-runtime-race', prompt: 'B', modelId: TEST_MODEL_ID }),
  ]);

  assert.notEqual(parked.sessionId, normal.sessionId, '并发首帧必须各建一条会话');
  assert.notEqual(parked.runId, normal.runId, '两条会话各自起一个 run');
  assert.equal(parked.instanceId, normal.instanceId, '同一 agent 的 runtime 会话共享实例');

  const instance = await instancesRepo.getOrCreate('api-runtime-race', 'runtime');
  assert.equal(await prisma.session.count({ where: { instanceId: instance.id } }), 2, '两条首帧的会话都不得被删除');

  const aborted = await api.post(`${API}/runs/abort`, { runId: parked.runId });
  assert.equal(aborted.status, 200);
  assert.equal((await api.waitTerminal(parked.runId)).status, 'aborted');
  assert.equal((await api.waitTerminal(normal.runId)).status, 'succeeded');
});

test('runtime 并发：实例已有活跃 run 时仍可建会话并发起 run，消息互不串联', async () => {
  const runtimeRoot = agentRootIn(env.workspaceDir, 'api-runtime-concurrent');
  mkdirSync(`${runtimeRoot}/development/output/agents/demo/v1`, { recursive: true });
  seedPipelineState(runtimeRoot, 'demo');
  const createRuntimeSession = () =>
    api.post(`${API}/sessions/create`, {
      agentId: 'api-runtime-concurrent',
      stage: 'runtime',
      modelId: TEST_MODEL_ID,
    });

  const a = await createRuntimeSession();
  assert.equal(a.status, 200);
  const aSent = await api.post(`${API}/messages/send`, { sessionId: a.body.id, prompt: FAKE_TRIGGER.approval });
  assert.equal(aSent.status, 200);
  await waitRunWaiting(aSent.body.run.id);

  // runtime 按 session 仲裁：实例上已有活跃 run 不再挡住新建会话
  const b = await createRuntimeSession();
  assert.equal(b.status, 200);
  assert.equal(b.body.instance.id, a.body.instance.id, '两条 runtime 会话挂在同一实例上');

  const bSent = await api.post(`${API}/messages/send`, { sessionId: b.body.id, prompt: 'B 的消息' });
  assert.equal(bSent.status, 200);
  assert.equal((await api.waitTerminal(bSent.body.run.id)).status, 'succeeded');
  assert.equal((await api.get(`${API}/runs/detail?runId=${aSent.body.run.id}`)).body.status, 'running');

  const aMessages = await api.get(`${API}/messages/list?sessionId=${a.body.id}`);
  assert.ok(
    aMessages.body.items.some((m: any) => m.role === 'assistant' && m.type === 'approval' && m.status === 'pending'),
    'A 应停在待审批消息上',
  );
  assert.ok(
    !aMessages.body.items.some((m: any) => m.content?.text === '收到：B 的消息'),
    'A 不得收到 B 的消息',
  );
  const bMessages = await api.get(`${API}/messages/list?sessionId=${b.body.id}`);
  assert.deepEqual(
    bMessages.body.items.map((m: any) => [m.seq, m.role, m.type]),
    [
      [1, 'user', 'text'],
      [2, 'assistant', 'text'],
    ],
  );
  assert.deepEqual(bMessages.body.items[1].content, { text: '收到：B 的消息' });

  const aborted = await api.post(`${API}/runs/abort`, { runId: aSent.body.run.id });
  assert.equal(aborted.status, 200);
  assert.equal((await api.waitTerminal(aSent.body.run.id)).status, 'aborted');
});

test('development 反向守卫：同智能体有活跃 runtime run 时再生成 409，结束后放行', async () => {
  const runtimeRoot = agentRootIn(env.workspaceDir, 'api-runtime-guard');
  mkdirSync(`${runtimeRoot}/development/output/agents/demo/v1`, { recursive: true });
  seedPipelineState(runtimeRoot, 'demo');

  const runtime = await sessionService.sendMessage({
    agentId: 'api-runtime-guard',
    prompt: FAKE_TRIGGER.approval,
    modelId: TEST_MODEL_ID,
  });
  await waitRunWaiting(runtime.runId);

  // 建 development 会话看的是 development 实例，不受 runtime 实例忙影响
  const created = await api.post(`${API}/sessions/create`, { agentId: 'api-runtime-guard', modelId: TEST_MODEL_ID });
  assert.equal(created.status, 200);
  assert.equal(created.body.instance.stage, 'development');

  const blocked = await api.post(`${API}/messages/send`, { sessionId: created.body.id, prompt: '重新生成' });
  assert.equal(blocked.status, 409);
  assert.equal(blocked.body.error, 'CONFLICT');
  assert.match(blocked.body.message, /正在运行/);
  assert.equal(await prisma.message.count({ where: { sessionId: created.body.id } }), 0, '被拒绝的发送不得落消息');
  assert.equal(await prisma.run.count({ where: { sessionId: created.body.id } }), 0, '被拒绝的发送不得落 run');

  const aborted = await api.post(`${API}/runs/abort`, { runId: runtime.runId });
  assert.equal(aborted.status, 200);
  assert.equal((await api.waitTerminal(runtime.runId)).status, 'aborted');

  const sent = await api.post(`${API}/messages/send`, { sessionId: created.body.id, prompt: '现在重新生成' });
  assert.equal(sent.status, 200);
  assert.equal((await api.waitTerminal(sent.body.run.id)).status, 'succeeded');
});

test('会话派生字段：messageCount 统计全部类型，lastMessage / firstUserMessage 取首尾 text', async () => {
  const { body: session } = await api.post(`${API}/sessions/create`, {
    agentId: 'api-derived',
    modelId: TEST_MODEL_ID,
  });
  await messagesRepo.append({ sessionId: session.id, role: 'user', type: 'text', content: { text: '首条用户' } });
  await messagesRepo.append({ sessionId: session.id, role: 'assistant', type: 'text', content: { text: '最早' } });
  await messagesRepo.append({ sessionId: session.id, role: 'assistant', type: 'approval', status: 'pending', content: { requestId: 'req_1' } });
  await messagesRepo.append({ sessionId: session.id, role: 'assistant', type: 'tool_interactive', status: 'pending', content: {} });
  await messagesRepo.append({ sessionId: session.id, role: 'assistant', type: 'text', content: { text: '最新' } });

  const listed = await api.get(`${API}/sessions/list?agentId=api-derived&stage=development`);
  const row = listed.body.items.find((item: any) => item.id === session.id);
  assert.equal(row.messageCount, 5, 'messageCount 计入审批与交互消息');
  assert.equal(row.lastMessage, '最新', 'lastMessage 取最新一条 text');
  assert.equal(row.firstUserMessage, '首条用户', 'firstUserMessage 取第一条 user text，不被后续消息顶掉');

  const { body: odd } = await api.post(`${API}/sessions/create`, {
    agentId: 'api-derived',
    modelId: TEST_MODEL_ID,
  });
  await messagesRepo.append({ sessionId: odd.id, role: 'user', type: 'text', content: { text: 42 } });
  await messagesRepo.append({ sessionId: odd.id, role: 'assistant', type: 'text', content: { text: 42 } });
  await messagesRepo.append({ sessionId: odd.id, role: 'assistant', type: 'approval', status: 'pending', content: {} });
  const listedOdd = await api.get(`${API}/sessions/list?agentId=api-derived&id=${odd.id}`);
  assert.equal(listedOdd.body.items[0].messageCount, 3);
  assert.equal(listedOdd.body.items[0].lastMessage, null, 'content.text 非字符串时 lastMessage 为 null');
  assert.equal(listedOdd.body.items[0].firstUserMessage, null, 'content.text 非字符串时 firstUserMessage 为 null');
});

test('删除仍有活跃 run 的会话返回 409，abort 后删除成功', async () => {
  const { body: session } = await api.post(`${API}/sessions/create`, {
    agentId: 'api-delete-busy',
    modelId: TEST_MODEL_ID,
  });
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: `${FAKE_TRIGGER.approval}` });
  assert.equal(sent.status, 200);

  let parked = false;
  for (let i = 0; i < 100 && !parked; i += 1) {
    const { body } = await api.get(`${API}/runs/detail?runId=${sent.body.run.id}`);
    parked = Boolean(body.waiting);
    if (!parked) await new Promise((resolve) => setTimeout(resolve, 50));
  }
  assert.ok(parked, 'run 应停在审批上等待应答');

  const blocked = await api.post(`${API}/sessions/delete`, { sessionId: session.id });
  assert.equal(blocked.status, 409);
  assert.equal(blocked.body.error, 'CONFLICT');
  assert.equal((await api.get(`${API}/sessions/detail?sessionId=${session.id}`)).status, 200);

  const aborted = await api.post(`${API}/runs/abort`, { runId: sent.body.run.id });
  assert.equal(aborted.status, 200);
  assert.equal(aborted.body.status, 'aborted');

  const removed = await api.post(`${API}/sessions/delete`, { sessionId: session.id });
  assert.equal(removed.status, 200);
  assert.equal((await api.get(`${API}/sessions/detail?sessionId=${session.id}`)).status, 404);
});

test('sessions/create：modelId 必填非空，带值原样落库并回显', async () => {
  const withModel = await api.post(`${API}/sessions/create`, { agentId: 'api-flow', modelId: TEST_MODEL_ALT_ID });
  assert.equal(withModel.status, 200, JSON.stringify(withModel.body));
  assert.equal(withModel.body.modelId, TEST_MODEL_ALT_ID);
  assert.equal(withModel.body.messageCount, 0);
  assert.equal(withModel.body.lastMessage, null);

  for (const body of [
    { agentId: 'api-flow' },
    { agentId: 'api-flow', modelId: '' },
    { agentId: 'api-flow', modelId: null },
  ]) {
    const res = await api.post(`${API}/sessions/create`, body);
    assert.equal(res.status, 400, JSON.stringify(body));
    assert.equal(res.body.error, 'BAD_REQUEST');
    assert.equal(res.body.message, 'modelId 必填');
  }
});

test('sessions/:id/update：切换模型；空串/缺失 modelId 400、不支持清空、未知会话 404', async () => {
  const { body: session } = await api.post(`${API}/sessions/create`, { agentId: 'api-flow', modelId: TEST_MODEL_ID });

  const switched = await api.post(`${API}/sessions/${session.id}/update`, { modelId: TEST_MODEL_ALT_ID });
  assert.equal(switched.status, 200);
  assert.equal(switched.body.modelId, TEST_MODEL_ALT_ID);
  assert.equal(switched.body.lastMessage, null);

  for (const body of [{ modelId: '' }, { modelId: null }, {}]) {
    const res = await api.post(`${API}/sessions/${session.id}/update`, body);
    assert.equal(res.status, 400, JSON.stringify(body));
    assert.equal(res.body.error, 'BAD_REQUEST');
  }

  const unknown = await api.post(`${API}/sessions/sess_never_existed/update`, { modelId: TEST_MODEL_ALT_ID });
  assert.equal(unknown.status, 404);

  const stored = await sessionsRepo.findById(session.id);
  assert.equal(stored?.modelId, TEST_MODEL_ALT_ID, '空补丁不得清空模型');
});

test('活跃 run 期间切换 409；run 结束后切换生效到下个 run', async () => {
  const { FakeAdapter } = await import('../src/shared/engine/fake-adapter.js');
  const { body: session } = await api.post(`${API}/sessions/create`, { agentId: 'api-flow', modelId: TEST_MODEL_ID });

  // 起一个停在审批上的 run，撑开活跃窗口
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: FAKE_TRIGGER.approval });
  assert.equal(sent.status, 200);
  let parked = false;
  for (let i = 0; i < 100 && !parked; i += 1) {
    const { body } = await api.get(`${API}/runs/detail?runId=${sent.body.run.id}`);
    parked = Boolean(body.waiting);
    if (!parked) await new Promise((resolve) => setTimeout(resolve, 50));
  }
  assert.ok(parked, 'run 应停在审批上等待应答');

  // 起跑时就把会话模型解析成运行配置下发给引擎
  assert.equal(FakeAdapter.lastModel?.modelName, 'test-sonnet');
  assert.equal(FakeAdapter.lastModel?.baseUrl, TEST_MODEL_BASE_URL);

  const busy = await api.post(`${API}/sessions/${session.id}/update`, { modelId: TEST_MODEL_ALT_ID });
  assert.equal(busy.status, 409);
  assert.equal(busy.body.error, 'CONFLICT');

  const aborted = await api.post(`${API}/runs/abort`, { runId: sent.body.run.id });
  assert.equal(aborted.status, 200);
  await api.waitTerminal(sent.body.run.id);

  const switched = await api.post(`${API}/sessions/${session.id}/update`, { modelId: TEST_MODEL_ALT_ID });
  assert.equal(switched.status, 200);

  const again = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: '第二次' });
  assert.equal(again.status, 200);
  await api.waitTerminal(again.body.run.id);
  assert.equal(FakeAdapter.lastModel?.modelName, 'test-opus');
  assert.equal(FakeAdapter.lastModel?.baseUrl, null);
});

test('switchModel / switchMode / switchEffort：活跃 run 存续时也立即改会话字段', async () => {
  const { body: session } = await api.post(`${API}/sessions/create`, {
    agentId: 'api-switch',
    modelId: TEST_MODEL_ID,
  });

  // 起一个停在审批上的 run，撑开活跃窗口
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: FAKE_TRIGGER.approval });
  assert.equal(sent.status, 200);
  let parked = false;
  for (let i = 0; i < 100 && !parked; i += 1) {
    const { body } = await api.get(`${API}/runs/detail?runId=${sent.body.run.id}`);
    parked = Boolean(body.waiting);
    if (!parked) await new Promise((resolve) => setTimeout(resolve, 50));
  }
  assert.ok(parked, 'run 应停在审批上等待应答');

  const modelSwitched = await sessionService.switchModel({ sessionId: session.id, modelId: TEST_MODEL_ID });
  assert.equal(modelSwitched.modelId, TEST_MODEL_ID);
  assert.equal(modelSwitched.instance.id, session.instance.id);

  const modeSwitched = await sessionService.switchMode({ sessionId: session.id, mode: 'full_access' });
  assert.equal(modeSwitched.approvalMode, 'full_access');

  const effortSwitched = await sessionService.switchEffort({ sessionId: session.id, effort: 'max' });
  assert.equal(effortSwitched.effort, 'max');

  const stored = await sessionsRepo.findById(session.id);
  assert.equal(stored?.modelId, TEST_MODEL_ID);
  assert.equal(stored?.approvalMode, 'full_access');
  assert.equal(stored?.effort, 'max');

  const aborted = await api.post(`${API}/runs/abort`, { runId: sent.body.run.id });
  assert.equal(aborted.status, 200);

  // 入参校验：模式 / 强度枚举、modelId 缺失、未知会话
  await assert.rejects(() => sessionService.switchMode({ sessionId: session.id, mode: 'root' }), (error: any) => error.status === 400);
  await assert.rejects(() => sessionService.switchEffort({ sessionId: session.id, effort: 'ultra' }), (error: any) => error.status === 400);
  await assert.rejects(() => sessionService.switchModel({ sessionId: session.id }), (error: any) => error.status === 400);
  await assert.rejects(
    () => sessionService.switchModel({ sessionId: session.id, modelId: '' }),
    (error: any) => error.status === 400,
  );
  await assert.rejects(
    () => sessionService.switchModel({ sessionId: 'sess_never_existed', modelId: TEST_MODEL_ID }),
    (error: any) => error.status === 404,
  );
});

test('resume：带会话触发 onSessionId 落库，下一轮把 resumeSessionId 下发给引擎', async (t) => {
  const { FakeAdapter } = await import('../src/shared/engine/fake-adapter.js');
  const resumeTrigger = (FAKE_TRIGGER as unknown as Record<string, string | undefined>).session;
  if (!resumeTrigger) {
    t.skip('依赖引擎侧的 FAKE_TRIGGER.session');
    return;
  }
  const adapter = FakeAdapter as unknown as { lastResumeSessionId?: string | null };

  const { body: session } = await api.post(`${API}/sessions/create`, {
    agentId: 'api-resume',
    modelId: TEST_MODEL_ID,
  });
  const first = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: resumeTrigger });
  assert.equal(first.status, 200);
  assert.equal((await api.waitTerminal(first.body.run.id)).status, 'succeeded');

  const stored = await sessionsRepo.findById(session.id);
  assert.ok(stored?.resumeSessionId, '首轮应把引擎给的 resume id 落库');

  const second = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: '第二轮' });
  assert.equal(second.status, 200);
  assert.equal((await api.waitTerminal(second.body.run.id)).status, 'succeeded');
  assert.equal(adapter.lastResumeSessionId, stored?.resumeSessionId);
});

/** 轮询会话名：补名发生在 run 终态之后，waitTerminal 返回时可能还没写完。 */
async function waitSessionName(sessionId: string, expected: string): Promise<string> {
  for (let i = 0; i < 100; i += 1) {
    const row = await sessionsRepo.findById(sessionId);
    if (row?.name === expected) return row.name;
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  return (await sessionsRepo.findById(sessionId))?.name ?? '';
}

test('空名会话在 run 收口后补上引擎标题，已有名字不被覆盖', async (t) => {
  const resumeTrigger = (FAKE_TRIGGER as unknown as Record<string, string | undefined>).session;
  if (!resumeTrigger) {
    t.skip('依赖引擎侧的 FAKE_TRIGGER.session');
    return;
  }

  const { body: unnamed } = await api.post(`${API}/sessions/create`, {
    agentId: 'api-named-by-engine',
    modelId: TEST_MODEL_ID,
  });
  assert.equal(unnamed.name, '');
  const unnamedRun = await api.post(`${API}/messages/send`, { sessionId: unnamed.id, prompt: resumeTrigger });
  assert.equal(unnamedRun.status, 200);
  assert.equal((await api.waitTerminal(unnamedRun.body.run.id)).status, 'succeeded');
  assert.equal(await waitSessionName(unnamed.id, '桩会话标题'), '桩会话标题');

  const { body: kept } = await api.post(`${API}/sessions/create`, {
    agentId: 'api-named-by-engine',
    modelId: TEST_MODEL_ID,
    name: '已有名字',
  });
  const keptRun = await api.post(`${API}/messages/send`, { sessionId: kept.id, prompt: resumeTrigger });
  assert.equal(keptRun.status, 200);
  assert.equal((await api.waitTerminal(keptRun.body.run.id)).status, 'succeeded');
  assert.equal((await sessionsRepo.findById(kept.id))?.name, '已有名字', '用户/调用方给的名字不被引擎标题覆盖');
});

test('sessions/list 支持按 resumeSessionId 反查，支持逗号分隔多值', async () => {
  const first = await api.post(`${API}/sessions/create`, {
    agentId: 'api-resume-lookup',
    modelId: TEST_MODEL_ID,
  });
  const second = await api.post(`${API}/sessions/create`, {
    agentId: 'api-resume-lookup',
    modelId: TEST_MODEL_ALT_ID,
  });
  assert.equal(first.status, 200);
  assert.equal(second.status, 200);

  await sessionsRepo.update(first.body.id, { resumeSessionId: 'sdk-lookup-a' });
  await sessionsRepo.update(second.body.id, { resumeSessionId: 'sdk-lookup-b' });

  const one = await api.get(`${API}/sessions/list?resumeSessionId=sdk-lookup-a`);
  assert.equal(one.status, 200);
  assert.equal(one.body.total, 1);
  assert.equal(one.body.items[0].id, first.body.id);
  assert.equal(one.body.items[0].resumeSessionId, 'sdk-lookup-a');

  const many = await api.get(`${API}/sessions/list?resumeSessionId=sdk-lookup-a,sdk-lookup-b`);
  assert.equal(many.status, 200);
  assert.equal(many.body.total, 2);
  assert.deepEqual(
    new Set(many.body.items.map((session: any) => session.id)),
    new Set([first.body.id, second.body.id]),
  );

  const missing = await api.get(`${API}/sessions/list?resumeSessionId=sdk-lookup-missing`);
  assert.equal(missing.status, 200);
  assert.equal(missing.body.total, 0);

  const detail = await api.get(`${API}/sessions/detail?sessionId=${first.body.id}`);
  assert.equal(detail.status, 200);
  assert.equal(detail.body.resumeSessionId, 'sdk-lookup-a');
});

test('sessions/create、update、switchModel：modelId 非字符串 / 空串 / 缺失一律 400', async () => {
  for (const modelId of [123, { id: TEST_MODEL_ID }]) {
    const created = await api.post(`${API}/sessions/create`, { agentId: 'api-validate', modelId });
    assert.equal(created.status, 400, JSON.stringify(modelId));
    assert.equal(created.body.error, 'BAD_REQUEST');
    assert.match(created.body.message, /modelId/);
  }

  const { body: session } = await api.post(`${API}/sessions/create`, {
    agentId: 'api-validate',
    modelId: TEST_MODEL_ID,
  });
  for (const modelId of ['', 123, { id: TEST_MODEL_ID }]) {
    const updated = await api.post(`${API}/sessions/${session.id}/update`, { modelId });
    assert.equal(updated.status, 400, JSON.stringify(modelId));
    assert.equal(updated.body.error, 'BAD_REQUEST');
    assert.match(updated.body.message, /modelId/);
  }

  await assert.rejects(
    () => sessionService.switchModel({ sessionId: session.id, modelId: '' }),
    (error: any) => error.status === 400,
  );
});

test('旧前缀已摘除：GET /api/health 返回 404', async () => {
  const { status, body } = await api.get('/api/health');
  assert.equal(status, 404);
  assert.equal(body.error, 'NOT_FOUND');
});

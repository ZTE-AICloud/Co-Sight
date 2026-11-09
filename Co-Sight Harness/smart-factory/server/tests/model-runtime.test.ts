/**
 * 会话模型运行时解析：起 run 时把会话 modelId 解析成框架详情里的
 * modelName / baseUrl / apiKey，经 EngineContext.model 下发给引擎。
 *
 * 会话必须显式绑定模型：没有 modelId、模型不存在、协议不符或没有密钥都直接 400，
 * 不回落工作区默认模型、框架生效模型或本机配置。
 */
import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { prepareTestEnv } from './helpers/test-db.js';
import {
  agentRootIn,
  seedAgent,
  seedAgents,
  seedDevelopmentDir,
  seedPipelineState,
  TEST_WORKSPACE_DEFAULT_ID,
} from './helpers/agents.js';
import {
  startWorkspaceStub,
  TEST_MODEL_ALT_ID,
  TEST_MODEL_ALT_KEY,
  TEST_MODEL_BASE_URL,
  TEST_MODEL_ID,
  TEST_MODEL_KEY,
  TEST_MODEL_NO_KEY_ID,
  TEST_MODEL_OPENAI_ID,
} from './helpers/workspace-stub.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

const env = prepareTestEnv('model-runtime');
const stub = await startWorkspaceStub(env);

const { FakeAdapter } = await import('../src/shared/engine/fake-adapter.js');
const { prisma } = await import('../src/shared/prisma/client.js');
const { instancesRepo } = await import('../src/shared/store/instances.repo.js');
const { sessionsRepo } = await import('../src/shared/store/sessions.repo.js');
const { sessionService } = await import('../src/modules/session/session.service.js');

/** 框架里不存在的模型 id；stub 的详情端点对它回 404。 */
const UNKNOWN_MODEL_ID = '00000000-0000-4000-8000-000000000000';

/** preview / runtime 起 run 需要 development 下恰好一个 agentName 的最新 vN 产物。 */
function seedProducedAgent(agentId: string): void {
  const agentRoot = agentRootIn(env.workspaceDir, agentId);
  const dir = join(agentRoot, 'development', 'output', 'agents', 'demo', 'v1');
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, 'artifact.txt'), 'v1');
  seedPipelineState(agentRoot, 'demo');
}

const AGENT_IDS = [
  'runtime-dev',
  'runtime-first',
  'runtime-preview',
  'runtime-runtime',
  'runtime-leak',
  'runtime-unknown',
  'runtime-openai',
  'runtime-no-key',
] as const;

/** 工作区默认模型存在但会话为空时也不得回落。 */
const WORKSPACE_DEFAULT_AGENT = 'runtime-workspace-default';

let api: TestApi;

before(async () => {
  await seedAgents(...AGENT_IDS);
  await seedAgent(WORKSPACE_DEFAULT_AGENT, '工作区默认模型', TEST_WORKSPACE_DEFAULT_ID);
  for (const agentId of [...AGENT_IDS, WORKSPACE_DEFAULT_AGENT]) {
    seedDevelopmentDir(env.workspaceDir, agentId);
  }
  seedProducedAgent('runtime-first');
  seedProducedAgent('runtime-preview');
  seedProducedAgent('runtime-runtime');
  api = await startTestApi();
});

after(async () => {
  await api.close();
  await stub.close();
  await prisma.$disconnect();
});

/** 建会话 → 发一条消息 → 等 run 落终态。 */
async function runOnce(input: { agentId: string; modelId: string; stage?: string }): Promise<{
  session: any;
  run: any;
}> {
  const created = await api.post(`${API}/sessions/create`, {
    agentId: input.agentId,
    modelId: input.modelId,
    ...(input.stage === undefined ? {} : { stage: input.stage }),
  });
  assert.equal(created.status, 200, JSON.stringify(created.body));

  const sent = await api.post(`${API}/messages/send`, { sessionId: created.body.id, prompt: '你好' });
  assert.equal(sent.status, 200, JSON.stringify(sent.body));
  return { session: created.body, run: await api.waitTerminal(sent.body.run.id) };
}

/** 直接造一条会话行：modelId 由调用方给定，可指向不存在或不可用的模型。 */
async function seedSession(
  agentId: string,
  modelId: string,
  stage: 'development' | 'runtime' = 'development',
): Promise<{ id: string; instanceId: string }> {
  const instance = await instancesRepo.getOrCreate(agentId, stage);
  return sessionsRepo.create({ instanceId: instance.id, modelId });
}

/** 解析失败不得留下 run。 */
async function assertNoRun(sessionId: string): Promise<void> {
  const runs = await api.get(`${API}/runs/list?sessionId=${sessionId}`);
  assert.equal(runs.body.total, 0, JSON.stringify(runs.body));
}

test('development：modelId 解析成 modelName / baseUrl / apiKey 下发给引擎', async () => {
  const { session, run } = await runOnce({ agentId: 'runtime-dev', modelId: TEST_MODEL_ID });

  assert.equal(run.status, 'succeeded');
  assert.equal(session.modelId, TEST_MODEL_ID);
  assert.deepEqual(FakeAdapter.lastModel, {
    modelName: 'test-sonnet',
    baseUrl: TEST_MODEL_BASE_URL,
    apiKey: TEST_MODEL_KEY,
  });
});

test('切换模型：下一次 run 用新的 modelName，baseUrl 为 null', async () => {
  const created = await api.post(`${API}/sessions/create`, { agentId: 'runtime-dev', modelId: TEST_MODEL_ID });
  assert.equal(created.status, 200);
  const session = created.body;

  const first = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: '第一次' });
  assert.equal(first.status, 200);
  assert.equal((await api.waitTerminal(first.body.run.id)).status, 'succeeded');
  assert.equal(FakeAdapter.lastModel?.modelName, 'test-sonnet');

  const switched = await api.post(`${API}/sessions/${session.id}/update`, { modelId: TEST_MODEL_ALT_ID });
  assert.equal(switched.status, 200);
  assert.equal(switched.body.modelId, TEST_MODEL_ALT_ID);

  const second = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: '第二次' });
  assert.equal(second.status, 200);
  assert.equal((await api.waitTerminal(second.body.run.id)).status, 'succeeded');
  assert.deepEqual(FakeAdapter.lastModel, {
    modelName: 'test-opus',
    baseUrl: null,
    apiKey: TEST_MODEL_ALT_KEY,
  });
});

test('preview 与 runtime 两个 stage 起 run 时同样解析并下发模型', async () => {
  for (const [agentId, stage] of [
    ['runtime-preview', 'preview'],
    ['runtime-runtime', 'runtime'],
  ] as const) {
    const { run } = await runOnce({ agentId, modelId: TEST_MODEL_ID, stage });
    assert.equal(run.status, 'succeeded', `${stage} 应能起跑`);
    assert.deepEqual(FakeAdapter.lastModel, {
      modelName: 'test-sonnet',
      baseUrl: TEST_MODEL_BASE_URL,
      apiKey: TEST_MODEL_KEY,
    });
  }
});

test('send { agentId }：新会话落请求的 modelId / mode / effort，首轮 run 使用它们', async () => {
  const resolved: string[] = [];
  const sent = await sessionService.sendMessage({
    agentId: 'runtime-first',
    prompt: '你好',
    modelId: TEST_MODEL_ALT_ID,
    mode: 'full_access',
    effort: 'max',
    onSessionResolved: (sessionId) => resolved.push(sessionId),
  });

  assert.deepEqual(resolved, [sent.sessionId], 'onSessionResolved 在建 run 后回调一次');
  assert.equal(sent.modelId, TEST_MODEL_ALT_ID);
  assert.equal(sent.modelName, 'test-opus');
  assert.equal(sent.effort, 'max');
  assert.equal(sent.modelFellBack, false);
  assert.equal('created' in sent, false, 'send 响应没有 created 字段');

  const row = await sessionsRepo.findById(sent.sessionId);
  assert.equal(row?.modelId, TEST_MODEL_ALT_ID);
  assert.equal(row?.approvalMode, 'full_access');
  assert.equal(row?.effort, 'max');
  assert.equal(row?.resumeSessionId, null, '新会话没有引擎接续标识');

  assert.equal((await api.waitTerminal(sent.runId)).status, 'succeeded');
  assert.equal(FakeAdapter.lastMode, 'full_access');
  assert.equal(FakeAdapter.lastEffort, 'max');
  assert.deepEqual(FakeAdapter.lastModel, {
    modelName: 'test-opus',
    baseUrl: null,
    apiKey: TEST_MODEL_ALT_KEY,
  });
});

test('无 modelId：sessions/create 400；空模型会话 send 400，不回落工作区默认或框架 active', async () => {
  // 该智能体所在工作区默认模型是 TEST_MODEL_ALT_ID，框架 active 是 TEST_MODEL_ID，两者都不得被使用
  const created = await api.post(`${API}/sessions/create`, { agentId: WORKSPACE_DEFAULT_AGENT });
  assert.equal(created.status, 400, JSON.stringify(created.body));
  assert.equal(created.body.error, 'BAD_REQUEST');
  assert.equal(created.body.message, 'modelId 必填');

  const session = await seedSession(WORKSPACE_DEFAULT_AGENT, '');
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: '你好' });
  assert.equal(sent.status, 400, JSON.stringify(sent.body));
  assert.equal(sent.body.error, 'BAD_REQUEST');
  assert.match(sent.body.message, /模型/);
  await assertNoRun(session.id);
});

test('未知 modelId：send 返回 400，不创建 run', async () => {
  const session = await seedSession('runtime-unknown', UNKNOWN_MODEL_ID);
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: '你好' });

  assert.equal(sent.status, 400, JSON.stringify(sent.body));
  assert.equal(sent.body.error, 'BAD_REQUEST');
  assert.equal(sent.body.messageKey, 'error.bad_request.session_model_missing');
  assert.match(sent.body.message, /已被删除/);
  assert.doesNotMatch(sent.body.message, new RegExp(UNKNOWN_MODEL_ID), '模型 id 不得出现在给人看的文案里');
  await assertNoRun(session.id);
});

test('openai 协议模型：send 返回 400，不创建 run', async () => {
  const session = await seedSession('runtime-openai', TEST_MODEL_OPENAI_ID);
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: '你好' });

  assert.equal(sent.status, 400, JSON.stringify(sent.body));
  assert.equal(sent.body.error, 'BAD_REQUEST');
  assert.match(sent.body.message, /协议/);
  assert.match(sent.body.message, /(openai|anthropic)/i);
  await assertNoRun(session.id);
});

test('无密钥模型：send 返回 400，不创建 run', async () => {
  const session = await seedSession('runtime-no-key', TEST_MODEL_NO_KEY_ID);
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: '你好' });

  assert.equal(sent.status, 400, JSON.stringify(sent.body));
  assert.equal(sent.body.error, 'BAD_REQUEST');
  assert.match(sent.body.message, /(密钥|API ?Key)/i);
  await assertNoRun(session.id);
});

test('成功 run 后 run / 消息 / 会话 / 智能体详情序列化后都不含模型密钥', async () => {
  const { session, run } = await runOnce({ agentId: 'runtime-leak', modelId: TEST_MODEL_ID });
  assert.equal(run.status, 'succeeded');

  const responses = [
    await api.get(`${API}/runs/detail?runId=${run.id}`),
    await api.get(`${API}/messages/list?sessionId=${session.id}`),
    await api.get(`${API}/sessions/detail?sessionId=${session.id}`),
    await api.get(`${API}/agents/runtime-leak`),
  ];

  for (const response of responses) {
    assert.equal(response.status, 200);
    const serialized = JSON.stringify(response.body);
    for (const secret of [TEST_MODEL_KEY, TEST_MODEL_ALT_KEY]) {
      assert.equal(serialized.includes(secret), false, `响应不得包含模型密钥 ${secret}`);
    }
  }
});

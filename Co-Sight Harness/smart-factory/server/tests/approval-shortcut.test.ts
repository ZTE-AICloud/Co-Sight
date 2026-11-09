import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { prepareTestEnv } from './helpers/test-db.js';
import { seedAgent, seedDevelopmentDir } from './helpers/agents.js';
import { startWorkspaceStub, TEST_MODEL_ID } from './helpers/workspace-stub.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

const env = prepareTestEnv('approval-shortcut');
const stub = await startWorkspaceStub(env);

const { prisma } = await import('../src/shared/prisma/client.js');
const { FAKE_TRIGGER } = await import('../src/shared/engine/fake-adapter.js');

let api: TestApi;

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

/** 轮询挂起消息（与 approval.test.ts 同一手法） */
async function waitPending(sessionId: string, timeoutMs = 5000): Promise<any> {
  for (let waited = 0; waited < timeoutMs; waited += 50) {
    const { body } = await api.get(`${API}/messages/list?sessionId=${sessionId}&status=pending`);
    if (body.items.length > 0) return body.items[0];
    await sleep(50);
  }
  throw new Error('未等到挂起消息');
}

async function newSession(agentId: string): Promise<any> {
  return (await api.post(`${API}/sessions/create`, { agentId, modelId: TEST_MODEL_ID })).body;
}

before(async () => {
  await seedAgent('ap-shortcut');
  await seedAgent('ap-shortcut-next');
  seedDevelopmentDir(env.workspaceDir, 'ap-shortcut');
  seedDevelopmentDir(env.workspaceDir, 'ap-shortcut-next');
  api = await startTestApi();
});

after(async () => {
  await api.close();
  await stub.close();
  await prisma.$disconnect();
});

test('同一 run 连续两次审批：respond approved_all 后第二次不挂起，落 approved_all_auto 审计', async () => {
  const session = await newSession('ap-shortcut');
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: `${FAKE_TRIGGER.approvalTwice}：执行两次 echo hi` });

  const first = await waitPending(session.id);
  assert.equal(first.type, 'approval');
  assert.equal(first.runId, sent.body.run.id);

  const responded = await api.post(`${API}/messages/respond`, { messageId: first.id, decision: 'approved_all' });
  assert.equal(responded.status, 200);
  assert.equal(responded.body.status, 'approved_all');
  const detail = await api.get(`${API}/sessions/detail?sessionId=${session.id}`);
  assert.equal(detail.body.approvalMode, 'full_access');
  assert.equal(detail.body.approvedAll, true);

  // 第二次审批不再挂起：无人应答也能收口
  const run = await api.waitTerminal(sent.body.run.id);
  assert.equal(run.status, 'succeeded');
  assert.equal(run.waiting, null);
  assert.equal((await api.get(`${API}/messages/list?sessionId=${session.id}&status=pending`)).body.items.length, 0);

  // 第二次审批留了一条 approved_all_auto 审计消息，不落 pending
  const audit = await api.get(`${API}/messages/list?sessionId=${session.id}&status=approved_all`);
  const auto = audit.body.items.filter((m: any) => m.content.decisionSource === 'approved_all_auto');
  assert.equal(auto.length, 1);
  assert.equal(auto[0].type, 'approval');
  assert.equal(auto[0].runId, sent.body.run.id);
  assert.equal(auto[0].content.decision, 'approved_all');

  // 引擎两次都拿到了放行决策
  const replies = (await api.get(`${API}/messages/list?sessionId=${session.id}`)).body.items.filter(
    (m: any) => m.content.text === '审批结果：approved_all',
  );
  assert.equal(replies.length, 2, '两次审批请求都应放行');
});

test('新 run 继承 approved_all：会话开关在 run 结束后仍生效', async () => {
  const session = await newSession('ap-shortcut-next');
  const first = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: `${FAKE_TRIGGER.approvalTwice}：执行两次 echo hi` });

  const pending = await waitPending(session.id);
  await api.post(`${API}/messages/respond`, { messageId: pending.id, decision: 'approved_all' });
  assert.equal((await api.waitTerminal(first.body.run.id)).status, 'succeeded');

  const detail = await api.get(`${API}/sessions/detail?sessionId=${session.id}`);
  assert.equal(detail.body.approvalMode, 'full_access');
  assert.equal(detail.body.approvedAll, true);

  // 新 run 不挂起：直接自动放行并收口
  const second = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: `${FAKE_TRIGGER.approval}：再执行一次 echo hi` });
  assert.equal(second.status, 200);
  assert.equal((await api.waitTerminal(second.body.run.id)).status, 'succeeded');
  assert.equal((await api.get(`${API}/messages/list?sessionId=${session.id}&status=pending`)).body.items.length, 0);

  const audit = await api.get(`${API}/messages/list?sessionId=${session.id}&status=approved_all`);
  const auto = audit.body.items.filter((m: any) => m.content.decisionSource === 'approved_all_auto');
  assert.ok(auto.some((m: any) => m.runId === second.body.run.id), '新 run 的审批应落 approved_all_auto 审计');
});

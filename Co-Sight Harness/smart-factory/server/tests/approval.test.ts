import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { WebSocket } from 'ws';
import { prepareTestEnv } from './helpers/test-db.js';
import { seedAgent, seedDevelopmentDir } from './helpers/agents.js';
import { startWorkspaceStub, TEST_MODEL_ID } from './helpers/workspace-stub.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

const env = prepareTestEnv('approval');
const stub = await startWorkspaceStub(env);

const { prisma } = await import('../src/shared/prisma/client.js');
const { messagesRepo } = await import('../src/shared/store/messages.repo.js');
const { attachWsGateway } = await import('../src/shared/live/ws-gateway.js');
const { sessionService } = await import('../src/modules/session/session.service.js');
const { config } = await import('../src/config/index.js');
const { FAKE_TRIGGER } = await import('../src/shared/engine/fake-adapter.js');

let api: TestApi;
let gateway: { close(): void };
let wsUrl = '';

let callSequence = 0;

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

async function newSession(agentId: string): Promise<any> {
  // 会话挂在智能体上：agents 表是存在的唯一权威，先建行再建会话
  await seedAgent(agentId);
  seedDevelopmentDir(env.workspaceDir, agentId);
  return (await api.post(`${API}/sessions/create`, { agentId, modelId: TEST_MODEL_ID })).body;
}

/** 轮询挂起消息（刷新后恢复弹窗走的就是这个接口） */
async function waitPending(sessionId: string, timeoutMs = 5000): Promise<any> {
  for (let waited = 0; waited < timeoutMs; waited += 50) {
    const { body } = await api.get(`${API}/messages/list?sessionId=${sessionId}&status=pending`);
    if (body.items.length > 0) return body.items[0];
    await sleep(50);
  }
  throw new Error('未等到挂起消息');
}

/** 建一条 WS 连接：事件按到达顺序入 `events`，`request` 按 id 关联响应；`onEvent` 在事件到达当轮同步回调。 */
async function connectWs(
  onEvent?: (envelope: any) => void,
): Promise<{ ws: WebSocket; events: any[]; request: (method: string, payload?: unknown) => Promise<any> }> {
  const ws = new WebSocket(wsUrl);
  const events: any[] = [];
  const responses = new Map<string, (envelope: any) => void>();

  ws.on('message', (raw) => {
    const envelope = JSON.parse(raw.toString());
    if (envelope.type !== 'event') {
      responses.get(envelope.id)?.(envelope);
      responses.delete(envelope.id);
      return;
    }
    events.push(envelope);
    onEvent?.(envelope);
  });
  await new Promise<void>((resolve) => ws.on('open', () => resolve()));

  function request(method: string, payload?: unknown): Promise<any> {
    callSequence += 1;
    const id = `wsreq_${callSequence}`;
    const answer = new Promise((resolve) => responses.set(id, resolve));
    ws.send(JSON.stringify({ id, type: 'request', method, timestamp: Date.now(), payload }));
    return answer;
  }

  return { ws, events, request };
}

before(async () => {
  api = await startTestApi();
  gateway = attachWsGateway(api.server, {
    send: (input) => sessionService.sendMessage(input),
    abortRun: (input) => sessionService.abortRun(input.runId),
    respond: (input) => sessionService.respondMessage(input),
    subscribeInfo: (sessionId) => sessionService.subscribeInfo(sessionId),
  });
  wsUrl = `${api.base.replace(/^http/, 'ws')}${config.wsPath}`;
});

after(async () => {
  gateway.close();
  await api.close();
  await stub.close();
  await prisma.$disconnect();
});

test('审批挂起 → REST 应答 approved → 引擎放行、run 收口', async () => {
  const session = await newSession('ap-approve');
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: `${FAKE_TRIGGER.approval}：执行 echo hi` });

  const pending = await waitPending(session.id);
  assert.equal(pending.type, 'approval');
  assert.equal(pending.status, 'pending');
  assert.equal(pending.content.title, '执行 Bash：echo hi');
  assert.equal(pending.runId, sent.body.run.id);

  const hanging = await api.get(`${API}/runs/detail?runId=${sent.body.run.id}`);
  assert.equal(hanging.body.waiting.count, 1);
  assert.equal(hanging.body.status, 'running');

  const responded = await api.post(`${API}/messages/respond`, { messageId: pending.id, decision: 'approved' });
  assert.equal(responded.status, 200);
  assert.equal(responded.body.status, 'approved');
  assert.equal(responded.body.content.decision, 'approved');
  assert.equal(responded.body.content.decisionSource, 'user');

  const run = await api.waitTerminal(sent.body.run.id);
  assert.equal(run.status, 'succeeded');
  assert.equal(run.waiting, null);

  const messages = await api.get(`${API}/messages/list?sessionId=${session.id}`);
  assert.ok(messages.body.items.some((m: any) => m.content.text === '审批结果：approved'));
});

test('重复应答 409、不存在 404、非交互类 404、审批缺 decision 400', async () => {
  const session = await newSession('ap-errors');
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: `${FAKE_TRIGGER.approval}` });
  const pending = await waitPending(session.id);

  assert.equal((await api.post(`${API}/messages/respond`, { messageId: 'msg_missing', decision: 'approved' })).status, 404);
  assert.equal((await api.post(`${API}/messages/respond`, { messageId: sent.body.message.id, decision: 'approved' })).status, 404);
  assert.equal((await api.post(`${API}/messages/respond`, { messageId: pending.id })).status, 400);

  assert.equal((await api.post(`${API}/messages/respond`, { messageId: pending.id, decision: 'rejected' })).status, 200);
  const again = await api.post(`${API}/messages/respond`, { messageId: pending.id, decision: 'approved' });
  assert.equal(again.status, 409);
  assert.equal(again.body.error, 'CONFLICT');

  assert.equal((await api.waitTerminal(sent.body.run.id)).status, 'succeeded');
});

test('交互挂起 → 应答 answers → answers 落库', async () => {
  const session = await newSession('ap-question');
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: `${FAKE_TRIGGER.interactive}` });

  const pending = await waitPending(session.id);
  assert.equal(pending.type, 'tool_interactive');
  assert.equal(pending.content.questions[0].question, '要处理什么格式？');

  const answered = await api.post(`${API}/messages/respond`, { messageId: pending.id, answers: { '要处理什么格式？': ['CSV'] } });
  assert.equal(answered.status, 200);
  assert.equal(answered.body.status, 'answered');
  assert.deepEqual(answered.body.content.answers, { '要处理什么格式？': ['CSV'] });

  assert.equal((await api.waitTerminal(sent.body.run.id)).status, 'succeeded');
  const messages = await api.get(`${API}/messages/list?sessionId=${session.id}`);
  assert.ok(messages.body.items.some((m: any) => m.content.text === '回答：{"要处理什么格式？":["CSV"]}'));
});

test('交互应答：answers 值不是字符串数组即 400，消息仍可再答（空对象合法）', async () => {
  const session = await newSession('ap-answers-shape');
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: `${FAKE_TRIGGER.interactive}` });
  const pending = await waitPending(session.id);

  for (const answers of [{ '要处理什么格式？': 'CSV' }, { '要处理什么格式？': [1] }, ['CSV']]) {
    const bad = await api.post(`${API}/messages/respond`, { messageId: pending.id, answers });
    assert.equal(bad.status, 400, `${JSON.stringify(answers)} 应 400`);
    assert.equal(bad.body.error, 'BAD_REQUEST');
  }

  const unanswered = await api.post(`${API}/messages/respond`, { messageId: pending.id, answers: {} });
  assert.equal(unanswered.status, 200);
  assert.deepEqual(unanswered.body.content.answers, {});
  assert.equal((await api.waitTerminal(sent.body.run.id)).status, 'succeeded');
});

test('approved_all：会话级生效，新 run 继承', async () => {
  const session = await newSession('ap-all');
  const first = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: `${FAKE_TRIGGER.approval}` });
  const pending = await waitPending(session.id);

  const all = await api.post(`${API}/messages/respond`, { messageId: pending.id, decision: 'approved_all' });
  assert.equal(all.body.status, 'approved_all');
  assert.equal((await api.waitTerminal(first.body.run.id)).status, 'succeeded');

  // 会话级开关：审批模式切到 full_access，approvedAll 置真
  const detail = await api.get(`${API}/sessions/detail?sessionId=${session.id}`);
  assert.equal(detail.body.approvalMode, 'full_access');
  assert.equal(detail.body.approvedAll, true);

  // 新 run 继承：审批不再挂起，直接收口
  const second = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: `${FAKE_TRIGGER.approval}` });
  assert.equal(second.status, 200);
  assert.equal((await api.waitTerminal(second.body.run.id)).status, 'succeeded');
  assert.equal((await api.get(`${API}/messages/list?sessionId=${session.id}&status=pending`)).body.items.length, 0);

  // 用户手动的 approved_all 一条；新 run 的自动放行落 approved_all_auto 审计
  const audit = await api.get(`${API}/messages/list?sessionId=${session.id}&status=approved_all`);
  const user = audit.body.items.filter((m: any) => m.content.decisionSource === 'user');
  const auto = audit.body.items.filter((m: any) => m.content.decisionSource === 'approved_all_auto');
  assert.equal(user.length, 1);
  assert.equal(auto.length, 1);
  assert.equal(auto[0].runId, second.body.run.id);
});

test('approvedAll 复位：切到非 full_access 清假，切到 full_access 不自动置真', async () => {
  const session = await newSession('ap-all-reset');
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: `${FAKE_TRIGGER.approval}` });
  const pending = await waitPending(session.id);
  await api.post(`${API}/messages/respond`, { messageId: pending.id, decision: 'approved_all' });
  assert.equal((await api.waitTerminal(sent.body.run.id)).status, 'succeeded');

  const downgraded = await sessionService.switchMode({ sessionId: session.id, mode: 'workspace_write' });
  assert.equal(downgraded.approvalMode, 'workspace_write');
  assert.equal(downgraded.approvedAll, false, '降级审批模式必须复位 approvedAll');

  const fresh = await newSession('ap-all-fresh');
  const upgraded = await sessionService.switchMode({ sessionId: fresh.id, mode: 'full_access' });
  assert.equal(upgraded.approvalMode, 'full_access');
  assert.equal(upgraded.approvedAll, false, '切到 full_access 不自动置真');
});

test('并发应答的败者不改会话开关：approved_all 落败拿 409 且 approvedAll 仍为 false', async () => {
  const session = await newSession('ap-all-loser');
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: `${FAKE_TRIGGER.approval}` });
  const pending = await waitPending(session.id);

  // 卡住第一次仲裁：让 approved_all 先到并停在仲裁前，后到的 rejected 抢到仲裁
  const originalSettle = messagesRepo.settlePending;
  let releaseFirst!: () => void;
  const firstGate = new Promise<void>((resolve) => {
    releaseFirst = resolve;
  });
  let firstEntered!: () => void;
  const entered = new Promise<void>((resolve) => {
    firstEntered = resolve;
  });
  let firstCall = true;
  messagesRepo.settlePending = async (id, patch) => {
    if (firstCall) {
      firstCall = false;
      firstEntered();
      await firstGate;
    }
    return originalSettle.call(messagesRepo, id, patch);
  };

  try {
    const approving = api.post(`${API}/messages/respond`, { messageId: pending.id, decision: 'approved_all' });
    await entered;
    const rejecting = await api.post(`${API}/messages/respond`, { messageId: pending.id, decision: 'rejected' });
    assert.equal(rejecting.status, 200, '后到的 rejected 应抢到仲裁');

    releaseFirst();
    const loser = await approving;
    assert.equal(loser.status, 409);
    assert.equal(loser.body.error, 'CONFLICT');
    // 败者不得置「允许所有」：会话开关必须仍为 false
    assert.equal((await api.get(`${API}/sessions/detail?sessionId=${session.id}`)).body.approvedAll, false);
  } finally {
    releaseFirst();
    messagesRepo.settlePending = originalSettle;
  }

  assert.equal((await api.waitTerminal(sent.body.run.id)).status, 'succeeded');
});

test('挂起期间中止：消息 aborted、引擎放行、run aborted', async () => {
  const session = await newSession('ap-abort');
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: `${FAKE_TRIGGER.approval}` });
  const pending = await waitPending(session.id);

  const aborted = await api.post(`${API}/runs/abort`, { runId: sent.body.run.id });
  assert.equal(aborted.status, 200);
  assert.equal(aborted.body.status, 'aborted');

  const stored = await prisma.message.findUnique({ where: { id: pending.id } });
  assert.equal(stored?.status, 'aborted');
  assert.equal(JSON.parse(stored!.content).decisionSource, 'abort');
  assert.equal((await api.get(`${API}/messages/list?sessionId=${session.id}&status=pending`)).body.items.length, 0);
});

test('WS 通道应答：message.respond 与 REST 同一条服务路径', async () => {
  const session = await newSession('ap-ws');
  const { ws, events, request } = await connectWs();

  await request('subscribe', { sessionId: session.id });
  const sent = await request('send', { sessionId: session.id, prompt: `${FAKE_TRIGGER.approval}` });
  assert.equal(sent.method, 'send.result');

  let pendingMessage: any;
  for (let waited = 0; waited < 5000 && !pendingMessage; waited += 50) {
    pendingMessage = events.find((e) => e.method === 'message' && e.payload.status === 'pending')?.payload;
    if (!pendingMessage) await sleep(50);
  }
  assert.ok(pendingMessage, '应收到 pending 的 message 事件');

  const responded = await request('message.respond', { messageId: pendingMessage.id, decision: 'approved' });
  assert.equal(responded.method, 'message.respond.result');
  assert.equal(responded.error, null);
  assert.deepEqual(Object.keys(responded.payload), ['message']);
  assert.equal(responded.payload.message.status, 'approved');

  const settlement = events.filter((e) => e.method === 'message' && e.payload.id === pendingMessage.id);
  assert.equal(settlement.length, 2, '挂起与结算各一条 upsert 事件');
  assert.equal(settlement[1].payload.status, 'approved');

  assert.equal((await api.waitTerminal(sent.payload.run.id)).status, 'succeeded');
  ws.close();
});

test('等待应答期间刷新：REST 能查到同一条挂起', async () => {
  const session = await newSession('ap-refresh');
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: `${FAKE_TRIGGER.approval}` });
  const pending = await waitPending(session.id);

  const again = await api.get(`${API}/messages/list?sessionId=${session.id}&status=pending`);
  assert.equal(again.body.items.length, 1);
  assert.equal(again.body.items[0].id, pending.id);

  await api.post(`${API}/messages/respond`, { messageId: pending.id, decision: 'rejected' });
  assert.equal((await api.waitTerminal(sent.body.run.id)).status, 'succeeded');
});

test('WS 竞态：收到挂起事件的同一轮立即应答，应答成功且 run 收口', async () => {
  const session = await newSession('ap-ws-race');
  let resolveResponded!: (envelope: any) => void;
  const settled = new Promise<any>((resolve) => {
    resolveResponded = resolve;
  });

  const { ws, request } = await connectWs((envelope) => {
    if (envelope.method !== 'message' || envelope.payload.status !== 'pending') return;
    // 不轮询、不等待：事件到达的当轮就发应答
    void request('message.respond', { messageId: envelope.payload.id, decision: 'approved' }).then(resolveResponded);
  });

  await request('subscribe', { sessionId: session.id });
  const sent = await request('send', { sessionId: session.id, prompt: `${FAKE_TRIGGER.approval}` });
  assert.equal(sent.method, 'send.result');

  const responded = await Promise.race([
    settled,
    sleep(5000).then(() => {
      throw new Error('5s 内未收到应答响应');
    }),
  ]);
  assert.equal(responded.method, 'message.respond.result');
  assert.equal(responded.error, null, '同一轮应答应成功');
  assert.equal(responded.payload.message.status, 'approved');

  const run = await api.waitTerminal(sent.payload.run.id);
  assert.equal(run.status, 'succeeded');
  assert.equal(run.waiting, null);
  ws.close();
});

test('挂起久等 1200ms 仍可应答（无超时器），run 正常收口', async () => {
  const session = await newSession('ap-slow');
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: `${FAKE_TRIGGER.approval}` });
  const pending = await waitPending(session.id);

  await sleep(1200);
  const stillPending = await api.get(`${API}/messages/list?sessionId=${session.id}&status=pending`);
  assert.equal(stillPending.body.items.length, 1);
  assert.equal(stillPending.body.items[0].id, pending.id);

  const responded = await api.post(`${API}/messages/respond`, { messageId: pending.id, decision: 'approved' });
  assert.equal(responded.status, 200);
  assert.equal(responded.body.status, 'approved');
  assert.equal((await api.waitTerminal(sent.body.run.id)).status, 'succeeded');
});

test('中止后引擎后到的返回不改写终态：run 保持 aborted、finishedAt 非空、会话 completed', async () => {
  const session = await newSession('ap-abort-terminal');
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: `${FAKE_TRIGGER.approval}` });
  await waitPending(session.id);

  const aborted = await api.post(`${API}/runs/abort`, { runId: sent.body.run.id });
  assert.equal(aborted.body.status, 'aborted');
  assert.ok(aborted.body.finishedAt, '中止即落 finishedAt');

  assert.equal((await api.get(`${API}/runs/detail?runId=${sent.body.run.id}`)).body.status, 'aborted');

  await sleep(300);
  const later = await api.get(`${API}/runs/detail?runId=${sent.body.run.id}`);
  assert.equal(later.body.status, 'aborted', '引擎后到的返回不得改写终态');
  assert.ok(later.body.finishedAt, 'finishedAt 非空');

  assert.equal((await api.get(`${API}/sessions/detail?sessionId=${session.id}`)).body.status, 'completed');
});

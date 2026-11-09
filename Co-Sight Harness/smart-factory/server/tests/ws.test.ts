import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { join } from 'node:path';
import { WebSocket } from 'ws';
import { prepareTestEnv } from './helpers/test-db.js';
import { agentRootIn, seedAgent, seedDevelopmentDir, seedPipelineState } from './helpers/agents.js';
import { startWorkspaceStub, TEST_MODEL_ALT_ID, TEST_MODEL_ID } from './helpers/workspace-stub.js';

// 心跳间隔压到 200ms（超时 400ms）、背压阈值压到 1KB，让这两条边界路径可在测试里跑完
process.env.WS_HEARTBEAT_MS = '200';
process.env.WS_MAX_BUFFERED_BYTES = '1024';

const env = prepareTestEnv('ws');
const stub = await startWorkspaceStub(env);

const { prisma } = await import('../src/shared/prisma/client.js');
const { createApp } = await import('../src/app.js');
const { attachWsGateway } = await import('../src/shared/live/ws-gateway.js');
const { liveHub } = await import('../src/shared/live/live-hub.js');
const { eventEnvelope } = await import('../src/shared/live/envelope.js');
const { sessionService } = await import('../src/modules/session/session.service.js');
const { FakeAdapter, FAKE_TRIGGER } = await import('../src/shared/engine/fake-adapter.js');
const { config } = await import('../src/config/index.js');

interface Envelope {
  id: string;
  type: 'request' | 'response' | 'event';
  method: string;
  payload?: any;
  error?: { code: string; message: string } | null;
}

let server: Server;
let gateway: { close(): void };
let url = '';

interface Client {
  ws: WebSocket;
  events: Envelope[];
  request(method: string, payload?: unknown): Promise<Envelope>;
  waitEvent(method: string, predicate?: (env: Envelope) => boolean, timeoutMs?: number): Promise<Envelope>;
  close(): void;
}

let requestSequence = 0;

async function connect(): Promise<Client> {
  const ws = new WebSocket(url);
  const events: Envelope[] = [];
  const pending = new Map<string, (env: Envelope) => void>();
  const waiters: Array<{ method: string; predicate: (env: Envelope) => boolean; resolve: (env: Envelope) => void }> = [];

  ws.on('message', (raw) => {
    const envelope = JSON.parse(raw.toString()) as Envelope;
    if (envelope.type === 'event') {
      events.push(envelope);
      const index = waiters.findIndex((w) => w.method === envelope.method && w.predicate(envelope));
      if (index >= 0) waiters.splice(index, 1)[0]!.resolve(envelope);
      return;
    }
    pending.get(envelope.id)?.(envelope);
    pending.delete(envelope.id);
  });

  await new Promise<void>((resolve) => ws.on('open', () => resolve()));

  return {
    ws,
    events,
    async request(method, payload) {
      requestSequence += 1;
      const id = `req_${requestSequence}`;
      const answer = new Promise<Envelope>((resolve) => pending.set(id, resolve));
      ws.send(JSON.stringify({ id, type: 'request', method, timestamp: Date.now(), payload }));
      return answer;
    },
    waitEvent(method, predicate = () => true, timeoutMs = 5000) {
      const existing = events.find((e) => e.method === method && predicate(e));
      if (existing) return Promise.resolve(existing);
      return new Promise<Envelope>((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error(`未在 ${timeoutMs}ms 内收到事件 ${method}`)), timeoutMs);
        waiters.push({
          method,
          predicate,
          resolve: (env) => {
            clearTimeout(timer);
            resolve(env);
          },
        });
      });
    },
    close() {
      ws.close();
    },
  };
}

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

/** 起一个真实会话：订阅会校验会话存在，不能再用假 id；会话还要挂在一个真实存在的智能体上。 */
async function newSession(agentId: string): Promise<any> {
  await seedAgent(agentId);
  seedDevelopmentDir(env.workspaceDir, agentId);
  const response = await fetch(`http://127.0.0.1:${(server.address() as AddressInfo).port}/api/smart-factory/v1/sessions/create`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ agentId, modelId: TEST_MODEL_ID }),
  });
  return response.json();
}

/** 等该会话出现挂起消息（订阅补发针对的就是它）。 */
async function waitPending(sessionId: string, timeoutMs = 5000): Promise<any> {
  for (let waited = 0; waited < timeoutMs; waited += 50) {
    const page = await sessionService.listMessages({ sessionId, status: 'pending' });
    if (page.items.length > 0) return page.items[0];
    await sleep(50);
  }
  throw new Error(`会话 ${sessionId} 未在 ${timeoutMs}ms 内出现挂起消息`);
}

/** 从 liveHub 直收的实时帧里等一条目标事件：订阅补发要与它逐字段同形。 */
async function waitEnvelope(
  events: Envelope[],
  method: string,
  predicate: (envelope: Envelope) => boolean,
  timeoutMs = 5000,
): Promise<Envelope> {
  for (let waited = 0; waited < timeoutMs; waited += 20) {
    const found = events.find((envelope) => envelope.method === method && predicate(envelope));
    if (found) return found;
    await sleep(20);
  }
  throw new Error(`未在 ${timeoutMs}ms 内收到实时事件 ${method}`);
}

/** liveHub 直收帧的线上形状：JSON 序列化会丢掉 undefined 字段，补发帧（过 WS）已是这个形状。 */
function wirePayload(envelope: Envelope): unknown {
  return JSON.parse(JSON.stringify(envelope.payload));
}

/** 等服务端断开连接，超时即判失败。 */
function waitClosed(ws: WebSocket, timeoutMs = 3000): Promise<{ code: number; reason: string }> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`未在 ${timeoutMs}ms 内被服务端断开`)), timeoutMs);
    ws.on('close', (code, reason) => {
      clearTimeout(timer);
      resolve({ code, reason: reason.toString() });
    });
  });
}

/** 发一帧原始 JSON 并等下一个非事件回帧：非法信封的 id 是空串，借不了 request 的 pending 匹配。 */
function rawRoundTrip(client: Client, frame: unknown): Promise<Envelope> {
  return new Promise((resolve) => {
    const onMessage = (raw: WebSocket.RawData) => {
      const envelope = JSON.parse(raw.toString()) as Envelope;
      if (envelope.type === 'event') return;
      client.ws.off('message', onMessage);
      resolve(envelope);
    };
    client.ws.on('message', onMessage);
    client.ws.send(JSON.stringify(frame));
  });
}

before(async () => {
  server = createServer(createApp());
  gateway = attachWsGateway(server, {
    send: (input) => sessionService.sendMessage(input),
    abortRun: (input) => sessionService.abortRun(input.runId),
    respond: (input) => sessionService.respondMessage(input),
    respondApproval: (input) => sessionService.respondApproval(input),
    respondTool: (input) => sessionService.respondTool(input),
    switchModel: (input) => sessionService.switchModel(input),
    switchMode: (input) => sessionService.switchMode(input),
    switchEffort: (input) => sessionService.switchEffort(input),
    history: (input) => sessionService.history(input),
    subscribeInfo: (sessionId) => sessionService.subscribeInfo(sessionId),
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  url = `ws://127.0.0.1:${(server.address() as AddressInfo).port}${config.wsPath}`;
});

after(async () => {
  gateway.close();
  await new Promise<void>((resolve) => server.close(() => resolve()));
  await stub.close();
  await prisma.$disconnect();
});

test('连接建立后立刻收到 connection.ready', async () => {
  const client = await connect();
  const ready = await client.waitEvent('connection.ready');
  assert.match(ready.payload.connectionId, /^conn_\d+$/);
  assert.deepEqual(ready.payload, {
    connectionId: ready.payload.connectionId,
    restored: false,
    sessionId: null,
  });
  assert.match(ready.id, /^evt_\d+_\d+$/);
  client.close();
});

test('ping → pong', async () => {
  const client = await connect();
  const answer = await client.request('ping');
  assert.equal(answer.type, 'response');
  assert.equal(answer.method, 'pong');
  assert.equal(typeof answer.payload.serverTime, 'number');
  assert.ok(answer.payload.serverTime > 0);
  assert.equal(answer.error, null);
  client.close();
});

test('未知方法：id 原样回显、method 为 error、code 为 VALIDATION', async () => {
  const client = await connect();
  const answer = await client.request('nope.method');
  assert.equal(answer.type, 'response');
  assert.equal(answer.method, 'error');
  assert.equal(answer.error?.code, 'VALIDATION');
  assert.equal(answer.error?.message, '未知方法：nope.method');
  assert.match(answer.id, /^req_\d+$/);
  client.close();
});

test('缺 type 的上行帧按非法信封回 unknown 错误帧', async () => {
  const client = await connect();
  const answer = await rawRoundTrip(client, { id: 'req_no_type', method: 'ping', timestamp: Date.now(), payload: {} });

  assert.equal(answer.type, 'response');
  assert.equal(answer.id, '');
  assert.equal(answer.method, 'error');
  assert.equal(answer.error?.code, 'VALIDATION');
  assert.equal(answer.error?.message, '信封格式非法');
  client.close();
});

test('type 非法值的上行帧按非法信封回空 id 错误帧', async () => {
  const client = await connect();
  const answer = await rawRoundTrip(client, { id: 'req_bad_type', type: 'bogus', method: 'ping', timestamp: Date.now(), payload: {} });

  assert.equal(answer.type, 'response');
  assert.equal(answer.id, '');
  assert.equal(answer.method, 'error');
  assert.equal(answer.error?.code, 'VALIDATION');
  assert.equal(answer.error?.message, '信封格式非法');

  // 非法帧被拒后连接不受影响，合法 request 帧照常处理
  const ping = await client.request('ping');
  assert.equal(ping.method, 'pong');
  client.close();
});

test('subscribe → send → 收到完整事件序列并跑完', async () => {
  const client = await connect();
  const created = await newSession('ws-flow');

  const subscribed = await client.request('subscribe', { sessionId: created.id });
  assert.equal(subscribed.method, 'subscribe.result');
  assert.deepEqual(subscribed.payload, { sessionId: created.id, subscribed: true, status: 'not_started' });

  // run.started 在 send 响应前广播：事件可能先于响应到达，waitEvent 先查已收事件
  const sent = await client.request('send', { sessionId: created.id, prompt: '你好' });
  assert.equal(sent.method, 'send.result');
  assert.equal(sent.error, null);
  assert.equal(sent.payload.sessionId, created.id);
  assert.equal(sent.payload.runId, sent.payload.run.id);
  assert.equal(sent.payload.instanceId, created.instanceId);
  assert.equal(sent.payload.status, 'running');
  assert.equal(sent.payload.effort, 'high');
  assert.equal(sent.payload.modelId, TEST_MODEL_ID, '首次 send 解析出模型并随响应返回');
  assert.equal(sent.payload.modelName, 'test-sonnet');
  assert.equal(sent.payload.modelFellBack, false, '本服务不做模型回落');
  assert.equal(sent.payload.message.content.text, '你好');
  assert.equal(sent.payload.run.status, 'running');
  assert.ok(sent.payload.run.startedAt, 'running run 必须带 startedAt');
  assert.ok(
    client.events.some((e) => e.method === 'run.started' && e.payload.id === sent.payload.runId),
    'run.started 在 send 响应到达前已广播',
  );

  const started = await client.waitEvent('run.started');
  assert.equal(started.payload.id, sent.payload.runId);
  assert.equal(started.payload.status, 'running');
  assert.ok(started.payload.startedAt, 'run.started 带 startedAt');

  const delta = await client.waitEvent('chat.delta');
  assert.equal(typeof delta.payload.delta, 'string');
  assert.deepEqual(delta.payload, {
    sessionId: created.id,
    runId: sent.payload.runId,
    parentRunId: null,
    messageType: 'text',
    delta: delta.payload.delta,
  });

  const status = await client.waitEvent('run.status');
  assert.equal(status.payload.id, sent.payload.runId);
  assert.equal(status.payload.status, 'succeeded');

  const messageEvents = client.events.filter((e) => e.method === 'message');
  assert.equal(messageEvents.length, 2);
  assert.deepEqual(
    messageEvents.map((e) => [e.payload.seq, e.payload.role]),
    [
      [1, 'user'],
      [2, 'assistant'],
    ],
  );
  assert.deepEqual(messageEvents[1]!.payload.content, { text: '收到：你好' });

  const final = await client.waitEvent('chat.final');
  assert.deepEqual(final.payload, {
    sessionId: created.id,
    runId: sent.payload.runId,
    parentRunId: null,
    content: '收到：你好',
    messageId: messageEvents[1]!.payload.id,
  });

  const sessionStatus = await client.waitEvent('session.status', (e) => e.payload.status === 'completed');
  assert.equal(sessionStatus.payload.status, 'completed');

  // 事件顺序：run.started < chat.delta < run.status < chat.final < session.status
  const methods = client.events.map((e) => e.method);
  assert.ok(methods.indexOf('run.started') < methods.indexOf('chat.delta'));
  assert.ok(methods.indexOf('chat.delta') < methods.indexOf('run.status'));
  assert.ok(methods.indexOf('run.status') < methods.indexOf('chat.final'));
  assert.ok(methods.indexOf('chat.final') < client.events.indexOf(sessionStatus), 'chat.final 先于 completed 的 session.status');
  client.close();
});

test('subscribe 不存在的会话 → NOT_FOUND 错误响应', async () => {
  const client = await connect();
  const answer = await client.request('subscribe', { sessionId: 'sess_missing' });
  assert.equal(answer.type, 'response');
  assert.equal(answer.method, 'subscribe.result');
  assert.equal(answer.error?.code, 'NOT_FOUND');
  assert.equal(answer.payload, undefined);
  assert.equal(liveHub.subscriberCount('sess_missing'), 0, '失败订阅不得留下订阅关系');
  client.close();
});

test('subscribe 补发该会话当前的挂起审批，形状与实时 approval.request 一致', async () => {
  const session = await newSession('ws-replay');
  const live: Envelope[] = [];
  const subscriber = { send: (envelope: Envelope): boolean => (live.push(envelope), true) };
  liveHub.subscribe(session.id, subscriber);

  const sent = await sessionService.sendMessage({ sessionId: session.id, prompt: FAKE_TRIGGER.approval });
  const pending = await waitPending(session.id);
  const liveFrame = await waitEnvelope(live, 'approval.request', (e) => e.payload.approvalId === pending.id);
  liveHub.unsubscribe(session.id, subscriber);

  const client = await connect();
  const subscribed = await client.request('subscribe', { sessionId: session.id });
  assert.equal(subscribed.method, 'subscribe.result');
  assert.equal(subscribed.error, null);
  assert.deepEqual(subscribed.payload, { sessionId: session.id, subscribed: true, status: 'in_progress' });

  const replayed = await client.waitEvent('approval.request', (e) => e.payload.approvalId === pending.id);
  assert.equal(replayed.type, 'event');
  assert.equal(replayed.payload.sessionId, session.id);
  assert.equal(replayed.payload.runId, sent.run.id);
  assert.equal(replayed.payload.parentRunId, null);
  assert.equal(replayed.payload.toolCallId, 'toolu_fake_approval');
  assert.equal('expiresAt' in replayed.payload, false);
  assert.deepEqual(replayed.payload, wirePayload(liveFrame), '补发帧与实时兼容帧必须同形');
  assert.equal(
    client.events.filter((e) => e.method === 'message' && e.payload.id === pending.id).length,
    0,
    '挂起审批不再以 message 帧补发',
  );
  assert.equal(
    client.events.filter((e) => e.method === 'message' && e.payload.id === sent.message.id).length,
    0,
    '普通历史消息随订阅补发一起下发是禁止的',
  );

  await sessionService.abortRun(sent.run.id);
  client.close();
});

test('subscribe 补发挂起交互：tool.interactive 与实时帧同形，不补发 message 帧', async () => {
  const session = await newSession('ws-replay-interactive');
  const live: Envelope[] = [];
  const subscriber = { send: (envelope: Envelope): boolean => (live.push(envelope), true) };
  liveHub.subscribe(session.id, subscriber);

  const sent = await sessionService.sendMessage({ sessionId: session.id, prompt: FAKE_TRIGGER.interactive });
  const pending = await waitPending(session.id);
  const liveFrame = await waitEnvelope(live, 'tool.interactive', (e) => e.payload.runId === sent.runId);
  liveHub.unsubscribe(session.id, subscriber);

  const client = await connect();
  const subscribed = await client.request('subscribe', { sessionId: session.id });
  assert.equal(subscribed.error, null);
  assert.deepEqual(subscribed.payload, { sessionId: session.id, subscribed: true, status: 'in_progress' });

  const replayed = await client.waitEvent('tool.interactive', (e) => e.payload.runId === sent.runId);
  assert.equal(replayed.type, 'event');
  assert.equal(replayed.payload.sessionId, session.id);
  assert.equal(replayed.payload.parentRunId, null);
  assert.equal(replayed.payload.toolName, 'AskUserQuestion');
  assert.deepEqual(replayed.payload, wirePayload(liveFrame), '补发帧与实时兼容帧必须同形');
  assert.equal(
    client.events.filter((e) => e.method === 'message' && e.payload.id === pending.id).length,
    0,
    '挂起交互不再以 message 帧补发',
  );

  await sessionService.abortRun(sent.run.id);
  client.close();
});

test('history.result：sessionId / messages / total，total 是会话全部消息数', async () => {
  const created = await newSession('ws-history');
  const client = await connect();
  const sent = await client.request('send', { sessionId: created.id, prompt: '你好' });
  await client.waitEvent('run.status', (e) => e.payload.id === sent.payload.runId && e.payload.status === 'succeeded');

  const answer = await client.request('history', { sessionId: created.id, limit: 1 });
  assert.equal(answer.method, 'history.result');
  assert.equal(answer.error, null);
  assert.equal(answer.payload.sessionId, created.id);
  assert.equal(answer.payload.total, 2, 'total 不受 limit 影响');
  assert.deepEqual(answer.payload.messages.map((message: any) => message.role), ['assistant'], 'limit=1 只取最新一条');
  client.close();
});

test('send 未显式订阅也能收到本次 run 的事件', async () => {
  const session = await newSession('ws-implicit');
  const client = await connect();

  const sent = await client.request('send', { sessionId: session.id, prompt: '你好' });
  assert.equal(sent.error, null);

  await client.waitEvent('chat.delta');
  const status = await client.waitEvent('run.status');
  assert.equal(status.payload.status, 'succeeded');
  assert.deepEqual(
    client.events.filter((e) => e.method === 'message').map((e) => [e.payload.seq, e.payload.role]),
    [
      [1, 'user'],
      [2, 'assistant'],
    ],
  );
  client.close();
});

test('无回放：跑完之后新订阅者收不到任何历史事件', async () => {
  const created = await newSession('ws-noreplay');

  const actor = await connect();
  await actor.request('subscribe', { sessionId: created.id });
  await actor.request('send', { sessionId: created.id, prompt: 'hi' });
  await actor.waitEvent('run.status');
  // run 终态之后宿主还会补一条 session.status（completed）：等它到齐再判「无回放」，
  // 否则晚订阅者收到的这条实时帧会被误当成历史回放
  await actor.waitEvent('session.status', (e) => e.payload.status === 'completed');

  const late = await connect();
  await late.request('subscribe', { sessionId: created.id });
  await sleep(300);
  assert.deepEqual(late.events.map((e) => e.method), ['connection.ready']);

  actor.close();
  late.close();
});

test('unsubscribe 之后不再收到该会话事件', async () => {
  const created = await newSession('ws-unsub');

  const client = await connect();
  await client.request('subscribe', { sessionId: created.id });
  const removed = await client.request('unsubscribe', { sessionId: created.id });
  assert.equal(removed.method, 'unsubscribe.result');
  assert.deepEqual(removed.payload, { sessionId: created.id, unsubscribed: true });

  await sessionService.sendMessage({ sessionId: created.id, prompt: 'hi' });
  await sleep(400);
  assert.deepEqual(client.events.map((e) => e.method), ['connection.ready']);
  client.close();
});

test('run.abort 经 WS 生效', async () => {
  const created = await newSession('ws-abort');

  const client = await connect();
  await client.request('subscribe', { sessionId: created.id });
  // 停在审批上：引擎不会先跑完，中止断言不靠时序运气
  const sent = await client.request('send', { sessionId: created.id, prompt: FAKE_TRIGGER.approval });
  await waitPending(created.id);
  const aborted = await client.request('run.abort', { runId: sent.payload.run.id });

  assert.equal(aborted.method, 'run.abort.result');
  assert.equal(aborted.error, null);
  assert.deepEqual(aborted.payload, { runId: sent.payload.runId, aborted: true });

  const chatAborted = await client.waitEvent('chat.aborted');
  assert.deepEqual(chatAborted.payload, {
    sessionId: created.id,
    runId: sent.payload.runId,
    parentRunId: null,
    reason: '用户中止',
  });
  client.close();
});

test('已知方法参数校验失败 → <method>.result 与 VALIDATION，错误帧不带 payload', async () => {
  const client = await connect();
  const answer = await client.request('subscribe', {});
  assert.equal(answer.type, 'response');
  assert.equal(answer.method, 'subscribe.result');
  assert.equal(answer.error?.code, 'VALIDATION');
  assert.equal(answer.error?.message, 'sessionId 必填');
  assert.equal('payload' in answer, false);
  client.close();
});

test('approval.request 事件与 approval.respond.result 走真实审批路径', async () => {
  const created = await newSession('ws-approval');
  const client = await connect();
  await client.request('subscribe', { sessionId: created.id });
  const sent = await client.request('send', { sessionId: created.id, prompt: FAKE_TRIGGER.approval });
  const pending = await waitPending(created.id);

  const request = await client.waitEvent('approval.request');
  assert.equal(request.payload.approvalId, pending.id);
  assert.equal(request.payload.sessionId, created.id);
  assert.equal(request.payload.runId, sent.payload.runId);
  assert.equal(request.payload.parentRunId, null);
  assert.equal(request.payload.toolName, 'Bash');
  assert.equal(request.payload.title, '执行 Bash：echo hi');
  assert.deepEqual(request.payload.input, { command: 'echo hi' });
  assert.equal(request.payload.toolCallId, 'toolu_fake_approval');
  assert.equal('agentId' in request.payload, false);
  assert.equal('expiresAt' in request.payload, false);

  const responded = await client.request('approval.respond', { approvalId: pending.id, decision: 'approved' });
  assert.equal(responded.method, 'approval.respond.result');
  assert.deepEqual(responded.payload, { approvalId: pending.id, decision: 'approved', resolved: true });
  await client.waitEvent(
    'run.status',
    (e) => e.payload.id === sent.payload.runId && e.payload.status === 'succeeded',
  );
  client.close();
});

test('chat.thinking 三阶段经 WS 下发，正文增量仍走 chat.delta', async () => {
  const created = await newSession('ws-thinking');
  const client = await connect();
  await client.request('subscribe', { sessionId: created.id });

  const originalRun = FakeAdapter.prototype.run;
  FakeAdapter.prototype.run = async (ctx) => {
    await ctx.emit({ type: 'thinking', phase: 'start' });
    await ctx.emit({ type: 'thinking', phase: 'delta', text: '想一' });
    await ctx.emit({ type: 'thinking', phase: 'delta', text: '想二' });
    await ctx.emit({ type: 'thinking', phase: 'stop' });
    await ctx.emit({ type: 'delta', messageType: 'text', delta: '正文' });
    await ctx.emit({ type: 'message', draft: { role: 'assistant', type: 'text', content: { text: '正文' } } });
    return { output: '正文' };
  };
  try {
    const sent = await client.request('send', { sessionId: created.id, prompt: '你好' });
    await client.waitEvent(
      'run.status',
      (e) => e.payload.id === sent.payload.runId && e.payload.status === 'succeeded',
    );

    assert.equal(client.events.filter((e) => e.method === 'chat.thinking.delta').length, 0, '旧事件必须移除');
    const thinking = client.events.filter((e) => e.method === 'chat.thinking');
    assert.deepEqual(thinking.map((e) => e.payload.phase), ['start', 'delta', 'delta', 'stop']);
    for (const event of thinking) {
      assert.equal(event.payload.sessionId, created.id);
      assert.equal(event.payload.runId, sent.payload.runId);
      assert.equal(event.payload.parentRunId, null);
      assert.match(event.payload.at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
    }
    assert.equal('text' in thinking[0]!.payload, false, 'start 不带正文');
    assert.equal('text' in thinking[3]!.payload, false, 'stop 不带正文');
    assert.deepEqual(thinking.slice(1, 3).map((e) => e.payload.text), ['想一', '想二']);

    const deltas = client.events.filter((e) => e.method === 'chat.delta');
    assert.ok(deltas.length > 0);
    assert.ok(deltas.every((e) => e.payload.messageType === 'text'));
    assert.equal(deltas.map((e) => e.payload.delta).join(''), '正文');
  } finally {
    FakeAdapter.prototype.run = originalRun;
    client.close();
  }
});

test('chat.retry：api_retry 经 WS 下发完整字段，parentRunId 恒为 null', async () => {
  const created = await newSession('ws-retry');
  const client = await connect();
  await client.request('subscribe', { sessionId: created.id });

  const originalRun = FakeAdapter.prototype.run;
  FakeAdapter.prototype.run = async (ctx) => {
    await ctx.emit({ type: 'api_retry', attempt: 1, maxRetries: 3, errorStatus: 529, error: 'overloaded_error' });
    return { output: '重试后成功' };
  };
  try {
    const sent = await client.request('send', { sessionId: created.id, prompt: '你好' });
    const retry = await client.waitEvent('chat.retry');
    assert.deepEqual(retry.payload, {
      sessionId: created.id,
      runId: sent.payload.runId,
      parentRunId: null,
      attempt: 1,
      maxRetries: 3,
      errorStatus: 529,
      error: 'overloaded_error',
    });
    await client.waitEvent('run.status', (e) => e.payload.id === sent.payload.runId && e.payload.status === 'succeeded');
  } finally {
    FakeAdapter.prototype.run = originalRun;
    client.close();
  }
});

test('chat.final：成功 run 没有助手文本消息时 messageId 为 null，正文取适配器终稿', async () => {
  const created = await newSession('ws-final-no-message');
  const client = await connect();
  await client.request('subscribe', { sessionId: created.id });

  const originalRun = FakeAdapter.prototype.run;
  FakeAdapter.prototype.run = async () => ({ output: '只有终稿' });
  try {
    const sent = await client.request('send', { sessionId: created.id, prompt: '你好' });
    const final = await client.waitEvent('chat.final', (e) => e.payload.runId === sent.payload.runId);
    assert.deepEqual(final.payload, {
      sessionId: created.id,
      runId: sent.payload.runId,
      parentRunId: null,
      content: '只有终稿',
      messageId: null,
    });
  } finally {
    FakeAdapter.prototype.run = originalRun;
    client.close();
  }
});

test('WS 切换设置：<method>.result 回执与 settings.changed（channel=ws）', async () => {
  const created = await newSession('ws-settings');
  const client = await connect();
  await client.request('subscribe', { sessionId: created.id });

  const modelSwitched = await client.request('model.switch', { sessionId: created.id, modelId: TEST_MODEL_ALT_ID });
  assert.equal(modelSwitched.method, 'model.switch.result');
  assert.deepEqual(modelSwitched.payload, { sessionId: created.id, modelId: TEST_MODEL_ALT_ID, appliesTo: 'nextRun' });
  await client.waitEvent('settings.changed', (e) => e.payload.settings.modelId === TEST_MODEL_ALT_ID);
  let settings = client.events.filter((e) => e.method === 'settings.changed');
  assert.match(settings[0]!.payload.at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
  assert.deepEqual(settings[0]!.payload, {
    sessionId: created.id,
    settings: { mode: created.approvalMode, effort: created.effort, modelId: TEST_MODEL_ALT_ID },
    changedBy: { channel: 'ws', actorId: '' },
    appliesTo: 'nextRun',
    at: settings[0]!.payload.at,
  });

  const modeSwitched = await client.request('mode.switch', { sessionId: created.id, mode: 'full_access' });
  assert.equal(modeSwitched.method, 'mode.switch.result');
  assert.deepEqual(modeSwitched.payload, { sessionId: created.id, mode: 'full_access' });
  await client.waitEvent('settings.changed', (e) => e.payload.settings.mode === 'full_access');
  settings = client.events.filter((e) => e.method === 'settings.changed');
  assert.deepEqual(settings[1]!.payload, {
    sessionId: created.id,
    settings: { mode: 'full_access', effort: created.effort, modelId: TEST_MODEL_ALT_ID },
    changedBy: { channel: 'ws', actorId: '' },
    at: settings[1]!.payload.at,
  });
  assert.equal('appliesTo' in settings[1]!.payload, false);

  const effortSwitched = await client.request('effort.switch', { sessionId: created.id, effort: 'max' });
  assert.equal(effortSwitched.method, 'effort.switch.result');
  assert.deepEqual(effortSwitched.payload, { sessionId: created.id, effort: 'max' });
  await client.waitEvent('settings.changed', (e) => e.payload.settings.effort === 'max');
  settings = client.events.filter((e) => e.method === 'settings.changed');
  assert.equal(settings.length, 3);
  assert.deepEqual(settings[2]!.payload.settings, { mode: 'full_access', effort: 'max', modelId: TEST_MODEL_ALT_ID });
  assert.equal('appliesTo' in settings[2]!.payload, false);
  client.close();
});

test('task.started / task.notified：线上用 toolCallId 与 SDK 状态 stopped', async () => {
  const created = await newSession('ws-task');
  const client = await connect();
  await client.request('subscribe', { sessionId: created.id });
  const sent = await client.request('send', { sessionId: created.id, prompt: FAKE_TRIGGER.subagentStop });
  await client.waitEvent(
    'run.status',
    (e) => e.payload.id === sent.payload.runId && e.payload.status === 'succeeded',
  );

  const started = await client.waitEvent('task.started');
  assert.deepEqual(started.payload, {
    sessionId: created.id,
    runId: started.payload.runId,
    parentRunId: sent.payload.runId,
    taskId: 'task_fake_1',
    toolCallId: 'toolu_fake_task_1',
    subagentType: 'general-purpose',
    delegationDepth: 1,
    description: '桩子代理任务',
  });
  assert.equal('parentToolUseId' in started.payload, false);

  const notified = await client.waitEvent('task.notified');
  assert.deepEqual(notified.payload, {
    sessionId: created.id,
    runId: started.payload.runId,
    parentRunId: sent.payload.runId,
    taskId: 'task_fake_1',
    status: 'stopped',
    subagentType: 'general-purpose',
    error: null,
    summary: '子代理已停止',
  });

  // 子 run 终态只发 task.notified；chat.aborted 只表示顶层 run
  assert.equal(
    client.events.some((event) => event.method === 'chat.aborted' && event.payload.runId === started.payload.runId),
    false,
    '子 run 不发 chat.aborted',
  );
  client.close();
});

test('心跳：客户端不发任何帧 → 超过 2 个周期被服务端以 1000 断开并清理订阅', async () => {
  const session = await newSession('ws-idle');
  const client = await connect();
  await client.request('subscribe', { sessionId: session.id });
  assert.equal(liveHub.subscriberCount(session.id), 1);

  const { code, reason } = await waitClosed(client.ws);
  assert.equal(code, 1000);
  assert.equal(reason, '心跳超时');
  assert.equal(liveHub.subscriberCount(session.id), 0, '断开即清理订阅');
});

test('心跳：客户端按间隔发 ping → 跨多个心跳周期仍在线', async () => {
  const client = await connect();

  // 5 × 150ms = 750ms，远超 400ms 的空闲阈值；每帧上行都刷新活跃时间
  for (let round = 0; round < 5; round += 1) {
    const answer = await client.request('ping');
    assert.equal(answer.method, 'pong');
    assert.equal(typeof answer.payload.serverTime, 'number');
    await sleep(150);
  }

  assert.equal(client.ws.readyState, WebSocket.OPEN);
  client.close();
});

test('慢消费者：写堆积超阈值被服务端断流', async () => {
  const session = await newSession('ws-slow');
  const client = await connect();
  await client.request('subscribe', { sessionId: session.id });
  const before = gateway.connectionCount;

  client.ws.pause(); // 模拟只连不读

  const big = 'x'.repeat(60_000);
  for (let i = 0; i < 200 && liveHub.subscriberCount(session.id) > 0; i += 1) {
    liveHub.broadcast(session.id, eventEnvelope('message', { big }));
  }

  for (let waited = 0; waited < 3000 && liveHub.subscriberCount(session.id) > 0; waited += 50) {
    await sleep(50);
  }
  assert.equal(liveHub.subscriberCount(session.id), 0, '慢消费者应从订阅集合移除');
  assert.ok(gateway.connectionCount < before, '连接数应下降');
});

test('慢消费者：断流前收到连接级 error 事件', async () => {
  const session = await newSession('ws-slow-event');
  const client = await connect();
  await client.request('subscribe', { sessionId: session.id });

  const closed = new Promise<void>((resolve) => client.ws.on('close', () => resolve()));

  client.ws.pause(); // 停止读取，让服务端写堆积越过 1KB 阈值
  const big = 'x'.repeat(60_000);
  for (let i = 0; i < 200 && liveHub.subscriberCount(session.id) > 0; i += 1) {
    liveHub.broadcast(session.id, eventEnvelope('message', { big }));
  }
  client.ws.resume(); // 恢复读取，把已发出的帧（含最后那条 error）收下来

  await closed;
  const last = client.events.at(-1);
  assert.equal(last?.type, 'event', '断流前最后一帧应是事件');
  assert.equal(last?.method, 'error');
  assert.equal(last?.payload.code, 'SLOW_CONSUMER');
  assert.equal(last?.payload.message, '客户端消费过慢，连接将被断开');
});

test('未订阅的旁观者在他人会话跑动期间零事件', async () => {
  const created = await newSession('ws-bystander');

  const listener = await connect();
  const bystander = await connect();
  await bystander.waitEvent('connection.ready');

  await listener.request('subscribe', { sessionId: created.id });
  await listener.request('send', { sessionId: created.id, prompt: '你好' });
  await listener.waitEvent('run.status');
  await sleep(300);

  assert.ok(listener.events.length > 1, '订阅者应收到会话事件');
  assert.deepEqual(bystander.events.map((e) => e.method), ['connection.ready'], '未订阅者不应收到任何会话事件');

  listener.close();
  bystander.close();
});

test('WS send：定位必须且只能一个，agentId 首帧缺 modelId、sessionId 分支带新建参数均 VALIDATION', async () => {
  await seedAgent('ws-send-validate');
  seedDevelopmentDir(env.workspaceDir, 'ws-send-validate');
  const created = await newSession('ws-send-validate-session');
  const client = await connect();

  const noTarget = await client.request('send', { prompt: 'hi' });
  assert.equal(noTarget.error?.code, 'VALIDATION');

  const bothTargets = await client.request('send', { sessionId: created.id, agentId: 'ws-send-validate', prompt: 'hi' });
  assert.equal(bothTargets.error?.code, 'VALIDATION');

  const noModel = await client.request('send', { agentId: 'ws-send-validate', prompt: 'hi' });
  assert.equal(noModel.error?.code, 'VALIDATION');
  assert.match(noModel.error?.message ?? '', /modelId 必填/);

  const invalidModel = await client.request('send', {
    agentId: 'ws-send-validate',
    prompt: 'hi',
    modelId: 'mdl_missing_for_ws',
  });
  assert.equal(invalidModel.error?.code, 'VALIDATION');
  assert.match(invalidModel.error?.message ?? '', /不存在/);

  // sessionId 续聊只认会话自身设置：任何新建参数都拒绝，显式 null 也算出现
  for (const extra of [
    { modelId: TEST_MODEL_ID },
    { modelId: null },
    { mode: 'read_only' },
    { mode: null },
    { effort: 'max' },
    { effort: null },
  ]) {
    const rejected = await client.request('send', { sessionId: created.id, prompt: 'hi', ...extra });
    assert.equal(rejected.error?.code, 'VALIDATION', JSON.stringify(extra));
  }

  // 非字符串 modelId 在真实服务路径上同样是 VALIDATION
  const nonStringModel = await client.request('send', { agentId: 'ws-send-validate', prompt: 'hi', modelId: 42 });
  assert.equal(nonStringModel.error?.code, 'VALIDATION');

  // 模型切换不接受空串
  const emptySwitch = await client.request('model.switch', { sessionId: created.id, modelId: '' });
  assert.equal(emptySwitch.error?.code, 'VALIDATION');
  client.close();
});

test('WS send 只给 agentId：每次新建会话，首个 run 使用请求的 model/mode/effort', async () => {
  await seedAgent('ws-new-session');
  seedDevelopmentDir(env.workspaceDir, 'ws-new-session');
  // agentId 首帧落在 runtime 阶段：必须先有 COMPLETED 的生产状态与最新产物
  seedPipelineState(agentRootIn(env.workspaceDir, 'ws-new-session'), 'demo');
  mkdirSync(join(agentRootIn(env.workspaceDir, 'ws-new-session'), 'development', 'output', 'agents', 'demo', 'v1'), {
    recursive: true,
  });
  const client = await connect();

  const first = await client.request('send', { agentId: 'ws-new-session', modelId: TEST_MODEL_ID, prompt: '第一次' });
  assert.equal(first.error, null);
  assert.equal(first.payload.modelId, TEST_MODEL_ID);
  assert.equal(first.payload.modelName, 'test-sonnet');
  assert.equal(first.payload.effort, 'high');
  await client.waitEvent(
    'run.status',
    (e) => e.payload.id === first.payload.runId && e.payload.status === 'succeeded',
  );

  const second = await client.request('send', {
    agentId: 'ws-new-session',
    modelId: TEST_MODEL_ALT_ID,
    mode: 'read_only',
    effort: 'max',
    prompt: '第二次',
  });
  assert.equal(second.error, null);
  assert.equal(second.payload.modelId, TEST_MODEL_ALT_ID);
  assert.equal(second.payload.modelName, 'test-opus');
  assert.equal(second.payload.effort, 'max');
  await client.waitEvent(
    'run.status',
    (e) => e.payload.id === second.payload.runId && e.payload.status === 'succeeded',
  );

  assert.notEqual(first.payload.sessionId, second.payload.sessionId, '首帧 send 不得复用已有会话');
  assert.notEqual(first.payload.runId, second.payload.runId);

  const sessions = await sessionService.listSessions({ agentId: 'ws-new-session' });
  assert.equal(sessions.total, 2, '两次 send 各落一行会话');
  const firstSession = await sessionService.getSession(first.payload.sessionId);
  const secondSession = await sessionService.getSession(second.payload.sessionId);
  assert.deepEqual(
    [firstSession.modelId, firstSession.approvalMode, firstSession.effort],
    [TEST_MODEL_ID, 'workspace_write', 'high'],
  );
  assert.deepEqual(
    [secondSession.modelId, secondSession.approvalMode, secondSession.effort],
    [TEST_MODEL_ALT_ID, 'read_only', 'max'],
  );
  assert.equal(secondSession.resumeSessionId, null, '新建会话首跑前没有 resume 标识');

  // 最近一次 run 收到的是请求里的模型与会话参数
  assert.equal(FakeAdapter.lastModel?.modelName, 'test-opus');
  assert.equal(FakeAdapter.lastMode, 'read_only');
  assert.equal(FakeAdapter.lastEffort, 'max');
  client.close();
});

test('WS send 只给 agentId：一个 runtime 首帧停在审批时，另一个首帧仍能建会话并起 run', async () => {
  await seedAgent('ws-runtime-concurrent');
  seedDevelopmentDir(env.workspaceDir, 'ws-runtime-concurrent');
  // agentId 首帧落在 runtime 阶段：必须先有 COMPLETED 的生产状态与最新产物
  seedPipelineState(agentRootIn(env.workspaceDir, 'ws-runtime-concurrent'), 'demo');
  mkdirSync(join(agentRootIn(env.workspaceDir, 'ws-runtime-concurrent'), 'development', 'output', 'agents', 'demo', 'v1'), {
    recursive: true,
  });
  const client = await connect();

  // 第一个首帧停在审批上：整个窗口内该 run 必须保持活跃，实例级串行实现会卡住第二个首帧
  const first = await client.request('send', {
    agentId: 'ws-runtime-concurrent',
    modelId: TEST_MODEL_ID,
    prompt: FAKE_TRIGGER.approval,
  });
  assert.equal(first.error, null);
  await waitPending(first.payload.sessionId);
  const parked = await sessionService.getRun(first.payload.runId);
  assert.ok(parked.waiting, '第一个 run 必须停在审批上');

  const second = await client.request('send', {
    agentId: 'ws-runtime-concurrent',
    modelId: TEST_MODEL_ID,
    prompt: '并发二',
  });
  assert.equal(second.error, null);
  assert.notEqual(first.payload.sessionId, second.payload.sessionId, '第二个首帧不得复用会话');
  assert.notEqual(first.payload.runId, second.payload.runId);

  await client.waitEvent('run.status', (e) => e.payload.id === second.payload.runId && e.payload.status === 'succeeded');
  assert.equal((await sessionService.getRun(second.payload.runId)).status, 'succeeded');

  await sessionService.abortRun(first.payload.runId);
  client.close();
});

test('WS send 撞上活跃 run 时回 CONFLICT 错误回执', async () => {
  const created = await newSession('ws-conflict');

  const client = await connect();
  // 停在审批上：第一个 run 在第二次 send 时必然仍活跃
  const first = await client.request('send', { sessionId: created.id, prompt: FAKE_TRIGGER.approval });
  assert.equal(first.error, null);
  await waitPending(created.id);

  // 第二个 send 必须被拒绝而不是静默失败
  const second = await client.request('send', { sessionId: created.id, prompt: '第二个' });
  assert.equal(second.type, 'response');
  assert.equal(second.error?.code, 'CONFLICT');
  await sessionService.abortRun(first.payload.runId);
  client.close();
});

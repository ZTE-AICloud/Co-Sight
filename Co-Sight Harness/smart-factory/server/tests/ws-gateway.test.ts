import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { WebSocket } from 'ws';
import { AppError, NotFoundError } from '../src/shared/errors.js';
import type { Message, Run, Session } from '../src/shared/types/index.js';
import { eventEnvelope } from '../src/shared/live/envelope.js';
import type { SendInput, SendResult, WsHandlers } from '../src/shared/live/ws-gateway.js';
import { TEST_MODEL_ALT_ID, TEST_MODEL_ID } from './helpers/workspace-stub.js';

// 拉长心跳周期：本文件没有空闲断连的用例，别让扫描线程搅局
process.env.WS_HEARTBEAT_MS = '60000';

const { attachWsGateway } = await import('../src/shared/live/ws-gateway.js');
const { liveHub } = await import('../src/shared/live/live-hub.js');
const { config } = await import('../src/config/index.js');

const message: Message = {
  id: 'msg_gateway',
  sessionId: 'sess_gateway',
  runId: 'run_gateway',
  seq: 1,
  role: 'user',
  type: 'text',
  status: null,
  content: { text: '你好' },
  createdAt: '2026-10-19T00:00:00.000Z',
};

const run: Run = {
  id: 'run_gateway',
  sessionId: 'sess_gateway',
  instanceId: 'inst_gateway',
  status: 'running',
  error: null,
  startedAt: '2026-10-19T00:00:00.000Z',
  finishedAt: null,
  createdAt: '2026-10-19T00:00:00.000Z',
  waiting: null,
};

const sessResult: SendResult = {
  sessionId: 'sess_gateway',
  runId: 'run_gateway',
  instanceId: 'inst_gateway',
  status: 'running',
  effort: 'medium',
  modelId: TEST_MODEL_ID,
  modelName: 'test-sonnet',
  modelFellBack: false,
  message,
  run,
};

const session: Session = {
  id: 'sess_switch',
  instanceId: 'inst_gateway',
  name: '网关测试会话',
  status: 'not_started',
  modelId: TEST_MODEL_ID,
  resumeSessionId: null,
  approvalMode: 'read_only',
  approvedAll: false,
  effort: 'medium',
  messageCount: 0,
  lastMessage: null,
  firstUserMessage: null,
  createdAt: '2026-10-19T00:00:00.000Z',
  updatedAt: '2026-10-19T00:00:00.000Z',
  instance: {
    id: 'inst_gateway',
    agentId: 'agent_1',
    stage: 'development',
    engine: 'claude-cli',
    createdAt: '2026-10-19T00:00:00.000Z',
    updatedAt: '2026-10-19T00:00:00.000Z',
  },
};

const historyResult = {
  sessionId: 'sess_hist',
  total: 1,
  messages: [
    {
      id: 'msg_hist',
      sessionId: 'sess_hist',
      runId: null,
      role: 'user' as const,
      type: 'text' as const,
      content: '{"text":"hi"}',
      createdAt: '2026-10-19T00:00:00.000Z',
    },
  ],
};

interface Call {
  method: string;
  input: any;
}

const calls: Call[] = [];
const rejectedHistorySessions = new Set<string>();
let nextHistoryError: Error | null = null;
let subscribedWhenSendCalled = -1;
let nextSend: (input: SendInput) => SendResult = () => sessResult;

function lastCall(method: string): Call | undefined {
  return calls.findLast((call) => call.method === method);
}

const handlers: WsHandlers = {
  async send(input) {
    calls.push({ method: 'send', input });
    subscribedWhenSendCalled = input.sessionId ? liveHub.subscriberCount(input.sessionId) : -1;
    return nextSend(input);
  },
  async abortRun(input) {
    calls.push({ method: 'abortRun', input });
    return run;
  },
  async respond(input) {
    calls.push({ method: 'respond', input });
    return message;
  },
  async respondApproval(input) {
    calls.push({ method: 'respondApproval', input });
    return message;
  },
  async respondTool(input) {
    calls.push({ method: 'respondTool', input });
    return message;
  },
  async switchModel(input) {
    calls.push({ method: 'switchModel', input });
    return session;
  },
  async switchMode(input) {
    calls.push({ method: 'switchMode', input });
    return session;
  },
  async switchEffort(input) {
    calls.push({ method: 'switchEffort', input });
    return session;
  },
  async history(input) {
    calls.push({ method: 'history', input });
    if (rejectedHistorySessions.has(input.sessionId)) throw new NotFoundError(`会话 ${input.sessionId}`);
    if (nextHistoryError) {
      const error = nextHistoryError;
      nextHistoryError = null;
      throw error;
    }
    return historyResult;
  },
  async subscribeInfo(sessionId) {
    calls.push({ method: 'subscribeInfo', input: { sessionId } });
    return null;
  },
};

interface Envelope {
  id: string;
  type: 'request' | 'response' | 'event';
  method: string;
  payload?: any;
  error?: { code: string; message: string } | null;
}

interface Client {
  ws: WebSocket;
  request(method: string, payload?: unknown): Promise<Envelope>;
  /** 发送原始帧；responseId 指定期望回执的 id（解析失败帧的 id 为空串）。 */
  sendRaw(raw: string, responseId?: string): Promise<Envelope>;
  waitEvent(method: string, timeoutMs?: number): Promise<Envelope>;
  close(): void;
}

let server: Server;
let gateway: { close(): void };
let url = '';
let requestSequence = 0;

async function connect(): Promise<Client> {
  const ws = new WebSocket(url);
  const pending = new Map<string, (env: Envelope) => void>();
  const eventWaiters: { method: string; resolve: (env: Envelope) => void }[] = [];
  // connection.ready 在 open 前后随时可能到达，先缓存，waitEvent 再来取
  const bufferedEvents: Envelope[] = [];

  ws.on('message', (raw) => {
    const envelope = JSON.parse(raw.toString()) as Envelope;
    if (envelope.type === 'event') {
      const index = eventWaiters.findIndex((waiter) => waiter.method === envelope.method);
      if (index >= 0) eventWaiters.splice(index, 1)[0].resolve(envelope);
      else bufferedEvents.push(envelope);
      return;
    }
    if (envelope.type !== 'response') return;
    pending.get(envelope.id)?.(envelope);
    pending.delete(envelope.id);
  });

  await new Promise<void>((resolve) => ws.on('open', () => resolve()));

  return {
    ws,
    async request(method, payload) {
      requestSequence += 1;
      const id = `req_${requestSequence}`;
      const answer = new Promise<Envelope>((resolve) => pending.set(id, resolve));
      ws.send(JSON.stringify({ id, type: 'request', method, timestamp: Date.now(), payload }));
      return answer;
    },
    sendRaw(raw, responseId = '') {
      const answer = new Promise<Envelope>((resolve) => pending.set(responseId, resolve));
      ws.send(raw);
      return answer;
    },
    waitEvent(method, timeoutMs = 500) {
      const buffered = bufferedEvents.findIndex((envelope) => envelope.method === method);
      if (buffered >= 0) return Promise.resolve(bufferedEvents.splice(buffered, 1)[0]);

      return new Promise<Envelope>((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error(`等待事件 ${method} 超时`)), timeoutMs);
        eventWaiters.push({
          method,
          resolve: (envelope) => {
            clearTimeout(timer);
            resolve(envelope);
          },
        });
      });
    },
    close() {
      ws.close();
    },
  };
}

before(async () => {
  server = createServer();
  gateway = attachWsGateway(server, handlers);
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  url = `ws://127.0.0.1:${(server.address() as AddressInfo).port}${config.wsPath}`;
});

after(async () => {
  gateway.close();
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

test('send 带 sessionId：先订阅再调用处理器，响应直接给出顶层 id', async () => {
  nextSend = () => sessResult;
  const client = await connect();

  const answer = await client.request('send', { sessionId: 'sess_send', prompt: '你好' });

  assert.equal(answer.error, null);
  assert.equal(answer.method, 'send.result');
  assert.equal(answer.payload.sessionId, 'sess_gateway');
  assert.equal(answer.payload.runId, 'run_gateway');
  assert.equal(answer.payload.instanceId, 'inst_gateway');
  assert.equal(answer.payload.status, 'running');
  assert.equal(answer.payload.effort, 'medium');
  assert.equal(answer.payload.modelId, TEST_MODEL_ID);
  assert.equal(answer.payload.modelName, 'test-sonnet');
  assert.equal(answer.payload.modelFellBack, false);
  assert.deepEqual(answer.payload.message.content, { text: '你好' });
  assert.equal(answer.payload.run.id, 'run_gateway');
  assert.equal(answer.payload.run.status, 'running');
  assert.equal(subscribedWhenSendCalled, 1, '处理器被调用时连接已订阅');
  assert.deepEqual(lastCall('send')?.input, {
    sessionId: 'sess_send',
    prompt: '你好',
  });
  client.close();
});

test('send 带 agentId：回调里订阅新会话并原样返回结果', async () => {
  let resolvedSessionId = '';
  nextSend = (input) => {
    input.onSessionResolved?.('sess_from_agent');
    resolvedSessionId = 'sess_from_agent';
    return { ...sessResult, sessionId: 'sess_from_agent' };
  };
  const client = await connect();

  const answer = await client.request('send', { agentId: 'agent_1', modelId: TEST_MODEL_ID, prompt: 'hi' });

  assert.equal(answer.error, null);
  assert.equal(answer.method, 'send.result');
  assert.equal(answer.payload.sessionId, resolvedSessionId);
  assert.equal(liveHub.subscriberCount('sess_from_agent'), 1, 'onSessionResolved 应完成订阅');
  const input = lastCall('send')?.input;
  assert.equal(input.agentId, 'agent_1');
  assert.equal(input.sessionId, undefined);
  assert.equal(input.modelId, TEST_MODEL_ID);
  assert.equal(input.prompt, 'hi');
  assert.equal(typeof input.onSessionResolved, 'function');
  client.close();
});

test('send 首帧 modelId：字符串透传，非字符串 VALIDATION', async () => {
  const client = await connect();
  const before = calls.length;

  const answer = await client.request('send', {
    agentId: 'agent_1',
    prompt: 'hi',
    modelId: TEST_MODEL_ALT_ID,
    mode: 'read_only',
    effort: 'max',
  });
  assert.equal(answer.error, null);
  assert.equal(lastCall('send')?.input.modelId, TEST_MODEL_ALT_ID);
  assert.equal(lastCall('send')?.input.mode, 'read_only');
  assert.equal(lastCall('send')?.input.effort, 'max');

  const invalid = await client.request('send', { agentId: 'agent_1', prompt: 'hi', modelId: 42 });
  assert.equal(invalid.error?.code, 'VALIDATION');
  assert.equal(calls.length, before + 1, '非法 modelId 不得触达业务处理器');
  client.close();
});

test('send 定位至多一个：都不给透传为自由对话，两个都给 / 缺 prompt → VALIDATION', async () => {
  const client = await connect();
  const before = calls.length;

  // 都不给：自由对话首帧，网关不拦，原样交给业务层
  const chat = await client.request('send', { prompt: 'hi', modelId: TEST_MODEL_ID });
  assert.equal(chat.method, 'send.result');
  assert.equal(chat.error, null);
  assert.equal(lastCall('send')?.input.agentId, undefined);
  assert.equal(lastCall('send')?.input.sessionId, undefined);

  const both = await client.request('send', {
    prompt: 'hi',
    sessionId: 'sess_x',
    agentId: 'agent_1',
    modelId: TEST_MODEL_ID,
  });
  assert.equal(both.error?.code, 'VALIDATION');

  const noPrompt = await client.request('send', { sessionId: 'sess_x' });
  assert.equal(noPrompt.method, 'send.result');
  assert.equal(noPrompt.error?.code, 'VALIDATION');

  assert.equal(calls.length, before + 1, '只有自由对话那一次触达业务处理器');
  client.close();
});

test('history 分派后以 history.result 响应', async () => {
  const client = await connect();

  const answer = await client.request('history', {
    sessionId: 'sess_hist',
    limit: 10,
    offset: 5,
    includeTelemetry: true,
  });

  assert.equal(answer.error, null);
  assert.equal(answer.method, 'history.result');
  assert.deepEqual(answer.payload, historyResult);
  assert.deepEqual(lastCall('history')?.input, {
    sessionId: 'sess_hist',
    limit: 10,
    offset: 5,
    includeTelemetry: true,
  });
  client.close();
});

test('history 成功后连接订阅该会话，可收到实时事件', async () => {
  const client = await connect();

  const answer = await client.request('history', { sessionId: 'sess_hist_live' });
  assert.equal(answer.error, null);
  assert.equal(liveHub.subscriberCount('sess_hist_live'), 1, 'history 成功后应完成订阅');

  const received = client.waitEvent('message');
  liveHub.broadcast('sess_hist_live', eventEnvelope('message', message));
  const event = await received;
  assert.deepEqual(event.payload, message);
  client.close();
});

test('history 被处理器拒绝时不留下订阅', async () => {
  rejectedHistorySessions.add('sess_hist_fail');
  const client = await connect();

  const answer = await client.request('history', { sessionId: 'sess_hist_fail' });

  assert.equal(answer.error?.code, 'NOT_FOUND');
  assert.equal(liveHub.subscriberCount('sess_hist_fail'), 0, '失败的历史请求应回滚订阅');
  client.close();
  rejectedHistorySessions.delete('sess_hist_fail');
});

test('approval.respond / tool.respond / model.switch / mode.switch / effort.switch 分派载荷', async () => {
  const client = await connect();

  const approval = await client.request('approval.respond', { approvalId: 'appr_1', decision: 'approved' });
  assert.equal(approval.error, null);
  assert.equal(approval.method, 'approval.respond.result');
  assert.deepEqual(approval.payload, { approvalId: 'appr_1', decision: 'approved', resolved: true });
  assert.deepEqual(lastCall('respondApproval')?.input, { approvalId: 'appr_1', decision: 'approved' });

  const invalid = await client.request('approval.respond', { approvalId: 'appr_1', decision: 'maybe' });
  assert.equal(invalid.method, 'approval.respond.result');
  assert.equal(invalid.error?.code, 'VALIDATION');

  const tool = await client.request('tool.respond', { toolCallId: 'tool_1', answers: { '问题?': ['A'] } });
  assert.equal(tool.error, null);
  assert.equal(tool.method, 'tool.respond.result');
  assert.deepEqual(tool.payload, { toolCallId: 'tool_1', received: true });
  assert.deepEqual(lastCall('respondTool')?.input, { toolCallId: 'tool_1', answers: { '问题?': ['A'] } });

  const model = await client.request('model.switch', { sessionId: 'sess_switch', modelId: TEST_MODEL_ALT_ID });
  assert.equal(model.error, null);
  assert.equal(model.method, 'model.switch.result');
  assert.deepEqual(model.payload, { sessionId: 'sess_switch', modelId: TEST_MODEL_ALT_ID, appliesTo: 'nextRun' });
  assert.deepEqual(lastCall('switchModel')?.input, { sessionId: 'sess_switch', modelId: TEST_MODEL_ALT_ID });

  const mode = await client.request('mode.switch', { sessionId: 'sess_switch', mode: 'workspace_write' });
  assert.equal(mode.error, null);
  assert.equal(mode.method, 'mode.switch.result');
  assert.deepEqual(mode.payload, { sessionId: 'sess_switch', mode: 'workspace_write' });
  assert.deepEqual(lastCall('switchMode')?.input, { sessionId: 'sess_switch', mode: 'workspace_write' });

  const effort = await client.request('effort.switch', { sessionId: 'sess_switch', effort: 'high' });
  assert.equal(effort.error, null);
  assert.equal(effort.method, 'effort.switch.result');
  assert.deepEqual(effort.payload, { sessionId: 'sess_switch', effort: 'high' });
  assert.deepEqual(lastCall('switchEffort')?.input, { sessionId: 'sess_switch', effort: 'high' });

  client.close();
});

test('tool.respond 的数组 answers 原样透传，缺失 answers 被拒', async () => {
  const client = await connect();
  const before = calls.length;
  const answers = [{ question: 'Q', answer: 'A' }];

  const tool = await client.request('tool.respond', { toolCallId: 'tool_array', answers });
  assert.equal(tool.error, null);
  assert.deepEqual(lastCall('respondTool')?.input, { toolCallId: 'tool_array', answers });

  const missing = await client.request('tool.respond', { toolCallId: 'tool_array' });
  assert.equal(missing.error?.code, 'VALIDATION');
  assert.equal(calls.length, before + 1, '缺失 answers 不得触达业务处理器');
  client.close();
});

test('未知方法：id 原样回，method 为 error，code 为 VALIDATION', async () => {
  const client = await connect();
  const answer = await client.sendRaw(
    JSON.stringify({ id: 'req_unknown', type: 'request', method: 'nope.method', timestamp: Date.now() }),
    'req_unknown',
  );
  assert.equal(answer.type, 'response');
  assert.equal(answer.id, 'req_unknown');
  assert.equal(answer.method, 'error');
  assert.equal(answer.error?.code, 'VALIDATION');
  client.close();
});

test('信封解析失败：id 为空串，method 为 error，code 为 VALIDATION', async () => {
  const client = await connect();
  const answer = await client.sendRaw('{not json');
  assert.equal(answer.type, 'response');
  assert.equal(answer.id, '');
  assert.equal(answer.method, 'error');
  assert.equal(answer.error?.code, 'VALIDATION');
  client.close();
});

test('connection.ready 事件带 connectionId、restored=false、sessionId=null', async () => {
  const client = await connect();
  const ready = await client.waitEvent('connection.ready');
  assert.match(ready.payload.connectionId, /^conn_\d+$/);
  assert.equal(ready.payload.restored, false);
  assert.equal(ready.payload.sessionId, null);
  client.close();
});

test('ping 响应 method 为 pong，payload 带 serverTime', async () => {
  const client = await connect();
  const answer = await client.request('ping');
  assert.equal(answer.error, null);
  assert.equal(answer.method, 'pong');
  assert.equal(typeof answer.payload.serverTime, 'number');
  assert.ok(answer.payload.serverTime > 0);
  client.close();
});

test('unsubscribe 回 {sessionId, unsubscribed:true} 并退订', async () => {
  const client = await connect();
  await client.request('history', { sessionId: 'sess_unsub' });
  assert.equal(liveHub.subscriberCount('sess_unsub'), 1);

  const answer = await client.request('unsubscribe', { sessionId: 'sess_unsub' });
  assert.equal(answer.error, null);
  assert.equal(answer.method, 'unsubscribe.result');
  assert.deepEqual(answer.payload, { sessionId: 'sess_unsub', unsubscribed: true });
  assert.equal(liveHub.subscriberCount('sess_unsub'), 0);
  client.close();
});

test('run.abort 回 {runId, aborted:true}', async () => {
  const client = await connect();
  const answer = await client.request('run.abort', { runId: 'run_gateway' });
  assert.equal(answer.error, null);
  assert.equal(answer.method, 'run.abort.result');
  assert.deepEqual(answer.payload, { runId: 'run_gateway', aborted: true });
  assert.deepEqual(lastCall('abortRun')?.input, { runId: 'run_gateway' });
  client.close();
});

test('内部错误统一映射为 INTERNAL，响应 method 仍为 history.result', async () => {
  const client = await connect();

  nextHistoryError = new Error('boom');
  const internal = await client.request('history', { sessionId: 'sess_hist' });
  assert.equal(internal.method, 'history.result');
  assert.equal(internal.error?.code, 'INTERNAL');

  nextHistoryError = new AppError(502, 'FRAMEWORK_UNAVAILABLE', 'down');
  const unavailable = await client.request('history', { sessionId: 'sess_hist' });
  assert.equal(unavailable.method, 'history.result');
  assert.equal(unavailable.error?.code, 'INTERNAL');

  client.close();
});

test('message.respond 响应保持 {message}', async () => {
  const client = await connect();
  const answer = await client.request('message.respond', { messageId: 'msg_gateway', decision: 'approved' });
  assert.equal(answer.error, null);
  assert.equal(answer.method, 'message.respond.result');
  assert.equal(answer.payload.message.id, message.id);
  client.close();
});

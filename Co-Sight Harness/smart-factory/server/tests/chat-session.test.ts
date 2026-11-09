import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, realpathSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { AddressInfo } from 'node:net';
import { WebSocket } from 'ws';
import { prepareTestEnv } from './helpers/test-db.js';
import { startWorkspaceStub, TEST_MODEL_ID } from './helpers/workspace-stub.js';
import { TEST_WORKSPACE_ID } from './helpers/agents.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

/**
 * 自由对话（不选智能体）：`send` 只给 prompt + modelId，落一条目录会话。
 *
 * 三种形态的另外两种（agentId / sessionId）的行为不在这里重复，
 * 本文件只覆盖「都不给」这条新分支及其与 WS 网关的接线。
 */
const env = prepareTestEnv('chat-session');
const stub = await startWorkspaceStub(env);

const { prisma } = await import('../src/shared/prisma/client.js');
const { attachWsGateway } = await import('../src/shared/live/ws-gateway.js');
const { sessionService } = await import('../src/modules/session/session.service.js');
const { config } = await import('../src/config/index.js');
const { FAKE_TRIGGER } = await import('../src/shared/engine/fake-adapter.js');

interface Envelope {
  id: string;
  type: 'request' | 'response' | 'event';
  method: string;
  payload?: any;
  error?: { code: string; message: string } | null;
}

let api: TestApi;
let gateway: { close(): void };
let wsUrl = '';

/** 轮询 run 直到停在挂起（审批）上：撑开「活跃窗口」用。 */
async function waitRunWaiting(runId: string): Promise<void> {
  for (let i = 0; i < 100; i += 1) {
    const { body } = await api.get(`${API}/runs/detail?runId=${runId}`);
    if (body.waiting) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`run ${runId} 未在 5s 内停在挂起上`);
}

before(async () => {
  mkdirSync(join(env.home, 'files'), { recursive: true });
  api = await startTestApi();
  // WS 网关不认业务实现：与 server/src/index.ts 同一份接线
  gateway = attachWsGateway(api.server, {
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
  wsUrl = `ws://127.0.0.1:${(api.server.address() as AddressInfo).port}${config.wsPath}`;
});

after(async () => {
  gateway.close();
  await api.close();
  await stub.close();
  await prisma.$disconnect();
});

/** 最小 WS 客户端：按 id 匹配响应，事件按方法收集。 */
async function connect(): Promise<{
  request(method: string, payload?: unknown): Promise<Envelope>;
  waitEvent(method: string, predicate?: (envelope: Envelope) => boolean): Promise<Envelope>;
  close(): void;
}> {
  const ws = new WebSocket(wsUrl);
  const events: Envelope[] = [];
  const pending = new Map<string, (envelope: Envelope) => void>();

  ws.on('message', (raw) => {
    const envelope = JSON.parse(raw.toString()) as Envelope;
    if (envelope.type === 'event') {
      events.push(envelope);
      return;
    }
    pending.get(envelope.id)?.(envelope);
    pending.delete(envelope.id);
  });
  await new Promise<void>((resolve) => ws.on('open', () => resolve()));

  let sequence = 0;
  return {
    async request(method, payload) {
      sequence += 1;
      const id = `req_${sequence}`;
      const answer = new Promise<Envelope>((resolve) => pending.set(id, resolve));
      ws.send(JSON.stringify({ id, type: 'request', method, timestamp: Date.now(), payload }));
      return answer;
    },
    async waitEvent(method, predicate = () => true) {
      const deadline = Date.now() + 5000;
      while (Date.now() < deadline) {
        const found = events.find((item) => item.method === method && predicate(item));
        if (found) return found;
        await new Promise((resolve) => setTimeout(resolve, 20));
      }
      throw new Error(`未在 5000ms 内收到事件 ${method}`);
    },
    close() {
      ws.close();
    },
  };
}

test('自由对话：只给 prompt + modelId，落当前工作区目录的目录会话', async () => {
  const sent = await api.post(`${API}/messages/send`, { prompt: '你好', modelId: TEST_MODEL_ID });
  assert.equal(sent.status, 200, JSON.stringify(sent.body));
  assert.equal(sent.body.status, 'running');

  const detail = await api.get(`${API}/sessions/detail?sessionId=${sent.body.sessionId}`);
  assert.equal(detail.status, 200);
  assert.equal(detail.body.instance.agentId, null);
  assert.equal(detail.body.instance.stage, 'runtime', '自由对话是运行时聊天，默认历史可见');
  assert.equal(detail.body.instance.cwd, realpathSync(env.workspaceDir));

  const run = await api.waitTerminal(sent.body.run.id);
  assert.equal(run.status, 'succeeded');

  const messages = await api.get(`${API}/messages/list?sessionId=${sent.body.sessionId}`);
  assert.deepEqual(
    messages.body.items.map((item: any) => [item.role, item.type]),
    [
      ['user', 'text'],
      ['assistant', 'text'],
    ],
  );
});

test('自由对话：只有附件、没有正文也发得出去', async () => {
  const file = join(env.home, 'files', 'note.txt');
  writeFileSync(file, 'hello');

  const sent = await api.post(`${API}/messages/send`, {
    prompt: '',
    attachments: [{ path: file }],
    modelId: TEST_MODEL_ID,
  });
  assert.equal(sent.status, 200, JSON.stringify(sent.body));
  assert.equal((await api.waitTerminal(sent.body.run.id)).status, 'succeeded');
});

test('自由对话：会话建好之后按 sessionId 续聊', async () => {
  const first = await api.post(`${API}/messages/send`, { prompt: '第一句', modelId: TEST_MODEL_ID });
  assert.equal(first.status, 200);
  await api.waitTerminal(first.body.run.id);

  const second = await api.post(`${API}/messages/send`, { sessionId: first.body.sessionId, prompt: '第二句' });
  assert.equal(second.status, 200, JSON.stringify(second.body));
  assert.equal(second.body.sessionId, first.body.sessionId);
  assert.equal((await api.waitTerminal(second.body.run.id)).status, 'succeeded');
});

test('自由对话：没有生效工作区时落到 chatRoot，并自动建目录', async () => {
  stub.activeWorkspaceId = null;
  try {
    const sent = await api.post(`${API}/messages/send`, { prompt: '无工作区也能聊', modelId: TEST_MODEL_ID });
    assert.equal(sent.status, 200, JSON.stringify(sent.body));

    const detail = await api.get(`${API}/sessions/detail?sessionId=${sent.body.sessionId}`);
    assert.equal(detail.body.instance.stage, 'runtime', '自由对话是运行时聊天，默认历史可见');
    assert.equal(detail.body.instance.agentId, null);
    assert.equal(detail.body.instance.cwd, realpathSync(config.chatRoot));
    assert.ok(existsSync(config.chatRoot), '兜底目录必须被创建');

    const list = await api.get(`${API}/sessions/list?cwd=${encodeURIComponent(realpathSync(config.chatRoot))}`);
    assert.equal(list.status, 200);
    assert.ok(list.body.items.some((item: any) => item.id === sent.body.sessionId));

    assert.equal((await api.waitTerminal(sent.body.run.id)).status, 'succeeded');
  } finally {
    stub.activeWorkspaceId = TEST_WORKSPACE_ID;
  }
});

test('自由对话：缺 modelId 400；sessionId 与 agentId 同给 400；续聊多带 modelId 400', async () => {
  const missingModel = await api.post(`${API}/messages/send`, { prompt: '你好' });
  assert.equal(missingModel.status, 400);
  assert.equal(missingModel.body.error, 'BAD_REQUEST');

  const both = await api.post(`${API}/messages/send`, {
    prompt: '你好',
    sessionId: 'sess_x',
    agentId: 'agt_00000000-0000-4000-8000-000000000000',
    modelId: TEST_MODEL_ID,
  });
  assert.equal(both.status, 400);
  assert.equal(both.body.message, 'sessionId 与 agentId 不能同时给');

  const created = await api.post(`${API}/messages/send`, { prompt: '你好', modelId: TEST_MODEL_ID });
  assert.equal(created.status, 200);
  await api.waitTerminal(created.body.run.id);
  const extra = await api.post(`${API}/messages/send`, {
    sessionId: created.body.sessionId,
    prompt: '续聊',
    modelId: TEST_MODEL_ID,
  });
  assert.equal(extra.status, 400);
  assert.match(extra.body.message, /不接受 modelId/);
});

test('自由对话是 runtime：同一工作区可以并行两场（会话级仲裁，不是实例级）', async () => {
  const first = await api.post(`${API}/messages/send`, { prompt: FAKE_TRIGGER.approval, modelId: TEST_MODEL_ID });
  assert.equal(first.status, 200, JSON.stringify(first.body));
  await waitRunWaiting(first.body.run.id);

  // 第二条自由对话落在同一 cwd 的另一个会话上：runtime 不按实例互斥
  const second = await api.post(`${API}/messages/send`, { prompt: '同时也能跑', modelId: TEST_MODEL_ID });
  assert.equal(second.status, 200, JSON.stringify(second.body));
  assert.notEqual(second.body.sessionId, first.body.sessionId, '每次自由对话都是新会话');
  assert.equal((await api.waitTerminal(second.body.run.id)).status, 'succeeded');

  await api.post(`${API}/runs/abort`, { runId: first.body.run.id });
  assert.equal((await api.waitTerminal(first.body.run.id)).status, 'aborted');
});

test('WS：首帧不带 agentId 也能建会话，并在这个连接上收到 chat.final', async () => {
  const client = await connect();
  try {
    const response = await client.request('send', { prompt: '你好', modelId: TEST_MODEL_ID });
    assert.equal(response.type, 'response');
    assert.equal(response.method, 'send.result');
    assert.equal(response.error, null, JSON.stringify(response.error));
    const sessionId = response.payload.sessionId as string;
    assert.ok(sessionId.startsWith('sess_'));

    const final = await client.waitEvent('chat.final', (item) => item.payload?.sessionId === sessionId);
    assert.equal(final.payload.content, '收到：你好');

    const detail = await api.get(`${API}/sessions/detail?sessionId=${sessionId}`);
    assert.equal(detail.body.instance.stage, 'runtime', '自由对话是运行时聊天，默认历史可见');
    assert.equal(detail.body.instance.cwd, realpathSync(env.workspaceDir));
  } finally {
    client.close();
  }
});

test('WS：sessionId 与 agentId 同时给返回 VALIDATION', async () => {
  const client = await connect();
  try {
    const response = await client.request('send', {
      prompt: '你好',
      sessionId: 'sess_x',
      agentId: 'agt_00000000-0000-4000-8000-000000000000',
      modelId: TEST_MODEL_ID,
    });
    assert.equal(response.type, 'response');
    assert.equal(response.error?.code, 'VALIDATION');
  } finally {
    client.close();
  }
});

import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { prepareTestEnv } from './helpers/test-db.js';
import { seedAgent, seedDevelopmentDir } from './helpers/agents.js';
import { TEST_MODEL_ID, startWorkspaceStub } from './helpers/workspace-stub.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

const env = prepareTestEnv('attachments');
const stub = await startWorkspaceStub(env);

const AGENT = 'att-agent';
const NOTES = join(env.workspaceDir, 'notes.md');
const SPEC = join(env.workspaceDir, 'spec', 'api.yaml');

let api: TestApi;

before(async () => {
  mkdirSync(join(env.workspaceDir, 'spec'), { recursive: true });
  writeFileSync(NOTES, '# 笔记\n');
  writeFileSync(SPEC, 'openapi: 3.0.0\n');
  await seedAgent(AGENT);
  seedDevelopmentDir(env.workspaceDir, AGENT);
  api = await startTestApi();
});

after(async () => {
  await api.close();
  await stub.close();
});

async function newSession(): Promise<string> {
  // 新契约：建会话必须绑定一个可运行的模型
  const created = await api.post(`${API}/sessions/create`, { agentId: AGENT, modelId: TEST_MODEL_ID });
  assert.equal(created.status, 200);
  return created.body.id;
}

/**
 * 发一轮并等它落终态，返回**整场会话**的消息。
 *
 * 按 sessionId 而不是 runId 取：用户消息不带 runId（`messagesRepo.append` 只在引擎事件里落 runId），
 * 按 runId 查会漏掉它 —— 而附件断言要看的正是那一条。
 */
async function sendRound(sessionId: string, payload: Record<string, unknown>) {
  const sent = await api.post(`${API}/messages/send`, { sessionId, ...payload });
  if (sent.status !== 200) return { sent, items: [] as any[], run: null };
  const run = await api.waitTerminal(sent.body.run.id);
  const history = await api.get(`${API}/messages/list?sessionId=${sessionId}&limit=200`);
  return { sent, items: history.body.items as any[], run };
}

/** 这一轮的用户消息（每场会话只有一轮，直接取最后一条 user text） */
function userMessageOf(items: any[]): any {
  const message = items.filter((item) => item.role === 'user' && item.type === 'text').at(-1);
  assert.ok(message, '没有找到用户消息');
  return message;
}

test('附件落进消息 content.files，正文保持用户原话', async () => {
  const sessionId = await newSession();
  const { sent, items } = await sendRound(sessionId, {
    prompt: '看看这两份材料',
    attachments: [{ path: NOTES }, { path: SPEC }],
  });
  assert.equal(sent.status, 200);

  const user = userMessageOf(items);
  assert.equal(user.content.text, '看看这两份材料', '落库正文不含附件清单');
  assert.deepEqual(user.content.files, [
    { id: 'file-1', name: NOTES },
    { id: 'file-2', name: SPEC },
  ]);
});

test('附件进引擎 prompt：终稿回显里能看到路径', async () => {
  const sessionId = await newSession();
  const { items } = await sendRound(sessionId, { prompt: '读一下', attachments: [NOTES] });

  // 桩适配器的终稿是「收到：<prompt>」—— 路径出现在这里，说明它确实到了引擎那一侧
  const assistant = items.filter((message) => message.role === 'assistant' && message.type === 'text').at(-1);
  assert.ok(assistant, '没有找到助手终稿');
  assert.match(assistant.content.text, /以下是用户指定的本机文件/);
  assert.ok(assistant.content.text.includes(NOTES));
});

test('只有附件、没有正文也能发', async () => {
  const sessionId = await newSession();
  const { sent, items } = await sendRound(sessionId, { prompt: '', attachments: [NOTES] });
  assert.equal(sent.status, 200);

  const user = userMessageOf(items);
  assert.equal(user.content.text, '');
  assert.equal(user.content.files.length, 1);
});

test('同一路径重复出现只留一份', async () => {
  const sessionId = await newSession();
  const { items } = await sendRound(sessionId, { prompt: '去重', attachments: [NOTES, { path: NOTES }] });

  const user = userMessageOf(items);
  assert.deepEqual(user.content.files, [{ id: 'file-1', name: NOTES }]);
});

test('不带附件时消息形状不变：content 里没有 files', async () => {
  const sessionId = await newSession();
  const { items } = await sendRound(sessionId, { prompt: '普通一句话' });

  const user = userMessageOf(items);
  assert.deepEqual(user.content, { text: '普通一句话' });
});

test('附件不在主目录 / 工作区内：也接受（浏览范围不设限）', async () => {
  // 放在 COSIGHT_HOME 下、但既不在主目录也不在工作区里：范围限制已取消
  const outside = join(env.home, 'outside.md');
  writeFileSync(outside, '# 界外\n');

  const sessionId = await newSession();
  const { sent, items } = await sendRound(sessionId, {
    prompt: '界外',
    attachments: [{ path: outside }],
  });
  assert.equal(sent.status, 200);

  const user = userMessageOf(items);
  assert.deepEqual(user.content.files, [{ id: 'file-1', name: outside }]);
});

test('附件路径不存在：404，且不建 run', async () => {
  const sessionId = await newSession();
  const { sent } = await sendRound(sessionId, { prompt: '缺失', attachments: [join(env.workspaceDir, 'nope.md')] });
  assert.equal(sent.status, 404);
  assert.equal(sent.body.error, 'NOT_FOUND');

  const runs = await api.get(`${API}/runs/list?sessionId=${sessionId}`);
  assert.deepEqual(runs.body.items, []);
});

test('附件指向目录：400', async () => {
  const sessionId = await newSession();
  const { sent } = await sendRound(sessionId, { prompt: '目录', attachments: [join(env.workspaceDir, 'spec')] });
  assert.equal(sent.status, 400);
  assert.equal(sent.body.error, 'BAD_REQUEST');
});

test('attachments 不是数组 / 超上限：400', async () => {
  const sessionId = await newSession();

  const notArray = await api.post(`${API}/messages/send`, { sessionId, prompt: 'x', attachments: NOTES });
  assert.equal(notArray.status, 400);

  const tooMany = await api.post(`${API}/messages/send`, {
    sessionId,
    prompt: 'x',
    attachments: Array.from({ length: 21 }, () => ({ path: NOTES })),
  });
  assert.equal(tooMany.status, 400);
});

test('既没有正文也没有附件：400', async () => {
  const sessionId = await newSession();
  const { sent } = await sendRound(sessionId, { prompt: '   ' });
  assert.equal(sent.status, 400);
  assert.equal(sent.body.error, 'BAD_REQUEST');
});

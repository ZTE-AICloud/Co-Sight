import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { prepareTestEnv } from './helpers/test-db.js';
import { seedAgent, seedDevelopmentDir } from './helpers/agents.js';
import { startWorkspaceStub, TEST_MODEL_ID } from './helpers/workspace-stub.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

const env = prepareTestEnv('message-persistence');
const stub = await startWorkspaceStub(env);

const { prisma } = await import('../src/shared/prisma/client.js');
const { FAKE_TRIGGER } = await import('../src/shared/engine/fake-adapter.js');

let api: TestApi;

before(async () => {
  await seedAgent('msg-persist');
  seedDevelopmentDir(env.workspaceDir, 'msg-persist');
  api = await startTestApi();
});

after(async () => {
  await api.close();
  await stub.close();
  await prisma.$disconnect();
});

/**
 * 建会话 → 发一条消息 → 等 run 落终态 → 按 runId 读回这一轮的消息。
 *
 * 按 runId 查并且显式给 limit：默认取数窗口只覆盖一段，不足以断言整轮内容。
 */
async function runOnce(prompt: string): Promise<any[]> {
  const created = await api.post(`${API}/sessions/create`, { agentId: 'msg-persist', modelId: TEST_MODEL_ID });
  assert.equal(created.status, 200);

  const sent = await api.post(`${API}/messages/send`, { sessionId: created.body.id, prompt });
  assert.equal(sent.status, 200);

  const run = await api.waitTerminal(sent.body.run.id);
  assert.equal(run.status, 'succeeded');

  const history = await api.get(`${API}/messages/list?runId=${run.id}&limit=200`);
  assert.equal(history.status, 200);
  return history.body.items;
}

/** 该轮里恰好一条的某类消息 */
function oneOf(items: any[], type: string): any {
  const matched = items.filter((message) => message.type === type);
  assert.equal(matched.length, 1, `期望恰好一条 ${type} 消息，实际 ${matched.length} 条`);
  return matched[0];
}

test('引擎跑完一轮：思考与工具调用 / 结果都落到会话历史', async () => {
  const items = await runOnce(`${FAKE_TRIGGER.thinking}${FAKE_TRIGGER.tool}`);

  const thinking = oneOf(items, 'thinking');
  assert.equal(thinking.role, 'assistant');
  assert.match(thinking.content.text, /桩适配器/);

  const toolUse = oneOf(items, 'tool_use');
  assert.deepEqual(toolUse.content, { toolCallId: 'toolu_fake_1', toolName: 'Bash', input: { command: 'echo hi' } });

  const toolResult = oneOf(items, 'tool_result');
  assert.equal(toolResult.role, 'assistant');
  assert.deepEqual(toolResult.content, { toolCallId: 'toolu_fake_1', output: 'hi', isError: false });

  // user 消息不挂在 run 上，这里只看引擎产出的四条：思考 → 工具调用 → 工具结果 → 收尾文本
  assert.deepEqual(
    items.map((message) => message.type),
    ['thinking', 'tool_use', 'tool_result', 'text'],
  );
  assert.equal(items[3].content.text, '收到：带思考带工具');
});

test('未带标记的提示词：历史仍只有一条助手文本（默认路径不变）', async () => {
  const items = await runOnce('你好');
  assert.deepEqual(
    items.map((message) => message.type),
    ['text'],
  );
  assert.equal(items[0].content.text, '收到：你好');
});

/**
 * 创建后的元数据自动刷新：后端用用户那句需求生成 name / description / tags 并落库。
 *
 * 权威：server/src/modules/agent/agent-metadata.ts（触发、上下文、清洗、条件更新）。
 */
import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { prepareTestEnv } from './helpers/test-db.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';
import { startWorkspaceStub } from './helpers/workspace-stub.js';
import { TEST_WORKSPACE_ID } from './helpers/agents.js';

const env = prepareTestEnv('agent-metadata');
// prepareTestEnv 默认关闭；本文件打开，模型地址指向下面的本地桩，不出网。
process.env.AUTO_META = '1';
const { prisma } = await import('../src/shared/prisma/client.js');

const MODEL_ID = '11111111-2222-4333-8444-555555555555';
const TIMESTAMP = '2026-01-01T00:00:00.000Z';

/** 本地模型桩：可切换「正常 JSON / 坏 JSON」，并记录调用次数与最后一次请求体。 */
let llm: Server;
let api: TestApi;
let framework: Awaited<ReturnType<typeof startWorkspaceStub>>;
let reply = '{"name":"会议纪要助手","description":"把会议速记整理成待办清单。","tags":["会议","纪要","待办"]}';
let delayMs = 0;
const calls: Array<{ model: string; body: any }> = [];

before(async () => {
  llm = createServer((req, res) => {
    let raw = '';
    req.on('data', (chunk) => (raw += chunk));
    req.on('end', () => {
      calls.push({ model: req.headers.authorization ?? '', body: JSON.parse(raw) });
      setTimeout(() => {
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ content: [{ type: 'text', text: `\`\`\`json\n${reply}\n\`\`\`` }] }));
      }, delayMs);
    });
  });
  await new Promise<void>((resolve) => llm.listen(0, '127.0.0.1', resolve));
  const llmUrl = `http://127.0.0.1:${(llm.address() as AddressInfo).port}`;

  const stub = await startWorkspaceStub(env);
  framework = stub;
  stub.models.push({
    id: MODEL_ID,
    provider: 'anthropic',
    protocol: 'anthropic',
    label: '自动命名测试模型',
    modelName: 'test-meta',
    baseUrl: llmUrl,
    hasApiKey: true,
    isActive: false,
    apiKey: 'sk-meta',
    temperature: 1,
    topP: 1,
    maxOutputTokens: null,
    contextWindow: null,
    timeoutSeconds: 60,
    createdAt: TIMESTAMP,
    updatedAt: TIMESTAMP,
  });

  api = await startTestApi();
});

after(async () => {
  await api.close();
  await framework.close();
  await new Promise<void>((resolve) => llm.close(() => resolve()));
  await prisma.$disconnect();
});

let seq = 0;
async function create(input: string | null): Promise<any> {
  seq += 1;
  const { status, body } = await api.post(`${API}/agents`, {
    workspaceId: TEST_WORKSPACE_ID,
    name: `兜底名字-${seq}`,
    description: '兜底描述',
    tags: [],
    init: {
      ...(input === null ? {} : { input }),
      modelId: MODEL_ID,
    },
  });
  assert.equal(status, 200);
  return body;
}

/** 轮询详情，直到 updatedAt 离开基线（后台任务落库）。 */
async function waitRefreshed(id: string, baseline: string): Promise<any> {
  for (let i = 0; i < 100; i += 1) {
    const { body } = await api.get(`${API}/agents/${id}`);
    if (body.updatedAt !== baseline) return body;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`智能体 ${id} 的元数据未在 5s 内被刷新`);
}

test('创建后自动写入 name / description / tags，模型拿到的是剥掉命令的需求', async () => {
  reply = '{"name":"会议纪要助手","description":"把会议速记整理成待办清单。","tags":["会议","纪要","待办"]}';
  delayMs = 0;
  const before = calls.length;

  const created = await create(
    '/agent-genesis:harness-create --knowledge-workflow-id RAG_Workflow_780f 做一个会议纪要助手，从速记里提取待办',
  );
  const refreshed = await waitRefreshed(created.id, created.updatedAt);

  assert.equal(refreshed.name, '会议纪要助手');
  assert.equal(refreshed.description, '把会议速记整理成待办清单。');
  assert.deepEqual(refreshed.tags, ['会议', '纪要', '待办']);

  assert.equal(calls.length, before + 1);
  const prompt = calls.at(-1)!.body.messages[0].content as string;
  assert.match(prompt, /做一个会议纪要助手，从速记里提取待办/);
  // 命令与知识检索参数都不该进元数据提示词（名字会变成 --knowledge-workflow-id …）
  assert.doesNotMatch(prompt, /harness-create/);
  assert.doesNotMatch(prompt, /--knowledge-workflow-id/);
});

test('生成期间用户手改了元数据：条件更新落空，保留用户的值', async () => {
  reply = '{"name":"AI 想改的名字","description":"AI 描述","tags":["AI"]}';
  delayMs = 200;

  const created = await create('做一个数据分析助手');
  // 给后台任务一点时间读到基线并进入模型调用，再模拟用户手改
  await new Promise((resolve) => setTimeout(resolve, 60));
  const { status } = await api.post(`${API}/agents/${created.id}/update`, { name: '我自己改的名字' });
  assert.equal(status, 200);

  await new Promise((resolve) => setTimeout(resolve, 500));
  const { body } = await api.get(`${API}/agents/${created.id}`);
  assert.equal(body.name, '我自己改的名字');
  assert.deepEqual(body.tags, []);
  delayMs = 0;
});

test('模型输出不可解析：创建照常成功，保留兜底值', async () => {
  reply = '我不知道该叫什么';
  const created = await create('做一个天气助手');

  await new Promise((resolve) => setTimeout(resolve, 400));
  const { body } = await api.get(`${API}/agents/${created.id}`);
  assert.equal(body.name, created.name);
  assert.equal(body.description, '兜底描述');
});

test('没有 init：完全不调用模型', async () => {
  reply = '{"name":"不该出现","description":"","tags":[]}';
  const before = calls.length;
  const { status } = await api.post(`${API}/agents`, {
    workspaceId: TEST_WORKSPACE_ID,
    name: '无 init 的智能体',
  });
  assert.equal(status, 200);

  await new Promise((resolve) => setTimeout(resolve, 300));
  assert.equal(calls.length, before);
});

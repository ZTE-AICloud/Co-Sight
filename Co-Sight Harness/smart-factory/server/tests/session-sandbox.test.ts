/**
 * 四阶段目录与物化：sessions/create 默认不碰磁盘（唯一例外是 `resetSandbox`），
 * preview / evaluation 在每次 run 前 ensure。
 *
 * 规则见 03-architecture/03-session-run.md §1.2–§1.4。
 */
import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { prepareTestEnv } from './helpers/test-db.js';
import { agentRootIn, seedAgent, seedDevelopmentDir, seedPipelineState } from './helpers/agents.js';
import { startWorkspaceStub, TEST_MODEL_ID } from './helpers/workspace-stub.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

const env = prepareTestEnv('session-sandbox');
const stub = await startWorkspaceStub(env);

const { prisma } = await import('../src/shared/prisma/client.js');

let api: TestApi;

before(async () => {
  await seedAgent('sandbox-preview');
  await seedAgent('sandbox-evaluation');
  await seedAgent('sandbox-runtime');
  await seedAgent('sandbox-missing');
  await seedAgent('sandbox-reset');
  for (const id of ['sandbox-preview', 'sandbox-evaluation', 'sandbox-runtime', 'sandbox-missing', 'sandbox-reset']) {
    seedDevelopmentDir(env.workspaceDir, id);
  }
  for (const id of ['sandbox-preview', 'sandbox-evaluation', 'sandbox-runtime', 'sandbox-reset']) {
    seedPipelineState(agentRootIn(env.workspaceDir, id), 'demo');
  }
  api = await startTestApi();
});

after(async () => {
  await api.close();
  await stub.close();
  await prisma.$disconnect();
});

function agentRoot(agentId: string): string {
  return agentRootIn(env.workspaceDir, agentId);
}

function write(path: string, content: string): void {
  mkdirSync(join(path, '..'), { recursive: true });
  writeFileSync(path, content);
}

async function createSession(agentId: string, stage: string): Promise<any> {
  const { status, body } = await api.post(`${API}/sessions/create`, { agentId, stage, modelId: TEST_MODEL_ID });
  assert.equal(status, 200, JSON.stringify(body));
  return body;
}

async function sendAndWait(sessionId: string, prompt = '你好'): Promise<any> {
  const sent = await api.post(`${API}/messages/send`, { sessionId, prompt });
  assert.equal(sent.status, 200);
  return api.waitTerminal(sent.body.run.id);
}

test('sessions/create 不物化、不碰磁盘；preview 在 run 前从最新产物整体拷贝', async () => {
  const session = await createSession('sandbox-preview', 'preview');
  assert.equal(session.instance.stage, 'preview');
  assert.ok(!existsSync(join(agentRoot('sandbox-preview'), 'preview')), 'create 不得创建 preview 目录');

  const produced = join(agentRoot('sandbox-preview'), 'development', 'output', 'agents', 'demo', 'v1');
  write(join(produced, 'notes', 'plan.md'), 'v1');
  write(join(produced, 'todo.txt'), 'v1');

  assert.equal((await sendAndWait(session.id)).status, 'succeeded');
  const preview = join(agentRoot('sandbox-preview'), 'preview');
  assert.equal(readFileSync(join(preview, 'notes', 'plan.md'), 'utf8'), 'v1');
  assert.equal(readFileSync(join(preview, 'todo.txt'), 'utf8'), 'v1');

  // 源变化后下一次 run 重新物化；沙箱里的旧文件被清掉
  write(join(produced, 'notes', 'plan.md'), 'v2');
  write(join(produced, 'extra.txt'), 'new');
  write(join(preview, 'stale.txt'), 'stale');
  mkdirSync(join(preview, 'stale-dir'), { recursive: true });

  assert.equal((await sendAndWait(session.id)).status, 'succeeded');
  assert.equal(readFileSync(join(preview, 'notes', 'plan.md'), 'utf8'), 'v2');
  assert.equal(readFileSync(join(preview, 'extra.txt'), 'utf8'), 'new');
  assert.ok(!existsSync(join(preview, 'stale.txt')), '沙箱旧文件应被清掉');
  assert.ok(!existsSync(join(preview, 'stale-dir')), '沙箱旧目录应被清掉');

  // 沙箱里的写不影响开发产物
  write(join(preview, 'sandbox-only.txt'), 'x');
  assert.ok(!existsSync(join(agentRoot('sandbox-preview'), 'development', 'sandbox-only.txt')));
});

test('evaluation 复制 preview 的完整沙箱内容到沙箱根下的 agent/', async () => {
  const session = await createSession('sandbox-evaluation', 'evaluation');
  const produced = join(agentRoot('sandbox-evaluation'), 'development', 'output', 'agents', 'demo', 'v3');
  write(join(produced, 'app.txt'), 'eval-source');

  assert.equal((await sendAndWait(session.id)).status, 'succeeded');
  assert.equal(
    readFileSync(join(agentRoot('sandbox-evaluation'), 'evaluation', 'agent', 'app.txt'), 'utf8'),
    'eval-source',
  );

  // preview 沙箱里新增文件，evaluation 下一次 run 应整体复制过来
  write(join(agentRoot('sandbox-evaluation'), 'preview', 'preview-only.txt'), 'from-preview');
  assert.equal((await sendAndWait(session.id)).status, 'succeeded');
  assert.equal(
    readFileSync(join(agentRoot('sandbox-evaluation'), 'evaluation', 'agent', 'preview-only.txt'), 'utf8'),
    'from-preview',
  );
});

test('resetSandbox：建会话时清空该阶段沙箱（评估旧报告一并删除），下一次 run 重拷', async () => {
  const first = await createSession('sandbox-reset', 'evaluation');
  const produced = join(agentRoot('sandbox-reset'), 'development', 'output', 'agents', 'demo', 'v1');
  write(join(produced, 'app.txt'), 'reset-source');
  assert.equal((await sendAndWait(first.id)).status, 'succeeded');

  const stageRoot = join(agentRoot('sandbox-reset'), 'evaluation');
  const oldReport = join(stageRoot, 'e2e-test-20260101-000000');
  write(join(oldReport, 'report.json'), '{}');

  // 普通建会话（复用沙箱）不删：旧报告属于历史轮次，仍可读
  await createSession('sandbox-reset', 'evaluation');
  assert.ok(existsSync(join(oldReport, 'report.json')), '普通建会话不得删沙箱');

  // 「重新评估」：沙箱根整个消失，旧报告不再可读
  const rebuilt = await api.post(`${API}/sessions/create`, {
    agentId: 'sandbox-reset',
    stage: 'evaluation',
    modelId: TEST_MODEL_ID,
    resetSandbox: true,
  });
  assert.equal(rebuilt.status, 200, JSON.stringify(rebuilt.body));
  assert.ok(!existsSync(stageRoot), 'resetSandbox 应删掉整个阶段沙箱');

  // 下一次 run 按最新产物整体重拷
  assert.equal((await sendAndWait(rebuilt.body.id)).status, 'succeeded');
  assert.equal(readFileSync(join(stageRoot, 'agent', 'app.txt'), 'utf8'), 'reset-source');
});

test('resetSandbox 只支持 preview / evaluation', async () => {
  const { status, body } = await api.post(`${API}/sessions/create`, {
    agentId: 'sandbox-reset',
    stage: 'development',
    modelId: TEST_MODEL_ID,
    resetSandbox: true,
  });
  assert.equal(status, 400, JSON.stringify(body));
  assert.match(body.message, /resetSandbox/);
});

test('runtime 原地使用最新 vN：产物缺失时 send 返回 404，不创建 run', async () => {
  const session = await createSession('sandbox-runtime', 'runtime');
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: '你好' });
  assert.equal(sent.status, 404, JSON.stringify(sent.body));
  assert.match(sent.body.message, /运行产物/);
  assert.equal((await api.get(`${API}/runs/list?sessionId=${session.id}`)).body.total, 0);

  const produced = join(agentRoot('sandbox-runtime'), 'development', 'output', 'agents', 'demo', 'v1');
  write(join(produced, 'app.txt'), 'v1');
  write(join(agentRoot('sandbox-runtime'), 'development', 'output', 'agents', 'demo', 'v2', 'app.txt'), 'v2');
  assert.equal((await sendAndWait(session.id)).status, 'succeeded');
});

test('preview 源缺失：send 返回 404，不创建 run 且不留下空目标', async () => {
  const session = await createSession('sandbox-missing', 'preview');
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: '你好' });
  assert.equal(sent.status, 404, JSON.stringify(sent.body));
  assert.match(sent.body.message, /运行产物/);
  assert.ok(!existsSync(join(agentRoot('sandbox-missing'), 'preview')), '物化失败不得用空目录兜底');
  assert.equal((await api.get(`${API}/runs/list?sessionId=${session.id}`)).body.total, 0);

  const messages = await api.get(`${API}/messages/list?sessionId=${session.id}`);
  assert.deepEqual(
    messages.body.items.map((m: any) => [m.role, m.type]),
    [],
  );
});

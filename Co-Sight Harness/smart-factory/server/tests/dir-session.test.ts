import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, realpathSync, symlinkSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { prepareTestEnv } from './helpers/test-db.js';
import { startWorkspaceStub, TEST_MODEL_ID } from './helpers/workspace-stub.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

const env = prepareTestEnv('dir-session');
const stub = await startWorkspaceStub(env);

const { prisma } = await import('../src/shared/prisma/client.js');
const { FAKE_TRIGGER } = await import('../src/shared/engine/fake-adapter.js');

let api: TestApi;

/** 工坊会话用的目录：都在测试 home 下，形态互不干扰。 */
const workshopDir = join(env.home, 'skill-workshop');
const otherDir = join(env.home, 'other-dir');
const linkDir = join(env.home, 'skill-link');

/** 轮询 run 直到停在挂起（审批）上：撑开「活跃窗口」用，不依赖 fake 的流式节奏。 */
async function waitRunWaiting(runId: string): Promise<void> {
  for (let i = 0; i < 100; i += 1) {
    const { body } = await api.get(`${API}/runs/detail?runId=${runId}`);
    if (body.waiting) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`run ${runId} 未在 5s 内停在挂起上`);
}

before(async () => {
  mkdirSync(join(workshopDir, 'output', 'skills'), { recursive: true });
  mkdirSync(otherDir, { recursive: true });
  api = await startTestApi();
});

after(async () => {
  await api.close();
  await stub.close();
  await prisma.$disconnect();
});

test('create { cwd } 正常：agentId 为 null、cwd 落 realpath、stage=development', async () => {
  const created = await api.post(`${API}/sessions/create`, { cwd: workshopDir, name: '工坊', modelId: TEST_MODEL_ID });
  assert.equal(created.status, 200, JSON.stringify(created.body));
  assert.equal(created.body.instance.agentId, null);
  assert.equal(created.body.instance.stage, 'development', '工坊是开发阶段；目录实例靠 agentId=null 区分');
  assert.equal(created.body.instance.cwd, realpathSync(workshopDir));
  assert.equal(created.body.instance.engine, 'fake');
  assert.equal(created.body.messageCount, 0);
  assert.equal(created.body.lastMessage, null);
  assert.equal(created.body.firstUserMessage, null);
});

test('agentId 与 cwd 必须给且只给一个：同时给 / 都不给 400', async () => {
  for (const body of [
    { agentId: 'agt_00000000-0000-4000-8000-000000000000', cwd: workshopDir, modelId: TEST_MODEL_ID },
    { modelId: TEST_MODEL_ID },
    { agentId: null, cwd: null, modelId: TEST_MODEL_ID },
  ]) {
    const res = await api.post(`${API}/sessions/create`, body);
    assert.equal(res.status, 400, JSON.stringify(body));
    assert.equal(res.body.error, 'BAD_REQUEST');
    assert.equal(res.body.message, 'agentId 与 cwd 必须给且只给一个');
    assert.equal(res.body.messageKey, 'error.bad_request.agent_or_cwd');
  }
  // 互斥拒绝不得落实例：目录实例数不变
  assert.equal(await prisma.instance.count({ where: { stage: 'development', agentId: null } }), 1);
});

test('cwd 相对路径 400、不存在 404、指向文件 400，均不落实例', async () => {
  const relative = await api.post(`${API}/sessions/create`, { cwd: 'relative/path', modelId: TEST_MODEL_ID });
  assert.equal(relative.status, 400);
  assert.match(relative.body.message, /绝对路径/);

  const missing = await api.post(`${API}/sessions/create`, {
    cwd: join(env.home, 'no-such-dir'),
    modelId: TEST_MODEL_ID,
  });
  assert.equal(missing.status, 404);
  assert.equal(missing.body.error, 'NOT_FOUND');

  const filePath = join(env.home, 'plain-file.txt');
  writeFileSync(filePath, 'x');
  const file = await api.post(`${API}/sessions/create`, { cwd: filePath, modelId: TEST_MODEL_ID });
  assert.equal(file.status, 400);
  assert.match(file.body.message, /不是目录/);

  assert.equal(await prisma.instance.count({ where: { cwd: filePath } }), 0, '非法 cwd 不得落实例');
});

test('同 cwd 建第二个会话：实例复用，会话新建', async () => {
  const first = await api.post(`${API}/sessions/create`, { cwd: otherDir, modelId: TEST_MODEL_ID });
  const second = await api.post(`${API}/sessions/create`, { cwd: otherDir, modelId: TEST_MODEL_ID });
  assert.equal(first.status, 200);
  assert.equal(second.status, 200, JSON.stringify(second.body));
  assert.notEqual(second.body.id, first.body.id);
  assert.equal(second.body.instance.id, first.body.instance.id);
  assert.equal(await prisma.instance.count({ where: { cwd: realpathSync(otherDir) } }), 1);
});

test('同 cwd 第二个活跃 run 409：目录实例级互斥（dir 非 runtime）', async () => {
  const list = await api.get(`${API}/sessions/list?cwd=${encodeURIComponent(realpathSync(otherDir))}`);
  const [a, b] = list.body.items as any[];

  const first = await api.post(`${API}/messages/send`, { sessionId: a.id, prompt: FAKE_TRIGGER.approval });
  assert.equal(first.status, 200, JSON.stringify(first.body));
  await waitRunWaiting(first.body.run.id);

  const blocked = await api.post(`${API}/messages/send`, { sessionId: b.id, prompt: '不该起跑' });
  assert.equal(blocked.status, 409);
  assert.equal(blocked.body.error, 'CONFLICT');
  assert.equal((await api.get(`${API}/messages/list?sessionId=${b.id}`)).body.items.length, 0, '被拒的发送不得落消息');

  const aborted = await api.post(`${API}/runs/abort`, { runId: first.body.run.id });
  assert.equal(aborted.status, 200);
  assert.equal((await api.waitTerminal(first.body.run.id)).status, 'aborted');

  const retried = await api.post(`${API}/messages/send`, { sessionId: b.id, prompt: '现在可以了' });
  assert.equal(retried.status, 200, JSON.stringify(retried.body));
  assert.equal((await api.waitTerminal(retried.body.run.id)).status, 'succeeded');
});

test('sessions/list?cwd 过滤目录会话，与 stage 取交集；相对路径 400', async () => {
  const real = realpathSync(otherDir);
  const list = await api.get(`${API}/sessions/list?cwd=${encodeURIComponent(real)}`);
  assert.equal(list.status, 200);
  assert.equal(list.body.total, 2, JSON.stringify(list.body));
  assert.ok(
    list.body.items.every(
      (item: any) => item.instance.cwd === real && item.instance.stage === 'development' && item.instance.agentId === null,
    ),
  );

  const dirOnly = await api.get(`${API}/sessions/list?cwd=${encodeURIComponent(real)}&stage=development`);
  assert.equal(dirOnly.status, 200);
  assert.equal(dirOnly.body.total, 2);

  const mismatch = await api.get(`${API}/sessions/list?cwd=${encodeURIComponent(real)}&stage=preview`);
  assert.equal(mismatch.status, 200);
  assert.equal(mismatch.body.total, 0);

  const notAbsolute = await api.get(`${API}/sessions/list?cwd=relative/path`);
  assert.equal(notAbsolute.status, 400);
  assert.equal(notAbsolute.body.message, 'cwd 必须是绝对路径');
});

test('符号链接 cwd：create 落 realpath，list 按真实路径可查', async () => {
  symlinkSync(workshopDir, linkDir, 'dir');
  const created = await api.post(`${API}/sessions/create`, { cwd: linkDir, modelId: TEST_MODEL_ID });
  assert.equal(created.status, 200, JSON.stringify(created.body));

  const real = realpathSync(workshopDir);
  assert.equal(created.body.instance.cwd, real);
  assert.notEqual(created.body.instance.cwd, linkDir);

  const list = await api.get(`${API}/sessions/list?cwd=${encodeURIComponent(real)}`);
  assert.equal(list.status, 200);
  assert.ok(list.body.items.some((item: any) => item.id === created.body.id), 'list?cwd=<realpath> 必须查到符号链接创建的会话');
});

test('目录会话 send：不 seed 智能体、不依赖工作区，FakeAdapter 正常收口', async () => {
  const created = await api.post(`${API}/sessions/create`, { cwd: workshopDir, name: '创建技能', modelId: TEST_MODEL_ID });
  assert.equal(created.status, 200);

  const sent = await api.post(`${API}/messages/send`, { sessionId: created.body.id, prompt: '你好' });
  assert.equal(sent.status, 200, JSON.stringify(sent.body));
  assert.equal(sent.body.status, 'running');
  assert.equal(sent.body.instanceId, created.body.instance.id);

  const run = await api.waitTerminal(sent.body.run.id);
  assert.equal(run.status, 'succeeded');
  assert.equal(run.error, null);

  // 该实例没有 agentId：起跑若走工作区解析必然失败；run 成功即证明走了 cwd 分支
  const messages = await api.get(`${API}/messages/list?sessionId=${created.body.id}`);
  assert.deepEqual(
    messages.body.items.map((m: any) => [m.seq, m.role, m.type]),
    [
      [1, 'user', 'text'],
      [2, 'assistant', 'text'],
    ],
  );
  assert.deepEqual(messages.body.items[1].content, { text: '收到：你好' });
  assert.equal((await api.get(`${API}/sessions/detail?sessionId=${created.body.id}`)).body.status, 'completed');
});

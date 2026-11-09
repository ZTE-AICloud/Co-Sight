/**
 * REST 契约边界测试：id 传法、过滤、分页与游标、错误码、刻意不存在的接口。
 *
 * 权威：server/docs/04-api/（4.02 通用规范、4.03 会话、4.04 消息、4.05 运行）
 */
import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { prepareTestEnv } from './helpers/test-db.js';
import { seedAgents, seedDevelopmentDir } from './helpers/agents.js';
import { startWorkspaceStub, TEST_MODEL_ALT_ID, TEST_MODEL_ID } from './helpers/workspace-stub.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

const env = prepareTestEnv('api-contract');
const stub = await startWorkspaceStub(env);

const { prisma } = await import('../src/shared/prisma/client.js');
const { instancesRepo } = await import('../src/shared/store/instances.repo.js');

let api: TestApi;

/** 直接造 N 条消息（seq 1..N），用于验证游标与 limit 边界。 */
async function seedMessages(sessionId: string, count: number): Promise<void> {
  const now = new Date();
  await prisma.message.createMany({
    data: Array.from({ length: count }, (_, index) => ({
      id: `msg_seed_${sessionId}_${index + 1}`,
      sessionId,
      seq: index + 1,
      role: 'assistant',
      type: 'text',
      content: JSON.stringify({ text: `seed-${index + 1}` }),
      createdAt: now,
    })),
  });
}

/** 直接造 N 个会话，用于验证分页缺省与上限。 */
async function seedSessions(instanceId: string, count: number): Promise<void> {
  const now = new Date();
  await prisma.session.createMany({
    data: Array.from({ length: count }, (_, index) => ({
      id: `sess_seed_${index + 1}`,
      instanceId,
      modelId: TEST_MODEL_ID,
      createdAt: now,
      updatedAt: now,
    })),
  });
}

before(async () => {
  await seedAgents('contract-runid', 'contract-cursor', 'contract-limit', 'contract-before', 'contract-filter');
  for (const agentId of ['contract-runid', 'contract-cursor', 'contract-limit', 'contract-before', 'contract-filter']) {
    seedDevelopmentDir(env.workspaceDir, agentId);
  }
  api = await startTestApi();
});

after(async () => {
  await api.close();
  await stub.close();
  await prisma.$disconnect();
});

test('messages/list 只给 runId 能列出该 run 的消息；两者都给或都缺返回 400', async () => {
  const { body: session } = await api.post(`${API}/sessions/create`, {
    agentId: 'contract-runid',
    modelId: TEST_MODEL_ID,
  });
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: '你好' });
  assert.equal(sent.status, 200);
  // send 响应：顶层 id 三件套与 message/run 并存，模型信息随响应返回且没有 created
  assert.equal(sent.body.sessionId, session.id);
  assert.equal(sent.body.runId, sent.body.run.id);
  assert.equal(sent.body.instanceId, session.instanceId);
  assert.equal(sent.body.modelId, TEST_MODEL_ID);
  assert.equal(sent.body.modelName, 'test-sonnet');
  assert.equal(sent.body.effort, 'high');
  assert.equal(sent.body.modelFellBack, false);
  assert.equal('created' in sent.body, false, 'send 响应没有 created 字段');
  assert.equal(sent.body.message.sessionId, session.id);
  assert.equal(sent.body.message.role, 'user');
  assert.equal(sent.body.message.type, 'text');
  assert.deepEqual(sent.body.message.content, { text: '你好' });
  assert.equal(sent.body.run.sessionId, session.id);
  assert.equal(sent.body.run.instanceId, sent.body.instanceId);
  await api.waitTerminal(sent.body.run.id);

  const byRun = await api.get(`${API}/messages/list?runId=${sent.body.run.id}`);
  assert.equal(byRun.status, 200);
  assert.equal(byRun.body.items.length, 1);
  assert.equal(byRun.body.items[0].runId, sent.body.run.id);
  assert.equal(byRun.body.items[0].role, 'assistant');
  assert.equal(byRun.body.nextAfterSeq, null);

  // 会话流 2 条（user + assistant），run 流只有 assistant 那条
  const bySession = await api.get(`${API}/messages/list?sessionId=${session.id}`);
  assert.equal(bySession.body.items.length, 2);

  const both = await api.get(`${API}/messages/list?sessionId=${session.id}&runId=${sent.body.run.id}`);
  assert.equal(both.status, 400);
  assert.equal(both.body.error, 'BAD_REQUEST');

  const neither = await api.get(`${API}/messages/list`);
  assert.equal(neither.status, 400);
  assert.equal(neither.body.error, 'BAD_REQUEST');
});

test('messages/send 定位至多一个（都不给 = 自由对话）；sessionId 分支禁止覆盖模型与运行参数', async () => {
  const { body: session } = await api.post(`${API}/sessions/create`, {
    agentId: 'contract-runid',
    modelId: TEST_MODEL_ID,
  });

  // 都不给不再报「定位缺失」：作为自由对话被接收，缺 modelId 才是这次的 400
  const neither = await api.post(`${API}/messages/send`, { prompt: '你好' });
  assert.equal(neither.status, 400);
  assert.equal(neither.body.error, 'BAD_REQUEST');
  assert.equal(neither.body.message, 'modelId 必填');

  const both = await api.post(`${API}/messages/send`, {
    sessionId: session.id,
    agentId: 'contract-runid',
    modelId: TEST_MODEL_ID,
    prompt: '你好',
  });
  assert.equal(both.status, 400);
  assert.equal(both.body.error, 'BAD_REQUEST');

  for (const [field, value] of [
    ['modelId', TEST_MODEL_ALT_ID],
    ['mode', 'workspace_write'],
    ['effort', 'high'],
  ] as const) {
    const res = await api.post(`${API}/messages/send`, {
      sessionId: session.id,
      prompt: '你好',
      [field]: value,
    });
    assert.equal(res.status, 400, `${field} 不得随 sessionId 传入`);
    assert.equal(res.body.error, 'BAD_REQUEST');
    assert.match(res.body.message, /不接受/);
  }

  const noModel = await api.post(`${API}/messages/send`, { agentId: 'contract-runid', prompt: '你好' });
  assert.equal(noModel.status, 400);
  assert.equal(noModel.body.error, 'BAD_REQUEST');
  assert.equal(noModel.body.message, 'modelId 必填');
});

test('游标：afterSeq 只返回 seq 严格大于它的消息', async () => {
  const { body: session } = await api.post(`${API}/sessions/create`, {
    agentId: 'contract-cursor',
    modelId: TEST_MODEL_ID,
  });
  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: '你好' });
  await api.waitTerminal(sent.body.run.id);

  const fromZero = await api.get(`${API}/messages/list?sessionId=${session.id}&afterSeq=0`);
  assert.deepEqual(
    fromZero.body.items.map((m: any) => m.seq),
    [1, 2],
  );

  const afterFirst = await api.get(`${API}/messages/list?sessionId=${session.id}&afterSeq=1`);
  assert.deepEqual(
    afterFirst.body.items.map((m: any) => m.seq),
    [2],
  );

  const afterLast = await api.get(`${API}/messages/list?sessionId=${session.id}&afterSeq=2`);
  assert.deepEqual(afterLast.body.items, []);
  assert.equal(afterLast.body.nextAfterSeq, null);
});

test('messages/list 的 limit：缺省 50、超过上限按 200 截断', async () => {
  const { body: session } = await api.post(`${API}/sessions/create`, {
    agentId: 'contract-limit',
    modelId: TEST_MODEL_ID,
  });
  await seedMessages(session.id, 250);

  // 不带游标 = 最近一段（不是最旧的），仍按 seq 升序
  const fallback = await api.get(`${API}/messages/list?sessionId=${session.id}`);
  assert.equal(fallback.status, 200);
  assert.deepEqual(
    fallback.body.items.map((m: any) => m.seq),
    Array.from({ length: 50 }, (_, index) => index + 201),
  );
  assert.equal(fallback.body.nextAfterSeq, 250);

  const capped = await api.get(`${API}/messages/list?sessionId=${session.id}&limit=500`);
  assert.equal(capped.body.items.length, 200);
  assert.equal(capped.body.items[0].seq, 51);
  assert.equal(capped.body.items.at(-1).seq, 250);
  assert.equal(capped.body.nextAfterSeq, 250);

  // 尾部不足 limit 时 nextAfterSeq 为 null
  const tail = await api.get(`${API}/messages/list?sessionId=${session.id}&afterSeq=200&limit=500`);
  assert.equal(tail.body.items.length, 50);
  assert.equal(tail.body.items[0].seq, 201);
  assert.equal(tail.body.nextAfterSeq, null);
});

test('游标：beforeSeq 向上翻页，与 afterSeq 互斥', async () => {
  const { body: session } = await api.post(`${API}/sessions/create`, {
    agentId: 'contract-before',
    modelId: TEST_MODEL_ID,
  });
  await seedMessages(session.id, 250);

  const page = await api.get(`${API}/messages/list?sessionId=${session.id}&beforeSeq=201&limit=50`);
  assert.equal(page.status, 200);
  assert.deepEqual(
    page.body.items.map((m: any) => m.seq),
    Array.from({ length: 50 }, (_, index) => index + 151),
  );
  assert.equal(page.body.nextAfterSeq, 200);

  // 最早一段之前没有更旧的消息
  const oldest = await api.get(`${API}/messages/list?sessionId=${session.id}&beforeSeq=1`);
  assert.deepEqual(oldest.body.items, []);
  assert.equal(oldest.body.nextAfterSeq, null);

  const conflict = await api.get(`${API}/messages/list?sessionId=${session.id}&afterSeq=1&beforeSeq=5`);
  assert.equal(conflict.status, 400);
  assert.equal(conflict.body.error, 'BAD_REQUEST');
});

test('sessions/list 的 stage 过滤，session 内联 instance 形状符合契约', async () => {
  const preview = await api.post(`${API}/sessions/create`, {
    agentId: 'contract-filter',
    stage: 'preview',
    modelId: TEST_MODEL_ID,
  });
  const development = await api.post(`${API}/sessions/create`, {
    agentId: 'contract-filter',
    modelId: TEST_MODEL_ID,
  });
  assert.equal(preview.status, 200);
  assert.equal(development.status, 200);

  const byStage = await api.get(`${API}/sessions/list?agentId=contract-filter&stage=preview`);
  assert.equal(byStage.status, 200);
  assert.equal(byStage.body.total, 1);
  assert.equal(byStage.body.items[0].id, preview.body.id);

  const byDevelopment = await api.get(`${API}/sessions/list?agentId=contract-filter&stage=development`);
  assert.equal(byDevelopment.body.total, 1);
  assert.equal(byDevelopment.body.items[0].id, development.body.id);

  const session = byStage.body.items[0];
  assert.deepEqual(Object.keys(session).sort(), [
    'approvalMode',
    'approvedAll',
    'createdAt',
    'effort',
    'firstUserMessage',
    'id',
    'instance',
    'instanceId',
    'lastMessage',
    'messageCount',
    'modelId',
    'name',
    'resumeSessionId',
    'status',
    'updatedAt',
  ]);
  assert.equal(session.modelId, TEST_MODEL_ID);
  assert.equal(session.resumeSessionId, null);
  assert.equal(session.approvalMode, 'workspace_write');
  assert.equal(session.approvedAll, false);
  assert.equal(session.messageCount, 0);
  assert.equal(session.lastMessage, null);
  assert.equal(session.firstUserMessage, null);
  assert.equal(session.effort, 'high');
  assert.deepEqual(Object.keys(session.instance).sort(), ['agentId', 'createdAt', 'cwd', 'engine', 'id', 'stage', 'updatedAt']);
  assert.equal(session.instance.agentId, 'contract-filter');
  assert.equal(session.instance.stage, 'preview');
  assert.equal(session.instance.engine, 'fake');
  // 智能体实例不落 cwd：运行期推导（10-skill-library.md §3.1）
  assert.equal(session.instance.cwd, null);
});

test('sessions/list 分页：page/pageSize 缺省 1/20，pageSize 超过上限按 200 截断', async () => {
  const instance = await instancesRepo.getOrCreate('contract-page', 'development');
  await seedSessions(instance.id, 221);

  const fallback = await api.get(`${API}/sessions/list?agentId=contract-page&stage=development`);
  assert.equal(fallback.status, 200);
  assert.equal(fallback.body.total, 221);
  assert.equal(fallback.body.items.length, 20);
  assert.equal(fallback.body.page, 1);
  assert.equal(fallback.body.pageSize, 20);

  const second = await api.get(`${API}/sessions/list?agentId=contract-page&stage=development&page=2`);
  assert.equal(second.body.items.length, 20);
  assert.equal(second.body.page, 2);
  assert.equal(second.body.pageSize, 20);

  const last = await api.get(`${API}/sessions/list?agentId=contract-page&stage=development&page=12`);
  assert.equal(last.body.items.length, 1);

  const capped = await api.get(`${API}/sessions/list?agentId=contract-page&stage=development&pageSize=500`);
  assert.equal(capped.body.items.length, 200);
  assert.equal(capped.body.total, 221);
  assert.equal(capped.body.pageSize, 200);
});

test('sessions/list 默认只看 runtime：agentId 不取消默认，instanceId / id / resumeSessionId 才取消', async () => {
  const development = await instancesRepo.getOrCreate('contract-default', 'development');
  const runtime = await instancesRepo.getOrCreate('contract-default', 'runtime');
  const now = new Date();
  const devId = 'sess_default_dev';
  const runtimeId = 'sess_default_runtime';
  await prisma.session.createMany({
    data: [
      { id: devId, instanceId: development.id, modelId: TEST_MODEL_ID, createdAt: now, updatedAt: now },
      { id: runtimeId, instanceId: runtime.id, modelId: TEST_MODEL_ID, createdAt: now, updatedAt: now },
    ],
  });

  // 空参：development / preview / evaluation / dir 都不再混进来
  const bare = await api.get(`${API}/sessions/list?pageSize=200`);
  assert.equal(bare.status, 200);
  assert.ok(
    bare.body.items.every((item: any) => item.instance.stage === 'runtime'),
    `默认必须只返回 runtime，实际：${JSON.stringify(bare.body.items.map((item: any) => item.instance.stage))}`,
  );
  assert.ok(bare.body.items.some((item: any) => item.id === runtimeId));
  assert.ok(!bare.body.items.some((item: any) => item.id === devId));

  // agentId 只是过滤、不是定位：仍只给 runtime
  const byAgent = await api.get(`${API}/sessions/list?agentId=contract-default`);
  assert.deepEqual(byAgent.body.items.map((item: any) => item.id), [runtimeId]);

  // 看别的阶段要么显式 stage，要么走实例（定位参数取消默认）
  const byStage = await api.get(`${API}/sessions/list?agentId=contract-default&stage=development`);
  assert.deepEqual(byStage.body.items.map((item: any) => item.id), [devId]);
  const byInstance = await api.get(`${API}/sessions/list?instanceId=${development.id}`);
  assert.deepEqual(byInstance.body.items.map((item: any) => item.id), [devId]);

  // id / resumeSessionId 是精确定位，同样不套默认阶段
  const byId = await api.get(`${API}/sessions/list?id=${devId}`);
  assert.deepEqual(byId.body.items.map((item: any) => item.id), [devId]);
  await prisma.session.update({ where: { id: devId }, data: { resumeSessionId: 'sdk-default-dev' } });
  const byResume = await api.get(`${API}/sessions/list?resumeSessionId=sdk-default-dev`);
  assert.deepEqual(byResume.body.items.map((item: any) => item.id), [devId]);
});

test('自由对话是目录实例 + runtime：默认列表可见，subjectType=agent 能把它排除', async () => {
  const chatInstance = await instancesRepo.getOrCreateByCwd(join(env.home, 'contract-chat'), 'runtime');
  const chatId = 'sess_default_chat';
  await prisma.session.create({ data: { id: chatId, instanceId: chatInstance.id, modelId: TEST_MODEL_ID } });

  const runtime = await api.get(`${API}/sessions/list?pageSize=200`);
  assert.ok(
    runtime.body.items.some((item: any) => item.id === chatId),
    '自由对话属于 runtime，默认的「历史运行会话」要能看到',
  );

  // subjectType=agent 等价于「只要智能体实例」：自由对话（agentId=null）不在其中
  const agentOnly = await api.get(`${API}/sessions/list?pageSize=200&subjectType=agent`);
  assert.ok(agentOnly.body.items.every((item: any) => item.instance.agentId !== null));
  assert.ok(!agentOnly.body.items.some((item: any) => item.id === chatId));
});

test('sessions/list 按 updatedAt 降序：旧会话有活动后排到最前', async () => {
  const instance = await instancesRepo.getOrCreate('contract-order', 'development');
  const early = new Date('2026-01-01T00:00:00Z');
  const late = new Date('2026-01-02T00:00:00Z');
  await prisma.session.createMany({
    data: [
      { id: 'sess_order_old', instanceId: instance.id, modelId: TEST_MODEL_ID, createdAt: early, updatedAt: early },
      { id: 'sess_order_new', instanceId: instance.id, modelId: TEST_MODEL_ID, createdAt: late, updatedAt: late },
    ],
  });

  // 创建更早，但刚有活动（改名会刷新 updatedAt）→ 排第一
  await prisma.session.update({ where: { id: 'sess_order_old' }, data: { name: '刚聊过' } });

  const list = await api.get(`${API}/sessions/list?agentId=contract-order&stage=development`);
  assert.deepEqual(list.body.items.map((item: any) => item.id), ['sess_order_old', 'sess_order_new']);
});

test('sessions/list 过滤：subject/type/status/name/id/created/instanceId 的组合语义', async () => {
  // 前一个用例已建 preview + development 两条；补一条 completed 并命名
  const extra = await api.post(`${API}/sessions/create`, {
    agentId: 'contract-filter',
    modelId: TEST_MODEL_ID,
  });
  await prisma.session.update({
    where: { id: extra.body.id },
    data: { status: 'completed', name: '评审会话' },
  });

  assert.equal((await api.get(`${API}/sessions/list?subjectType=skill`)).status, 400);
  assert.equal((await api.get(`${API}/sessions/list?agentId=contract-filter&subjectId=other`)).status, 400);

  // subjectId 是过滤不是定位：不取消默认阶段，看全部阶段要显式给 type=all
  const bySubject = await api.get(`${API}/sessions/list?subjectType=agent&subjectId=contract-filter&type=all`);
  assert.equal(bySubject.body.total, 3);

  const byType = await api.get(`${API}/sessions/list?agentId=contract-filter&type=preview,development`);
  assert.equal(byType.body.total, 3);

  // all 取消阶段过滤，同时给出的 stage 不再生效
  const all = await api.get(`${API}/sessions/list?agentId=contract-filter&type=all&stage=preview`);
  assert.equal(all.body.total, 3);

  assert.equal(
    (await api.get(`${API}/sessions/list?agentId=contract-filter&stage=preview&type=development`)).status,
    400,
  );

  assert.equal(
    (await api.get(`${API}/sessions/list?agentId=contract-filter&type=all&status=completed`)).body.total,
    1,
  );
  assert.equal((await api.get(`${API}/sessions/list?agentId=contract-filter&status=nope`)).status, 400);

  assert.equal(
    (
      await api.get(
        `${API}/sessions/list?agentId=contract-filter&type=all&name=${encodeURIComponent('评审')}`,
      )
    ).body.total,
    1,
  );
  assert.equal((await api.get(`${API}/sessions/list?agentId=contract-filter&id=${extra.body.id}`)).body.total, 1);

  assert.equal(
    (await api.get(`${API}/sessions/list?agentId=contract-filter&createdFrom=not-a-date`)).status,
    400,
  );
  const future = encodeURIComponent(new Date(Date.now() + 86_400_000).toISOString());
  assert.equal(
    (await api.get(`${API}/sessions/list?agentId=contract-filter&type=all&createdFrom=${future}`)).body.total,
    0,
  );
  assert.equal(
    (await api.get(`${API}/sessions/list?agentId=contract-filter&type=all&createdTo=${future}`)).body.total,
    3,
  );

  // instanceId 与 agentId 取交集；交集为空返回空页而不是 404
  const other = await instancesRepo.getOrCreate('contract-other', 'development');
  const empty = await api.get(`${API}/sessions/list?agentId=contract-filter&instanceId=${other.id}`);
  assert.equal(empty.status, 200);
  assert.equal(empty.body.total, 0);

  const own = await api.get(`${API}/sessions/list?agentId=contract-filter&instanceId=${extra.body.instanceId}`);
  assert.equal(own.body.total, 2, 'development 实例下有两条会话');
});

test('404：runs/detail、messages/send、sessions/delete 遇不存在的 id', async () => {
  const run = await api.get(`${API}/runs/detail?runId=run_missing`);
  assert.equal(run.status, 404);
  assert.equal(run.body.error, 'NOT_FOUND');
  assert.equal(typeof run.body.message, 'string');

  const send = await api.post(`${API}/messages/send`, { sessionId: 'sess_missing', prompt: '你好' });
  assert.equal(send.status, 404);
  assert.equal(send.body.error, 'NOT_FOUND');

  const removed = await api.post(`${API}/sessions/delete`, { sessionId: 'sess_missing' });
  assert.equal(removed.status, 404);
  assert.equal(removed.body.error, 'NOT_FOUND');
});

test('400：sessions/create 的 stage 不在枚举内，且不留下会话', async () => {
  const created = await api.post(`${API}/sessions/create`, {
    agentId: 'contract-bad-stage',
    stage: 'nope',
    modelId: TEST_MODEL_ID,
  });
  assert.equal(created.status, 400);
  assert.equal(created.body.error, 'BAD_REQUEST');

  const list = await api.get(`${API}/sessions/list?agentId=contract-bad-stage`);
  assert.equal(list.body.total, 0);
});

// `/api/agents/*` 已从「刻意不存在」名单里移出（见 99-adr/0002）：
// 智能体管理收进本仓，六个端点见 05-openapi/5.01-agent-openapi.yaml，用例在 tests/agents.test.ts。
test('刻意不存在的接口：instances/* 一律 404', async () => {
  const res = await api.get(`${API}/instances/list`);
  assert.equal(res.status, 404);
  assert.equal(res.body.error, 'NOT_FOUND');
});

test('畸形 JSON 请求体：按 400 回，不落 500', async () => {
  // 用 fetch 直发非 JSON 正文：helper 的 post 会 JSON.stringify，表达不了这个场景
  const response = await fetch(`${api.base}${API}/sessions/create`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: '{ 半截 JSON',
  });
  assert.equal(response.status, 400);
  assert.equal((await response.json()).error, 'BAD_REQUEST');
});

// 评估报告（4.09-评估报告 §4）：id 一律走 query，末段是动作词白名单。
test('evaluations/*：缺 agentId 400；id 不进路径（无此路由 404）', async () => {
  const noAgent = await api.get(`${API}/evaluations/list`);
  assert.equal(noAgent.status, 400);
  assert.equal(noAgent.body.error, 'BAD_REQUEST');

  // reportId 不进路径：路径式地址落进通配 404，而不是被当成 reportId 解析
  const pathStyle = await api.get(`${API}/evaluations/detail/${encodeURIComponent('e2e-test-x')}`);
  assert.equal(pathStyle.status, 404);
  assert.equal(pathStyle.body.error, 'NOT_FOUND');

  const badReport = await api.get(`${API}/evaluations/cases/list?agentId=contract-runid&reportId=..%2Fx`);
  assert.equal(badReport.status, 400);
});

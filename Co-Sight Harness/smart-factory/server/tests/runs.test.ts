import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { prepareTestEnv } from './helpers/test-db.js';
import { TEST_MODEL_ID } from './helpers/workspace-stub.js';

prepareTestEnv('runs');

const { prisma } = await import('../src/shared/prisma/client.js');
const { instancesRepo } = await import('../src/shared/store/instances.repo.js');
const { sessionsRepo } = await import('../src/shared/store/sessions.repo.js');
const { runsRepo } = await import('../src/shared/store/runs.repo.js');
const { BadRequestError, ConflictError } = await import('../src/shared/errors.js');

let sessionId: string;
let instanceId: string;
let runtimeInstanceId: string;
let parentRunId: string;
let firstChildId: string;
let secondChildId: string;
let thirdChildId: string;
let grandchildId: string;

before(async () => {
  const instance = await instancesRepo.getOrCreate('run-demo', 'development');
  instanceId = instance.id;
  const session = await sessionsRepo.create({ instanceId, modelId: TEST_MODEL_ID });
  sessionId = session.id;

  // 独立 agent：避免 development 侧的活跃 run 触发跨阶段守卫
  const runtimeInstance = await instancesRepo.getOrCreate('run-demo-runtime', 'runtime');
  runtimeInstanceId = runtimeInstance.id;
});

after(async () => {
  await prisma.$disconnect();
});

test('建库启用 WAL', async () => {
  const rows = await prisma.$queryRawUnsafe<Array<{ journal_mode: string }>>('PRAGMA journal_mode');
  assert.equal(rows[0]?.journal_mode, 'wal');
});

test('部分唯一索引：session 级全局 + 非 runtime 实例级', async () => {
  const rows = await prisma.$queryRawUnsafe<Array<{ name: string; sql: string }>>(
    "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND name LIKE 'uq_runs_one_active%'",
  );
  assert.deepEqual(
    rows.map((row) => row.name).sort(),
    ['uq_runs_one_active_top_per_instance_non_runtime', 'uq_runs_one_active_top_per_session'].sort(),
  );

  const byName = new Map(rows.map((row) => [row.name, row.sql]));
  const sessionSql = byName.get('uq_runs_one_active_top_per_session')!;
  assert.match(sessionSql, /"session_id"/i);
  assert.match(sessionSql, /"status"\s+IN\s*\('pending',\s*'running'\)/i);
  assert.match(sessionSql, /"parent_run_id"\s+IS\s+NULL/i);

  const instanceSql = byName.get('uq_runs_one_active_top_per_instance_non_runtime')!;
  assert.match(instanceSql, /"instance_id"/i);
  assert.match(instanceSql, /"status"\s+IN\s*\('pending',\s*'running'\)/i);
  assert.match(instanceSql, /"parent_run_id"\s+IS\s+NULL/i);
  assert.match(instanceSql, /"stage"\s*<>\s*'runtime'/i);
});

test('同 session 第二个活跃顶层 run 被拒（409），且库里只有一条活跃', async () => {
  const first = await runsRepo.createActiveRun({ sessionId, instanceId });
  assert.equal(first.status, 'pending');
  assert.equal('stage' in first, false, 'RunRow 不暴露 stage');

  await assert.rejects(
    () => runsRepo.createActiveRun({ sessionId, instanceId }),
    (error: unknown) => error instanceof ConflictError && error.status === 409 && /会话/.test(error.message),
  );

  const active = await prisma.run.count({ where: { instanceId, status: { in: ['pending', 'running'] } } });
  assert.equal(active, 1);
});

test('createActiveRun：会话归属实例与传入实例不一致时 400', async () => {
  const otherInstance = await instancesRepo.getOrCreate('run-mismatch', 'development');
  await assert.rejects(
    () => runsRepo.createActiveRun({ sessionId, instanceId: otherInstance.id }),
    (error: unknown) => error instanceof BadRequestError && error.status === 400,
  );
});

test('绕过事务检查直接插第二条活跃顶层 run，也被索引拒绝', async () => {
  const active = await runsRepo.findActiveBySession(sessionId);
  assert.ok(active);
  await assert.rejects(() =>
    prisma.run.create({
      data: { id: 'run_bypass', sessionId, instanceId, stage: 'development', status: 'running' },
    }),
  );
});

test('development 同 instance 跨 session 仍 409（实例级互斥）', async () => {
  const otherSession = await sessionsRepo.create({ instanceId, modelId: TEST_MODEL_ID });
  await assert.rejects(
    () => runsRepo.createActiveRun({ sessionId: otherSession.id, instanceId }),
    (error: unknown) => error instanceof ConflictError && error.status === 409 && /实例/.test(error.message),
  );
});

test('runtime：同 instance 不同 session 可各起一个活跃顶层 run，stage 落库', async () => {
  const firstSession = await sessionsRepo.create({ instanceId: runtimeInstanceId, modelId: TEST_MODEL_ID });
  const secondSession = await sessionsRepo.create({ instanceId: runtimeInstanceId, modelId: TEST_MODEL_ID });

  const first = await runsRepo.createActiveRun({ sessionId: firstSession.id, instanceId: runtimeInstanceId });
  const second = await runsRepo.createActiveRun({ sessionId: secondSession.id, instanceId: runtimeInstanceId });

  const rows = await prisma.run.findMany({
    where: { id: { in: [first.id, second.id] } },
    select: { stage: true, status: true },
  });
  assert.deepEqual(rows.map((row) => row.stage), ['runtime', 'runtime']);
  assert.deepEqual(rows.map((row) => row.status), ['pending', 'pending']);

  await runsRepo.finish(first.id, 'succeeded');
  await runsRepo.finish(second.id, 'succeeded');
});

test('runtime：同 session 第二个活跃顶层 run 仍 409', async () => {
  const session = await sessionsRepo.create({ instanceId: runtimeInstanceId, modelId: TEST_MODEL_ID });
  const first = await runsRepo.createActiveRun({ sessionId: session.id, instanceId: runtimeInstanceId });

  await assert.rejects(
    () => runsRepo.createActiveRun({ sessionId: session.id, instanceId: runtimeInstanceId }),
    (error: unknown) => error instanceof ConflictError && error.status === 409 && /会话/.test(error.message),
  );

  await runsRepo.finish(first.id, 'succeeded');
});

test('终态守卫幂等：第二次更新受影响 0 行，状态不变', async () => {
  const active = await runsRepo.findActiveBySession(sessionId);
  assert.ok(active);

  assert.equal(await runsRepo.finish(active.id, 'succeeded'), true);
  assert.equal(await runsRepo.finish(active.id, 'failed', '不应生效'), false);

  const row = await runsRepo.findById(active.id);
  assert.equal(row?.status, 'succeeded');
  assert.equal(row?.error, null);
});

test('派生会话状态：无活跃 run 置 completed（且时间戳格式被 Prisma 读回）', async () => {
  await sessionsRepo.markInProgress(sessionId);
  await sessionsRepo.completeIfNoActiveRun(sessionId);

  const row = await sessionsRepo.findById(sessionId);
  assert.equal(row?.status, 'completed');
  assert.ok(!Number.isNaN(Date.parse(row!.updatedAt)));

  await sessionsRepo.markInProgress(sessionId);
  const run = await runsRepo.createActiveRun({ sessionId, instanceId });
  parentRunId = run.id;
  await sessionsRepo.completeIfNoActiveRun(sessionId);
  assert.equal((await sessionsRepo.findById(sessionId))?.status, 'in_progress');
});

test('createSubRun：running 起步、继承归属、记录委派字段', async () => {
  const child = await runsRepo.createSubRun({
    sessionId,
    instanceId,
    parentRunId,
    parentToolUseId: 'toolu_parent',
    subagentType: 'general-purpose',
    delegationDepth: 1,
    taskId: 'task_a',
  });

  assert.equal(child.status, 'running');
  assert.ok(child.startedAt);
  assert.equal(child.sessionId, sessionId);
  assert.equal(child.instanceId, instanceId);
  assert.equal(child.parentRunId, parentRunId);
  assert.equal(child.parentToolUseId, 'toolu_parent');
  assert.equal(child.subagentType, 'general-purpose');
  assert.equal(child.delegationDepth, 1);
  assert.equal(child.taskId, 'task_a');
  assert.equal(child.finishedAt, null);

  firstChildId = child.id;
});

test('同一父 run 下多个活跃子 run 可并存', async () => {
  const second = await runsRepo.createSubRun({
    sessionId,
    instanceId,
    parentRunId,
    delegationDepth: 1,
    taskId: 'task_b',
  });
  const third = await runsRepo.createSubRun({
    sessionId,
    instanceId,
    parentRunId,
    delegationDepth: 1,
    taskId: 'task_c',
  });
  secondChildId = second.id;
  thirdChildId = third.id;

  assert.equal(second.status, 'running');
  assert.equal(third.status, 'running');
  const running = await prisma.run.count({ where: { parentRunId, status: 'running' } });
  assert.equal(running, 3);
});

test('listBySession 只返回顶层 run', async () => {
  const page = await runsRepo.listBySession(sessionId, 1, 10);
  assert.equal(page.total, 2);
  assert.ok(page.items.every((run) => run.parentRunId === null));

  const ids = page.items.map((run) => run.id);
  assert.ok(ids.includes(parentRunId));
  assert.ok(!ids.includes(firstChildId));
});

test('listChildren 按 startedAt 升序分页', async () => {
  const base = Date.UTC(2026, 0, 1);
  await prisma.run.update({ where: { id: firstChildId }, data: { startedAt: new Date(base + 3000) } });
  await prisma.run.update({ where: { id: secondChildId }, data: { startedAt: new Date(base + 1000) } });
  await prisma.run.update({ where: { id: thirdChildId }, data: { startedAt: new Date(base + 2000) } });

  const firstPage = await runsRepo.listChildren(parentRunId, 1, 2);
  assert.equal(firstPage.total, 3);
  assert.deepEqual(firstPage.items.map((run) => run.id), [secondChildId, thirdChildId]);

  const secondPage = await runsRepo.listChildren(parentRunId, 2, 2);
  assert.deepEqual(secondPage.items.map((run) => run.id), [firstChildId]);
});

test('findRoot 上溯顶层；断链与成环退回原 run', async () => {
  assert.equal((await runsRepo.findRoot(parentRunId))?.id, parentRunId);
  assert.equal((await runsRepo.findRoot(firstChildId))?.id, parentRunId);

  const grandchild = await runsRepo.createSubRun({
    sessionId,
    instanceId,
    parentRunId: thirdChildId,
    delegationDepth: 2,
    taskId: 'task_grandchild',
  });
  grandchildId = grandchild.id;
  assert.equal((await runsRepo.findRoot(grandchild.id))?.id, parentRunId);

  assert.equal(await runsRepo.findRoot('run_missing_entirely'), null);

  await prisma.run.create({
    data: {
      id: 'run_orphan',
      sessionId,
      instanceId,
      stage: 'development',
      parentRunId: 'run_absent',
      status: 'succeeded',
    },
  });
  assert.equal((await runsRepo.findRoot('run_orphan'))?.id, 'run_orphan');

  await prisma.run.create({
    data: {
      id: 'run_cycle_a',
      sessionId,
      instanceId,
      stage: 'development',
      parentRunId: 'run_cycle_b',
      status: 'succeeded',
    },
  });
  await prisma.run.create({
    data: {
      id: 'run_cycle_b',
      sessionId,
      instanceId,
      stage: 'development',
      parentRunId: 'run_cycle_a',
      status: 'succeeded',
    },
  });
  assert.equal((await runsRepo.findRoot('run_cycle_a'))?.id, 'run_cycle_a');
});

test('abortActiveDescendants：按血缘中止子 run、不碰顶层，只返回真正落终态的行', async () => {
  // 中间节点已终态、其下仍有活跃孙 run：遍历必须继续深入而不是只沿活跃节点走
  await runsRepo.finish(thirdChildId, 'succeeded');
  await prisma.run.create({
    data: {
      id: 'run_below_terminal',
      sessionId,
      instanceId,
      stage: 'development',
      parentRunId: thirdChildId,
      status: 'running',
    },
  });

  const settled = await runsRepo.abortActiveDescendants(parentRunId);
  assert.deepEqual(
    settled.map((run) => run.id).sort(),
    [firstChildId, secondChildId, grandchildId, 'run_below_terminal'].sort(),
  );
  for (const run of settled) {
    assert.equal(run.status, 'aborted');
    assert.ok(run.finishedAt);
  }

  const stillTop = await runsRepo.findById(parentRunId);
  assert.notEqual(stillTop?.status, 'aborted');

  assert.equal(await runsRepo.finish(parentRunId, 'aborted'), true);
  assert.equal(await runsRepo.findActiveBySession(sessionId), null);
});

test('迟到的收口只按血缘收敛：中止后新建的顶层 run 不受影响', async () => {
  const oldTop = await runsRepo.createActiveRun({ sessionId, instanceId });
  const oldChild = await runsRepo.createSubRun({
    sessionId,
    instanceId,
    parentRunId: oldTop.id,
    delegationDepth: 1,
    taskId: 'task_late_close',
  });
  // abortRun 先抢顶层终态并返回，新顶层 run 随即可起跑
  assert.equal(await runsRepo.finish(oldTop.id, 'aborted'), true);
  const newTop = await runsRepo.createActiveRun({ sessionId, instanceId });

  // 驱动链的 closeRun 稍后才收口：只能碰旧顶层 run 的后代
  const settled = await runsRepo.abortActiveDescendants(oldTop.id);
  assert.deepEqual(settled.map((run) => run.id), [oldChild.id]);
  assert.equal((await runsRepo.findById(newTop.id))?.status, 'pending');

  await runsRepo.finish(newTop.id, 'failed');
});

test('并发收口同一棵树：每行只由一方返回，不重复广播 aborted', async () => {
  const top = await runsRepo.createActiveRun({ sessionId, instanceId });
  const child = await runsRepo.createSubRun({
    sessionId,
    instanceId,
    parentRunId: top.id,
    delegationDepth: 1,
    taskId: 'task_concurrent_close',
  });

  const results = await Promise.all([
    runsRepo.abortActiveDescendants(top.id),
    runsRepo.abortActiveDescendants(top.id),
  ]);

  const ids = results.flat().map((run) => run.id);
  assert.deepEqual(ids, [child.id], '同一子 run 只能被一方从活跃态迁移出去');
  assert.equal((await runsRepo.findById(child.id))?.status, 'aborted');
  await runsRepo.finish(top.id, 'failed');
});

test('启动收口：活跃 run（含子 run）全部 failed，并返回待重算的会话', async () => {
  const top = await runsRepo.createActiveRun({ sessionId, instanceId });
  const child = await runsRepo.createSubRun({
    sessionId,
    instanceId,
    parentRunId: top.id,
    delegationDepth: 1,
    taskId: 'task_restart',
  });

  const touched = await runsRepo.failAllActiveRuns();
  assert.deepEqual(touched, [sessionId]);

  const topRow = await runsRepo.findById(top.id);
  assert.equal(topRow?.status, 'failed');
  assert.equal(topRow?.error, '服务重启');
  const childRow = await runsRepo.findById(child.id);
  assert.equal(childRow?.status, 'failed');
  assert.equal(childRow?.error, '服务重启');
  assert.equal(await runsRepo.findActiveBySession(sessionId), null);
});

test('并发：runtime 同 instance 两个 session 可同时起跑', async () => {
  const instance = await instancesRepo.getOrCreate('run-concurrent-runtime', 'runtime');
  const firstSession = await sessionsRepo.create({ instanceId: instance.id, modelId: TEST_MODEL_ID });
  const secondSession = await sessionsRepo.create({ instanceId: instance.id, modelId: TEST_MODEL_ID });

  const results = await Promise.allSettled([
    runsRepo.createActiveRun({ sessionId: firstSession.id, instanceId: instance.id }),
    runsRepo.createActiveRun({ sessionId: secondSession.id, instanceId: instance.id }),
  ]);

  assert.deepEqual(
    results.map((result) => result.status),
    ['fulfilled', 'fulfilled'],
  );
  assert.equal(
    await prisma.run.count({ where: { instanceId: instance.id, status: { in: ['pending', 'running'] } } }),
    2,
  );

  for (const result of results) {
    if (result.status === 'fulfilled') await runsRepo.finish(result.value.id, 'succeeded');
  }
});

test('并发：runtime 同一 session 起两次只放行一条', async () => {
  const instance = await instancesRepo.getOrCreate('run-concurrent-runtime-session', 'runtime');
  const session = await sessionsRepo.create({ instanceId: instance.id, modelId: TEST_MODEL_ID });

  const results = await Promise.allSettled([
    runsRepo.createActiveRun({ sessionId: session.id, instanceId: instance.id }),
    runsRepo.createActiveRun({ sessionId: session.id, instanceId: instance.id }),
  ]);

  const fulfilled = results.flatMap((result) => (result.status === 'fulfilled' ? [result.value] : []));
  const rejected = results.flatMap((result) => (result.status === 'rejected' ? [result.reason] : []));
  assert.equal(fulfilled.length, 1);
  assert.equal(rejected.length, 1);
  const error = rejected[0];
  assert.ok(error instanceof ConflictError);
  assert.equal(error.status, 409);

  assert.equal(
    await prisma.run.count({ where: { sessionId: session.id, status: { in: ['pending', 'running'] } } }),
    1,
  );
  await runsRepo.finish(fulfilled[0]!.id, 'succeeded');
});

test('并发：development 同 instance 两个 session 只放行一条', async () => {
  const instance = await instancesRepo.getOrCreate('run-concurrent-dev', 'development');
  const firstSession = await sessionsRepo.create({ instanceId: instance.id, modelId: TEST_MODEL_ID });
  const secondSession = await sessionsRepo.create({ instanceId: instance.id, modelId: TEST_MODEL_ID });

  const results = await Promise.allSettled([
    runsRepo.createActiveRun({ sessionId: firstSession.id, instanceId: instance.id }),
    runsRepo.createActiveRun({ sessionId: secondSession.id, instanceId: instance.id }),
  ]);

  const fulfilled = results.flatMap((result) => (result.status === 'fulfilled' ? [result.value] : []));
  const rejected = results.flatMap((result) => (result.status === 'rejected' ? [result.reason] : []));
  assert.equal(fulfilled.length, 1);
  assert.equal(rejected.length, 1);
  const error = rejected[0];
  assert.ok(error instanceof ConflictError);
  assert.equal(error.status, 409);
  assert.match(error.message, /实例/);

  await runsRepo.finish(fulfilled[0]!.id, 'succeeded');
});

test('并发：development 与 runtime 跨阶段只放行一条', async () => {
  const agentId = 'run-concurrent-cross';
  const development = await instancesRepo.getOrCreate(agentId, 'development');
  const runtime = await instancesRepo.getOrCreate(agentId, 'runtime');
  const developmentSession = await sessionsRepo.create({ instanceId: development.id, modelId: TEST_MODEL_ID });
  const runtimeSession = await sessionsRepo.create({ instanceId: runtime.id, modelId: TEST_MODEL_ID });

  const results = await Promise.allSettled([
    runsRepo.createActiveRun({ sessionId: developmentSession.id, instanceId: development.id }),
    runsRepo.createActiveRun({ sessionId: runtimeSession.id, instanceId: runtime.id }),
  ]);

  const fulfilled = results.flatMap((result) => (result.status === 'fulfilled' ? [result.value] : []));
  const rejected = results.flatMap((result) => (result.status === 'rejected' ? [result.reason] : []));
  assert.equal(fulfilled.length, 1, '跨阶段并发必须只放行一次插入');
  assert.equal(rejected.length, 1);
  const error = rejected[0];
  assert.ok(error instanceof ConflictError);
  assert.equal(error.status, 409);
  assert.match(error.message, /智能体正在/);

  await runsRepo.finish(fulfilled[0]!.id, 'succeeded');
});

test('绕过事务：development 同 instance 跨 session 第二条被实例索引拒绝', async () => {
  const instance = await instancesRepo.getOrCreate('run-bypass-cross', 'development');
  const firstSession = await sessionsRepo.create({ instanceId: instance.id, modelId: TEST_MODEL_ID });
  const secondSession = await sessionsRepo.create({ instanceId: instance.id, modelId: TEST_MODEL_ID });
  const run = await runsRepo.createActiveRun({ sessionId: firstSession.id, instanceId: instance.id });

  await assert.rejects(() =>
    prisma.run.create({
      data: {
        id: 'run_bypass_cross_session',
        sessionId: secondSession.id,
        instanceId: instance.id,
        stage: 'development',
        status: 'running',
      },
    }),
  );

  assert.equal(
    await prisma.run.count({ where: { instanceId: instance.id, status: { in: ['pending', 'running'] } } }),
    1,
  );
  await runsRepo.finish(run.id, 'succeeded');
});

test('deleteCascadeIfIdle：任意层级有活跃 run 时拒绝删除，终态后可删', async () => {
  const instance = await instancesRepo.getOrCreate('run-delete-idle', 'development');
  const session = await sessionsRepo.create({ instanceId: instance.id, modelId: TEST_MODEL_ID });
  const top = await runsRepo.createActiveRun({ sessionId: session.id, instanceId: instance.id });

  await assert.rejects(
    () => sessionsRepo.deleteCascadeIfIdle(session.id),
    (error: unknown) => error instanceof ConflictError && error.status === 409 && /活跃 run/.test(error.message),
  );
  assert.ok(await sessionsRepo.findById(session.id));
  assert.ok(await runsRepo.findById(top.id));

  // 顶层已终态、子 run 仍活跃：任意层级检查仍应拒绝
  const child = await runsRepo.createSubRun({
    sessionId: session.id,
    instanceId: instance.id,
    parentRunId: top.id,
    delegationDepth: 1,
  });
  await runsRepo.finish(top.id, 'succeeded');
  await assert.rejects(
    () => sessionsRepo.deleteCascadeIfIdle(session.id),
    (error: unknown) => error instanceof ConflictError && error.status === 409,
  );

  await runsRepo.finish(child.id, 'aborted');
  await sessionsRepo.deleteCascadeIfIdle(session.id);
  assert.equal(await sessionsRepo.findById(session.id), null);
  assert.equal(await prisma.run.count({ where: { sessionId: session.id } }), 0);
  assert.equal(await prisma.message.count({ where: { sessionId: session.id } }), 0);
});

test('deleteCascade：未使用会话即使有活跃 run 也无条件级联删除', async () => {
  const instance = await instancesRepo.getOrCreate('run-delete-unused', 'development');
  const session = await sessionsRepo.create({ instanceId: instance.id, modelId: TEST_MODEL_ID });
  await runsRepo.createActiveRun({ sessionId: session.id, instanceId: instance.id });

  await sessionsRepo.deleteCascade(session.id);

  assert.equal(await sessionsRepo.findById(session.id), null);
  assert.equal(await prisma.run.count({ where: { sessionId: session.id } }), 0);
});

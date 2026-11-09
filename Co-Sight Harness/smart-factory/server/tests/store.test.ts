import { after, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { prepareTestEnv } from './helpers/test-db.js';
import { TEST_MODEL_ID } from './helpers/workspace-stub.js';

prepareTestEnv('store');

const { prisma } = await import('../src/shared/prisma/client.js');
const { instancesRepo } = await import('../src/shared/store/instances.repo.js');
const { sessionsRepo } = await import('../src/shared/store/sessions.repo.js');
const { runsRepo } = await import('../src/shared/store/runs.repo.js');
const { messagesRepo } = await import('../src/shared/store/messages.repo.js');

let instanceId: string;

beforeEach(async () => {
  await prisma.message.deleteMany();
  await prisma.run.deleteMany();
  await prisma.session.deleteMany();
  await prisma.instance.deleteMany();
  instanceId = (await instancesRepo.getOrCreate('store-demo', 'development')).id;
});

after(async () => {
  await prisma.$disconnect();
});

async function newSession(): Promise<string> {
  return (await sessionsRepo.create({ instanceId, modelId: TEST_MODEL_ID })).id;
}

test('seq 分配：连续追加严格递增', async () => {
  const sessionId = await newSession();
  const a = await messagesRepo.append({ sessionId, role: 'user', type: 'text', content: { text: 'a' } });
  const b = await messagesRepo.append({ sessionId, role: 'assistant', type: 'text', content: { text: 'b' } });
  const c = await messagesRepo.append({ sessionId, role: 'assistant', type: 'text', content: { text: 'c' } });

  assert.deepEqual([a.seq, b.seq, c.seq], [1, 2, 3]);
  assert.deepEqual(a.content, { text: 'a' });
});

test('seq 分配：并发追加不重号，seq 恰好铺满 1..5', async () => {
  const sessionId = await newSession();
  const results = await Promise.all(
    Array.from({ length: 5 }, (_, i) =>
      messagesRepo.append({ sessionId, role: 'assistant', type: 'text', content: { text: `p${i}` } }),
    ),
  );

  const seqs = results.map((m) => m.seq).sort((x, y) => x - y);
  assert.deepEqual(seqs, [1, 2, 3, 4, 5]);
});

test('list：afterSeq 游标与 limit 决定 nextAfterSeq', async () => {
  const sessionId = await newSession();
  for (let i = 0; i < 8; i += 1) {
    await messagesRepo.append({ sessionId, role: 'assistant', type: 'text', content: { text: `m${i}` } });
  }

  const page1 = await messagesRepo.list({ sessionId, limit: 3 });
  assert.deepEqual(page1.items.map((m) => m.seq), [1, 2, 3]);
  assert.equal(page1.nextAfterSeq, 3);

  const page2 = await messagesRepo.list({ sessionId, afterSeq: page1.nextAfterSeq!, limit: 3 });
  assert.deepEqual(page2.items.map((m) => m.seq), [4, 5, 6]);
  assert.equal(page2.nextAfterSeq, 6);

  const tail = await messagesRepo.list({ sessionId, afterSeq: 6, limit: 10 });
  assert.deepEqual(tail.items.map((m) => m.seq), [7, 8]);
  assert.equal(tail.nextAfterSeq, null);
});

test('settlePending：先到者胜，第二次返回 null，且原有 content 保留', async () => {
  const sessionId = await newSession();
  const run = await runsRepo.createActiveRun({ sessionId, instanceId });
  const pending = await messagesRepo.append({
    sessionId,
    runId: run.id,
    role: 'assistant',
    type: 'approval',
    status: 'pending',
    content: { title: '执行 Bash', toolName: 'Bash' },
  });

  const settled = await messagesRepo.settlePending(pending.id, {
    status: 'approved',
    content: { decision: 'approved', decisionSource: 'user' },
  });
  assert.equal(settled?.status, 'approved');
  assert.deepEqual(settled?.content, {
    title: '执行 Bash',
    toolName: 'Bash',
    decision: 'approved',
    decisionSource: 'user',
  });

  assert.equal(
    await messagesRepo.settlePending(pending.id, { status: 'rejected', content: { decision: 'rejected' } }),
    null,
  );
});

test('waitingOf：统计 approval + tool_interactive 的 pending，忽略已结算', async () => {
  const sessionId = await newSession();
  const run = await runsRepo.createActiveRun({ sessionId, instanceId });
  await messagesRepo.append({
    sessionId,
    runId: run.id,
    role: 'assistant',
    type: 'approval',
    status: 'pending',
    content: { title: 't' },
  });
  const question = await messagesRepo.append({
    sessionId,
    runId: run.id,
    role: 'assistant',
    type: 'tool_interactive',
    status: 'pending',
    content: { questions: [{ header: 'H', question: 'Q?' }] },
  });

  const waiting = await runsRepo.waitingOf(run.id);
  assert.equal(waiting?.count, 2);
  assert.ok(!Number.isNaN(Date.parse(waiting!.since)));

  await messagesRepo.settlePending(question.id, { status: 'answered', content: { answers: { 'Q?': ['A'] } } });
  assert.equal((await runsRepo.waitingOf(run.id))?.count, 1);
});

test('abortPendingByRuns：挂起全部 aborted，approval 带 decision=aborted', async () => {
  const sessionId = await newSession();
  const run = await runsRepo.createActiveRun({ sessionId, instanceId });
  await messagesRepo.append({
    sessionId,
    runId: run.id,
    role: 'assistant',
    type: 'approval',
    status: 'pending',
    content: { title: 't' },
  });
  await messagesRepo.append({
    sessionId,
    runId: run.id,
    role: 'assistant',
    type: 'tool_interactive',
    status: 'pending',
    content: { questions: [] },
  });

  const settled = await messagesRepo.abortPendingByRuns([run.id], 'abort');
  assert.equal(settled.length, 2);

  const approval = settled.find((m) => m.type === 'approval')!;
  assert.equal((approval.content as { decision?: string }).decision, 'aborted');
  assert.equal((approval.content as { decisionSource?: string }).decisionSource, 'abort');
  assert.equal(await runsRepo.waitingOf(run.id), null);
});

test('abortAllPending：启动收口扫掉所有残留 pending', async () => {
  const sessionId = await newSession();
  await messagesRepo.append({ sessionId, role: 'assistant', type: 'approval', status: 'pending', content: { title: 't' } });
  await messagesRepo.append({ sessionId, role: 'assistant', type: 'text', content: { text: 'x' } });

  const settled = await messagesRepo.abortAllPending('restart');
  assert.equal(settled.length, 1);
  assert.equal((settled[0]!.content as { decisionSource?: string }).decisionSource, 'restart');
  assert.equal((await messagesRepo.list({ sessionId, limit: 50, status: 'pending' })).items.length, 0);
});

test('删除级联：删会话连带清掉 run 与 message', async () => {
  const doomed = await newSession();
  await runsRepo.createActiveRun({ sessionId: doomed, instanceId });
  await messagesRepo.append({ sessionId: doomed, role: 'user', type: 'text', content: { text: 'x' } });

  await sessionsRepo.deleteCascade(doomed);

  assert.equal(await sessionsRepo.findById(doomed), null);
  assert.equal(await prisma.run.count({ where: { sessionId: doomed } }), 0);
  assert.equal(await prisma.message.count({ where: { sessionId: doomed } }), 0);
});

test('list 过滤：status=pending 是刷新后恢复弹窗的入口', async () => {
  const sessionId = await newSession();
  const run = await runsRepo.createActiveRun({ sessionId, instanceId });
  await messagesRepo.append({
    sessionId,
    runId: run.id,
    role: 'assistant',
    type: 'approval',
    status: 'pending',
    content: { title: 'p' },
  });

  const pending = await messagesRepo.list({ sessionId, limit: 50, status: 'pending' });
  assert.equal(pending.items.length, 1);
  assert.equal(pending.items[0]!.status, 'pending');
});

test('runs.markRunning：仅 pending 可转 running，终态不被复活', async () => {
  const sessionId = await newSession();
  const run = await runsRepo.createActiveRun({ sessionId, instanceId });
  assert.equal(await runsRepo.markRunning(run.id), true);

  assert.equal(await runsRepo.finish(run.id, 'succeeded'), true);
  const settled = (await runsRepo.findById(run.id))!;

  assert.equal(await runsRepo.markRunning(run.id), false);
  const stored = (await runsRepo.findById(run.id))!;
  assert.equal(stored.status, 'succeeded');
  assert.equal(stored.startedAt, settled.startedAt);
  assert.equal(stored.finishedAt, settled.finishedAt);
});

test('runs.finish：二次终结返回 false，已写终态、error 与 finishedAt 不被覆盖', async () => {
  const sessionId = await newSession();
  const run = await runsRepo.createActiveRun({ sessionId, instanceId });

  assert.equal(await runsRepo.finish(run.id, 'aborted', '用户中止'), true);
  const settled = (await runsRepo.findById(run.id))!;

  assert.equal(await runsRepo.finish(run.id, 'failed', '重放不应覆盖'), false);

  const stored = (await runsRepo.findById(run.id))!;
  assert.equal(stored.status, 'aborted');
  assert.equal(stored.error, '用户中止');
  assert.equal(stored.finishedAt, settled.finishedAt);
});

test('sessions.list：按 agentId 过滤并分页', async () => {
  await sessionsRepo.create({ instanceId, modelId: TEST_MODEL_ID });
  await sessionsRepo.create({ instanceId, modelId: TEST_MODEL_ID });

  const all = await sessionsRepo.list({ agentId: 'store-demo', page: 1, pageSize: 10 });
  assert.equal(all.total, 2);
  assert.equal(all.items.length, 2);

  const other = await sessionsRepo.list({ agentId: 'store-other', page: 1, pageSize: 10 });
  assert.equal(other.total, 0);
});

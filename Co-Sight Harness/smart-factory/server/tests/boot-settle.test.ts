import { after, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { prepareTestEnv } from './helpers/test-db.js';
import { TEST_MODEL_ID } from './helpers/workspace-stub.js';

prepareTestEnv('boot-settle');

const { prisma } = await import('../src/shared/prisma/client.js');
const { instancesRepo } = await import('../src/shared/store/instances.repo.js');
const { sessionsRepo } = await import('../src/shared/store/sessions.repo.js');
const { runsRepo } = await import('../src/shared/store/runs.repo.js');
const { messagesRepo } = await import('../src/shared/store/messages.repo.js');
const { settleOnBoot } = await import('../src/boot-settle.js');

let instanceIndex = 0;

beforeEach(async () => {
  await prisma.message.deleteMany();
  await prisma.run.deleteMany();
  await prisma.session.deleteMany();
  await prisma.instance.deleteMany();
});

after(async () => {
  await prisma.$disconnect();
});

/** 每个用例用独立实例：部分唯一索引按 instance 约束活跃 run。 */
async function newInProgressSession(): Promise<{ instanceId: string; sessionId: string }> {
  const instance = await instancesRepo.getOrCreate(`boot-settle-${instanceIndex++}`, 'development');
  const session = await sessionsRepo.create({ instanceId: instance.id, modelId: TEST_MODEL_ID });
  await sessionsRepo.markInProgress(session.id);
  return { instanceId: instance.id, sessionId: session.id };
}

async function sessionStatus(id: string): Promise<string | undefined> {
  return (await sessionsRepo.findById(id))?.status;
}

test('活跃 run 被置 failed（服务重启），挂起消息被置 aborted（restart），会话重算 completed', async () => {
  const { instanceId, sessionId } = await newInProgressSession();
  const run = await runsRepo.createActiveRun({ sessionId, instanceId });
  const approval = await messagesRepo.append({
    sessionId,
    runId: run.id,
    role: 'assistant',
    type: 'approval',
    status: 'pending',
    content: { text: '请审批' },
  });
  const interactive = await messagesRepo.append({
    sessionId,
    runId: run.id,
    role: 'assistant',
    type: 'tool_interactive',
    status: 'pending',
    content: { text: '请选择' },
  });

  await settleOnBoot();

  const settledRun = await runsRepo.findById(run.id);
  assert.equal(settledRun?.status, 'failed');
  assert.equal(settledRun?.error, '服务重启');
  assert.equal(await sessionStatus(sessionId), 'completed');

  const settledApproval = await prisma.message.findUnique({ where: { id: approval.id } });
  const settledInteractive = await prisma.message.findUnique({ where: { id: interactive.id } });
  for (const row of [settledApproval, settledInteractive]) {
    assert.equal(row?.status, 'aborted');
    assert.equal((JSON.parse(row!.content) as { decisionSource?: string }).decisionSource, 'restart');
  }
});

test('run 已落终态但会话仍 in_progress：启动收口也要重算', async () => {
  const { instanceId, sessionId } = await newInProgressSession();
  // 模拟「run 条件落终态后、closeRun 重算前进程被杀」留下的残留
  const run = await runsRepo.createActiveRun({ sessionId, instanceId });
  assert.equal(await runsRepo.finish(run.id, 'succeeded'), true);
  assert.equal(await sessionStatus(sessionId), 'in_progress');

  await settleOnBoot();

  assert.equal(await sessionStatus(sessionId), 'completed');
});

test('无活跃 run 的 in_progress 残留一并收口；已 completed 会话不受影响', async () => {
  const stuck = await newInProgressSession();
  const settled = await newInProgressSession();
  await sessionsRepo.completeIfNoActiveRun(settled.sessionId);

  await settleOnBoot();

  assert.equal(await sessionStatus(stuck.sessionId), 'completed');
  assert.equal(await sessionStatus(settled.sessionId), 'completed');
});

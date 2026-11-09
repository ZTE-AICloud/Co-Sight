import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { prepareTestEnv } from './helpers/test-db.js';
import { seedAgent, seedDevelopmentDir, TEST_WORKSPACE_DEFAULT_ID } from './helpers/agents.js';
import { startWorkspaceStub, TEST_MODEL_ID } from './helpers/workspace-stub.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

const env = prepareTestEnv('run-failure');
const stub = await startWorkspaceStub(env);

const { prisma } = await import('../src/shared/prisma/client.js');
const { messagesRepo } = await import('../src/shared/store/messages.repo.js');
const { runsRepo } = await import('../src/shared/store/runs.repo.js');
const { sessionsRepo } = await import('../src/shared/store/sessions.repo.js');
const { instancesRepo } = await import('../src/shared/store/instances.repo.js');
const { liveHub } = await import('../src/shared/live/live-hub.js');
const { settleRunPendings, sessionService } = await import('../src/modules/session/session.service.js');
const { FakeAdapter } = await import('../src/shared/engine/fake-adapter.js');
const { ConflictError } = await import('../src/shared/errors.js');
import type { EngineEvent } from '../src/shared/engine/port.js';

let api: TestApi;

before(async () => {
  // agents 表是智能体存在的唯一权威（08-agent.md §1）：没有这一行，下面的
  // sessions/create 会 404 而不是建会话
  await seedAgent('run-failure');
  await seedAgent('run-failure-pending');
  await seedAgent('run-failure-duplicate');
  await seedAgent('run-failure-resume');
  await seedAgent('run-failure-model');
  // 工作区默认模型可用的智能体：空模型时仍必须失败，不得回落到工作区默认值
  await seedAgent('run-failure-fallback', 'run-failure-fallback', TEST_WORKSPACE_DEFAULT_ID);
  // 起跑条件解析在建 run 之前：development 目录不存在会先于引擎 / 模型失败
  seedDevelopmentDir(env.workspaceDir, 'run-failure');
  seedDevelopmentDir(env.workspaceDir, 'run-failure-pending');
  seedDevelopmentDir(env.workspaceDir, 'run-failure-duplicate');
  seedDevelopmentDir(env.workspaceDir, 'run-failure-resume');
  seedDevelopmentDir(env.workspaceDir, 'run-failure-model');
  seedDevelopmentDir(env.workspaceDir, 'run-failure-fallback');
  api = await startTestApi();
});

after(async () => {
  await api.close();
  await stub.close();
  await prisma.$disconnect();
});

test('引擎解析失败：send 返回错误，不建 run、不落用户消息、会话状态不变', async () => {
  const created = await api.post(`${API}/sessions/create`, { agentId: 'run-failure', modelId: TEST_MODEL_ID });
  assert.equal(created.status, 200);

  // 未知引擎在 resolveRunSetup 里 fail-fast：发生在建 run 之前
  await prisma.instance.update({ where: { id: created.body.instance.id }, data: { engine: 'nope' } });

  const sent = await api.post(`${API}/messages/send`, { sessionId: created.body.id, prompt: '你好' });
  assert.equal(sent.status, 400);
  assert.equal(sent.body.error, 'BAD_REQUEST');
  assert.match(sent.body.message, /未知引擎/);

  assert.equal(await prisma.run.count({ where: { sessionId: created.body.id } }), 0, '解析失败不得留下 run');
  assert.equal(await prisma.message.count({ where: { sessionId: created.body.id } }), 0, '解析失败不得落下用户消息');
  assert.equal((await api.get(`${API}/sessions/detail?sessionId=${created.body.id}`)).body.status, 'not_started');
});

test('模型解析失败：send 400，不建 run、不落用户消息、会话状态不变', async () => {
  // sessions/create 会先校验模型；这里直接落一行非法模型，覆盖 send 时的解析失败
  const instance = await instancesRepo.getOrCreate('run-failure-model', 'development');
  const session = await sessionsRepo.create({ instanceId: instance.id, modelId: 'mdl_missing_for_run_failure' });

  const sent = await api.post(`${API}/messages/send`, { sessionId: session.id, prompt: '你好' });
  assert.equal(sent.status, 400);
  assert.equal(sent.body.error, 'BAD_REQUEST');
  assert.equal(sent.body.messageKey, 'error.bad_request.session_model_missing');
  assert.match(sent.body.message, /已被删除/);

  assert.equal(await prisma.run.count({ where: { sessionId: session.id } }), 0, '解析失败不得留下 run');
  assert.equal(await prisma.message.count({ where: { sessionId: session.id } }), 0, '解析失败不得落下用户消息');
  assert.equal((await api.get(`${API}/sessions/detail?sessionId=${session.id}`)).body.status, 'not_started');
});

test('空模型不回落到工作区默认模型或框架 activeId：send 400，不建 run', async () => {
  const created = await api.post(`${API}/sessions/create`, { agentId: 'run-failure-fallback', modelId: TEST_MODEL_ID });
  assert.equal(created.status, 200);
  // 框架有生效模型（activeId = TEST_MODEL_ID），但会话模型为空时必须直接失败，不得回退
  await prisma.session.update({ where: { id: created.body.id }, data: { modelId: '' } });

  const sent = await api.post(`${API}/messages/send`, { sessionId: created.body.id, prompt: '你好' });
  assert.equal(sent.status, 400);
  assert.equal(sent.body.error, 'BAD_REQUEST');
  assert.match(sent.body.message, /没有模型/);
  assert.equal(await prisma.run.count({ where: { sessionId: created.body.id } }), 0);
  assert.equal(await prisma.message.count({ where: { sessionId: created.body.id } }), 0);
});

test('引擎已把同一错误当助手文本落库：失败收口不再补 system/error，错误文本只出现一次', async () => {
  const created = await api.post(`${API}/sessions/create`, { agentId: 'run-failure-duplicate', modelId: TEST_MODEL_ID });
  assert.equal(created.status, 200);

  // 真机形态：SDK 先把上游 API 错误当助手文本 emit，随后 result 又抛同一个错
  const errorText = 'API Error: 400 The supported API model names are …';
  const originalRun = FakeAdapter.prototype.run;
  FakeAdapter.prototype.run = async (ctx) => {
    await ctx.emit({ type: 'message', draft: { role: 'assistant', type: 'text', content: { text: errorText } } });
    throw new Error(errorText);
  };
  try {
    const sent = await api.post(`${API}/messages/send`, { sessionId: created.body.id, prompt: '你好' });
    assert.equal(sent.status, 200);

    const run = await api.waitTerminal(sent.body.run.id);
    assert.equal(run.status, 'failed');
    assert.equal(run.error, errorText);
  } finally {
    FakeAdapter.prototype.run = originalRun;
  }

  const messages = await api.get(`${API}/messages/list?sessionId=${created.body.id}`);
  assert.deepEqual(
    messages.body.items.map((m: any) => [m.seq, m.role, m.type]),
    [
      [1, 'user', 'text'],
      [2, 'assistant', 'text'],
    ],
  );
  const occurrences = messages.body.items.filter((m: any) => JSON.stringify(m.content).includes(errorText));
  assert.equal(occurrences.length, 1, '同一错误文本只能落一条');
});

test('共用结算函数：直调后该 run 的挂起全部落 aborted、等待句柄被放行，不影响其它 run', async () => {
  const instance = await instancesRepo.getOrCreate('rf-settle', 'development');
  const session = await sessionsRepo.create({ instanceId: instance.id, modelId: TEST_MODEL_ID });
  const run = await runsRepo.createActiveRun({ sessionId: session.id, instanceId: instance.id });
  const approval = await messagesRepo.append({
    sessionId: session.id,
    runId: run.id,
    role: 'assistant',
    type: 'approval',
    status: 'pending',
    content: { title: '执行 Bash：echo hi' },
  });
  const interactive = await messagesRepo.append({
    sessionId: session.id,
    runId: run.id,
    role: 'assistant',
    type: 'tool_interactive',
    status: 'pending',
    content: { questions: [] },
  });

  // 另一实例 / run 的挂起：结算必须是 run 粒度
  const otherInstance = await instancesRepo.getOrCreate('rf-settle-other', 'development');
  const otherSession = await sessionsRepo.create({ instanceId: otherInstance.id, modelId: TEST_MODEL_ID });
  const otherRun = await runsRepo.createActiveRun({ sessionId: otherSession.id, instanceId: otherInstance.id });
  const otherPending = await messagesRepo.append({
    sessionId: otherSession.id,
    runId: otherRun.id,
    role: 'assistant',
    type: 'approval',
    status: 'pending',
    content: { title: '别的 run' },
  });

  const released = liveHub.waitFor<{ decision?: string }>(approval.id);
  await settleRunPendings([run.id]);
  assert.deepEqual(await released, { decision: 'aborted' }, '被阻塞的引擎应拿到放行句柄');

  const approvalRow = await prisma.message.findUnique({ where: { id: approval.id } });
  assert.equal(approvalRow?.status, 'aborted');
  const approvalContent = JSON.parse(approvalRow!.content);
  assert.equal(approvalContent.decision, 'aborted');
  assert.equal(approvalContent.decisionSource, 'abort');
  assert.equal(approvalContent.title, '执行 Bash：echo hi', '结算不得丢原 content');

  const interactiveRow = await prisma.message.findUnique({ where: { id: interactive.id } });
  assert.equal(interactiveRow?.status, 'aborted');
  const interactiveContent = JSON.parse(interactiveRow!.content);
  assert.equal(interactiveContent.decisionSource, 'abort');
  assert.equal('answers' in interactiveContent, false);
  assert.equal('decision' in interactiveContent, false);

  assert.equal((await prisma.message.findUnique({ where: { id: otherPending.id } }))?.status, 'pending');
});

test('同一 task_id 的新 run_id：新建子 run 并切换内容归属，迟到内容被终态守卫丢弃', async () => {
  const created = await api.post(`${API}/sessions/create`, { agentId: 'run-failure-resume', modelId: TEST_MODEL_ID });
  assert.equal(created.status, 200);

  const taskStarted = (runId: string, toolUseId: string | null): EngineEvent => ({
    type: 'task_started',
    taskId: 'task_resume',
    runId,
    toolUseId,
    parentTaskId: null,
    subagentType: 'general-purpose',
    delegationDepth: 1,
    description: '恢复任务',
  });
  const text = (value: string): EngineEvent =>
    ({ type: 'message', draft: { role: 'assistant', type: 'text', content: { text: value } }, agentId: 'task_resume' }) as EngineEvent;
  // 恢复后的流式/工具结果帧只有 parent_tool_use_id，没有 agent_id
  const toolText = (value: string): EngineEvent =>
    ({ type: 'message', draft: { role: 'assistant', type: 'text', content: { text: value } }, parentToolUseId: 'tu_resume' }) as EngineEvent;

  let sent!: { status: number; body: any };
  const originalRun = FakeAdapter.prototype.run;
  FakeAdapter.prototype.run = async (ctx) => {
    // 第一轮 run 尚未收到 notification，SDK 就以同一 task_id、新 run_id 恢复
    await ctx.emit(taskStarted('run-a', 'tu_resume'));
    await ctx.emit(text('第一轮内容'));
    // 恢复后的 task_started 可能不再带 tool_use_id，任务级工具映射仍须切到新 run
    await ctx.emit(taskStarted('run-b', null));
    await ctx.emit(toolText('第二轮内容'));
    await ctx.emit({
      type: 'task_notified',
      taskId: 'task_resume',
      runId: 'run-b',
      status: 'completed',
      summary: '恢复完成',
      error: null,
    });
    // run-b 已终态：迟到内容不得落库
    await ctx.emit(toolText('迟到内容'));
    return { output: 'ok' };
  };
  try {
    sent = await api.post(`${API}/messages/send`, { sessionId: created.body.id, prompt: '恢复' });
    assert.equal(sent.status, 200);
    const parent = await api.waitTerminal(sent.body.run.id);
    assert.equal(parent.status, 'succeeded');
  } finally {
    FakeAdapter.prototype.run = originalRun;
  }

  const children = (await api.get(`${API}/runs/children?runId=${sent.body.run.id}`)).body.items;
  assert.equal(children.length, 2, '同一 task_id 的新 run_id 必须新建子 run');
  assert.deepEqual(children.map((child: any) => child.taskId), ['task_resume', 'task_resume']);
  const stopped = children.find((child: any) => child.status === 'aborted');
  const resumed = children.find((child: any) => child.status === 'succeeded');
  assert.ok(stopped, '未收到 notification 的旧 run 在收口时落 aborted');
  assert.ok(resumed, '新 run 按 run_id 落 succeeded');

  const first = (await api.get(`${API}/messages/list?runId=${stopped.id}`)).body.items;
  assert.ok(first.some((message: any) => message.content.text === '第一轮内容'));
  const second = (await api.get(`${API}/messages/list?runId=${resumed.id}`)).body.items;
  assert.ok(second.some((message: any) => message.content.text === '第二轮内容'));
  assert.ok(!second.some((message: any) => message.content.text === '迟到内容'));
});

test('中止已终态的子 run：409，顶层 run 与其挂起均不受影响', async () => {
  const instance = await instancesRepo.getOrCreate('rf-terminal-child', 'development');
  const session = await sessionsRepo.create({ instanceId: instance.id, modelId: TEST_MODEL_ID });
  const root = await runsRepo.createActiveRun({ sessionId: session.id, instanceId: instance.id });
  const child = await runsRepo.createSubRun({
    sessionId: session.id,
    instanceId: instance.id,
    parentRunId: root.id,
    delegationDepth: 1,
    taskId: 'task_terminal_child',
  });
  await runsRepo.finish(child.id, 'succeeded');
  const pending = await messagesRepo.append({
    sessionId: session.id,
    runId: root.id,
    role: 'assistant',
    type: 'approval',
    status: 'pending',
    content: { title: '不应被结算' },
  });

  try {
    await assert.rejects(
      () => sessionService.abortRun(child.id),
      (error: unknown) => error instanceof ConflictError && error.status === 409,
    );
    assert.equal((await runsRepo.findById(root.id))?.status, 'pending');
    assert.equal((await messagesRepo.findById(pending.id))?.status, 'pending');
  } finally {
    await runsRepo.finish(root.id, 'failed');
  }
});

test('引擎失败时清扫残留挂起：failed run 不留 pending、waiting 恒 null', async () => {
  const created = await api.post(`${API}/sessions/create`, { agentId: 'run-failure-pending', modelId: TEST_MODEL_ID });
  assert.equal(created.status, 200);

  // 引擎在运行期失败（起跑条件已解析成功）
  const originalRun = FakeAdapter.prototype.run;
  FakeAdapter.prototype.run = async () => {
    throw new Error('桩失败');
  };

  // 起 run 时挂一条 pending：模拟「引擎失败瞬间仍有审批在等」的残留
  const originalCreate = runsRepo.createActiveRun;
  runsRepo.createActiveRun = async (input) => {
    const run = await originalCreate.call(runsRepo, input);
    await prisma.message.create({
      data: {
        id: 'msg_failure_pending',
        sessionId: run.sessionId,
        runId: run.id,
        seq: 999,
        role: 'assistant',
        type: 'approval',
        status: 'pending',
        content: JSON.stringify({ title: '残留的审批' }),
      },
    });
    return run;
  };

  try {
    const sent = await api.post(`${API}/messages/send`, { sessionId: created.body.id, prompt: '你好' });
    assert.equal(sent.status, 200);
    const run = await api.waitTerminal(sent.body.run.id);
    assert.equal(run.status, 'failed');
    // 4.05 §6.1：终态 run 的派生 waiting 恒为 null
    assert.equal(run.waiting, null);
  } finally {
    FakeAdapter.prototype.run = originalRun;
    runsRepo.createActiveRun = originalCreate;
  }

  const stored = await prisma.message.findUnique({ where: { id: 'msg_failure_pending' } });
  assert.equal(stored?.status, 'aborted');
  const content = JSON.parse(stored!.content);
  assert.equal(content.decision, 'aborted');
  assert.equal(content.decisionSource, 'abort');
  assert.equal(await prisma.message.count({ where: { sessionId: created.body.id, status: 'pending' } }), 0);
});

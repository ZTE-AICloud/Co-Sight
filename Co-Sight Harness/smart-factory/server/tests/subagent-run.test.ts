import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import type { Envelope } from '../src/shared/live/envelope.js';
import { prepareTestEnv } from './helpers/test-db.js';
import { seedAgent, seedDevelopmentDir } from './helpers/agents.js';
import { startWorkspaceStub, TEST_MODEL_ID } from './helpers/workspace-stub.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

const env = prepareTestEnv('subagent-run');
const stub = await startWorkspaceStub(env);

const { prisma } = await import('../src/shared/prisma/client.js');
const { liveHub } = await import('../src/shared/live/live-hub.js');
const { FAKE_TRIGGER, FakeAdapter } = await import('../src/shared/engine/fake-adapter.js');
const { runsRepo } = await import('../src/shared/store/runs.repo.js');
const { sessionsRepo } = await import('../src/shared/store/sessions.repo.js');
const { instancesRepo } = await import('../src/shared/store/instances.repo.js');

let api: TestApi;

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

interface RecordedEvent {
  method: string;
  payload: any;
}

/** 订阅会话实时事件：与 WS 网关共用同一个 liveHub 广播源。 */
function collect(sessionId: string): { events: RecordedEvent[]; stop: () => void } {
  const events: RecordedEvent[] = [];
  const subscriber = {
    send(envelope: Envelope): boolean {
      events.push({ method: envelope.method, payload: envelope.payload });
      return true;
    },
  };
  liveHub.subscribe(sessionId, subscriber);
  return { events, stop: () => liveHub.unsubscribe(sessionId, subscriber) };
}

async function waitEvent(
  events: RecordedEvent[],
  method: string,
  predicate: (event: RecordedEvent) => boolean = () => true,
  timeoutMs = 5000,
): Promise<RecordedEvent> {
  for (let waited = 0; waited < timeoutMs; waited += 20) {
    const found = events.find((event) => event.method === method && predicate(event));
    if (found) return found;
    await sleep(20);
  }
  throw new Error(`未在 ${timeoutMs}ms 内收到事件 ${method}`);
}

async function newSession(agentId: string): Promise<any> {
  await seedAgent(agentId);
  seedDevelopmentDir(env.workspaceDir, agentId);
  return (await api.post(`${API}/sessions/create`, { agentId, modelId: TEST_MODEL_ID })).body;
}

async function waitPending(sessionId: string, timeoutMs = 5000): Promise<any> {
  for (let waited = 0; waited < timeoutMs; waited += 50) {
    const { body } = await api.get(`${API}/messages/list?sessionId=${sessionId}&status=pending`);
    if (body.items.length > 0) return body.items[0];
    await sleep(50);
  }
  throw new Error(`会话 ${sessionId} 未在 ${timeoutMs}ms 内出现挂起消息`);
}

async function waitFor(predicate: () => boolean, what: string, timeoutMs = 5000): Promise<void> {
  for (let waited = 0; waited < timeoutMs; waited += 20) {
    if (predicate()) return;
    await sleep(20);
  }
  throw new Error(`未在 ${timeoutMs}ms 内等到 ${what}`);
}

async function waitChildren(runId: string, count = 1, timeoutMs = 5000): Promise<any[]> {
  for (let waited = 0; waited < timeoutMs; waited += 50) {
    const { body } = await api.get(`${API}/runs/children?runId=${runId}`);
    if (body.items.length >= count) return body.items;
    await sleep(50);
  }
  throw new Error(`run ${runId} 未在 ${timeoutMs}ms 内出现 ${count} 个子 run`);
}

before(async () => {
  api = await startTestApi();
});

after(async () => {
  await api.close();
  await stub.close();
  await prisma.$disconnect();
});

test('子 run 字段与内容归位：runs/list 只看顶层、runs/children 返回子 run', async () => {
  const session = await newSession('sub-flow');
  const { events, stop } = collect(session.id);
  try {
    const sent = await api.post(`${API}/messages/send`, {
      sessionId: session.id,
      prompt: `${FAKE_TRIGGER.subagent}：整理目录`,
    });
    const parent = await api.waitTerminal(sent.body.run.id);
    assert.equal(parent.status, 'succeeded');

    const children = await api.get(`${API}/runs/children?runId=${parent.id}`);
    assert.equal(children.status, 200);
    assert.equal(children.body.total, 1);
    const child = children.body.items[0];
    assert.equal(child.parentRunId, parent.id);
    assert.equal(child.parentToolUseId, 'toolu_fake_task_1');
    assert.equal(child.subagentType, 'general-purpose');
    assert.equal(child.delegationDepth, 1);
    assert.equal(child.taskId, 'task_fake_1');
    assert.equal(child.status, 'succeeded');
    assert.ok(child.startedAt);
    assert.ok(child.finishedAt);
    assert.equal(child.waiting, null);

    // runs/detail 可查子 run
    const detail = await api.get(`${API}/runs/detail?runId=${child.id}`);
    assert.equal(detail.status, 200);
    assert.equal(detail.body.id, child.id);
    assert.equal(detail.body.parentRunId, parent.id);

    // runs/list 只返回顶层 run
    const list = await api.get(`${API}/runs/list?sessionId=${session.id}`);
    assert.equal(list.body.total, 1);
    assert.deepEqual(
      list.body.items.map((run: any) => run.id),
      [parent.id],
    );
    assert.equal(list.body.items[0].parentRunId, null);

    // task.started 负载带齐血缘字段：线上一律用 toolCallId
    const started = await waitEvent(events, 'task.started');
    assert.deepEqual(started.payload, {
      sessionId: session.id,
      runId: child.id,
      parentRunId: parent.id,
      taskId: 'task_fake_1',
      toolCallId: 'toolu_fake_task_1',
      subagentType: 'general-purpose',
      delegationDepth: 1,
      description: '桩子代理任务',
    });
    assert.equal('parentToolUseId' in started.payload, false);

    // 子 run 内容：tool_use / tool_result 均归位到子 run
    const childMessages = await api.get(`${API}/messages/list?runId=${child.id}`);
    const childTools = childMessages.body.items.filter(
      (message: any) => message.type === 'tool_use' || message.type === 'tool_result',
    );
    assert.deepEqual(
      childTools.map((message: any) => [message.type, message.content.toolCallId, message.runId]),
      [
        ['tool_use', 'toolu_fake_child_1', child.id],
        ['tool_result', 'toolu_fake_child_1', child.id],
      ],
    );

    // 父 run 的 Task 调用与结果留在顶层
    const parentMessages = await api.get(`${API}/messages/list?runId=${parent.id}`);
    const tasks = parentMessages.body.items.filter(
      (message: any) => message.content.toolCallId === 'toolu_fake_task_1',
    );
    assert.deepEqual(
      tasks.map((message: any) => [message.type, message.runId]),
      [
        ['tool_use', parent.id],
        ['tool_result', parent.id],
      ],
    );
    assert.equal(tasks[0]!.content.toolName, 'Task');

    // 工具兼容事件带子 runId 与父 runId
    const executing = await waitEvent(
      events,
      'tool.executing',
      (event) => event.payload.toolCallId === 'toolu_fake_child_1',
    );
    assert.equal(executing.payload.sessionId, session.id);
    assert.equal(executing.payload.runId, child.id);
    assert.equal(executing.payload.parentRunId, parent.id);
    const executed = await waitEvent(
      events,
      'tool.executed',
      (event) => event.payload.toolCallId === 'toolu_fake_child_1',
    );
    assert.equal(executed.payload.sessionId, session.id);
    assert.equal(executed.payload.runId, child.id);
    assert.equal(executed.payload.parentRunId, parent.id);

    // run.started / run.status 只表示顶层 run：事件必须存在，且不得指向子 run
    await waitEvent(events, 'run.status', (event) => event.payload.id === parent.id);
    assert.ok(
      events.some((event) => event.method === 'run.started' && event.payload.id === parent.id),
      '顶层 run.started 必须存在',
    );
    assert.ok(
      events.filter((event) => event.method === 'run.started').every((event) => event.payload.id === parent.id),
      'run.started 不得指向子 run',
    );
    assert.ok(
      events.some((event) => event.method === 'run.status' && event.payload.id === parent.id),
      '顶层 run.status 必须存在',
    );
    assert.ok(
      events.filter((event) => event.method === 'run.status').every((event) => event.payload.id === parent.id),
      'run.status 不得指向子 run',
    );

    // task.notified 恰好一次
    const notified = events.filter((event) => event.method === 'task.notified');
    assert.equal(notified.length, 1);
    assert.deepEqual(notified[0]!.payload, {
      sessionId: session.id,
      runId: child.id,
      parentRunId: parent.id,
      taskId: 'task_fake_1',
      status: 'completed',
      subagentType: 'general-purpose',
      error: null,
      summary: '子代理完成',
    });

    // 会话 completed 发生父子全部终态之后
    const completed = await waitEvent(events, 'session.status', (event) => event.payload.status === 'completed');
    const parentStatus = events.find(
      (event) => event.method === 'run.status' && event.payload.id === parent.id,
    )!;
    assert.ok(events.indexOf(notified[0]!) < events.indexOf(parentStatus));
    assert.ok(events.indexOf(parentStatus) < events.indexOf(completed));
    assert.equal((await api.get(`${API}/runs/detail?runId=${parent.id}`)).body.status, 'succeeded');
    assert.equal((await api.get(`${API}/runs/detail?runId=${child.id}`)).body.status, 'succeeded');
    assert.equal((await api.get(`${API}/sessions/detail?sessionId=${session.id}`)).body.status, 'completed');
  } finally {
    stop();
  }
});

test('子审批落在子 run：可正常应答，approvedAll 是会话级开关', async () => {
  const session = await newSession('sub-approval');
  const { events, stop } = collect(session.id);
  try {
    const sent = await api.post(`${API}/messages/send`, {
      sessionId: session.id,
      prompt: `${FAKE_TRIGGER.subagent}：${FAKE_TRIGGER.approval}`,
    });
    const pending = await waitPending(session.id);
    const child = (await waitChildren(sent.body.run.id))[0]!;

    assert.equal(pending.type, 'approval');
    assert.equal(pending.runId, child.id);
    assert.equal(pending.content.title, '子代理执行 Bash：echo child');

    // waiting 是子 run 的派生字段
    const hanging = await api.get(`${API}/runs/detail?runId=${child.id}`);
    assert.equal(hanging.body.status, 'running');
    assert.equal(hanging.body.waiting.count, 1);

    // 审批兼容事件带子 runId 与父 runId
    const request = await waitEvent(
      events,
      'approval.request',
      (event) => event.payload.approvalId === pending.id,
    );
    assert.equal(request.payload.sessionId, session.id);
    assert.equal(request.payload.runId, child.id);
    assert.equal(request.payload.parentRunId, sent.body.run.id);
    assert.equal(request.payload.agentId, 'task_fake_1');
    assert.equal('expiresAt' in request.payload, false);

    const responded = await api.post(`${API}/messages/respond`, {
      messageId: pending.id,
      decision: 'approved_all',
    });
    assert.equal(responded.status, 200);
    assert.equal(responded.body.status, 'approved_all');
    assert.equal(responded.body.runId, child.id);

    // 开关挂在会话上：子 run 与顶层 run 同源
    const detail = await api.get(`${API}/sessions/detail?sessionId=${session.id}`);
    assert.equal(detail.body.approvalMode, 'full_access');
    assert.equal(detail.body.approvedAll, true);

    const parent = await api.waitTerminal(sent.body.run.id);
    assert.equal(parent.status, 'succeeded');
    assert.equal((await api.get(`${API}/runs/detail?runId=${child.id}`)).body.status, 'succeeded');

    const childMessages = await api.get(`${API}/messages/list?runId=${child.id}`);
    assert.ok(
      childMessages.body.items.some((message: any) => message.content.text === '子审批结果：approved_all'),
    );
    assert.equal((await api.get(`${API}/messages/list?sessionId=${session.id}&status=pending`)).body.items.length, 0);
  } finally {
    stop();
  }
});

test('子代理连续审批：同一子 run 内先后两次，approved_all 后第二次短路', async () => {
  const session = await newSession('sub-approval-twice');
  const sent = await api.post(`${API}/messages/send`, {
    sessionId: session.id,
    prompt: `${FAKE_TRIGGER.subagent}：${FAKE_TRIGGER.approvalTwice}`,
  });

  const first = await waitPending(session.id);
  const child = (await waitChildren(sent.body.run.id))[0]!;
  assert.equal(first.runId, child.id, '第一次审批挂在子 run');

  await api.post(`${API}/messages/respond`, { messageId: first.id, decision: 'approved_all' });
  assert.equal((await api.waitTerminal(sent.body.run.id)).status, 'succeeded');

  const approvals = (await api.get(`${API}/messages/list?runId=${child.id}`)).body.items.filter(
    (message: any) => message.type === 'approval',
  );
  assert.deepEqual(
    approvals.map((message: any) => [message.runId, message.content.decisionSource]),
    [
      [child.id, 'user'],
      [child.id, 'approved_all_auto'],
    ],
    '同一子 run 内必须先后请求两次审批',
  );
  const replies = (await api.get(`${API}/messages/list?runId=${child.id}`)).body.items.filter(
    (message: any) => message.content.text === '子审批结果：approved_all',
  );
  assert.equal(replies.length, 2, '两次审批都应放行');
});

test('嵌套子代理：内层 run 挂在外层下、深度为 2、两级 task.notified', async () => {
  const session = await newSession('sub-nested');
  const { events, stop } = collect(session.id);
  try {
    const sent = await api.post(`${API}/messages/send`, {
      sessionId: session.id,
      prompt: `${FAKE_TRIGGER.subagentNested}：检查文件`,
    });
    const parent = await api.waitTerminal(sent.body.run.id);
    assert.equal(parent.status, 'succeeded');

    const outerChildren = await api.get(`${API}/runs/children?runId=${parent.id}`);
    assert.equal(outerChildren.body.total, 1, '顶层只直连外层子 run');
    const outer = outerChildren.body.items[0];
    assert.equal(outer.parentRunId, parent.id);
    assert.equal(outer.delegationDepth, 1);

    const innerChildren = await api.get(`${API}/runs/children?runId=${outer.id}`);
    assert.equal(innerChildren.body.total, 1);
    const inner = innerChildren.body.items[0];
    assert.equal(inner.parentRunId, outer.id);
    assert.equal(inner.parentToolUseId, 'toolu_fake_task_2');
    assert.equal(inner.delegationDepth, 2);
    assert.equal(inner.taskId, 'task_fake_2');
    assert.equal(inner.status, 'succeeded');

    // 内层工具消息靠 parent_tool_use_id 归位（真机工具事件不带 agent_id）
    const innerMessages = await api.get(`${API}/messages/list?runId=${inner.id}`);
    assert.deepEqual(
      innerMessages.body.items
        .filter((message: any) => message.type === 'tool_use' || message.type === 'tool_result')
        .map((message: any) => [message.type, message.content.toolCallId, message.runId]),
      [
        ['tool_use', 'toolu_fake_child_2', inner.id],
        ['tool_result', 'toolu_fake_child_2', inner.id],
      ],
    );

    const notified = events.filter((event) => event.method === 'task.notified');
    assert.deepEqual(
      notified.map((event) => [event.payload.runId, event.payload.status]),
      [
        [inner.id, 'completed'],
        [outer.id, 'completed'],
      ],
    );
  } finally {
    stop();
  }
});

test('中止子 run 向上解析顶层：父子 aborted、挂起清空、task.notified stopped、迟到事件丢弃', async () => {
  const session = await newSession('sub-abort');
  const { events, stop } = collect(session.id);
  try {
    const sent = await api.post(`${API}/messages/send`, {
      sessionId: session.id,
      prompt: `${FAKE_TRIGGER.subagentAbort}`,
    });
    const pending = await waitPending(session.id);
    const child = (await waitChildren(sent.body.run.id))[0]!;
    assert.equal(pending.runId, child.id);

    // 用子 run id 发起中止：服务端向上解析到顶层，响应返回顶层 run
    const aborted = await api.post(`${API}/runs/abort`, { runId: child.id });
    assert.equal(aborted.status, 200);
    assert.equal(aborted.body.id, sent.body.run.id);
    assert.equal(aborted.body.status, 'aborted');
    // 中止在方法内立即广播，不等适配器从挂起中醒来
    assert.ok(
      events.some((event) => event.method === 'task.notified' && event.payload.runId === child.id),
      'abort 返回前已广播 task.notified',
    );
    assert.ok(
      events.some((event) => event.method === 'run.status' && event.payload.id === sent.body.run.id),
      'abort 返回前已广播顶层 run.status',
    );

    assert.equal((await api.get(`${API}/runs/detail?runId=${sent.body.run.id}`)).body.status, 'aborted');
    assert.equal((await api.get(`${API}/runs/detail?runId=${child.id}`)).body.status, 'aborted');
    assert.equal(
      await prisma.run.count({ where: { sessionId: session.id, status: { in: ['pending', 'running'] } } }),
      0,
      '中止后不得残留活跃 run',
    );

    // 挂起全部 aborted
    assert.equal((await api.get(`${API}/messages/list?sessionId=${session.id}&status=pending`)).body.items.length, 0);
    const stored = await prisma.message.findUnique({ where: { id: pending.id } });
    assert.equal(stored?.status, 'aborted');
    assert.equal(JSON.parse(stored!.content).decisionSource, 'abort');

    // task.notified 线上状态为 stopped（库里 aborted），且先于顶层 run.status
    const notified = await waitEvent(
      events,
      'task.notified',
      (event) => event.payload.runId === child.id,
    );
    assert.deepEqual(notified.payload, {
      sessionId: session.id,
      runId: child.id,
      parentRunId: sent.body.run.id,
      taskId: 'task_fake_1',
      status: 'stopped',
      subagentType: 'general-purpose',
      error: null,
      summary: null,
    });
    const status = await waitEvent(events, 'run.status', (event) => event.payload.id === sent.body.run.id);
    assert.equal(status.payload.status, 'aborted');
    assert.ok(events.indexOf(notified) < events.indexOf(status), '子 run 通知先于顶层 run.status');

    // 顺序：挂起结算 -> 子 run 通知 -> 顶层 run.status / 顶层 chat.aborted -> session.status
    const settled = events.find(
      (event) => event.method === 'message' && event.payload.id === pending.id && event.payload.status === 'aborted',
    );
    assert.ok(settled, '挂起结算应先广播');
    assert.ok(events.indexOf(settled) < events.indexOf(notified), '挂起结算先于子 run 通知');
    assert.equal(
      events.some((event) => event.method === 'chat.aborted' && event.payload.runId === child.id),
      false,
      '子 run 终态只发 task.notified，不发 chat.aborted',
    );
    const chatAborted = await waitEvent(events, 'chat.aborted', (event) => event.payload.runId === sent.body.run.id);
    assert.ok(events.indexOf(status) < events.indexOf(chatAborted), 'run.status 先于顶层 chat.aborted');

    // 会话 completed 在顶层 run 落终态之后
    const completed = await waitEvent(events, 'session.status', (event) => event.payload.status === 'completed');
    assert.ok(events.indexOf(chatAborted) < events.indexOf(completed));
    assert.equal((await api.get(`${API}/sessions/detail?sessionId=${session.id}`)).body.status, 'completed');

    // 中止信号必须真的传到引擎；迟到内容在子 run 终态之后才发出，必须被丢弃
    await waitFor(() => FakeAdapter.lastAborted, '适配器观测到中止信号');
    assert.equal(FakeAdapter.lastAborted, true, '适配器必须观测到中止信号');
    await waitFor(() => FakeAdapter.lateContentEmitted, '适配器发出迟到内容');
    const childMessages = await api.get(`${API}/messages/list?runId=${child.id}`);
    assert.ok(
      !childMessages.body.items.some((message: any) => message.content.text === '子代理中止后的迟到消息'),
      '已终态子 run 不得接受迟到内容',
    );
    assert.equal(
      events.filter((event) => event.method === 'run.status' && event.payload.id === sent.body.run.id).length,
      1,
      '顶层 run.status 不重复',
    );
    assert.equal(
      events.filter((event) => event.method === 'task.notified' && event.payload.runId === child.id).length,
      1,
      'task.notified 不重复',
    );
  } finally {
    stop();
  }
});

test('子代理停止：子 run 落 aborted，task.notified 线上状态为 stopped', async () => {
  const session = await newSession('sub-stopped');
  const { events, stop } = collect(session.id);
  try {
    const sent = await api.post(`${API}/messages/send`, {
      sessionId: session.id,
      prompt: `${FAKE_TRIGGER.subagentStop}：停止一个任务`,
    });
    const parent = await api.waitTerminal(sent.body.run.id);
    assert.equal(parent.status, 'succeeded');

    const child = (await api.get(`${API}/runs/children?runId=${parent.id}`)).body.items[0];
    assert.equal(child.status, 'aborted');

    const notified = await waitEvent(events, 'task.notified', (event) => event.payload.runId === child.id);
    assert.deepEqual(notified.payload, {
      sessionId: session.id,
      runId: child.id,
      parentRunId: parent.id,
      taskId: 'task_fake_1',
      status: 'stopped',
      subagentType: 'general-purpose',
      error: null,
      summary: '子代理已停止',
    });
  } finally {
    stop();
  }
});

test('子代理失败：子 run 落 failed，task.notified 透传 error', async () => {
  const session = await newSession('sub-failed');
  const { events, stop } = collect(session.id);
  try {
    const sent = await api.post(`${API}/messages/send`, {
      sessionId: session.id,
      prompt: `${FAKE_TRIGGER.subagentFail}：跑一个会失败的任务`,
    });
    const parent = await api.waitTerminal(sent.body.run.id);
    assert.equal(parent.status, 'succeeded');

    const child = (await api.get(`${API}/runs/children?runId=${parent.id}`)).body.items[0];
    assert.equal(child.status, 'failed');
    assert.equal(child.error, '桩子代理异常');

    const notified = await waitEvent(events, 'task.notified', (event) => event.payload.runId === child.id);
    assert.deepEqual(notified.payload, {
      sessionId: session.id,
      runId: child.id,
      parentRunId: parent.id,
      taskId: 'task_fake_1',
      status: 'failed',
      subagentType: 'general-purpose',
      error: '桩子代理异常',
      summary: '子代理失败',
    });
  } finally {
    stop();
  }
});

test('子代理 worker 重启：同一 task_id 建新 run，恢复后的内容与终态落在新 run', async () => {
  const session = await newSession('sub-resume');
  const { events, stop } = collect(session.id);
  try {
    const sent = await api.post(`${API}/messages/send`, {
      sessionId: session.id,
      prompt: `${FAKE_TRIGGER.subagentResume}：恢复任务`,
    });
    const parent = await api.waitTerminal(sent.body.run.id);
    assert.equal(parent.status, 'succeeded');

    const children = (await api.get(`${API}/runs/children?runId=${parent.id}`)).body.items;
    assert.equal(children.length, 2, 'resume 必须为新 run_id 建一条子 run');
    assert.deepEqual(children.map((child: any) => child.taskId), ['task_fake_1', 'task_fake_1']);
    const stopped = children.find((child: any) => child.status === 'aborted');
    const resumed = children.find((child: any) => child.status === 'succeeded');
    assert.ok(stopped, 'stopped 映射为 aborted');
    assert.ok(resumed, '恢复后的任务落 succeeded');

    const started = events.filter((event) => event.method === 'task.started');
    assert.deepEqual(started.map((event) => event.payload.runId), [stopped.id, resumed.id]);
    const notified = events.filter((event) => event.method === 'task.notified');
    assert.deepEqual(
      notified.map((event) => [event.payload.runId, event.payload.status]),
      [
        [stopped.id, 'stopped'],
        [resumed.id, 'completed'],
      ],
    );

    // 恢复后的内容按 agent_id=task_id 归到新 run，不被旧 run 的终态守卫吞掉
    for (const [runId, label] of [[stopped.id, '首轮'], [resumed.id, '恢复轮']] as const) {
      const messages = await api.get(`${API}/messages/list?runId=${runId}`);
      const tools = messages.body.items.filter((message: any) => message.type === 'tool_use');
      assert.equal(tools.length, 1, `${label}子 run 应各自落一条 tool_use`);
      assert.equal(tools[0].runId, runId);
    }
  } finally {
    stop();
  }
});

test('中止已终态的子 run：409，且不触碰仍在运行的顶层 run', async () => {
  const instance = await instancesRepo.getOrCreate('sub-terminal-child', 'development');
  const session = await sessionsRepo.create({ instanceId: instance.id, modelId: TEST_MODEL_ID });
  const root = await runsRepo.createActiveRun({ sessionId: session.id, instanceId: instance.id });
  const child = await runsRepo.createSubRun({
    sessionId: session.id,
    instanceId: instance.id,
    parentRunId: root.id,
    delegationDepth: 1,
  });
  await runsRepo.finish(child.id, 'succeeded');

  try {
    const aborted = await api.post(`${API}/runs/abort`, { runId: child.id });
    assert.equal(aborted.status, 409);
    assert.equal(aborted.body.error, 'CONFLICT');
    assert.equal((await api.get(`${API}/runs/detail?runId=${root.id}`)).body.status, 'pending');
  } finally {
    await runsRepo.finish(root.id, 'failed');
  }
});

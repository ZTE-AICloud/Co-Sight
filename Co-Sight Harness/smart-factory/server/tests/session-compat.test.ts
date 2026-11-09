import { after, test } from 'node:test';
import assert from 'node:assert/strict';
import type { Envelope } from '../src/shared/live/envelope.js';
import { prepareTestEnv } from './helpers/test-db.js';
import { seedAgent, seedDevelopmentDir } from './helpers/agents.js';
import { startWorkspaceStub, TEST_MODEL_ALT_ID, TEST_MODEL_ID } from './helpers/workspace-stub.js';

const env = prepareTestEnv('session-compat');
const stub = await startWorkspaceStub(env);

const { prisma } = await import('../src/shared/prisma/client.js');
const { liveHub } = await import('../src/shared/live/live-hub.js');
const { messagesRepo } = await import('../src/shared/store/messages.repo.js');
const { sessionService } = await import('../src/modules/session/session.service.js');
const { FakeAdapter, FAKE_TRIGGER } = await import('../src/shared/engine/fake-adapter.js');

interface RecordedEvent {
  method: string;
  payload: any;
}

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

/** 订阅会话的实时事件；返回值带退订句柄。 */
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

async function waitEvent(events: RecordedEvent[], method: string, timeoutMs = 5000): Promise<RecordedEvent> {
  for (let waited = 0; waited < timeoutMs; waited += 20) {
    const found = events.find((event) => event.method === method);
    if (found) return found;
    await sleep(20);
  }
  throw new Error(`未在 ${timeoutMs}ms 内收到事件 ${method}`);
}

async function newSession(agentId: string): Promise<any> {
  await seedAgent(agentId);
  seedDevelopmentDir(env.workspaceDir, agentId);
  return sessionService.createSession({ agentId, modelId: TEST_MODEL_ID });
}

async function waitRun(runId: string, timeoutMs = 5000): Promise<any> {
  for (let waited = 0; waited < timeoutMs; waited += 50) {
    const run = await sessionService.getRun(runId);
    if (['succeeded', 'failed', 'aborted'].includes(run.status)) return run;
    await sleep(50);
  }
  throw new Error(`run ${runId} 未在 ${timeoutMs}ms 内落终态`);
}

async function waitPending(sessionId: string, type?: string, timeoutMs = 5000): Promise<any> {
  for (let waited = 0; waited < timeoutMs; waited += 50) {
    const page = await sessionService.listMessages({ sessionId, status: 'pending' });
    const found = type ? page.items.find((message) => message.type === type) : page.items[0];
    if (found) return found;
    await sleep(50);
  }
  throw new Error(`会话 ${sessionId} 未在 ${timeoutMs}ms 内出现挂起消息`);
}

after(async () => {
  await stub.close();
  await prisma.$disconnect();
});

test('history：按 seq 升序返回，content 拍平成字符串', async () => {
  const session = await newSession('compat-history');
  const sent = await sessionService.sendMessage({ sessionId: session.id, prompt: '你好' });
  assert.equal((await waitRun(sent.runId)).status, 'succeeded');

  const result = await sessionService.history({ sessionId: session.id });
  assert.equal(result.sessionId, session.id);
  assert.equal(result.total, 2, 'total 是会话全部消息数');
  assert.deepEqual(
    result.messages.map((message) => [message.role, message.type, message.content]),
    [
      ['user', 'text', '你好'],
      ['assistant', 'text', '收到：你好'],
    ],
  );
  assert.equal(result.messages[0]!.sessionId, session.id);
  assert.equal(result.messages[1]!.runId, sent.runId);
  assert.ok(result.messages[0]!.createdAt);
});

test('history：offset 从最新往前跳过，越界返回空', async () => {
  const session = await newSession('compat-history-offset');
  const sent = await sessionService.sendMessage({ sessionId: session.id, prompt: '你好' });
  await waitRun(sent.runId);

  const newest = await sessionService.history({ sessionId: session.id, limit: 1, offset: 0 });
  assert.deepEqual(newest.messages.map((message) => message.content), ['收到：你好']);
  assert.equal(newest.total, 2, 'total 不受 limit / offset 影响');

  const older = await sessionService.history({ sessionId: session.id, limit: 1, offset: 1 });
  assert.deepEqual(older.messages.map((message) => message.content), ['你好']);
  assert.equal(older.total, 2);

  const beyond = await sessionService.history({ sessionId: session.id, limit: 10, offset: 10 });
  assert.deepEqual(beyond.messages, []);
  assert.equal(beyond.total, 2, '越界分页的 total 仍是全量');
});

test('history：缺 sessionId 400、会话不存在 404，各类 content 拍平', async () => {
  await assert.rejects(() => sessionService.history({}), { name: 'BadRequestError' });
  await assert.rejects(() => sessionService.history({ sessionId: 'sess_missing' }), { name: 'NotFoundError' });

  const session = await newSession('compat-flatten');
  await messagesRepo.append({
    sessionId: session.id,
    role: 'assistant',
    type: 'tool_use',
    content: { toolCallId: 't1', toolName: 'Bash', input: { command: 'ls' } },
  });
  await messagesRepo.append({
    sessionId: session.id,
    role: 'assistant',
    type: 'tool_result',
    content: { toolCallId: 't1', output: { ok: true } },
  });
  await messagesRepo.append({ sessionId: session.id, role: 'assistant', type: 'approval', content: { title: '执行 ls' } });
  await messagesRepo.append({
    sessionId: session.id,
    role: 'assistant',
    type: 'tool_interactive',
    content: { toolCallId: 't2', questions: [{ header: 'h', question: 'q' }] },
  });
  await messagesRepo.append({ sessionId: session.id, role: 'assistant', type: 'thinking', content: { text: '想一下' } });
  await messagesRepo.append({ sessionId: session.id, role: 'system', type: 'error', content: { message: '出错' } });

  const { messages, total } = await sessionService.history({ sessionId: session.id });
  assert.equal(total, 6, 'total 覆盖会话全部消息，与拍平后的条数一致');
  assert.deepEqual(
    messages.map((message) => message.content),
    ['{"command":"ls"}', '{"ok":true}', '执行 ls', '[{"header":"h","question":"q"}]', '想一下', '{"message":"出错"}'],
  );
});

test('approval.respond：approvalId 即审批消息 id，应答后 run 收口', async () => {
  const session = await newSession('compat-approval');
  const { events, stop } = collect(session.id);
  const sent = await sessionService.sendMessage({ sessionId: session.id, prompt: FAKE_TRIGGER.approval });
  const pending = await waitPending(session.id, 'approval');

  const request = await waitEvent(events, 'approval.request');
  assert.equal(request.payload.approvalId, pending.id);
  assert.equal(request.payload.sessionId, session.id);
  assert.equal(request.payload.runId, sent.runId);
  assert.equal(request.payload.toolName, 'Bash');
  assert.equal(request.payload.title, '执行 Bash：echo hi');
  assert.equal(request.payload.input.command, 'echo hi');
  assert.equal(request.payload.toolCallId, 'toolu_fake_approval');
  assert.equal('agentId' in request.payload, false);
  assert.deepEqual(request.payload.options, [
    { value: 'approved', label: '允许', enLabel: 'Allow' },
    { value: 'approved_all', label: '本会话全部允许', enLabel: 'Allow all' },
    { value: 'rejected', label: '拒绝', enLabel: 'Reject' },
  ]);
  assert.equal('expiresAt' in request.payload, false);

  // 非交互消息沿用 respondMessage 的 404 规则
  await assert.rejects(
    () => sessionService.respondApproval({ approvalId: sent.message.id, decision: 'approved' }),
    { name: 'NotFoundError' },
  );

  const settled = await sessionService.respondApproval({ approvalId: pending.id, decision: 'approved' });
  assert.equal(settled.status, 'approved');
  assert.equal((await waitRun(sent.runId)).status, 'succeeded');
  stop();
});

test('approval.request：allowAll 为 false 时不提供 approved_all', async () => {
  const session = await newSession('compat-approval-no-all');
  const { events, stop } = collect(session.id);
  const originalRun = FakeAdapter.prototype.run;
  FakeAdapter.prototype.run = async (ctx) => {
    const decision = await ctx.requestInput({
      kind: 'approval',
      toolCallId: 'toolu_fake_approval',
      toolName: 'Bash',
      title: '执行 Bash',
      input: { command: 'ls' },
      agentId: 'task_fake_approval',
      allowAll: false,
    });
    return { output: `审批结果：${decision.decision ?? 'unknown'}` };
  };
  try {
    const sent = await sessionService.sendMessage({ sessionId: session.id, prompt: 'x' });
    const pending = await waitPending(session.id, 'approval');
    const request = await waitEvent(events, 'approval.request');
    assert.deepEqual(
      request.payload.options.map((option: any) => option.value),
      ['approved', 'rejected'],
    );
    assert.equal(request.payload.toolCallId, 'toolu_fake_approval');
    assert.equal(request.payload.agentId, 'task_fake_approval');
    assert.equal(pending.content.agentId, 'task_fake_approval', 'agentId 必须随审批消息落库');

    await sessionService.respondApproval({ approvalId: pending.id, decision: 'approved' });
    assert.equal((await waitRun(sent.runId)).status, 'succeeded');
  } finally {
    FakeAdapter.prototype.run = originalRun;
    stop();
  }
});

test('tool.respond：按 toolCallId 找到待应答交互，数组 answers 归一为 Record', async () => {
  const session = await newSession('compat-tool-respond');
  const { events, stop } = collect(session.id);
  const originalRun = FakeAdapter.prototype.run;
  FakeAdapter.prototype.run = async (ctx) => {
    const decision = await ctx.requestInput({
      kind: 'tool_interactive',
      toolCallId: 'toolu_ask_1',
      toolName: 'AskUserQuestion',
      title: '需要澄清',
      questions: [{ header: '格式', question: '要处理什么格式？', options: [{ label: 'JSON' }, { label: 'CSV' }] }],
    });
    const output = `回答：${JSON.stringify(decision.answers ?? {})}`;
    await ctx.emit({ type: 'message', draft: { role: 'assistant', type: 'text', content: { text: output } } });
    return { output };
  };
  try {
    const sent = await sessionService.sendMessage({ sessionId: session.id, prompt: 'x' });
    const pending = await waitPending(session.id, 'tool_interactive');

    const interactive = await waitEvent(events, 'tool.interactive');
    assert.deepEqual(interactive.payload, {
      sessionId: session.id,
      runId: sent.runId,
      parentRunId: null,
      toolCallId: 'toolu_ask_1',
      toolName: 'AskUserQuestion',
      input: { questions: pending.content.questions },
    });
    assert.equal('timeout' in interactive.payload, false);

    const settled = await sessionService.respondTool({
      toolCallId: 'toolu_ask_1',
      answers: [{ question: '要处理什么格式？', answer: 'CSV' }],
    });
    assert.equal(settled.status, 'answered');
    assert.deepEqual(settled.content.answers, { '要处理什么格式？': ['CSV'] });

    assert.equal((await waitRun(sent.runId)).status, 'succeeded');
    const { messages } = await sessionService.history({ sessionId: session.id });
    assert.ok(messages.some((message) => message.content === '回答：{"要处理什么格式？":["CSV"]}'));
  } finally {
    FakeAdapter.prototype.run = originalRun;
    stop();
  }
});

test('tool.respond：对象 answers 归一，非法格式 400 且消息仍待应答', async () => {
  const session = await newSession('compat-tool-answers');
  const pending = await messagesRepo.append({
    sessionId: session.id,
    role: 'assistant',
    type: 'tool_interactive',
    status: 'pending',
    content: { toolCallId: 'toolu_obj', toolName: 'AskUserQuestion', questions: [] },
  });

  await assert.rejects(
    () => sessionService.respondTool({ toolCallId: 'toolu_obj', answers: 42 }),
    { name: 'BadRequestError', message: 'answers 格式非法' },
  );
  await assert.rejects(
    () => sessionService.respondTool({ toolCallId: 'toolu_missing', answers: {} }),
    { name: 'NotFoundError' },
  );
  assert.equal((await messagesRepo.findById(pending.id))?.status, 'pending');

  const settled = await sessionService.respondTool({
    toolCallId: 'toolu_obj',
    answers: { q: 'A', multi: ['B', 'C'], skipped: 'D' },
  });
  assert.equal(settled.status, 'answered');
  assert.deepEqual(settled.content.answers, { q: ['A'], multi: ['B', 'C'], skipped: ['D'] });
});

test('tool.executing / tool.executed：结果消息回填工具名与入参', async () => {
  const session = await newSession('compat-tool-events');
  const { events, stop } = collect(session.id);
  const sent = await sessionService.sendMessage({ sessionId: session.id, prompt: FAKE_TRIGGER.tool });
  assert.equal((await waitRun(sent.runId)).status, 'succeeded');

  const executing = await waitEvent(events, 'tool.executing');
  const executed = await waitEvent(events, 'tool.executed');
  assert.deepEqual(executing.payload, {
    sessionId: session.id,
    runId: sent.runId,
    parentRunId: null,
    toolCallId: 'toolu_fake_1',
    toolName: 'Bash',
    input: { command: 'echo hi' },
  });
  assert.deepEqual(executed.payload, {
    sessionId: session.id,
    runId: sent.runId,
    parentRunId: null,
    toolCallId: 'toolu_fake_1',
    toolName: 'Bash',
    input: { command: 'echo hi' },
    output: 'hi',
    isError: false,
  });
  assert.ok(events.indexOf(executing) < events.indexOf(executed));
  stop();
});

test('chat.final：成功 run 恰好一次，内容为适配器终稿', async () => {
  const session = await newSession('compat-final');
  const { events, stop } = collect(session.id);
  const sent = await sessionService.sendMessage({ sessionId: session.id, prompt: '你好' });
  assert.equal((await waitRun(sent.runId)).status, 'succeeded');

  await waitEvent(events, 'chat.final');
  const finals = events.filter((event) => event.method === 'chat.final');
  assert.equal(finals.length, 1);
  const assistant = (await sessionService.listMessages({ sessionId: session.id })).items.find(
    (message) => message.role === 'assistant' && message.type === 'text',
  )!;
  assert.deepEqual(finals[0]!.payload, {
    sessionId: session.id,
    runId: sent.runId,
    parentRunId: null,
    content: '收到：你好',
    messageId: assistant.id,
  });
  stop();
});

test('chat.final：适配器终稿为空时退回累积正文', async () => {
  const session = await newSession('compat-final-fallback');
  const { events, stop } = collect(session.id);
  const originalRun = FakeAdapter.prototype.run;
  FakeAdapter.prototype.run = async (ctx) => {
    await ctx.emit({ type: 'delta', messageType: 'text', delta: '半截' });
    await ctx.emit({ type: 'message', draft: { role: 'assistant', type: 'text', content: { text: '半截正文' } } });
    return { output: '' };
  };
  try {
    const sent = await sessionService.sendMessage({ sessionId: session.id, prompt: 'x' });
    assert.equal((await waitRun(sent.runId)).status, 'succeeded');
    const final = await waitEvent(events, 'chat.final');
    const assistant = (await sessionService.listMessages({ sessionId: session.id })).items.find(
      (message) => message.type === 'text' && message.content.text === '半截正文',
    )!;
    assert.deepEqual(final.payload, {
      sessionId: session.id,
      runId: sent.runId,
      parentRunId: null,
      content: '半截',
      messageId: assistant.id,
    });
  } finally {
    FakeAdapter.prototype.run = originalRun;
    stop();
  }
});

test('chat.error：失败 run 带原因', async () => {
  const session = await newSession('compat-error');
  const { events, stop } = collect(session.id);
  const originalRun = FakeAdapter.prototype.run;
  FakeAdapter.prototype.run = async () => {
    throw new Error('桩失败');
  };
  try {
    const sent = await sessionService.sendMessage({ sessionId: session.id, prompt: 'x' });
    assert.equal((await waitRun(sent.runId)).status, 'failed');
    const error = await waitEvent(events, 'chat.error');
    assert.deepEqual(error.payload, {
      sessionId: session.id,
      runId: sent.runId,
      parentRunId: null,
      code: 'RUN_ERROR',
      message: '桩失败',
    });
  } finally {
    FakeAdapter.prototype.run = originalRun;
    stop();
  }
});

test('chat.aborted：中止 run 发可读原因', async () => {
  const session = await newSession('compat-aborted');
  const { events, stop } = collect(session.id);
  // 适配器挂到中止信号上：run 不会先跑完，中止断言不靠时序运气
  const originalRun = FakeAdapter.prototype.run;
  FakeAdapter.prototype.run = async (ctx) => {
    if (!ctx.signal.aborted) {
      await new Promise<void>((resolve) => ctx.signal.addEventListener('abort', () => resolve(), { once: true }));
    }
    return { output: '' };
  };
  try {
    const sent = await sessionService.sendMessage({ sessionId: session.id, prompt: 'x' });
    const aborted = await sessionService.abortRun(sent.runId);
    assert.equal(aborted.status, 'aborted');
    assert.equal((await waitRun(sent.runId)).status, 'aborted');

    const event = await waitEvent(events, 'chat.aborted');
    assert.deepEqual(event.payload, {
      sessionId: session.id,
      runId: sent.runId,
      parentRunId: null,
      reason: '用户中止',
    });
  } finally {
    FakeAdapter.prototype.run = originalRun;
    stop();
  }
});

test('思考事件走 chat.thinking 三阶段，正文增量仍走 chat.delta', async () => {
  const session = await newSession('compat-thinking');
  const { events, stop } = collect(session.id);
  const originalRun = FakeAdapter.prototype.run;
  FakeAdapter.prototype.run = async (ctx) => {
    await ctx.emit({ type: 'thinking', phase: 'start' });
    await ctx.emit({ type: 'thinking', phase: 'delta', text: '想一' });
    await ctx.emit({ type: 'thinking', phase: 'delta', text: '想二' });
    await ctx.emit({ type: 'thinking', phase: 'stop' });
    await ctx.emit({ type: 'delta', messageType: 'text', delta: '正文' });
    await ctx.emit({ type: 'message', draft: { role: 'assistant', type: 'text', content: { text: '正文' } } });
    return { output: '正文' };
  };
  try {
    const sent = await sessionService.sendMessage({ sessionId: session.id, prompt: 'x' });
    assert.equal((await waitRun(sent.runId)).status, 'succeeded');

    assert.equal(events.filter((event) => event.method === 'chat.thinking.delta').length, 0, '旧事件必须移除');
    const thinking = events.filter((event) => event.method === 'chat.thinking');
    assert.deepEqual(
      thinking.map((event) => event.payload.phase),
      ['start', 'delta', 'delta', 'stop'],
    );
    for (const event of thinking) {
      assert.equal(event.payload.sessionId, session.id);
      assert.equal(event.payload.runId, sent.runId);
      assert.equal(event.payload.parentRunId, null);
      assert.ok(event.payload.at);
    }
    assert.equal('text' in thinking[0]!.payload, false, 'start 不带正文');
    assert.equal('text' in thinking[3]!.payload, false, 'stop 不带正文');
    assert.deepEqual(
      thinking.slice(1, 3).map((event) => event.payload.text),
      ['想一', '想二'],
    );

    const textDeltas = events.filter((event) => event.method === 'chat.delta');
    assert.ok(textDeltas.length > 0);
    assert.ok(textDeltas.every((event) => event.payload.messageType === 'text'));
    assert.equal(textDeltas.map((event) => event.payload.delta).join(''), '正文');
  } finally {
    FakeAdapter.prototype.run = originalRun;
    stop();
  }
});

test('sessions/create：modelId 必填非空且必须可运行', async () => {
  await seedAgent('compat-model-required');

  await assert.rejects(
    () => sessionService.createSession({ agentId: 'compat-model-required' }),
    { name: 'BadRequestError', message: 'modelId 必填' },
  );
  await assert.rejects(
    () => sessionService.createSession({ agentId: 'compat-model-required', modelId: '' }),
    { name: 'BadRequestError', message: 'modelId 必填' },
  );
  await assert.rejects(
    () => sessionService.createSession({ agentId: 'compat-model-required', modelId: 'mdl_missing_for_compat' }),
    { name: 'BadRequestError' },
  );
});

test('model.switch / sessions update：空 modelId 一律 400，不支持清空', async () => {
  const session = await newSession('compat-model-switch');

  for (const modelId of [undefined, '']) {
    await assert.rejects(
      () => sessionService.switchModel({ sessionId: session.id, modelId }),
      { name: 'BadRequestError', message: 'modelId 必填' },
    );
    await assert.rejects(
      () => sessionService.updateSession(session.id, { modelId }),
      { name: 'BadRequestError', message: 'modelId 必填' },
    );
  }
  await assert.rejects(
    () => sessionService.updateSession(session.id, { modelId: 'mdl_missing_for_compat' }),
    { name: 'BadRequestError' },
  );
  assert.equal((await sessionService.getSession(session.id)).modelId, TEST_MODEL_ID, '失败不得改动模型');
});

test('send 定位：至多给一个（都不给 = 自由对话）；sessionId 分支拒绝新建参数；新建会话缺 modelId 400', async () => {
  await seedAgent('compat-send-rules');
  const session = await newSession('compat-send-rules');

  // 两个都不给走自由对话分支（chat-session.test.ts 覆盖正常路径），这里先被缺 modelId 挡下
  await assert.rejects(
    () => sessionService.sendMessage({ prompt: 'hi' }),
    { name: 'BadRequestError', message: 'modelId 必填' },
  );
  await assert.rejects(
    () => sessionService.sendMessage({ sessionId: session.id, agentId: 'compat-send-rules', prompt: 'hi' }),
    { name: 'BadRequestError', message: 'sessionId 与 agentId 不能同时给' },
  );
  for (const extra of [
    { modelId: TEST_MODEL_ID },
    { modelId: null },
    { mode: 'read_only' },
    { mode: null },
    { effort: 'max' },
    { effort: null },
  ]) {
    await assert.rejects(
      () => sessionService.sendMessage({ sessionId: session.id, prompt: 'hi', ...extra }),
      { name: 'BadRequestError', message: `send { sessionId } 不接受 ${Object.keys(extra)[0]}` },
    );
  }
  await assert.rejects(
    () => sessionService.sendMessage({ agentId: 'compat-send-rules', prompt: 'hi' }),
    { name: 'BadRequestError', message: 'modelId 必填' },
  );

  // 全部被拒：会话不多、run 不多
  assert.equal(
    (await sessionService.listSessions({ agentId: 'compat-send-rules', stage: 'development' })).total,
    1,
  );
  assert.equal((await sessionService.listRuns(session.id, 1, 20)).total, 0);
});

test('settings.changed：WS 切换与 REST 更新各带渠道，只有模型切换带 appliesTo', async () => {
  const session = await newSession('compat-settings');
  const { events, stop } = collect(session.id);
  try {
    const modeSwitched = await sessionService.switchMode({ sessionId: session.id, mode: 'read_only' });
    const afterMode = events.filter((event) => event.method === 'settings.changed');
    assert.equal(afterMode.length, 1);
    assert.deepEqual(afterMode[0]!.payload, {
      sessionId: session.id,
      settings: { mode: 'read_only', effort: session.effort, modelId: session.modelId },
      changedBy: { channel: 'ws', actorId: '' },
      at: modeSwitched.updatedAt,
    });
    assert.equal('appliesTo' in afterMode[0]!.payload, false);

    const modelSwitched = await sessionService.switchModel({ sessionId: session.id, modelId: TEST_MODEL_ALT_ID });
    const afterModel = events.filter((event) => event.method === 'settings.changed');
    assert.equal(afterModel.length, 2);
    assert.deepEqual(afterModel[1]!.payload, {
      sessionId: session.id,
      settings: { mode: 'read_only', effort: session.effort, modelId: TEST_MODEL_ALT_ID },
      changedBy: { channel: 'ws', actorId: '' },
      appliesTo: 'nextRun',
      at: modelSwitched.updatedAt,
    });

    const restUpdated = await sessionService.updateSession(session.id, { modelId: TEST_MODEL_ID });
    const afterRest = events.filter((event) => event.method === 'settings.changed');
    assert.equal(afterRest.length, 3);
    assert.deepEqual(afterRest[2]!.payload, {
      sessionId: session.id,
      settings: { mode: 'read_only', effort: session.effort, modelId: TEST_MODEL_ID },
      changedBy: { channel: 'http', actorId: '' },
      appliesTo: 'nextRun',
      at: restUpdated.updatedAt,
    });
  } finally {
    stop();
  }
});

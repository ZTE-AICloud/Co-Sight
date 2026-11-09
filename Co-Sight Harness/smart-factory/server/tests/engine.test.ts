import { test } from 'node:test';
import assert from 'node:assert/strict';
import type { ClaudeMessage } from '../src/shared/engine/claude-protocol.js';
import type { EngineContext } from '../src/shared/engine/port.js';
import { prepareTestEnv } from './helpers/test-db.js';

// 引擎层不碰数据库；这里只借 helper 隔离 COSIGHT_HOME。
prepareTestEnv('engine');

const { resolveEngineAdapter } = await import('../src/shared/engine/registry.js');
const { FakeAdapter, FAKE_TRIGGER } = await import('../src/shared/engine/fake-adapter.js');
const {
  ClaudeAdapter,
  apiRetryOf,
  backgroundTasksOf,
  draftsOf,
  modelOptionsOf,
  openThinkingStops,
  permissionModeOf,
  permissionOf,
  resultErrorOf,
  sdkAnswers,
  subagentMetaOf,
  taskEventOf,
  thinkingPhaseOf,
  toInputRequest,
} = await import('../src/shared/engine/claude-adapter.js');
const { BadRequestError, ConflictError } = await import('../src/shared/errors.js');

test('未知引擎在解析时就报错（fail-fast），且列出可用值', () => {
  assert.throws(
    () => resolveEngineAdapter('codex-sdk'),
    (error: unknown) => error instanceof BadRequestError && /未知引擎/.test(error.message) && /claude-cli/.test(error.message),
  );
});

test('注册表解析两个已实现适配器', () => {
  assert.equal(resolveEngineAdapter('fake')().engine, 'fake');
  assert.equal(resolveEngineAdapter('claude-cli')().engine, 'claude-cli');
  assert.ok(resolveEngineAdapter('fake')() instanceof FakeAdapter);
  assert.ok(resolveEngineAdapter('claude-cli')() instanceof ClaudeAdapter);
});

test('冲突错误带 409 语义', () => {
  const error = new ConflictError('已有活跃 run');
  assert.equal(error.status, 409);
  assert.equal(error.code, 'CONFLICT');
});

test('modelOptionsOf：返回值恒带 model 与 flag-settings env，不存在仅 settings 的跟随本机形态', () => {
  const options = modelOptionsOf({ modelName: 'test-sonnet', baseUrl: null, apiKey: 'sk-test' });

  assert.equal(options.model, 'test-sonnet');
  assert.equal(typeof options.env, 'object');
  assert.deepEqual(Object.keys(options.settings).sort(), ['disableAllHooks', 'env']);
  assert.equal('settingSources' in options, false);
});

test('modelOptionsOf：有模型时模型标识走 options.model，端点与凭据走 flag settings', () => {
  const inherited = {
    ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY,
    ANTHROPIC_AUTH_TOKEN: process.env.ANTHROPIC_AUTH_TOKEN,
    ANTHROPIC_BASE_URL: process.env.ANTHROPIC_BASE_URL,
    ANTHROPIC_MODEL: process.env.ANTHROPIC_MODEL,
    CLAUDE_CODE_SUBAGENT_MODEL: process.env.CLAUDE_CODE_SUBAGENT_MODEL,
    ANTHROPIC_DEFAULT_OPUS_MODEL: process.env.ANTHROPIC_DEFAULT_OPUS_MODEL,
    ANTHROPIC_DEFAULT_SONNET_MODEL: process.env.ANTHROPIC_DEFAULT_SONNET_MODEL,
    ANTHROPIC_DEFAULT_HAIKU_MODEL: process.env.ANTHROPIC_DEFAULT_HAIKU_MODEL,
    ANTHROPIC_DEFAULT_FABLE_MODEL: process.env.ANTHROPIC_DEFAULT_FABLE_MODEL,
  };
  // 本机继承值必须在有模型时被删除，否则会经 options.env 混进子进程
  process.env.ANTHROPIC_API_KEY = 'sk-local-key';
  process.env.ANTHROPIC_AUTH_TOKEN = 'local-auth-token';
  process.env.ANTHROPIC_BASE_URL = 'https://local-gateway.test/anthropic';
  process.env.ANTHROPIC_MODEL = 'local-model';
  process.env.CLAUDE_CODE_SUBAGENT_MODEL = 'local-subagent-model';
  process.env.ANTHROPIC_DEFAULT_OPUS_MODEL = 'local-opus';
  process.env.ANTHROPIC_DEFAULT_SONNET_MODEL = 'local-sonnet';
  process.env.ANTHROPIC_DEFAULT_HAIKU_MODEL = 'local-haiku';
  process.env.ANTHROPIC_DEFAULT_FABLE_MODEL = 'local-fable';
  try {
    const model = { modelName: 'test-sonnet', baseUrl: 'https://gateway.test/anthropic', apiKey: 'sk-test-model-key' };
    const options = modelOptionsOf(model);

    // modelName 是发给供应商的模型名，不是配置 id
    assert.equal(options.model, 'test-sonnet');
    // 不限制 settings 源：用户级插件 / 命令照常加载
    assert.equal('settingSources' in options, false);
    assert.deepEqual(options.settings, {
      disableAllHooks: false,
      env: {
        ANTHROPIC_AUTH_TOKEN: 'sk-test-model-key',
        ANTHROPIC_BASE_URL: 'https://gateway.test/anthropic',
        CLAUDE_CODE_SUBAGENT_MODEL: 'test-sonnet',
        // 子代理定义里的 `model: sonnet` 等别名也锁到本场模型
        ANTHROPIC_DEFAULT_OPUS_MODEL: 'test-sonnet',
        ANTHROPIC_DEFAULT_SONNET_MODEL: 'test-sonnet',
        ANTHROPIC_DEFAULT_HAIKU_MODEL: 'test-sonnet',
        ANTHROPIC_DEFAULT_FABLE_MODEL: 'test-sonnet',
      },
    });
    // 模型配置在 flag-settings 层下发，不再经 options.env
    assert.equal('ANTHROPIC_API_KEY' in (options.env ?? {}), false);
    assert.equal('ANTHROPIC_AUTH_TOKEN' in (options.env ?? {}), false);
    assert.equal('ANTHROPIC_BASE_URL' in (options.env ?? {}), false);
    assert.equal('ANTHROPIC_MODEL' in (options.env ?? {}), false);
    assert.equal('CLAUDE_CODE_SUBAGENT_MODEL' in (options.env ?? {}), false);
    assert.equal('ANTHROPIC_DEFAULT_SONNET_MODEL' in (options.env ?? {}), false);
  } finally {
    for (const [key, value] of Object.entries(inherited)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
});

test('modelOptionsOf：baseUrl 为 null 时 flag settings 用空端点压过本机', () => {
  const originalBaseUrl = process.env.ANTHROPIC_BASE_URL;
  const originalAuthToken = process.env.ANTHROPIC_AUTH_TOKEN;
  try {
    process.env.ANTHROPIC_BASE_URL = 'https://local-gateway.test/anthropic';
    process.env.ANTHROPIC_AUTH_TOKEN = 'local-auth-token';

    const options = modelOptionsOf({ modelName: 'test-opus', baseUrl: null, apiKey: 'sk-test-alt-key' });

    assert.equal(options.model, 'test-opus');
    assert.equal('settingSources' in options, false);
    // null = 官方地址：空串清掉本机端点，认证走 Bearer，子代理锁同一模型
    assert.equal(options.settings.env?.ANTHROPIC_AUTH_TOKEN, 'sk-test-alt-key');
    assert.equal(options.settings.env?.ANTHROPIC_BASE_URL, '');
    assert.equal(options.settings.env?.CLAUDE_CODE_SUBAGENT_MODEL, 'test-opus');
    assert.equal(options.settings.env?.ANTHROPIC_DEFAULT_SONNET_MODEL, 'test-opus');
    // 本机继承值不进 options.env
    assert.equal('ANTHROPIC_BASE_URL' in (options.env ?? {}), false);
    assert.equal('ANTHROPIC_AUTH_TOKEN' in (options.env ?? {}), false);
  } finally {
    if (originalBaseUrl === undefined) delete process.env.ANTHROPIC_BASE_URL;
    else process.env.ANTHROPIC_BASE_URL = originalBaseUrl;
    if (originalAuthToken === undefined) delete process.env.ANTHROPIC_AUTH_TOKEN;
    else process.env.ANTHROPIC_AUTH_TOKEN = originalAuthToken;
  }
});

test('permissionModeOf：会话审批模式映射到 SDK 权限模式', () => {
  assert.equal(permissionModeOf('read_only'), 'plan');
  assert.equal(permissionModeOf('workspace_write'), 'acceptEdits');
  assert.equal(permissionModeOf('full_access'), 'bypassPermissions');
});

/** 造一条 SDK 消息：只填 draftsOf 读得到的字段，其余由断言方各自补齐 */
const sdkMessage = (type: 'assistant' | 'user', content: unknown): ClaudeMessage =>
  ({ type, message: { role: type, content } }) as unknown as ClaudeMessage;

test('draftsOf：assistant 的 text / thinking / tool_use 各落一条草稿', () => {
  assert.deepEqual(draftsOf(sdkMessage('assistant', [{ type: 'text', text: '你好' }])), [
    { role: 'assistant', type: 'text', content: { text: '你好' } },
  ]);
  assert.deepEqual(draftsOf(sdkMessage('assistant', [{ type: 'thinking', thinking: '先想一下' }])), [
    { role: 'assistant', type: 'thinking', content: { text: '先想一下' } },
  ]);
  assert.deepEqual(draftsOf(sdkMessage('assistant', [{ type: 'tool_use', id: 'tu_1', name: 'Bash', input: { command: 'ls' } }])), [
    { role: 'assistant', type: 'tool_use', content: { toolCallId: 'tu_1', toolName: 'Bash', input: { command: 'ls' } } },
  ]);
});

test('draftsOf：user 的 tool_result 落一条草稿，isError 归一成布尔', () => {
  assert.deepEqual(draftsOf(sdkMessage('user', [{ type: 'tool_result', tool_use_id: 'tu_1', content: 'hi' }])), [
    { role: 'assistant', type: 'tool_result', content: { toolCallId: 'tu_1', output: 'hi', isError: false } },
  ]);
  assert.deepEqual(draftsOf(sdkMessage('user', [{ type: 'tool_result', tool_use_id: 'tu_1', content: 'boom', is_error: true }])), [
    { role: 'assistant', type: 'tool_result', content: { toolCallId: 'tu_1', output: 'boom', isError: true } },
  ]);
});

test('draftsOf：空 / 只有空白的文本块不落库（否则界面上是一条没有内容的空行）', () => {
  assert.deepEqual(draftsOf(sdkMessage('assistant', [{ type: 'text', text: '' }])), []);
  assert.deepEqual(draftsOf(sdkMessage('assistant', [{ type: 'text', text: ' \n\t' }])), []);
  // 同一条消息里的其它块不受影响
  const drafts = draftsOf(
    sdkMessage('assistant', [
      { type: 'text', text: '\n' },
      { type: 'tool_use', id: 'tu_1', name: 'Read', input: { file_path: 'a.txt' } },
    ]),
  );
  assert.deepEqual(drafts, [
    { role: 'assistant', type: 'tool_use', content: { toolCallId: 'tu_1', toolName: 'Read', input: { file_path: 'a.txt' } } },
  ]);
});

test('draftsOf：一条消息多个块就产出多条草稿', () => {
  const drafts = draftsOf(
    sdkMessage('assistant', [
      { type: 'thinking', thinking: '想' },
      { type: 'text', text: '说' },
      { type: 'tool_use', id: 'tu_1', name: 'Read', input: { file_path: 'a.txt' } },
    ]),
  );
  assert.deepEqual(
    drafts.map((draft) => draft.type),
    ['thinking', 'text', 'tool_use'],
  );
});

test('draftsOf：AskUserQuestion 的调用与其结果都不落库', () => {
  const questionToolCallIds = new Set<string>();
  const ask = sdkMessage('assistant', [{ type: 'tool_use', id: 'tu_q', name: 'AskUserQuestion', input: { questions: [] } }]);

  assert.deepEqual(draftsOf(ask, questionToolCallIds), []);
  assert.deepEqual([...questionToolCallIds], ['tu_q']);
  assert.deepEqual(draftsOf(sdkMessage('user', [{ type: 'tool_result', tool_use_id: 'tu_q', content: 'JSON' }]), questionToolCallIds), []);
});

test('draftsOf：delta / result / 纯文本 user 消息都不产出草稿', () => {
  assert.deepEqual(draftsOf(sdkMessage('user', '纯文本')), []);
  assert.deepEqual(draftsOf(sdkMessage('user', [{ type: 'text', text: '用户自己说的话' }])), []);
  assert.deepEqual(draftsOf({ type: 'result', subtype: 'success', result: 'ok' } as unknown as ClaudeMessage), []);
  assert.deepEqual(draftsOf({ type: 'system', subtype: 'init' } as unknown as ClaudeMessage), []);
});

/** 造一条 result 消息：只填被测字段 */
const resultMessage = (fields: Record<string, unknown>): ClaudeMessage => ({ type: 'result', ...fields }) as unknown as ClaudeMessage;

test('resultErrorOf：success 且 is_error=true 时把 result 里的错误文本交出来', () => {
  const message = resultMessage({ subtype: 'success', is_error: true, result: 'API 错误：429 触发限流' });
  assert.equal(resultErrorOf(message), 'API 错误：429 触发限流');
});

test('resultErrorOf：正常 success 返回 null', () => {
  assert.equal(resultErrorOf(resultMessage({ subtype: 'success', is_error: false, result: '终稿' })), null);
});

test('resultErrorOf：非 success 子类型返回含子类型的错误文本', () => {
  assert.equal(resultErrorOf(resultMessage({ subtype: 'error_max_turns', is_error: true })), '模型调用未成功：error_max_turns');
});

test('subagentMetaOf：assistant 帧带父工具调用与 agent_id', () => {
  const message = {
    type: 'assistant',
    message: { role: 'assistant', content: [{ type: 'tool_use', id: 'tu_1', name: 'Read', input: {} }] },
    parent_tool_use_id: 'tu_parent',
    agent_id: 'task_1',
    subagent_type: 'general-purpose',
  } as unknown as ClaudeMessage;

  assert.deepEqual(subagentMetaOf(message), {
    parentToolUseId: 'tu_parent',
    agentId: 'task_1',
  });
});

test('subagentMetaOf：顶层帧与不带子代理字段的帧都归一成 null', () => {
  assert.deepEqual(subagentMetaOf(sdkMessage('assistant', [])), {
    parentToolUseId: null,
    agentId: null,
  });
  // stream_event 只有 parent_tool_use_id，没有 agent_id
  assert.deepEqual(
    subagentMetaOf({ type: 'stream_event', parent_tool_use_id: 'tu_parent', event: {} } as unknown as ClaudeMessage),
    { parentToolUseId: 'tu_parent', agentId: null },
  );
});

/** 造一条 system 任务消息：只填被测字段 */
const taskMessage = (subtype: string, fields: Record<string, unknown>): ClaudeMessage =>
  ({ type: 'system', subtype, ...fields }) as unknown as ClaudeMessage;

test('taskEventOf：local_agent 的 task_started 映射为 task_started 事件', () => {
  const message = taskMessage('task_started', {
    task_id: 'task_1',
    tool_use_id: 'tu_1',
    description: '调研方案',
    subagent_type: 'general-purpose',
    is_backgrounded: true,
    spawn_depth: 2,
    parent_task_id: 'task_0',
    task_type: 'local_agent',
  });

  assert.deepEqual(taskEventOf(message), {
    type: 'task_started',
    taskId: 'task_1',
    toolUseId: 'tu_1',
    parentTaskId: 'task_0',
    subagentType: 'general-purpose',
    delegationDepth: 2,
    description: '调研方案',
  });
});

test('taskEventOf：缺 spawn_depth 时记 0 交由宿主补齐；无 task_type 但有 subagent_type 也算子代理', () => {
  assert.deepEqual(taskEventOf(taskMessage('task_started', { task_id: 't', description: 'x', subagent_type: 'Explore' })), {
    type: 'task_started',
    taskId: 't',
    toolUseId: null,
    parentTaskId: null,
    subagentType: 'Explore',
    delegationDepth: 0,
    description: 'x',
  });
});

test('taskEventOf：透传 SDK run_id（resume 后 task_id 不变、run_id 变），缺省不落键', () => {
  assert.deepEqual(
    taskEventOf(taskMessage('task_started', { task_id: 't', run_id: 'r2', description: 'x', subagent_type: 'Explore' })),
    {
      type: 'task_started',
      taskId: 't',
      runId: 'r2',
      toolUseId: null,
      parentTaskId: null,
      subagentType: 'Explore',
      delegationDepth: 0,
      description: 'x',
    },
  );
  assert.deepEqual(
    taskEventOf(taskMessage('task_notification', { task_id: 't', run_id: 'r2', status: 'stopped', summary: '重启' })),
    {
      type: 'task_notified',
      taskId: 't',
      runId: 'r2',
      status: 'stopped',
      summary: '重启',
      error: null,
    },
  );
  const withoutRunId = taskEventOf(taskMessage('task_started', { task_id: 't', subagent_type: 'Explore', description: 'x' }));
  assert.equal(withoutRunId !== null && 'runId' in withoutRunId, false);
});

test('taskEventOf：bash 等非子代理任务与普通消息都忽略', () => {
  assert.equal(taskEventOf(taskMessage('task_started', { task_id: 't', description: 'ls', task_type: 'local_bash' })), null);
  assert.equal(taskEventOf(taskMessage('init', {})), null);
  assert.equal(taskEventOf(sdkMessage('assistant', [])), null);
});

test('taskEventOf：task_notification 按状态映射，error 只在 failed 时带', () => {
  assert.deepEqual(taskEventOf(taskMessage('task_notification', { task_id: 't', tool_use_id: 'tu', status: 'completed', summary: '完成' })), {
    type: 'task_notified',
    taskId: 't',
    status: 'completed',
    summary: '完成',
    error: null,
  });
  assert.deepEqual(taskEventOf(taskMessage('task_notification', { task_id: 't', status: 'failed', summary: 'boom' })), {
    type: 'task_notified',
    taskId: 't',
    status: 'failed',
    summary: 'boom',
    error: 'boom',
  });
  // failed 缺 summary 用固定文案，stopped 不算错误
  assert.deepEqual(taskEventOf(taskMessage('task_notification', { task_id: 't', status: 'failed' })), {
    type: 'task_notified',
    taskId: 't',
    status: 'failed',
    summary: null,
    error: '子任务失败',
  });
  assert.deepEqual(taskEventOf(taskMessage('task_notification', { task_id: 't', status: 'stopped', summary: '已停止' })), {
    type: 'task_notified',
    taskId: 't',
    status: 'stopped',
    summary: '已停止',
    error: null,
  });
});

test('backgroundTasksOf：background_tasks_changed 按 REPLACE 语义给出全量存活任务', () => {
  const message = taskMessage('background_tasks_changed', {
    tasks: [
      { task_id: 'task_1', task_type: 'local_bash', description: '跑用例' },
      { task_id: 'task_2', task_type: 'local_agent', description: '调研' },
    ],
  });

  assert.deepEqual(backgroundTasksOf(message), ['task_1', 'task_2']);
});

test('backgroundTasksOf：载荷清空即没有后台任务；缺 tasks 字段按空集处理', () => {
  assert.deepEqual(backgroundTasksOf(taskMessage('background_tasks_changed', { tasks: [] })), []);
  assert.deepEqual(backgroundTasksOf(taskMessage('background_tasks_changed', {})), []);
});

test('backgroundTasksOf：ambient 内务任务不计入（否则 run 会被看门狗一直挂住）', () => {
  const message = taskMessage('background_tasks_changed', {
    tasks: [
      { task_id: 'watch', task_type: 'local_bash', description: 'watch', ambient: true },
      { task_id: 'real', task_type: 'local_bash', description: '跑用例', ambient: false },
    ],
  });

  assert.deepEqual(backgroundTasksOf(message), ['real']);
});

test('backgroundTasksOf：其余消息返回 null（集合不动），task_notification 不算集合来源', () => {
  assert.equal(backgroundTasksOf(taskMessage('task_notification', { task_id: 't', status: 'completed', summary: '完成' })), null);
  assert.equal(backgroundTasksOf(taskMessage('init', {})), null);
  assert.equal(backgroundTasksOf(sdkMessage('assistant', [])), null);
});

/** 造一条 stream_event：只填被测字段 */
const streamEvent = (event: unknown, parentToolUseId: string | null = null): ClaudeMessage =>
  ({ type: 'stream_event', event, parent_tool_use_id: parentToolUseId }) as unknown as ClaudeMessage;

test('thinkingPhaseOf：按流 + index 跟踪思考块，输出 start / delta / stop 三阶段', () => {
  const blocks = new Map();

  assert.deepEqual(
    thinkingPhaseOf(streamEvent({ type: 'content_block_start', index: 1, content_block: { type: 'thinking' } }), blocks),
    { phase: 'start' },
  );
  assert.deepEqual(
    thinkingPhaseOf(streamEvent({ type: 'content_block_delta', index: 1, delta: { type: 'thinking_delta', thinking: '先想' } }), blocks),
    { phase: 'delta', text: '先想' },
  );
  assert.deepEqual(thinkingPhaseOf(streamEvent({ type: 'content_block_stop', index: 1 }), blocks), { phase: 'stop' });
  // stop 已消费该 index：同一 index 的后续块不再被当成思考块
  assert.equal(thinkingPhaseOf(streamEvent({ type: 'content_block_start', index: 1, content_block: { type: 'text' } }), blocks), null);
  assert.equal(thinkingPhaseOf(streamEvent({ type: 'content_block_stop', index: 1 }), blocks), null);
  assert.equal(blocks.size, 0);
});

test('thinkingPhaseOf：顶层与子代理流的 index 互不覆盖，stop 按各自流配对', () => {
  const blocks = new Map();

  // 两条流都从 index 0 起：子代理的 text 块不得覆盖顶层的 thinking 块
  assert.deepEqual(
    thinkingPhaseOf(streamEvent({ type: 'content_block_start', index: 0, content_block: { type: 'thinking' } }), blocks),
    { phase: 'start' },
  );
  assert.equal(
    thinkingPhaseOf(streamEvent({ type: 'content_block_start', index: 0, content_block: { type: 'text' } }, 'toolu_task'), blocks),
    null,
  );
  assert.deepEqual(thinkingPhaseOf(streamEvent({ type: 'content_block_stop', index: 0 }), blocks), { phase: 'stop' });
  assert.equal(thinkingPhaseOf(streamEvent({ type: 'content_block_stop', index: 0 }, 'toolu_task'), blocks), null);
  assert.equal(blocks.size, 0);
});

test('openThinkingStops：收尾补 stop 时带上开启块的血缘，非思考块不补', () => {
  const blocks = new Map();
  thinkingPhaseOf(streamEvent({ type: 'content_block_start', index: 1, content_block: { type: 'thinking' } }), blocks);
  thinkingPhaseOf(streamEvent({ type: 'content_block_start', index: 1, content_block: { type: 'thinking' } }, 'toolu_task'), blocks);
  thinkingPhaseOf(streamEvent({ type: 'content_block_start', index: 2, content_block: { type: 'text' } }, 'toolu_task'), blocks);

  assert.deepEqual(openThinkingStops(blocks), [
    { type: 'thinking', phase: 'stop', parentToolUseId: null, agentId: null },
    { type: 'thinking', phase: 'stop', parentToolUseId: 'toolu_task', agentId: null },
  ]);
  assert.equal(blocks.size, 0);
});

test('thinkingPhaseOf：文本块、孤立 stop 与非流事件都不产出思考阶段', () => {
  const blocks = new Map();

  assert.equal(thinkingPhaseOf(streamEvent({ type: 'content_block_start', index: 0, content_block: { type: 'text' } }), blocks), null);
  assert.equal(
    thinkingPhaseOf(streamEvent({ type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text: '正文' } }), blocks),
    null,
  );
  assert.equal(thinkingPhaseOf(streamEvent({ type: 'content_block_stop', index: 0 }), blocks), null);
  assert.equal(thinkingPhaseOf(streamEvent({ type: 'content_block_stop', index: 9 }), blocks), null);
  assert.equal(thinkingPhaseOf(sdkMessage('assistant', []), blocks), null);
});

test('apiRetryOf：system/api_retry 映射为 api_retry，字段齐全', () => {
  const message = {
    type: 'system',
    subtype: 'api_retry',
    attempt: 2,
    max_retries: 5,
    error_status: 429,
    error: 'rate_limit',
  } as unknown as ClaudeMessage;

  assert.deepEqual(apiRetryOf(message), { type: 'api_retry', attempt: 2, maxRetries: 5, errorStatus: 429, error: 'rate_limit' });
});

test('apiRetryOf：error_status 缺省归一成 null，非 api_retry 消息忽略', () => {
  const message = { type: 'system', subtype: 'api_retry', attempt: 1, max_retries: 3, error: 'unknown' } as unknown as ClaudeMessage;

  assert.deepEqual(apiRetryOf(message), { type: 'api_retry', attempt: 1, maxRetries: 3, errorStatus: null, error: 'unknown' });
  assert.equal(apiRetryOf(taskMessage('init', {})), null);
  assert.equal(apiRetryOf(sdkMessage('assistant', [])), null);
});

/** 造一份权限回调第三参：只填被测字段，其余用最小合法值兜底 */
const permissionOptions = (fields: Partial<Parameters<typeof toInputRequest>[2]> = {}): Parameters<typeof toInputRequest>[2] => ({
  signal: new AbortController().signal,
  toolUseID: 'tu_1',
  requestId: 'req_1',
  ...fields,
});

/** 一条结构化提问：AskUserQuestion 的入参形态 */
const question = { header: '格式', question: '要处理什么格式？', options: [{ label: 'JSON' }, { label: 'CSV' }], multiSelect: false };

/** SDK 给出的一条可持久权限规则 */
const suggestion = { type: 'addRules', rules: [{ toolName: 'Bash' }], behavior: 'allow', destination: 'session' } as const;

test('toInputRequest：AskUserQuestion 走交互分支，toolCallId 取回调第三参', () => {
  const request = toInputRequest('AskUserQuestion', { questions: [question] }, permissionOptions({ toolUseID: 'tu_q' }));

  assert.equal(request.kind, 'tool_interactive');
  assert.equal(request.toolName, 'AskUserQuestion');
  assert.equal(request.title, '需要澄清');
  assert.equal(request.toolCallId, 'tu_q');
  assert.deepEqual(request.questions, [question]);
  assert.equal('allowAll' in request, false);
});

test('toInputRequest：审批分支优先用 SDK 渲染的卡片文案，缺失才按工具名与输入拼', () => {
  const fromBridge = toInputRequest('Bash', { command: 'ls' }, permissionOptions({ title: 'Claude 想执行 ls', description: '会读取当前目录' }));
  assert.equal(fromBridge.kind, 'approval');
  assert.equal(fromBridge.title, 'Claude 想执行 ls');
  assert.equal(fromBridge.description, '会读取当前目录');

  const bare = toInputRequest('Bash', { command: 'ls' }, permissionOptions());
  assert.equal(bare.title, '允许执行 Bash？');
  assert.equal(bare.description, 'ls');
  assert.equal(bare.toolCallId, 'tu_1');

  assert.equal(toInputRequest('Read', { file_path: 'a.txt' }, permissionOptions()).description, 'a.txt');
});

test('toInputRequest：SDK 禁止「全部允许」时 allowAll 为 false，否则不带该字段', () => {
  assert.equal(toInputRequest('Bash', { command: 'ls' }, permissionOptions({ suppressAlwaysAllowRule: true })).allowAll, false);
  assert.equal('allowAll' in toInputRequest('Bash', { command: 'ls' }, permissionOptions()), false);
});

test('toInputRequest：子代理内的审批与交互都带上 agentId，顶层为 undefined', () => {
  assert.equal(toInputRequest('Bash', { command: 'ls' }, permissionOptions({ agentID: 'task_1' })).agentId, 'task_1');
  assert.equal(
    toInputRequest('AskUserQuestion', { questions: [question] }, permissionOptions({ agentID: 'task_1' })).agentId,
    'task_1',
  );
  assert.equal(toInputRequest('Bash', { command: 'ls' }, permissionOptions()).agentId, undefined);
});

test('sdkAnswers：以被问的问题为权威，多选按「, 」拼接，未问到的 key 丢弃', () => {
  const asked = [question, { header: '范围', question: '处理哪些文件？' }];

  assert.deepEqual(sdkAnswers(asked, { '要处理什么格式？': ['JSON', 'CSV'], '处理哪些文件？': ['a.txt'], '没被问到的': ['x'] }), {
    '要处理什么格式？': 'JSON, CSV',
    '处理哪些文件？': 'a.txt',
  });
  assert.deepEqual(sdkAnswers(asked, { '要处理什么格式？': [], '处理哪些文件？': ['a.txt'] }), { '处理哪些文件？': 'a.txt' });
  assert.deepEqual(sdkAnswers(asked, {}), {});
  assert.deepEqual(sdkAnswers('不是问题数组', { '要处理什么格式？': ['JSON'] }), {});
});

test('permissionOf：approved 放行且入参原样回传，分类是临时', () => {
  const input = { command: 'ls' };
  const result = permissionOf({ decision: 'approved' }, 'Bash', input, permissionOptions());

  assert.deepEqual(result, { behavior: 'allow', updatedInput: input, toolUseID: 'tu_1', decisionClassification: 'user_temporary' });
});

test('permissionOf：approved_all 只标永久分类，不回填 SDK 建议规则（不写共享 settings）', () => {
  const result = permissionOf({ decision: 'approved_all' }, 'Bash', { command: 'ls' }, permissionOptions({ suggestions: [suggestion] }));

  assert.equal(result.behavior, 'allow');
  if (result.behavior !== 'allow') throw new Error('应为放行');
  assert.equal(result.decisionClassification, 'user_permanent');
  assert.equal(result.updatedPermissions, undefined);
  assert.equal('updatedPermissions' in result, false);
});

test('permissionOf：rejected / aborted / 无决定一律拒绝，并回显 toolUseID', () => {
  for (const decision of [{ decision: 'rejected' }, { decision: 'aborted' }, {}] as const) {
    assert.deepEqual(permissionOf(decision, 'Bash', { command: 'ls' }, permissionOptions({ toolUseID: 'tu_9' })), {
      behavior: 'deny',
      message: '用户拒绝了这次工具调用',
      toolUseID: 'tu_9',
      decisionClassification: 'user_reject',
    });
  }
});

test('permissionOf：AskUserQuestion 的 updatedInput 是归一后的 questions + answers', () => {
  const input = { questions: [question] };
  const result = permissionOf(
    { decision: 'approved', answers: { '要处理什么格式？': ['JSON', 'CSV'], '没被问到的': ['x'] } },
    'AskUserQuestion',
    input,
    permissionOptions({ toolUseID: 'tu_q' }),
  );

  assert.equal(result.behavior, 'allow');
  if (result.behavior !== 'allow') throw new Error('应为放行');
  assert.deepEqual(result.updatedInput, { questions: input.questions, answers: { '要处理什么格式？': 'JSON, CSV' } });
});

test('permissionOf：交互应答只带 answers（无 decision）也必须放行', () => {
  // 真实链路（respondMessage → liveHub.settle）给的就是这个形状：只有 answers，没有 decision。
  // 曾经这里按「无决定 = 拒绝」处理，用户答完题后模型只看到「用户拒绝了这次工具调用」。
  const input = { questions: [question] };
  const answerCases = [{ '要处理什么格式？': ['JSON'] }, {}];

  for (const answers of answerCases) {
    const result = permissionOf({ answers }, 'AskUserQuestion', input, permissionOptions({ toolUseID: 'tu_q' }));

    assert.equal(result.behavior, 'allow');
    if (result.behavior !== 'allow') throw new Error('应为放行');
    assert.deepEqual(result.updatedInput, {
      questions: input.questions,
      answers: '要处理什么格式？' in answers ? { '要处理什么格式？': 'JSON' } : {},
    });
    assert.equal(result.decisionClassification, 'user_temporary');
  }
});

test('permissionOf：交互挂起随中止作废时仍是拒绝（哪怕带空 answers）', () => {
  const result = permissionOf(
    { decision: 'aborted', answers: {} },
    'AskUserQuestion',
    { questions: [question] },
    permissionOptions({ toolUseID: 'tu_q' }),
  );

  assert.equal(result.behavior, 'deny');
});

test('FakeAdapter.run：记录会话级参数，并在「带会话」时回调一次引擎会话标识', async () => {
  const sessionIds: string[] = [];
  const ctx = {
    prompt: FAKE_TRIGGER.session,
    model: { modelName: 'test-model', baseUrl: null, apiKey: 'sk-test' },
    resumeSessionId: 'sdk-session-1',
    mode: 'read_only',
    effort: 'high',
    onSessionId: (id: string) => {
      sessionIds.push(id);
    },
    emit: () => undefined,
    requestInput: async () => ({}),
    signal: new AbortController().signal,
  } as unknown as EngineContext;

  await new FakeAdapter().run(ctx);

  assert.deepEqual(sessionIds, ['fake-sdk-session']);
  assert.equal(FakeAdapter.lastResumeSessionId, 'sdk-session-1');
  assert.equal(FakeAdapter.lastMode, 'read_only');
  assert.equal(FakeAdapter.lastEffort, 'high');
});

test('ClaudeAdapter.run：signal 已中止时空手返回，不读上下文、不建会话', async () => {
  const controller = new AbortController();
  controller.abort();
  // 中毒上下文：run 若在已中止后仍往下走（读上下文或建 query），会当场抛错而不是真的起引擎
  const poisoned = {
    signal: controller.signal,
    get prompt(): string {
      throw new Error('已中止的 run 不应读取 prompt');
    },
    get cwd(): string {
      throw new Error('已中止的 run 不应读取 cwd');
    },
  } as unknown as EngineContext;

  assert.deepEqual(await new ClaudeAdapter().run(poisoned), { output: '' });
});

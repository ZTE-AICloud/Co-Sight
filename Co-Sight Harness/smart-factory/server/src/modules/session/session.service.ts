import { mkdirSync, realpathSync } from 'node:fs';
import { isAbsolute } from 'node:path';
import { config } from '../../config/index.js';
import { resolveEngineAdapter } from '../../shared/engine/registry.js';
import type {
  EngineAdapter,
  EngineContext,
  EngineEvent,
  EngineModel,
  InputDecision,
  InputRequest,
} from '../../shared/engine/port.js';
import { AppError, BadGatewayError, BadRequestError, ConflictError, NotFoundError } from '../../shared/errors.js';
import { fetchWorkspaces } from '../../shared/framework/client.js';
import { eventEnvelope } from '../../shared/live/envelope.js';
import { liveHub } from '../../shared/live/live-hub.js';
import type { HistoryResult, SubscribeInfo } from '../../shared/live/ws-gateway.js';
import { agentsRepo } from '../../shared/store/agents.repo.js';
import { instancesRepo } from '../../shared/store/instances.repo.js';
import { messagesRepo } from '../../shared/store/messages.repo.js';
import { STAGE_GUARD_MESSAGES, runsRepo } from '../../shared/store/runs.repo.js';
import { sessionsRepo, type SessionUpdateData } from '../../shared/store/sessions.repo.js';
import { agentRoot, assertAgentId } from '../../shared/workspace/dir-resolver.js';
import { resolveAttachmentPaths, resolveLocalTarget } from '../../shared/workspace/local-path.js';
import { resetStage, resolveStageCwd } from '../../shared/workspace/materialize.js';
import {
  resolveAgentRoot,
  resolveAgentWorkspace,
  resolveWorkspaceDirectory,
} from '../../shared/workspace/workspace-resolver.js';
import type {
  AgentRunStatus,
  ApprovalDecision,
  DecisionSource,
  Instance,
  InstanceStage,
  Message,
  MessageContent,
  MessageFile,
  MessagePage,
  MessageRole,
  MessageStatus,
  MessageType,
  PageResult,
  Run,
  RunRow,
  Session,
  SessionEffort,
  SessionMode,
  SessionRow,
  SessionStatus,
} from '../../shared/types/index.js';
import {
  MESSAGE_LIMIT_MAX,
  answersParam,
  csvStrings,
  limitParam,
  messageCursor,
  optionalInt,
  optionalString,
  pageParams,
  requireEnum,
  requireString,
} from '../../shared/validate.js';
import { assertModelRunnable, resolveRunModel, type ResolvedRunModel } from '../model/model.service.js';

/**
 * 全部合法阶段。目录实例也落在这四种里（工坊 = `development`）：
 * 「目录 vs 智能体」由 `instance.agentId` 是否为空区分，不由 stage 区分
 * （10-skill-library.md §3.3）。
 */
const STAGES = ['development', 'preview', 'runtime', 'evaluation'] as const satisfies readonly InstanceStage[];
/** 建会话时 agentId 形态接受的阶段；与 STAGES 同源，单独留名让意图可读。 */
const AGENT_STAGES = STAGES;
const SESSION_MODES = ['read_only', 'workspace_write', 'full_access'] as const satisfies readonly SessionMode[];
const SESSION_EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max'] as const satisfies readonly SessionEffort[];
const SESSION_STATUSES = ['not_started', 'in_progress', 'completed'] as const satisfies readonly SessionStatus[];
/** `type` 是 `stage` 的逗号分隔别名；`all` 取消阶段过滤。 */
const SESSION_TYPES = [...STAGES, 'all'] as const;
const MESSAGE_STATUSES = ['pending', 'approved', 'approved_all', 'rejected', 'answered', 'aborted'] as const satisfies readonly MessageStatus[];

/** 「不设上界」的游标：历史消息不带游标时取最近 limit 条。 */
const TAIL_SEQ = Number.MAX_SAFE_INTEGER;

/** 进程内活跃 run 的中止句柄；run 落终态后移除。 */
const abortControllers = new Map<string, AbortController>();

/**
 * 顶层 run 的驱动链句柄：`sendMessage` 起跑时登记，驱动链（含引擎退出后的收尾）走完才移除。
 * 中止只落终态、不等引擎，删除智能体要等引擎真正退出再删盘时靠它。
 */
const drivePromises = new Map<string, Promise<void>>();

/** 去重集合的容量上限：长进程里 run id 不断累积，超出后淘汰最旧的一条。 */
const DEDUP_LIMIT = 4096;

/** 已广播终态的事件去重：abortRun 与 closeRun 可能先后收口同一顶层 run。 */
const finalizedRuns = new Set<string>();
/** 已广播 task.notified 的子 run：task_notification、中止与收尾收敛共用。 */
const notifiedChildRuns = new Set<string>();

/** 记一次去重标记；已存在返回 false。 */
function remember(set: Set<string>, id: string): boolean {
  if (set.has(id)) return false;
  set.add(id);
  if (set.size > DEDUP_LIMIT) {
    const oldest = set.values().next().value;
    if (oldest !== undefined) set.delete(oldest);
  }
  return true;
}

/**
 * 顶层 run 的进程内子 run 索引：task / tool_use / agent 到 run 的映射与子 run 行。
 *
 * 内容事件靠它归位到子 run；closeRun 时整体清理。
 */
interface RunTree {
  /**
   * 任务运行键 -> 子 run id：键为 taskId + runId。
   * 同一 taskId 恢复后会拿到新 runId 并新建子 run；无 runId 的旧 CLI 事件以 taskId 为键指向最近一次运行。
   */
  taskRuns: Map<string, string>;
  /** 工具调用 id -> run id：task 的 tool_use 指向子 run，其余 tool_use 指向产出它的 run */
  toolRuns: Map<string, string>;
  /** 子代理 agent_id -> 子 run id（等于 task_id） */
  agentRuns: Map<string, string>;
  /** 子 run id -> 子 run 行：内容落库与血缘字段回填用 */
  childRuns: Map<string, RunRow>;
  /** 已落终态的子 run：其迟到内容事件直接丢弃 */
  terminal: Set<string>;
}

const runTrees = new Map<string, RunTree>();

/** 取顶层 run 的子 run 索引，没有就建一个。 */
function runTreeOf(top: RunRow): RunTree {
  const existing = runTrees.get(top.id);
  if (existing) return existing;
  const tree: RunTree = {
    taskRuns: new Map(),
    toolRuns: new Map(),
    agentRuns: new Map(),
    childRuns: new Map(),
    terminal: new Set(),
  };
  runTrees.set(top.id, tree);
  return tree;
}

/** 按 agent_id -> parent_tool_use_id -> toolCallId -> 顶层 run 的顺序解析内容归属。 */
function resolveRunId(
  top: RunRow,
  hints: { agentId?: string | null; parentToolUseId?: string | null; toolCallId?: string | null },
): string {
  const tree = runTrees.get(top.id);
  if (!tree) return top.id;
  const agentRunId = hints.agentId ? tree.agentRuns.get(hints.agentId) : undefined;
  if (agentRunId) return agentRunId;
  const parentToolRunId = hints.parentToolUseId ? tree.toolRuns.get(hints.parentToolUseId) : undefined;
  if (parentToolRunId) return parentToolRunId;
  const toolRunId = hints.toolCallId ? tree.toolRuns.get(hints.toolCallId) : undefined;
  return toolRunId ?? top.id;
}

/** 解析出的 run id -> run 行；查不到时退回顶层 run。 */
function targetRunOf(top: RunRow, runId: string): RunRow {
  if (runId === top.id) return top;
  return runTrees.get(top.id)?.childRuns.get(runId) ?? top;
}

function isTerminalStatus(status: AgentRunStatus | string): boolean {
  return status === 'succeeded' || status === 'failed' || status === 'aborted';
}

/** 实时事件只推给当前在线的订阅者，无回放。 */
function broadcast(sessionId: string, method: string, payload: unknown): void {
  liveHub.broadcast(sessionId, eventEnvelope(method, payload));
}

/** 派生 waiting 后广播一条 run 事件；run.started 只属于仍在 running 的 run。 */
async function broadcastRun(sessionId: string, runId: string, method: 'run.started' | 'run.status'): Promise<Run | null> {
  // waiting 先查、状态后查：run.started 的 running 判定是广播前最后一次读，压缩中止竞态窗口
  const waiting = await runsRepo.waitingByRunIds([runId]);
  const run = await runsRepo.findById(runId);
  if (!run) return null;
  // 终态 run 绝不补发起跑事件：中止可能落在起跑条件解析与广播之间
  if (method === 'run.started' && run.status !== 'running') return null;
  const payload = { ...run, waiting: waiting.get(run.id) ?? null };
  broadcast(sessionId, method, payload);
  return payload;
}

/** 商用客户端的审批选项；`allowAll === false` 时不提供「本会话全部允许」。 */
const APPROVAL_OPTIONS = [
  { value: 'approved', label: '允许', enLabel: 'Allow' },
  { value: 'approved_all', label: '本会话全部允许', enLabel: 'Allow all' },
  { value: 'rejected', label: '拒绝', enLabel: 'Reject' },
];

/** 工具调用上下文：runId → toolCallId → { toolName, input }，run 收口时整体清空。 */
const toolCallContext = new Map<string, Map<string, { toolName?: unknown; input?: unknown }>>();

/** run 的正文累积：适配器终稿为空时，chat.final 退回用增量或文本消息拼出的内容。 */
const runTexts = new Map<string, { delta: string; message: string }>();
/** 适配器返回的终稿：chat.final 的主来源。 */
const runOutputs = new Map<string, string>();
/** 该 run 最近一条助手文本消息 id：chat.final 的 messageId 来源。 */
const lastAssistantMessageIds = new Map<string, string>();

/** 消息 content 按运行时结构读，不依赖具体消息类型的字段声明。 */
function contentOf(message: Message): Record<string, unknown> {
  return message.content as Record<string, unknown>;
}

function textStateOf(runId: string): { delta: string; message: string } {
  const state = runTexts.get(runId) ?? { delta: '', message: '' };
  runTexts.set(runId, state);
  return state;
}

function rememberTool(runId: string | null, toolCallId: unknown, context: { toolName?: unknown; input?: unknown }): void {
  if (!runId || typeof toolCallId !== 'string') return;
  const perRun = toolCallContext.get(runId) ?? new Map<string, { toolName?: unknown; input?: unknown }>();
  perRun.set(toolCallId, context);
  toolCallContext.set(runId, perRun);
}

function takeTool(runId: string | null, toolCallId: unknown): { toolName?: unknown; input?: unknown } | undefined {
  if (!runId || typeof toolCallId !== 'string') return undefined;
  const perRun = toolCallContext.get(runId);
  const context = perRun?.get(toolCallId);
  perRun?.delete(toolCallId);
  return context;
}

/** 挂起审批 / 交互的兼容帧；订阅补发与实时广播共用，保证形状一致。 */
function pendingFrameOf(
  message: Message,
  parentRunId: string | null,
): { method: 'approval.request' | 'tool.interactive'; payload: Record<string, unknown> } | null {
  const content = contentOf(message);
  if (message.status !== 'pending') return null;
  if (message.type === 'approval') {
    const options = content.allowAll === false ? APPROVAL_OPTIONS.filter((option) => option.value !== 'approved_all') : APPROVAL_OPTIONS;
    return {
      method: 'approval.request',
      payload: {
        approvalId: message.id,
        sessionId: message.sessionId,
        runId: message.runId,
        parentRunId,
        toolCallId: content.toolCallId ?? null,
        ...(typeof content.agentId === 'string' ? { agentId: content.agentId } : {}),
        toolName: content.toolName,
        title: content.title,
        description: content.description,
        input: content.input,
        options,
      },
    };
  }
  if (message.type === 'tool_interactive') {
    return {
      method: 'tool.interactive',
      payload: {
        sessionId: message.sessionId,
        toolCallId: content.toolCallId,
        runId: message.runId,
        parentRunId,
        toolName: content.toolName,
        input: { questions: content.questions ?? [] },
      },
    };
  }
  return null;
}

/** 兼容事件：商用客户端按事件名消费，原生 `message` 事件保持不变；子 run 额外带血缘。 */
function broadcastCompatibility(message: Message, parentRunId: string | null): void {
  const pending = pendingFrameOf(message, parentRunId);
  if (pending) {
    broadcast(message.sessionId, pending.method, pending.payload);
    return;
  }
  const content = contentOf(message);
  switch (message.type) {
    case 'tool_use':
      rememberTool(message.runId, content.toolCallId, { toolName: content.toolName, input: content.input });
      broadcast(message.sessionId, 'tool.executing', {
        sessionId: message.sessionId,
        toolCallId: content.toolCallId,
        runId: message.runId,
        parentRunId,
        toolName: content.toolName,
        input: content.input,
      });
      return;
    case 'tool_result': {
      const context = takeTool(message.runId, content.toolCallId);
      broadcast(message.sessionId, 'tool.executed', {
        sessionId: message.sessionId,
        toolCallId: content.toolCallId,
        runId: message.runId,
        parentRunId,
        toolName: context?.toolName ?? content.toolName,
        input: context?.input ?? content.input,
        output: content.output,
        isError: content.isError,
      });
      return;
    }
  }
}

/** 顶层 run 终态 → 兼容事件：成功发 chat.final，失败发 chat.error，中止发 chat.aborted；子 run 只发 task.notified。 */
function broadcastRunOutcome(sessionId: string, run: RunRow): void {
  if (run.status === 'succeeded') {
    const accumulated = runTexts.get(run.id);
    const content = runOutputs.get(run.id) || accumulated?.delta || accumulated?.message || '';
    broadcast(sessionId, 'chat.final', {
      sessionId,
      runId: run.id,
      parentRunId: run.parentRunId,
      content,
      messageId: lastAssistantMessageIds.get(run.id) ?? null,
    });
    return;
  }
  if (run.status === 'failed') {
    broadcast(sessionId, 'chat.error', {
      sessionId,
      runId: run.id,
      parentRunId: run.parentRunId,
      code: 'RUN_ERROR',
      message: run.error ?? '',
    });
    return;
  }
  if (run.status === 'aborted') {
    broadcast(sessionId, 'chat.aborted', {
      sessionId,
      runId: run.id,
      parentRunId: run.parentRunId,
      reason: run.error ?? '用户中止',
    });
  }
}

/** run 收口：清掉只属于该 run 的进程内状态。 */
function clearRunState(runId: string): void {
  runOutputs.delete(runId);
  runTexts.delete(runId);
  toolCallContext.delete(runId);
  lastAssistantMessageIds.delete(runId);
}

/** 兼容 `tool.respond` 的 answers：数组形态按问题归并，对象形态逐值归一。 */
function normalizeToolAnswers(value: unknown): Record<string, string[]> {
  const answers: Record<string, string[]> = {};
  if (Array.isArray(value)) {
    for (const item of value) {
      if (!item || typeof item !== 'object') throw new BadRequestError('answers 格式非法', 'error.bad_request.answer_shape', { question: 'answers' });
      const { question, answer } = item as { question?: unknown; answer?: unknown };
      if (typeof question !== 'string') continue;
      answers[question] = answerList(answer);
    }
    return answers;
  }
  if (value && typeof value === 'object') {
    for (const [question, answer] of Object.entries(value as Record<string, unknown>)) {
      answers[question] = answerList(answer);
    }
    return answers;
  }
  throw new BadRequestError('answers 格式非法', 'error.bad_request.answer_shape', { question: 'answers' });
}

function answerList(value: unknown): string[] {
  if (typeof value === 'string') return [value];
  if (Array.isArray(value)) return value as string[];
  throw new BadRequestError('answers 格式非法', 'error.bad_request.answer_shape', { question: 'answers' });
}

/** 兼容 history 的 content 拍平：客户端只消费字符串正文。 */
function flattenContent(message: Message): string {
  const content = contentOf(message);
  switch (message.type) {
    case 'text':
    case 'thinking':
      return typeof content.text === 'string' ? content.text : '';
    case 'tool_use':
      return JSON.stringify(content.input ?? content);
    case 'tool_result':
      return typeof content.output === 'string' ? content.output : JSON.stringify(content.output ?? '');
    case 'approval':
      return typeof content.title === 'string' ? content.title : JSON.stringify(content);
    case 'tool_interactive':
      return JSON.stringify(content.questions ?? content);
    default:
      return JSON.stringify(content);
  }
}

/** 引擎请求 → 挂起消息的 content（形状见 4.04 消息 §3）。 */
function requestContent(request: InputRequest): MessageContent {
  if (request.kind === 'tool_interactive') {
    return { toolCallId: request.toolCallId, toolName: request.toolName, questions: request.questions ?? [] };
  }
  return {
    toolCallId: request.toolCallId,
    toolName: request.toolName,
    title: request.title,
    description: request.description,
    agentId: request.agentId,
    // 缺省（undefined）序列化后即字段缺失，前端据此判断是否可以「本会话全部允许」
    allowAll: request.allowAll,
    input: request.input,
  };
}

/**
 * 装配会话 DTO：内联实例 + 派生字段。
 *
 * 实例、消息计数与首尾正文并行取；`withMessageSummary` 只给列表用，
 * 详情 / 创建 / 更新的首尾正文恒为 null（契约 4.03 §3.1）。
 */
async function hydrateSessions(rows: SessionRow[], withMessageSummary = false): Promise<Session[]> {
  if (rows.length === 0) return [];
  const ids = rows.map((row) => row.id);
  const [instances, counts, lastMessages, firstUserMessages] = await Promise.all([
    instancesRepo.findByIds([...new Set(rows.map((row) => row.instanceId))]),
    messagesRepo.countBySessions(ids),
    withMessageSummary ? messagesRepo.lastTextBySession(ids) : undefined,
    withMessageSummary ? messagesRepo.firstTextBySession(ids) : undefined,
  ]);
  return rows.map((row) => {
    const instance = instances.get(row.instanceId);
    if (!instance) throw new NotFoundError(`实例 ${row.instanceId}`, 'error.not_found.instance', { instanceId: row.instanceId });
    return {
      ...row,
      instance,
      messageCount: counts.get(row.id) ?? 0,
      lastMessage: lastMessages?.get(row.id) ?? null,
      firstUserMessage: firstUserMessages?.get(row.id) ?? null,
    };
  });
}

function decorate(run: RunRow, waiting: Map<string, { count: number; since: string }>): Run {
  return { ...run, waiting: waiting.get(run.id) ?? null };
}

/** 落一条 run 内的消息并广播（seq 由仓储分配）；终态守卫在写入前后各查一次。 */
async function appendAndBroadcast(
  input: { session: SessionRow; run: RunRow },
  draft: { role: MessageRole; type: MessageType; status: MessageStatus | null; content: MessageContent },
  terminal?: () => boolean,
): Promise<Message | null> {
  if (terminal?.()) return null;
  const message = await messagesRepo.append({ sessionId: input.session.id, runId: input.run.id, ...draft });
  // 写入期间 run 可能被收口：复判后撤回，不得让终态后的内容进入历史
  if (terminal?.()) {
    await messagesRepo.remove(message.id);
    return null;
  }
  if (message.role === 'assistant' && message.type === 'text') {
    lastAssistantMessageIds.set(input.run.id, message.id);
  }
  // 边界：复判之后到广播之前落下的终态无法再拦 - 消息已写入，无法撤回
  broadcast(input.session.id, 'message', message);
  broadcastCompatibility(message, input.run.parentRunId);
  return message;
}

type TaskStartedEvent = Extract<EngineEvent, { type: 'task_started' }>;
type TaskNotifiedEvent = Extract<EngineEvent, { type: 'task_notified' }>;

/** 任务运行键：CLI 的 run_id 区分同一 task_id 的多次运行（resume 后 task_id 不变、run_id 变）。 */
function taskRunKey(taskId: string, runId: string | null): string {
  return runId ? `${taskId}\u0000${runId}` : taskId;
}

/** 读任务事件上的 CLI run_id；适配器缺省时不带该字段，按 task_id 最近一次运行归位。 */
function taskRunIdOf(event: TaskStartedEvent | TaskNotifiedEvent): string | null {
  return event.runId !== undefined && event.runId !== '' ? event.runId : null;
}

/** task_started：建子 run、登记血缘映射并广播 task.started。 */
async function handleTaskStarted(input: { session: SessionRow; run: RunRow }, event: TaskStartedEvent): Promise<void> {
  const tree = runTreeOf(input.run);
  const runId = taskRunIdOf(event);
  const key = taskRunKey(event.taskId, runId);
  const existing = tree.taskRuns.get(key);
  // 同一 task 的同一 run 重复上报直接忽略；只有旧 CLI（不带 run_id）才靠旧 run 终态识别 resume
  if (existing && (runId !== null || !tree.terminal.has(existing))) return;

  const parentRunId = (event.parentTaskId ? tree.taskRuns.get(event.parentTaskId) : undefined) ?? input.run.id;
  const parentRun = targetRunOf(input.run, parentRunId);
  const delegationDepth = event.delegationDepth > 0 ? event.delegationDepth : parentRun.delegationDepth + 1;
  const child = await runsRepo.createSubRun({
    sessionId: input.session.id,
    instanceId: input.run.instanceId,
    parentRunId,
    parentToolUseId: event.toolUseId,
    subagentType: event.subagentType,
    delegationDepth,
    taskId: event.taskId,
  });
  registerChildRun(tree, event, child, key);
  broadcastTaskStarted(input.session.id, event, child);
  await abortLateChild(input, tree, child);
}

/** 登记子 run 的 task / agent / tool 索引；同一 task_id 的新 run_id 覆盖最新映射。 */
function registerChildRun(tree: RunTree, event: TaskStartedEvent, child: RunRow, key: string): void {
  const previous = tree.agentRuns.get(event.taskId);
  tree.taskRuns.set(key, child.id);
  // 无 run_id 的 task_notification 按该 task 最近一次运行归位
  tree.taskRuns.set(event.taskId, child.id);
  tree.agentRuns.set(event.taskId, child.id);
  tree.childRuns.set(child.id, child);
  // 流式与工具结果帧只有 parent_tool_use_id：恢复后把任务级 tool_use id 一并切到新 run
  const previousToolUseId = previous ? tree.childRuns.get(previous)?.parentToolUseId : null;
  if (previousToolUseId) tree.toolRuns.set(previousToolUseId, child.id);
  if (event.toolUseId) tree.toolRuns.set(event.toolUseId, child.id);
}

function broadcastTaskStarted(sessionId: string, event: TaskStartedEvent, child: RunRow): void {
  broadcast(sessionId, 'task.started', {
    sessionId,
    runId: child.id,
    parentRunId: child.parentRunId,
    taskId: child.taskId,
    toolCallId: child.parentToolUseId,
    subagentType: child.subagentType,
    delegationDepth: child.delegationDepth,
    ...(event.description ? { description: event.description } : {}),
  });
}

/** task_started 与中止并发：子 run 落库晚于中止收敛时立即收口，避免中止返回后残留 running。 */
async function abortLateChild(input: { session: SessionRow; run: RunRow }, tree: RunTree, child: RunRow): Promise<void> {
  const top = await runsRepo.findById(input.run.id);
  if (!top || !isTerminalStatus(top.status)) return;
  if (!(await runsRepo.finish(child.id, 'aborted'))) return;
  tree.terminal.add(child.id);
  const row = (await runsRepo.findById(child.id)) ?? child;
  tree.childRuns.set(row.id, row);
  broadcastTaskNotified(input.session.id, row, 'stopped', null, null);
}

/**
 * 广播一条 task.notified；同一子 run 只广播一次。
 *
 * 线上 status 用 CLI 值 completed / failed / stopped；中止与收尾收敛一律报 stopped，
 * 库里仍按 succeeded / failed / aborted 落。
 * 子 run 的终态只走本事件；chat.final / chat.error / chat.aborted 只表示顶层 run。
 */
function broadcastTaskNotified(
  sessionId: string,
  run: RunRow,
  status: TaskNotifiedEvent['status'],
  error: string | null,
  summary: string | null,
): void {
  if (!remember(notifiedChildRuns, run.id)) return;
  broadcast(sessionId, 'task.notified', {
    sessionId,
    runId: run.id,
    parentRunId: run.parentRunId,
    taskId: run.taskId,
    status,
    subagentType: run.subagentType,
    error,
    summary,
  });
}

/** 会话没有活跃 run 时置 completed；状态真的变化才广播。 */
async function settleSessionStatus(sessionId: string): Promise<void> {
  const before = await sessionsRepo.findById(sessionId);
  await sessionsRepo.completeIfNoActiveRun(sessionId);
  const after = await sessionsRepo.findById(sessionId);
  if (before && after && before.status !== after.status) {
    broadcast(sessionId, 'session.status', { sessionId, status: after.status });
  }
}

/** task_notification：条件更新子 run 终态，更新成功才广播 task.notified。 */
async function handleTaskNotified(input: { session: SessionRow; run: RunRow }, event: TaskNotifiedEvent): Promise<void> {
  const tree = runTrees.get(input.run.id);
  if (!tree) return;
  const runId = taskRunIdOf(event);
  // 带 run_id 的按 taskId + runId 精确定位（迟到通知不得结算恢复后的新 run）；旧 CLI 缺字段时退回最近一次运行
  const childRunId = runId
    ? tree.taskRuns.get(taskRunKey(event.taskId, runId))
    : tree.taskRuns.get(event.taskId);
  if (!childRunId || tree.terminal.has(childRunId)) return;

  const status = event.status === 'completed' ? 'succeeded' : event.status === 'failed' ? 'failed' : 'aborted';
  const error = status === 'failed' ? event.error ?? '子任务失败' : null;
  if (!(await runsRepo.finish(childRunId, status, error ?? undefined))) return;

  const child = (await runsRepo.findById(childRunId)) ?? tree.childRuns.get(childRunId);
  tree.terminal.add(childRunId);
  if (child) {
    tree.childRuns.set(child.id, child);
    broadcastTaskNotified(input.session.id, child, event.status, error, event.summary);
  }
  await settleSessionStatus(input.session.id);
}

/** 引擎事件 → 实时通道：任务生命周期交给专用处理，内容事件统一走终态守卫。 */
async function emitEngineEvent(input: { session: SessionRow; run: RunRow }, event: EngineEvent): Promise<void> {
  if (event.type === 'task_started') return handleTaskStarted(input, event);
  if (event.type === 'task_notified') return handleTaskNotified(input, event);
  if (event.type === 'api_retry') {
    broadcast(input.session.id, 'chat.retry', {
      sessionId: input.session.id,
      runId: input.run.id,
      parentRunId: null,
      attempt: event.attempt,
      maxRetries: event.maxRetries,
      errorStatus: event.errorStatus,
      error: event.error,
    });
    return;
  }
  await emitContentEvent(input, event);
}

type ContentEvent = Extract<EngineEvent, { type: 'delta' | 'thinking' | 'message' }>;

/** 内容事件：按血缘归位到子 run；终态子 run 的迟到内容直接丢弃。 */
async function emitContentEvent(input: { session: SessionRow; run: RunRow }, event: ContentEvent): Promise<void> {
  const targetRunId = resolveRunId(input.run, {
    agentId: event.agentId,
    parentToolUseId: event.parentToolUseId,
  });
  const terminal = (): boolean => runTrees.get(input.run.id)?.terminal.has(targetRunId) ?? false;
  if (terminal()) return;
  const target = targetRunOf(input.run, targetRunId);

  if (event.type === 'delta') {
    emitDelta(input, event, target);
    return;
  }
  if (event.type === 'thinking') {
    emitThinking(input, event, target);
    return;
  }
  if (event.draft.role === 'assistant' && event.draft.type === 'text') {
    const { text } = event.draft.content as { text?: unknown };
    if (typeof text === 'string') textStateOf(target.id).message += text;
  }
  if (event.draft.type === 'tool_use') {
    const { toolCallId } = event.draft.content as { toolCallId?: unknown };
    if (typeof toolCallId === 'string') runTrees.get(input.run.id)?.toolRuns.set(toolCallId, target.id);
  }
  await appendAndBroadcast({ session: input.session, run: target }, {
    role: event.draft.role,
    type: event.draft.type,
    status: event.draft.status ?? null,
    content: event.draft.content,
  }, terminal);
}

/** 正文增量是瞬态不落库。 */
function emitDelta(
  input: { session: SessionRow; run: RunRow },
  event: Extract<EngineEvent, { type: 'delta' }>,
  target: RunRow,
): void {
  textStateOf(target.id).delta += event.delta;
  broadcast(input.session.id, 'chat.delta', {
    sessionId: input.session.id,
    runId: target.id,
    parentRunId: target.parentRunId,
    messageType: 'text',
    delta: event.delta,
  });
}

/** 思考阶段是瞬态不落库；start/stop 不带正文，delta 才带 text。 */
function emitThinking(
  input: { session: SessionRow; run: RunRow },
  event: Extract<EngineEvent, { type: 'thinking' }>,
  target: RunRow,
): void {
  broadcast(input.session.id, 'chat.thinking', {
    sessionId: input.session.id,
    runId: target.id,
    parentRunId: target.parentRunId,
    phase: event.phase,
    ...(event.phase === 'delta' && event.text !== undefined ? { text: event.text } : {}),
    at: new Date().toISOString(),
  });
}

/** approved_all 短路：检查会话级开关，审计消息落在实际发起请求的 run 上。 */
async function autoApproveIfEnabled(
  input: { session: SessionRow; run: RunRow },
  request: InputRequest,
  target: RunRow,
): Promise<InputDecision | null> {
  if (request.kind !== 'approval') return null;
  // 读新行：同一 run 内用户刚选 approved_all 时，send 时的会话快照还是 false
  const session = await sessionsRepo.findById(input.session.id);
  if (!session?.approvedAll) return null;
  await appendAndBroadcast({ session: input.session, run: target }, {
    role: 'assistant',
    type: 'approval',
    status: 'approved_all',
    content: { ...requestContent(request), decision: 'approved_all', decisionSource: 'approved_all_auto' },
  });
  return { decision: 'approved_all' };
}

/** 落一条 pending 并等应答，返回放行句柄（应答 / 中止 / 重启）。 */
async function parkUntilResponded(input: { session: SessionRow; run: RunRow }, request: InputRequest): Promise<InputDecision> {
  const pending = await messagesRepo.append({
    sessionId: input.session.id,
    runId: input.run.id,
    role: 'assistant',
    type: request.kind,
    status: 'pending',
    content: requestContent(request),
  });
  // 先注册等待句柄、再广播：客户端可能在收到 message 事件后立即应答
  const decision = liveHub.waitFor<InputDecision>(pending.id);
  broadcast(input.session.id, 'message', pending);
  broadcastCompatibility(pending, input.run.parentRunId);
  // 挂起落库与中止并发：目标 run 已收口时补一次自结算，避免引擎永久阻塞
  if (await runSettled(input.run)) await settleLatePending(pending, request);
  // 真相在库里：这里只等一个放行句柄（应答 / 中止 / 重启）
  return decision;
}

/** 目标 run 是否已落终态；收口窗口内的挂起靠它自结算。 */
async function runSettled(run: RunRow): Promise<boolean> {
  const row = await runsRepo.findById(run.id);
  return row !== null && isTerminalStatus(row.status);
}

/** 收口窗口内才落库的挂起：补一次中止结算并放行引擎。 */
async function settleLatePending(pending: Message, request: InputRequest): Promise<void> {
  const content = request.kind === 'approval'
    ? { decision: 'aborted' as const, decisionSource: 'abort' as const }
    : { decisionSource: 'abort' as const };
  const settled = await messagesRepo.settlePending(pending.id, { status: 'aborted', content });
  // 条件更新落空说明别的路径已结算并放行，不再补第二个决策
  if (!settled) return;
  liveHub.settle(pending.id, { decision: 'aborted' });
  broadcast(pending.sessionId, 'message', settled);
}

/** 引擎请求 → 放行决策：请求按 agentId / toolCallId 归位到顶层或子 run。 */
async function requestInputViaMessage(input: { session: SessionRow; run: RunRow }, request: InputRequest): Promise<InputDecision> {
  const target = targetRunOf(
    input.run,
    resolveRunId(input.run, { agentId: request.agentId, toolCallId: request.toolCallId }),
  );
  const auto = await autoApproveIfEnabled(input, request, target);
  return auto ?? parkUntilResponded({ session: input.session, run: target }, request);
}

/** 组装引擎上下文：落库与广播收口到 emit / requestInput 两个钩子。 */
function buildEngineContext(
  input: { session: SessionRow; instance: Instance; run: RunRow; prompt: string },
  cwd: string,
  model: EngineModel,
  controller: AbortController,
): EngineContext {
  return {
    session: input.session,
    run: input.run,
    instance: input.instance,
    cwd,
    prompt: input.prompt,
    model,
    resumeSessionId: input.session.resumeSessionId,
    mode: input.session.approvalMode,
    effort: input.session.effort,
    // 引擎首次产出接续标识即落库；写失败交给驱动链收口，不在回调里吞错
    onSessionId: async (resumeSessionId) => {
      await sessionsRepo.update(input.session.id, { resumeSessionId });
    },
    emit: (event) => emitEngineEvent(input, event),
    requestInput: (request) => requestInputViaMessage(input, request),
    signal: controller.signal,
  };
}

/** 结算给定 run（顶层及其子 run）的全部挂起：先落库再放行被阻塞的引擎，并按条广播。 */
export async function settleRunPendings(runIds: string[]): Promise<void> {
  broadcastSettled(await messagesRepo.abortPendingByRuns(runIds, 'abort'));
}

/** 结算该会话（含子 run）的全部挂起：失败与启动收口共用。 */
export async function settleSessionPendings(sessionId: string): Promise<void> {
  broadcastSettled(await messagesRepo.abortPendingBySession(sessionId, 'abort'));
}

/** 放行被阻塞的引擎并按条广播结算后的消息。 */
function broadcastSettled(pending: Message[]): void {
  for (const message of pending) {
    liveHub.settle(message.id, { decision: 'aborted' });
    broadcast(message.sessionId, 'message', message);
  }
}

/**
 * 顶层 run 及其子 run 的 id：优先用进程内 RunTree 已登记的 child run id，
 * 再并入按 parentRunId 收敛到的行；绝不按会话扫描，避免误伤中止后新建的顶层 run。
 */
function treeRunIds(top: RunRow, converged: RunRow[] = []): string[] {
  const ids = new Set<string>([top.id, ...(runTrees.get(top.id)?.childRuns.keys() ?? [])]);
  for (const row of converged) ids.add(row.id);
  return [...ids];
}

/** 该消息若是助手文本，取其正文；失败收口靠它判断引擎是否已把同一段错误当文本落过。 */
function assistantTextOf(message: Message | null): string | null {
  if (message?.role !== 'assistant' || message.type !== 'text') return null;
  const { text } = message.content as { text?: unknown };
  return typeof text === 'string' ? text : null;
}

/** 失败收口：已中止只落终态，否则先结算挂起、补一条 system/error，再落 failed。 */
async function failRun(input: { session: SessionRow; run: RunRow }, error: unknown, controller: AbortController): Promise<void> {
  const reason = error instanceof Error ? error.message : String(error);
  if (controller.signal.aborted) {
    await runsRepo.finish(input.run.id, 'aborted');
    return;
  }
  // 终态 run 不得残留挂起（waiting 恒 null），失败与中止走同一条结算
  await settleSessionPendings(input.session.id);
  // CLI 会把 API 错误当助手文本吐出来，result 又报同一个错：引擎已落同文时不再补 system/error，
  // 否则前端对话流里同一个错误出现两次
  const alreadyShown = assistantTextOf(await messagesRepo.lastByRun(input.run.id))?.trim() === reason.trim();
  if (!alreadyShown) {
    const message = await messagesRepo.append({
      sessionId: input.session.id,
      runId: input.run.id,
      role: 'system',
      type: 'error',
      content: { message: reason },
    });
    broadcast(input.session.id, 'message', message);
  }
  // 顺序不可反：先落错误消息再落终态，客户端查到的 failed 必然配得上一条可读的错误消息
  await runsRepo.finish(input.run.id, 'failed', reason);
}

/** 广播顶层 run 终态与兼容事件；abortRun 与 closeRun 共用，只生效一次。 */
async function broadcastRunTerminal(sessionId: string, runId: string): Promise<void> {
  if (!remember(finalizedRuns, runId)) return;
  const run = await broadcastRun(sessionId, runId, 'run.status');
  if (run && run.parentRunId === null) broadcastRunOutcome(sessionId, run);
}

/**
 * 把该顶层 run 血缘下残留的活跃子 run 收敛为 aborted，并补发 task.notified。
 *
 * 只沿 parentRunId 遍历后代：中止返回后新建的顶层 run（parentRunId 为 null）不在其中。
 * 不在 RunTree 里的后代（另一进程或注册表丢失）也由这次遍历补上。
 */
async function convergeActiveRuns(sessionId: string, topRunId: string): Promise<RunRow[]> {
  const rows = await runsRepo.abortActiveDescendants(topRunId);
  const tree = runTrees.get(topRunId);
  for (const row of rows) {
    tree?.terminal.add(row.id);
    broadcastTaskNotified(sessionId, row, 'stopped', null, null);
  }
  return rows;
}

/** 清理顶层 run 的注册表与该 run 名下所有子 run 的进程内状态。 */
function clearRunTree(topRunId: string): void {
  const tree = runTrees.get(topRunId);
  if (!tree) return;
  for (const childId of tree.childRuns.keys()) clearRunState(childId);
  runTrees.delete(topRunId);
}

/** 收尾：收敛残留子 run、结算挂起，再把 run 终态与兼容事件广播出去。 */
async function closeRun(input: { session: SessionRow; run: RunRow }): Promise<void> {
  abortControllers.delete(input.run.id);
  const converged = await convergeActiveRuns(input.session.id, input.run.id);
  // 先算会话状态：run 终态已可见，会话不能再停留在 in_progress
  await sessionsRepo.completeIfNoActiveRun(input.session.id);
  await settleRunPendings(treeRunIds(input.run, converged));
  await broadcastRunTerminal(input.session.id, input.run.id);
  clearRunState(input.run.id);
  clearRunTree(input.run.id);
  const session = await sessionsRepo.findById(input.session.id);
  if (session) broadcast(input.session.id, 'session.status', { sessionId: session.id, status: session.status });
}

/** 补会话名时的长度上限：引擎标题可能是长句，列表行只留一段 */
const SESSION_NAME_MAX = 60;

/**
 * 会话名仍为空时，用引擎侧给出的标题补上（Claude Code 的自动摘要 / 自定义名）。
 *
 * 放在 run 收口之后：会话文件此时已落盘，首轮也已经拿到 resumeSessionId。
 * 失败只记日志——补名是锦上添花，不得影响 run 终态与后续轮次。
 */
async function adoptEngineSessionName(input: {
  sessionId: string;
  /** 发消息时读到的会话名：非空直接跳过，省掉每轮的 DB 查询 */
  sessionName: string;
  cwd: string;
  adapter: EngineAdapter;
}): Promise<void> {
  try {
    if (input.sessionName !== '' || input.adapter.sessionTitle === undefined) return;
    const row = await sessionsRepo.findById(input.sessionId);
    if (!row || row.name !== '' || row.resumeSessionId === null) return;
    const title = await input.adapter.sessionTitle(row.resumeSessionId, input.cwd);
    if (title === null) return;
    const name = title.length > SESSION_NAME_MAX ? `${title.slice(0, SESSION_NAME_MAX)}…` : title;
    const updated = await sessionsRepo.nameIfEmpty(input.sessionId, name);
    if (updated) broadcast(input.sessionId, 'session.named', { sessionId: updated.id, name: updated.name });
  } catch (error) {
    console.error(`[smart-factory] 读取引擎会话标题失败（${input.sessionId}）：`, error);
  }
}

interface RunSetup {
  /** 引擎适配器工厂：绑定点在注册表，起跑时才实例化 */
  adapter: () => EngineAdapter;
  /** 阶段 cwd：development 必须已存在，preview / evaluation 先物化 */
  cwd: string;
  /** 会话绑定的模型及其运行配置，没有回落 */
  resolved: ResolvedRunModel;
}

/**
 * 解析起跑条件：引擎适配器、工作区目录/阶段 cwd、模型。
 *
 * 必须在建 run 之前完成：解析失败直接返回错误，不落 run、用户消息，也不改会话状态。
 * 业务错误原样上抛，其它异常统一收口为 502（上游工作区或模型面不可用）。
 */
async function resolveRunSetup(session: SessionRow, instance: Instance): Promise<RunSetup> {
  try {
    const adapter = resolveEngineAdapter(instance.engine);

    // 目录实例（`agentId === null`）：cwd 创建时已定，跳过工作区解析 / stage 门禁 / 物化
    // （10-skill-library.md §3.5）。工作区不可达不再影响目录会话 —— 技能库就在框架之外。
    //
    // 判据是 agentId 而不是 stage：工坊是 development、runtime 会话的 cwd 也是一个目录，
    // 用 stage 判「目录实例」会两头都错。按 `cwd !== null` 判也不行：库结构落后于代码时
    // Prisma Client 不返回该列（undefined），`undefined !== null` 会把智能体实例误判成目录实例。
    if (instance.agentId === null) {
      if (typeof instance.cwd !== 'string' || instance.cwd === '') {
        throw new BadGatewayError(
          `目录实例 ${instance.id} 缺少 cwd，数据库结构与生成的 Prisma Client 可能未同步（prisma generate / scripts/db.mjs sync）`,
        );
      }
      const resolved = await resolveRunModel(session.modelId);
      return { adapter, cwd: instance.cwd, resolved };
    }
    // 智能体实例必有非空 agentId（instances.repo 两个入口保证的不变量）。`undefined` 只可能来自
    // 结构漂移（库里有列、生成的 client 没有）：明确报 502，不要带着 undefined 去解析工作区。
    if (typeof instance.agentId !== 'string' || instance.agentId === '') {
      throw new BadGatewayError(
        `实例 ${instance.id} 缺少 agentId，数据库结构与生成的 Prisma Client 可能未同步（prisma generate / scripts/db.mjs sync）`,
      );
    }
    const workspace = await resolveAgentWorkspace(instance.agentId);

    // 重建期不进其它阶段：development 正在跑时产物可能正被改写，
    // 旧状态/旧产物不能作为 preview / runtime / evaluation 的起跑依据
    if (instance.stage !== 'development') {
      const development = await instancesRepo.findByAgentAndStage(instance.agentId, 'development');
      if (development !== null && (await runsRepo.hasActiveIn([development.id]))) {
        throw new ConflictError(STAGE_GUARD_MESSAGES.developmentBusy, 'error.conflict.active_run');
      }
    } else {
      // 反向守卫：runtime 正在读取 development 产物树，重新生成会改写它正在使用的文件
      const runtime = await instancesRepo.findByAgentAndStage(instance.agentId, 'runtime');
      if (runtime !== null && (await runsRepo.hasActiveIn([runtime.id]))) {
        throw new ConflictError(STAGE_GUARD_MESSAGES.runtimeBusy, 'error.conflict.active_run');
      }
    }

    // 内置智能体：cwd 就是定义目录本身，完全跳过 stageDir / 产物定位 / 物化。
    // 定义目录随产品分发（data/ 是它自己的运行数据区），没有产物生产线。
    let cwd: string;
    if (workspace.source === 'builtin') {
      if (instance.stage !== 'runtime') throw new ConflictError(`内置智能体只支持 runtime 会话：${instance.stage}`, 'error.conflict.builtin_agent');
      cwd = workspace.directory;
    } else {
      cwd = resolveStageCwd(agentRoot(workspace.directory, instance.agentId), instance.stage);
    }
    const resolved = await resolveRunModel(session.modelId);
    return { adapter, cwd, resolved };
  } catch (error) {
    if (error instanceof AppError) throw error;
    throw new BadGatewayError(error instanceof Error ? error.message : String(error));
  }
}

/**
 * 驱动一次运行：起跑条件（适配器、cwd、模型）由 `sendMessage` 解析并传入，
 * 这里只负责驱动引擎与收口：run 落终态、会话重算。
 *
 * 中止句柄由调用方建好并注册（见 `sendMessage`），驱动链只负责用它。
 */
async function driveRun(
  input: {
    session: SessionRow;
    instance: Instance;
    run: RunRow;
    prompt: string;
    adapter: () => EngineAdapter;
    cwd: string;
    model: EngineModel;
  },
  controller: AbortController,
): Promise<void> {
  try {
    // 中止先于引擎启动：不实例化适配器，run 已由 abortRun 落终态，由 finally 收口
    if (controller.signal.aborted) return;
    // 引擎可能是在被中止后才返回的（挂起被放行），此时终态必须是 aborted
    const { output } = await input.adapter().run(buildEngineContext(input, input.cwd, input.model, controller));
    runOutputs.set(input.run.id, output ?? '');
    await runsRepo.finish(input.run.id, controller.signal.aborted ? 'aborted' : 'succeeded');
  } catch (error) {
    await failRun(input, error, controller);
  } finally {
    await closeRun(input);
    // 收口之后再补名：会话文件已落盘，首轮的 resumeSessionId 也已由 onSessionId 落库
    await adoptEngineSessionName({
      sessionId: input.session.id,
      sessionName: input.session.name,
      cwd: input.cwd,
      adapter: input.adapter(),
    });
  }
}

export interface CreateSessionInput {
  agentId?: unknown;
  /** 目录形态：绝对路径、必须存在且是目录；与 `agentId` 恰好给一个。 */
  cwd?: unknown;
  stage?: unknown;
  name?: unknown;
  modelId?: unknown;
  /**
   * 建会话前先清空该阶段的沙箱（「重新开始预览」/「重新评估」用），只支持
   * `preview` / `evaluation`。评估的旧报告在沙箱根下，会一起删掉。
   */
  resetSandbox?: unknown;
}

/** REST 更新只收 modelId；mode / effort 走 switch*（下个 run 生效）。身份走路径（照 agents/:agentId/update）。 */
export interface UpdateSessionInput {
  modelId?: unknown;
}

/** 「字段给过了」判定（照 agent.service 的 given）：null 算没给。 */
function given(value: unknown): boolean {
  return value !== undefined && value !== null;
}

/** ISO 8601 日期时间：必须 T 分隔且带 Z 或时区偏移，日期分量按日历校验。 */
const ISO_DATE_TIME = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/;

/** 会话列表的 ISO 日期时间参数：非法值 400，并回显字段名。 */
function readDateTime(value: unknown, name: 'createdFrom' | 'createdTo'): Date | undefined {
  const text = optionalString(value);
  if (text === undefined) return undefined;
  const match = ISO_DATE_TIME.exec(text);
  const parsed = match ? new Date(text) : null;
  if (!match || !parsed || Number.isNaN(parsed.getTime()) || !calendarDateValid(match)) {
    throw new BadRequestError(`${name} 不是合法的日期时间`);
  }
  return parsed;
}

/** 日历校验：拒绝 2026-02-30 这类被 Date 自动进位的日期，以及越界的时分秒。 */
function calendarDateValid(match: RegExpExecArray): boolean {
  const [, year, month, day, hour, minute, second = '00'] = match;
  const y = Number(year);
  const m = Number(month);
  const d = Number(day);
  const probe = new Date(0);
  probe.setUTCFullYear(y, m - 1, d);
  probe.setUTCHours(0, 0, 0, 0);
  return (
    probe.getUTCFullYear() === y &&
    probe.getUTCMonth() === m - 1 &&
    probe.getUTCDate() === d &&
    Number(hour) <= 23 &&
    Number(minute) <= 59 &&
    Number(second) <= 59
  );
}

/** 会话状态过滤：逗号分隔多值，任一非法即 400。 */
function readSessionStatuses(value: unknown): SessionStatus[] | undefined {
  const values = csvStrings(value);
  if (!values) return undefined;
  return values.map((item) => requireEnum(item, SESSION_STATUSES, 'status'));
}

/** 阶段别名过滤：逗号分隔多值，`all` 表示不按阶段过滤。 */
function readSessionTypes(value: unknown): Array<InstanceStage | 'all'> | undefined {
  const values = csvStrings(value);
  if (!values) return undefined;
  return values.map((item) => requireEnum(item, SESSION_TYPES, 'type'));
}

/** 正文允许为空**当且仅当**带了附件：类型不对当场 400，空串交给调用点联合判定。 */
function readPrompt(value: unknown): string {
  if (value === undefined || value === null) return '';
  if (typeof value !== 'string') throw new BadRequestError('prompt 必须是字符串', 'error.bad_request.prompt_string');
  return value;
}

/**
 * 附件入参 → 落库 / 渲染形状。
 *
 * 形态与路径校验统一走 `resolveAttachmentPaths`（`shared/workspace/local-path`）：
 * 绝对路径、存在、是文件（不限制目录）—— 与文件选择器、`agents/create` 的
 * `init.attachments` 共用同一份实现，不各写一套。
 */
async function readAttachments(value: unknown): Promise<MessageFile[]> {
  const paths = await resolveAttachmentPaths(value);
  return paths.map((path, index) => ({ id: `file-${index + 1}`, name: path }));
}

/**
 * 附件只在**引擎那一侧**展开成文本。
 *
 * 落库的正文保持用户原话：附件是消息的结构化字段（`content.files`），
 * 拼进正文等于把展示层格式烧进历史，之后想换渲染方式就得改数据。
 */
function promptWithAttachments(prompt: string, files: MessageFile[]): string {
  if (files.length === 0) return prompt;
  const list = files.map((file) => `- ${file.name}`).join('\n');
  const head = prompt.trim() === '' ? '' : `${prompt}\n\n`;
  return `${head}以下是用户指定的本机文件，请直接用 Read 工具读取：\n${list}`;
}

export interface SendMessageInput {
  sessionId?: unknown;
  agentId?: unknown;
  prompt?: unknown;
  /** 本机文件：`[{ path }]` 或裸路径字符串；只有附件、没有正文也发得出去 */
  attachments?: unknown;
  /** 新建会话（agentId / 自由对话）绑定的模型 id，必填非空；续聊不接受。 */
  modelId?: unknown;
  /** 新建会话的审批模式，缺省 workspace_write；续聊不接受。 */
  mode?: unknown;
  /** 新建会话的推理强度，缺省 high；续聊不接受。 */
  effort?: unknown;
  /** 建 run 成功、用户消息落库前回调；WS 网关借此先订阅再收事件。 */
  onSessionResolved?: (sessionId: string) => void;
}

export interface SendMessageResult {
  sessionId: string;
  runId: string;
  instanceId: string;
  /** run 在返回时已进入 running（起跑条件已解析完） */
  status: 'running';
  effort: SessionEffort;
  modelId: string;
  modelName: string;
  /** 本服务不做模型回落，恒为 false；字段与 agent-runtime 对齐 */
  modelFellBack: false;
  message: Message;
  run: Run;
}

/**
 * 发送目标三种形态，`sessionId` / `agentId` 至多给一个：
 *
 * - `sessionId`：直取已有会话续聊，拒绝 agentId / modelId / mode / effort；
 * - `agentId`：每次新建一条 runtime 会话，绝不复用；
 * - 都不给：自由对话（不选智能体），每次新建一条目录会话，cwd 由 `resolveChatCwd` 决定。
 *
 * 后两种是新建会话，要求非空 modelId；mode / effort 缺省 workspace_write / high，落到新会话。
 */
async function resolveSendTarget(
  input: SendMessageInput,
): Promise<{ session: SessionRow; instance: Instance; created: boolean }> {
  if (given(input.sessionId)) {
    // 按字段是否出现判定：显式 null 也算出现，与 WS 的校验口径一致
    for (const field of ['agentId', 'modelId', 'mode', 'effort'] as const) {
      if (input[field] !== undefined) throw new BadRequestError(`send { sessionId } 不接受 ${field}`);
    }
    const sessionId = requireString(input.sessionId, 'sessionId');
    const session = await sessionsRepo.findById(sessionId);
    if (!session) throw new NotFoundError(`会话 ${sessionId}`, 'error.not_found.session', { sessionId });
    const instance = await instancesRepo.findById(session.instanceId);
    if (!instance) throw new NotFoundError(`实例 ${session.instanceId}`, 'error.not_found.instance', { instanceId: session.instanceId });
    return { session, instance, created: false };
  }

  if (!given(input.agentId)) return createChatSession(input);

  const agentId = input.agentId;
  assertAgentId(agentId);
  // agents 表是智能体存在的唯一权威：未知 id 不得先建出实例与会话再等 run 失败
  if (!(await agentsRepo.exists(agentId))) throw new NotFoundError(`智能体 ${agentId}`, 'error.not_found.agent', { agentId });

  const modelId = requireString(input.modelId, 'modelId');
  const mode = requireEnum(input.mode, SESSION_MODES, 'mode', 'workspace_write');
  const effort = requireEnum(input.effort, SESSION_EFFORTS, 'effort', 'high');
  await assertModelRunnable(modelId, 'modelId');

  const instance = await instancesRepo.getOrCreate(agentId, 'runtime');
  const session = await sessionsRepo.create({
    instanceId: instance.id,
    modelId,
    approvalMode: mode,
    effort,
  });
  return { session, instance, created: true };
}

/**
 * 自由对话：既没有会话也没有智能体时，落到一条目录会话上。
 *
 * 与 `agentId` 分支的区别只有 cwd —— 这里不查 agents 表、不碰产物；
 * 会话建好之后与 agent 会话共用同一条起跑 / 事件 / 审批链路（`resolveRunSetup` 按
 * `agentId === null` 分流的目录实例分支）。
 */
async function createChatSession(
  input: SendMessageInput,
): Promise<{ session: SessionRow; instance: Instance; created: true }> {
  const modelId = requireString(input.modelId, 'modelId');
  const mode = requireEnum(input.mode, SESSION_MODES, 'mode', 'workspace_write');
  const effort = requireEnum(input.effort, SESSION_EFFORTS, 'effort', 'high');
  await assertModelRunnable(modelId, 'modelId');

  // 自由对话是运行时聊天，不是开发流程：stage=runtime，默认的「历史运行会话」里能看到
  const instance = await instancesRepo.getOrCreateByCwd(await resolveChatCwd(), 'runtime');
  const session = await sessionsRepo.create({
    instanceId: instance.id,
    modelId,
    approvalMode: mode,
    effort,
  });
  return { session, instance, created: true };
}

/**
 * 自由对话的 cwd：框架当前生效工作区的目录；没有生效工作区时落到 `config.chatRoot`（按需创建）。
 *
 * 工作区存在但未绑目录 / 框架不可达都按 502 上抛，不悄悄换成兜底目录 ——
 * 「有工作区却用不了」和「本来就没有工作区」是两回事。
 *
 * 兜底目录落 realpath：与 `sessions/create { cwd }` 的口径一致，避免 symlink 让同一个目录
 * 落下两条实例。
 */
async function resolveChatCwd(): Promise<string> {
  const list = await fetchWorkspaces();
  if (list.activeId !== null) return resolveWorkspaceDirectory(list.activeId);
  mkdirSync(config.chatRoot, { recursive: true });
  return realpathSync(config.chatRoot);
}

interface PreparedSend {
  session: SessionRow;
  instance: Instance;
  run: RunRow;
  setup: RunSetup;
  /** 内部标记：本次 send 是否新建了会话；只用于失败清理，不进响应 */
  created: boolean;
}

/**
 * 解析发送目标并抢到活跃 run 名额。
 *
 * 只读预检的仲裁粒度按阶段区分：runtime 是 session（同一 agent 的不同会话可并发各起一个），
 * 其他阶段是 instance。
 */
async function prepareSend(input: SendMessageInput): Promise<PreparedSend> {
  const { session, instance, created } = await resolveSendTarget(input);
  try {
    // 只读预检：解析里的 preview / evaluation 物化会清空目标目录，不能先动盘再等事务仲裁
    if (instance.stage === 'runtime') {
      if (await runsRepo.findActiveTopBySession(session.id)) {
        throw new ConflictError(`会话 ${session.id} 已有活跃 run`, 'error.conflict.active_run', { sessionId: session.id });
      }
    } else if (await runsRepo.findActiveByInstance(instance.id)) {
      throw new ConflictError(`实例 ${instance.id} 已有活跃 run`, 'error.conflict.active_run', { instanceId: instance.id });
    }

    // 起跑条件解析先于建 run：失败直接返回错误，不留 run、用户消息与会话状态变更
    const setup = await resolveRunSetup(session, instance);

    // 活跃 run 的仲裁只有这一个入口：runtime 由 session 唯一约束兜底，其他阶段由 instance 唯一约束兜底
    const run = await runsRepo.createActiveRun({ sessionId: session.id, instanceId: instance.id, status: 'running' });

    // 抢到名额后再通知订阅：清理路径不会把已删除的会话推给网关
    input.onSessionResolved?.(session.id);
    return { session, instance, run, setup, created };
  } catch (error) {
    // 本次新建且未投入使用的会话不得留下，否则会污染实例上的会话列表
    if (created) await discardUnusedSession(session.id);
    throw error;
  }
}

/**
 * 首帧新建但未投入使用的会话：直接级联删除，清理失败只记日志。
 *
 * 该会话只在本请求内可见；失败分支早于用户消息落库，run 若已建也随会话级联删除。
 */
async function discardUnusedSession(sessionId: string): Promise<void> {
  try {
    await sessionsRepo.deleteCascade(sessionId);
  } catch (error) {
    console.error(`[smart-factory] 清理未使用的会话 ${sessionId} 失败：`, error);
  }
}

/** 会话设置变更广播：WS 切换与 REST 更新共用，只有模型切换带 appliesTo。 */
function broadcastSettingsChanged(session: SessionRow, channel: 'ws' | 'http', appliesToNextRun: boolean): void {
  broadcast(session.id, 'settings.changed', {
    sessionId: session.id,
    settings: { mode: session.approvalMode, effort: session.effort, modelId: session.modelId },
    changedBy: { channel, actorId: '' },
    ...(appliesToNextRun ? { appliesTo: 'nextRun' } : {}),
    at: session.updatedAt,
  });
}

/** 下个 run 生效的字段切换：活跃 run 不拦，只改库里的会话字段。 */
async function switchSessionField(sessionId: unknown, patch: SessionUpdateData): Promise<Session> {
  const id = requireString(sessionId, 'sessionId');
  const row = await sessionsRepo.findById(id);
  if (!row) throw new NotFoundError(`会话 ${id}`, 'error.not_found.session', { sessionId: id });
  const updated = await sessionsRepo.update(id, patch);
  if (!updated) throw new NotFoundError(`会话 ${id}`, 'error.not_found.session', { sessionId: id });
  const session = (await hydrateSessions([updated], false))[0]!;
  broadcastSettingsChanged(updated, 'ws', patch.modelId !== undefined);
  return session;
}

export interface SessionListQuery {
  agentId?: unknown;
  /** 目录会话按实例 cwd 精确过滤；绝对路径否则 400，与 agentId / stage 取交集。 */
  cwd?: unknown;
  /** 主体类型，只接受 `agent`（agent-runtime 对齐参数）。 */
  subjectType?: unknown;
  /** `agentId` 的别名；与 `agentId` 同时给出时以本参数为准，取值不同则 400。 */
  subjectId?: unknown;
  instanceId?: unknown;
  stage?: unknown;
  /** `stage` 的逗号分隔别名，或 `all`；`all` 取消阶段过滤。 */
  type?: unknown;
  /** 逗号分隔的会话状态。 */
  status?: unknown;
  name?: unknown;
  /** 逗号分隔的会话 id。 */
  id?: unknown;
  /** 引擎 resume 标识；支持逗号分隔多值，用于 resumeSessionId -> sessionId 反查。 */
  resumeSessionId?: unknown;
  createdFrom?: unknown;
  createdTo?: unknown;
  page?: unknown;
  pageSize?: unknown;
}

export interface MessageListQuery {
  sessionId?: unknown;
  runId?: unknown;
  afterSeq?: unknown;
  beforeSeq?: unknown;
  limit?: unknown;
  status?: unknown;
}

export interface HistoryQuery {
  sessionId?: unknown;
  limit?: unknown;
  offset?: unknown;
  /** 商用客户端的遥测开关：当前没有遥测消息，入参不影响结果。 */
  includeTelemetry?: unknown;
}

export const sessionService = {
  /**
   * 建会话：两种形态互斥（10-skill-library.md §3.4）。
   *
   * - `agentId` 形态：`(agentId, stage)` get-or-create 实例；不解析工作区目录、不物化、不碰磁盘。
   *   `agents` 表是智能体存在的唯一权威，所以先查表：未知 agentId 一律 404，
   *   不再是「顺着字符串建目录」（08-agent.md §1）。
   * - `cwd` 形态：目录实例（`agentId = null`、`stage = 'development'`）。路径统一走
   *   `resolveLocalTarget`（绝对路径、存在、是目录、realpath 后落库）；不查 agents 表、
   *   不查内置、不物化 —— 工坊目录在框架之外。
   *
   * `modelId` 必填非空并校验可运行（存在、anthropic 协议、已配密钥）。默认模型由调用方
   * （Web / viewer）自己解析后显式传入，服务端不猜、不回落。对照组是 `sessions/list?agentId=` -
   * 那是过滤不是取数，面对未知 id 返回空页。
   */
  async createSession(input: CreateSessionInput): Promise<Session> {
    // `agentId` 与 `cwd` 恰给一个：同时给或都不给一律 400
    const hasAgent = given(input.agentId);
    const hasCwd = given(input.cwd);
    if (hasCwd === hasAgent) {
      throw new BadRequestError('agentId 与 cwd 必须给且只给一个', 'error.bad_request.agent_or_cwd');
    }
    const name = optionalString(input.name) ?? '';

    if (hasCwd) {
      const cwd = resolveLocalTarget(input.cwd, 'dir');
      const modelId = requireString(input.modelId, 'modelId');
      await assertModelRunnable(modelId, 'modelId');

      // 目录形态固定是开发阶段（技能工坊：创建 / 优化技能）
      const instance = await instancesRepo.getOrCreateByCwd(cwd, 'development');
      // dir 非 runtime：实例级仲裁，至多一个活跃顶层 run（免费继承非 runtime 索引）
      if (await runsRepo.findActiveByInstance(instance.id)) {
        throw new ConflictError(`实例 ${instance.id} 已有活跃 run`, 'error.conflict.active_run', { instanceId: instance.id });
      }

      const row = await sessionsRepo.create({ instanceId: instance.id, name, modelId });
      // 新会话还没有消息：派生字段直接给零值，不必再查库
      return { ...row, instance, messageCount: 0, lastMessage: null, firstUserMessage: null };
    }

    const stage = requireEnum(input.stage, AGENT_STAGES, 'stage', 'development');
    assertAgentId(input.agentId);
    const modelId = requireString(input.modelId, 'modelId');

    if (input.resetSandbox !== undefined && typeof input.resetSandbox !== 'boolean') {
      throw new BadRequestError('resetSandbox 必须是布尔值');
    }
    const resetSandbox = input.resetSandbox === true;
    /** 能重建沙箱的阶段；`resetSandbox` 时它必须非 null，否则 400 */
    const resettableStage = stage === 'preview' || stage === 'evaluation' ? stage : null;
    if (resetSandbox && resettableStage === null) {
      throw new BadRequestError(`resetSandbox 只支持 preview / evaluation 阶段：${stage}`);
    }

    if (!(await agentsRepo.exists(input.agentId))) throw new NotFoundError(`智能体 ${input.agentId}`, 'error.not_found.agent', { agentId: input.agentId });
    // 内置智能体没有产物生产线，四态里只认 runtime（默认值 development 同样被拦）
    if (stage !== 'runtime') {
      const agent = await agentsRepo.findById(input.agentId);
      if (agent?.source === 'builtin') throw new ConflictError(`内置智能体只支持 runtime 会话：${stage}`, 'error.conflict.builtin_agent', { agentId: input.agentId, stage });
    }
    await assertModelRunnable(modelId, 'modelId');

    const instance = await instancesRepo.getOrCreate(input.agentId, stage);
    // runtime 以 session 为仲裁粒度，实例上已有活跃 run 不妨碍新建会话；
    // 其他阶段实例至多一个活跃顶层 run
    if (stage !== 'runtime' && (await runsRepo.findActiveByInstance(instance.id))) {
      throw new ConflictError(`实例 ${instance.id} 已有活跃 run`, 'error.conflict.active_run', { instanceId: instance.id });
    }

    /*
     * 「重新评估 / 重新开始预览」重建沙箱：删掉该阶段整个目录（评估的旧报告就在沙箱
     * 根下），下一次 run 前的物化会整体重拷。必须排在活跃 run 检查之后 —— 正跑着的
     * 沙箱不能删；409 退回旧会话时也走不到这里，旧沙箱与旧报告自然保留。
     */
    if (resetSandbox && resettableStage !== null) {
      resetStage(await resolveAgentRoot(input.agentId), resettableStage);
    }

    const row = await sessionsRepo.create({ instanceId: instance.id, name, modelId });
    // 新会话还没有消息：派生字段直接给零值，不必再查库
    return { ...row, instance, messageCount: 0, lastMessage: null, firstUserMessage: null };
  },

  /**
   * 切换会话模型：run 间隙生效，正跑的 run 不受影响。
   *
   * 活跃 run 存续时拒绝：run 的模型在启动时读定，中途改值会让「这轮用的哪个模型」说不清；
   * modelId 必填非空且必须可运行，不支持清空。
   */
  async updateSession(sessionId: string, input: UpdateSessionInput): Promise<Session> {
    const row = await sessionsRepo.findById(sessionId);
    if (!row) throw new NotFoundError(`会话 ${sessionId}`, 'error.not_found.session', { sessionId });
    const modelId = requireString(input.modelId, 'modelId');
    await assertModelRunnable(modelId, 'modelId');

    const instance = await instancesRepo.findById(row.instanceId);
    if (!instance) throw new NotFoundError(`实例 ${row.instanceId}`, 'error.not_found.instance', { instanceId: row.instanceId });
    if (await runsRepo.findActiveBySession(row.id)) throw new ConflictError(`会话 ${row.id} 已有活跃 run`, 'error.conflict.active_run', { sessionId: row.id });

    const updated = await sessionsRepo.update(row.id, { modelId });
    if (!updated) throw new NotFoundError(`会话 ${sessionId}`, 'error.not_found.session', { sessionId });
    broadcastSettingsChanged(updated, 'http', true);
    return (await hydrateSessions([updated], false))[0]!;
  },

  async listSessions(query: SessionListQuery): Promise<PageResult<Session>> {
    const { page, pageSize } = pageParams(query.page, query.pageSize);

    const subjectType = optionalString(query.subjectType);
    if (subjectType !== undefined && subjectType !== 'agent') {
      throw new BadRequestError(`subjectType 只支持 agent：${JSON.stringify(subjectType)}`);
    }
    const agentIdParam = optionalString(query.agentId);
    const subjectId = optionalString(query.subjectId);
    if (agentIdParam) assertAgentId(agentIdParam);
    if (subjectId) assertAgentId(subjectId);
    if (agentIdParam && subjectId && agentIdParam !== subjectId) {
      throw new BadRequestError('agentId 与 subjectId 不一致');
    }
    const agentId = subjectId ?? agentIdParam;

    // 目录会话过滤：只要绝对路径形态（存在与否交给空结果，与 agentId 同为「过滤不是取数」）
    const cwd = optionalString(query.cwd);
    if (cwd !== undefined && !isAbsolute(cwd)) {
      throw new BadRequestError('cwd 必须是绝对路径');
    }

    const stage = optionalString(query.stage) === undefined ? undefined : requireEnum(query.stage, STAGES, 'stage');
    const types = readSessionTypes(query.type);
    const instanceId = optionalString(query.instanceId);
    const ids = csvStrings(query.id);
    const resumeSessionIds = csvStrings(query.resumeSessionId);

    /*
     * 默认只看运行会话（runtime），与 agent-runtime 在「无精确定位参数」时的口径一致。
     *
     * 例外是**精确定位参数**：调用方给了 instanceId / cwd / id / resumeSessionId，说明它在找
     * 具体的某一场（某个实例、某个目录、按会话 id 或引擎标识反查），这时不能套默认阶段，
     * 否则 development / preview / evaluation 的会话会被悄悄筛掉。
     *
     * `agentId` 只是过滤、不定位，**不**取消默认：`?agentId=` 返回该智能体的 runtime 会话；
     * 要看其它阶段必须显式给 `stage` / `type`，或者用 `instanceId`。
     */
    const located =
      instanceId !== undefined || cwd !== undefined || ids !== undefined || resumeSessionIds !== undefined;

    let stages: InstanceStage[] | undefined;
    if (types !== undefined) {
      // all 吸收其余值，取消阶段过滤；否则 type 必须覆盖同时给出的 stage
      const all = types.includes('all');
      if (!all && stage !== undefined && !types.includes(stage)) {
        throw new BadRequestError(`type 未包含 stage：${stage}`);
      }
      stages = all ? undefined : types.filter((item): item is InstanceStage => item !== 'all');
    } else if (stage !== undefined) {
      stages = [stage];
    } else if (!located) {
      stages = ['runtime'];
    }

    const result = await sessionsRepo.list({
      agentId,
      // subjectType=agent 语义：只命中智能体实例。自由对话是目录实例（agentId=null），
      // stage 也是 runtime，不排除的话会混进任务中心的「智能体会话」列表。
      agentOnly: subjectType === 'agent',
      cwd,
      stages,
      instanceId,
      statuses: readSessionStatuses(query.status),
      name: optionalString(query.name),
      ids,
      resumeSessionIds,
      createdFrom: readDateTime(query.createdFrom, 'createdFrom'),
      createdTo: readDateTime(query.createdTo, 'createdTo'),
      page,
      pageSize,
    });
    return { items: await hydrateSessions(result.items, true), total: result.total, page, pageSize };
  },

  async getSession(sessionId: string): Promise<Session> {
    const row = await sessionsRepo.findById(sessionId);
    if (!row) throw new NotFoundError(`会话 ${sessionId}`, 'error.not_found.session', { sessionId });
    return (await hydrateSessions([row], false))[0]!;
  },

  /** 订阅握手：会话不存在回 null；否则给出状态快照与当前挂起的兼容帧，由网关补发。 */
  async subscribeInfo(sessionId: string): Promise<SubscribeInfo | null> {
    const session = await sessionsRepo.findById(sessionId);
    if (!session) return null;
    // 挂起天然很少：0 游标 + 分页上限即等价于「全部挂起」
    const pending = await messagesRepo.list({ sessionId, status: 'pending', afterSeq: 0, limit: MESSAGE_LIMIT_MAX });
    const frames: SubscribeInfo['pending'] = [];
    for (const message of pending.items) {
      const run = message.runId ? await runsRepo.findById(message.runId) : null;
      const frame = pendingFrameOf(message, run?.parentRunId ?? null);
      if (frame) frames.push(frame);
    }
    return { status: session.status, pending: frames };
  },

  /** 删会话：404 先行；活跃 run 的检查与级联删除由同一事务内的 deleteCascadeIfIdle 裁决。 */
  async deleteSession(sessionId: string): Promise<void> {
    const row = await sessionsRepo.findById(sessionId);
    if (!row) throw new NotFoundError(`会话 ${sessionId}`, 'error.not_found.session', { sessionId });
    await sessionsRepo.deleteCascadeIfIdle(sessionId);
  },

  /**
   * 发消息并起 run：sessionId 续聊已有会话；agentId 每次新建 runtime 会话；
   * 两者都不给是自由对话（不选智能体），每次新建一条目录会话。
   * 再解析起跑条件（适配器、cwd、模型），建 running run 抢仲裁、落 user 消息，
   * 广播 run.started 后返回，引擎在后台异步启动。
   */
  async sendMessage(input: SendMessageInput): Promise<SendMessageResult> {
    const bySession = given(input.sessionId);
    const byAgent = given(input.agentId);
    // 至多给一个：都给是调用方错误；都不给按自由对话处理（4.06 实时通道 send）
    if (bySession && byAgent) throw new BadRequestError('sessionId 与 agentId 不能同时给', 'error.bad_request.session_or_agent');
    // 正文与附件在**任何副作用之前**校验完：附件路径不合法时不建 run、不落消息、不建会话
    const prompt = readPrompt(input.prompt);
    const attachments = await readAttachments(input.attachments);
    if (prompt.trim() === '' && attachments.length === 0) {
      throw new BadRequestError('prompt 必填', 'error.bad_request.prompt_required');
    }
    // 新建会话的两条分支（agentId / 自由对话）各自新建一条会话，并发首帧由数据库约束各自放行
    const prepared = await prepareSend(input);
    const { session, instance, run, setup, created } = prepared;
    const { adapter, cwd, resolved } = setup;
    // 子 run 注册表随顶层 run 建立，closeRun 时清理
    runTreeOf(run);

    // 中止句柄先于响应注册：send 一返回，runs/abort 就必须能中上，不留 409 窗口
    const controller = new AbortController();
    abortControllers.set(run.id, controller);

    let message: Message;
    let messagePersisted = false;
    let runStarted = false;
    try {
      // 附件是这条消息的结构化字段：落库、广播、历史读回都带着它，刷新后 chip 还在
      message = await messagesRepo.append({
        sessionId: session.id,
        role: 'user',
        type: 'text',
        content: attachments.length === 0 ? { text: prompt } : { text: prompt, files: attachments },
      });
      messagePersisted = true;
      broadcast(session.id, 'message', message);
      await sessionsRepo.markInProgress(session.id);
      broadcast(session.id, 'session.status', { sessionId: session.id, status: 'in_progress' });

      // run.started 在返回前广播；已中止或已落终态的 run 不发（broadcastRun 复判 running）
      if (!controller.signal.aborted) {
        runStarted = (await broadcastRun(session.id, run.id, 'run.started')) !== null;
      }
    } catch (error) {
      abortControllers.delete(run.id);
      runTrees.delete(run.id);
      if (created && !messagePersisted) {
        // 新会话还没落用户消息：整体删除，run 一并级联清理
        await discardUnusedSession(session.id);
      } else {
        // 起跑前的失败不得留下没有驱动链的活跃 run
        await runsRepo.finish(run.id, 'failed', error instanceof Error ? error.message : String(error));
        // 已广播 run.started 的订阅者必须看到终态与 chat.error，否则永远停在 running
        if (runStarted) await broadcastRunTerminal(session.id, run.id);
        // 消息或会话状态可能已广播：收口并只广播真实变化
        await settleSessionStatus(session.id);
      }
      throw error;
    }

    // 后台驱动链兜底：异常只记日志，不得外泄为未处理拒绝（例如关服时在途查询被断开）
    // 引擎看到的是正文 + 附件清单；落库的那条仍是干净的用户原话（见 promptWithAttachments）
    // 句柄落表（不是 `void`）：中止之后还有人要等引擎真正退出（删智能体，见 awaitRunStopped）
    drivePromises.set(
      run.id,
      driveRun(
        { session, instance, run, prompt: promptWithAttachments(prompt, attachments), adapter, cwd, model: resolved.config },
        controller,
      )
        .catch((error) => {
          console.error(`[smart-factory] run ${run.id} 驱动链异常：`, error);
        })
        .finally(() => drivePromises.delete(run.id)),
    );

    return {
      sessionId: session.id,
      runId: run.id,
      instanceId: instance.id,
      status: 'running',
      effort: session.effort,
      modelId: resolved.modelId,
      modelName: resolved.config.modelName,
      modelFellBack: false,
      message,
      run: { ...run, waiting: null },
    };
  },

  /** 切换会话模型（下个 run 生效）：活跃 run 存续时也允许，正跑的 run 不受影响。 */
  async switchModel(input: { sessionId?: unknown; modelId?: unknown }): Promise<Session> {
    const modelId = requireString(input.modelId, 'modelId');
    await assertModelRunnable(modelId, 'modelId');
    return switchSessionField(input.sessionId, { modelId });
  },

  /** 切换审批模式（下个 run 生效）：活跃 run 存续时也允许；非 full_access 会复位 approvedAll。 */
  async switchMode(input: { sessionId?: unknown; mode?: unknown }): Promise<Session> {
    const approvalMode = requireEnum(input.mode, SESSION_MODES, 'mode');
    return switchSessionField(input.sessionId, {
      approvalMode,
      // 切到 full_access 不会自动置真：只有用户的 approved_all 决策会
      ...(approvalMode === 'full_access' ? {} : { approvedAll: false }),
    });
  },

  /** 切换推理强度（下个 run 生效）：活跃 run 存续时也允许。 */
  async switchEffort(input: { sessionId?: unknown; effort?: unknown }): Promise<Session> {
    return switchSessionField(input.sessionId, { effort: requireEnum(input.effort, SESSION_EFFORTS, 'effort') });
  },

  /**
   * 结算一条挂起（审批或交互）。
   *
   * 载荷与消息 `type` 不匹配 → 400；消息不存在或不是交互类 → 404；已结算 → 409。
   */
  async respondMessage(input: { messageId?: unknown; decision?: unknown; answers?: unknown }): Promise<Message> {
    const messageId = requireString(input.messageId, 'messageId');
    const message = await messagesRepo.findById(messageId);
    if (!message || (message.type !== 'approval' && message.type !== 'tool_interactive')) {
      throw new NotFoundError(`待结算的消息 ${messageId}`, 'error.not_found.message', { messageId });
    }
    if (message.status !== 'pending') throw new ConflictError(`消息 ${messageId} 已结算`, 'error.conflict.message_settled', { messageId });

    let status: MessageStatus;
    let patch: Partial<MessageContent> & {
      decision?: ApprovalDecision;
      decisionSource?: DecisionSource;
      answers?: Record<string, string[]>;
    };

    if (message.type === 'approval') {
      const decision = requireEnum(input.decision, ['approved', 'approved_all', 'rejected'] as const, 'decision');
      status = decision;
      patch = { decision, decisionSource: 'user' };
    } else {
      status = 'answered';
      patch = { answers: answersParam(input.answers) };
    }

    const settled = await messagesRepo.settlePending(messageId, { status, content: patch });
    if (!settled) throw new ConflictError(`消息 ${messageId} 已结算`, 'error.conflict.message_settled', { messageId });

    // 抢到仲裁才置「允许所有」：会话级开关，后续 run 继承；写失败只记日志，不影响本次应答
    if (patch.decision === 'approved_all') {
      try {
        await sessionsRepo.update(message.sessionId, { approvalMode: 'full_access', approvedAll: true });
      } catch (error) {
        console.error(`[smart-factory] 会话 ${message.sessionId} 写 approvedAll 失败：`, error);
      }
    }

    liveHub.settle(messageId, { decision: patch.decision, answers: patch.answers });
    broadcast(message.sessionId, 'message', settled);
    return settled;
  },

  /** 兼容审批应答：`approvalId` 即审批消息 id，校验与结算走同一条 `respondMessage`。 */
  async respondApproval(input: { approvalId?: unknown; decision?: unknown }): Promise<Message> {
    return this.respondMessage({ messageId: input.approvalId, decision: input.decision });
  },

  /** 兼容工具应答：按 `toolCallId` 找到待应答交互，answers 归一后走 `respondMessage`。 */
  async respondTool(input: { toolCallId?: unknown; answers?: unknown }): Promise<Message> {
    const toolCallId = requireString(input.toolCallId, 'toolCallId');
    const pending = await messagesRepo.findPendingInteractiveByToolCallId(toolCallId);
    if (!pending) throw new NotFoundError(`待应答的交互 ${toolCallId}`, 'error.not_found.interaction', { toolCallId });
    return this.respondMessage({ messageId: pending.id, answers: normalizeToolAnswers(input.answers) });
  },

  /** 兼容历史：最近 limit 条里跳过最新 offset 条，content 拍平成字符串。 */
  async history(input: HistoryQuery): Promise<HistoryResult> {
    const sessionId = requireString(input.sessionId, 'sessionId');
    if (!(await sessionsRepo.findById(sessionId))) throw new NotFoundError(`会话 ${sessionId}`, 'error.not_found.session', { sessionId });

    const [items, total] = await Promise.all([
      messagesRepo.listRecent({
        sessionId,
        limit: limitParam(input.limit),
        offset: optionalInt(input.offset) ?? 0,
      }),
      messagesRepo.countBySession(sessionId),
    ]);
    return {
      sessionId,
      total,
      messages: items.map((message) => ({
        id: message.id,
        sessionId: message.sessionId,
        runId: message.runId,
        role: message.role,
        type: message.type,
        content: flattenContent(message),
        createdAt: message.createdAt,
      })),
    };
  },

  /** 历史取数：无游标即最近一段，`beforeSeq` 向上翻页、`afterSeq` 向下续拉。 */
  async listMessages(query: MessageListQuery): Promise<MessagePage> {
    const sessionId = optionalString(query.sessionId);
    const runId = optionalString(query.runId);
    if ((sessionId ? 1 : 0) + (runId ? 1 : 0) !== 1) {
      throw new BadRequestError('sessionId 与 runId 必须给且只给一个');
    }
    const status = query.status === undefined || query.status === '' ? undefined : requireEnum(query.status, MESSAGE_STATUSES, 'status');

    const cursor = messageCursor(query.afterSeq, query.beforeSeq);
    // 无游标 = 最近 limit 条：把上界推到无限大，与 beforeSeq 共用「向上取一段」这条路
    const bounds =
      cursor.afterSeq !== undefined ? { afterSeq: cursor.afterSeq } : { beforeSeq: cursor.beforeSeq ?? TAIL_SEQ };

    return messagesRepo.list({
      sessionId,
      runId,
      ...bounds,
      limit: limitParam(query.limit),
      status,
    });
  },

  async listRuns(sessionId: string, page: unknown, pageSize: unknown): Promise<PageResult<Run>> {
    if (!(await sessionsRepo.findById(sessionId))) throw new NotFoundError(`会话 ${sessionId}`, 'error.not_found.session', { sessionId });
    const params = pageParams(page, pageSize);
    const result = await runsRepo.listBySession(sessionId, params.page, params.pageSize);
    const waiting = await runsRepo.waitingByRunIds(result.items.map((run) => run.id));
    return {
      items: result.items.map((run) => decorate(run, waiting)),
      total: result.total,
      page: params.page,
      pageSize: params.pageSize,
    };
  },

  async getRun(runId: string): Promise<Run> {
    const run = await runsRepo.findById(runId);
    if (!run) throw new NotFoundError(`运行 ${runId}`, 'error.not_found.run', { runId });
    return decorate(run, await runsRepo.waitingByRunIds([run.id]));
  },

  /** 某 run 的直属子 run：startedAt 升序，每条带派生 waiting。 */
  async listChildRuns(runId: string, page: unknown, pageSize: unknown): Promise<PageResult<Run>> {
    if (!(await runsRepo.findById(runId))) throw new NotFoundError(`运行 ${runId}`, 'error.not_found.run', { runId });
    const params = pageParams(page, pageSize);
    const result = await runsRepo.listChildren(runId, params.page, params.pageSize);
    const waiting = await runsRepo.waitingByRunIds(result.items.map((run) => run.id));
    return {
      items: result.items.map((run) => decorate(run, waiting)),
      total: result.total,
      page: params.page,
      pageSize: params.pageSize,
    };
  },

  /**
   * 中止运行：子 run id 向上解析到顶层 run，按顶层 run 中止（引擎共享同一个 AbortController）。
   *
   * 中止在方法内立即广播，不等 adapter 返回；closeRun 靠去重集合跳过重复终态。
   */
  async abortRun(runId: string): Promise<Run> {
    const run = await runsRepo.findById(runId);
    if (!run) throw new NotFoundError(`运行 ${runId}`, 'error.not_found.run', { runId });
    const root = await runsRepo.findRoot(run.id);
    if (!root) throw new NotFoundError(`运行 ${runId}`, 'error.not_found.run', { runId });

    // 请求的 run 或顶层 run 任一已终态即 409：先判定，后产生任何副作用
    if (isTerminalStatus(run.status) || isTerminalStatus(root.status)) {
      throw new ConflictError(`运行 ${runId} 已终态`, 'error.conflict.run_terminal', { runId });
    }

    // 先抢终态：抢不到说明驱动链已收口；并发中止已写 aborted 时继续幂等收敛
    const parentFinished = await runsRepo.finish(root.id, 'aborted');
    if (!parentFinished && (await runsRepo.findById(root.id))?.status !== 'aborted') {
      throw new ConflictError(`运行 ${runId} 已终态`, 'error.conflict.run_terminal', { runId });
    }

    // 终态先于放行引擎：引擎读到的必然是 aborted，不会把本次中止写成 succeeded
    abortControllers.get(root.id)?.abort();
    abortControllers.delete(root.id);

    const sessionId = run.sessionId;
    const abortedChildren = await runsRepo.abortActiveDescendants(root.id);
    const tree = runTrees.get(root.id);
    for (const child of abortedChildren) tree?.terminal.add(child.id);

    await settleRunPendings(treeRunIds(root, abortedChildren));
    for (const child of abortedChildren) broadcastTaskNotified(sessionId, child, 'stopped', null, null);
    await broadcastRunTerminal(sessionId, root.id);
    await settleSessionStatus(sessionId);
    // 传子 run id 时响应仍返回顶层 run：中止的是整棵 run 树
    return this.getRun(root.id);
  },

  /** 会话粒度中止：等价于中止它当前的活跃 run。 */
  async abortSession(sessionId: string): Promise<Run> {
    if (!(await sessionsRepo.findById(sessionId))) throw new NotFoundError(`会话 ${sessionId}`, 'error.not_found.session', { sessionId });
    const active = await runsRepo.findActiveBySession(sessionId);
    if (!active) throw new ConflictError(`会话 ${sessionId} 没有活跃 run`, 'error.conflict.no_active_run', { sessionId });
    return this.abortRun(active.id);
  },

  /**
   * 中止之后等驱动链彻底走完（引擎退出、收尾落库），再放行后续动作。
   *
   * `abortRun` 只抢终态、不等引擎 —— 但引擎在收尾里仍会碰产物目录，
   * 删除智能体不能在引擎还没退出时就去删盘。超时兜底：适配器不响应中止时
   * 也不能把调用方吊死，到点就放行。
   */
  async awaitRunStopped(runId: string, timeoutMs: number): Promise<void> {
    const pending = drivePromises.get(runId);
    if (pending === undefined) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<void>((resolve) => {
      timer = setTimeout(resolve, timeoutMs);
    });
    try {
      await Promise.race([pending, timeout]);
    } finally {
      clearTimeout(timer);
    }
  },
};

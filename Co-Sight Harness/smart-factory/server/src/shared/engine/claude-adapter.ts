import { config } from '../../config/index.js';
import { CLAUDE_CLI_INSTALL_HINT, ClaudeCliQuery } from './claude-cli.js';
import type {
  ClaudeCanUseTool as CanUseTool,
  ClaudeInitializeResponse,
  ClaudeMessage,
  ClaudePermissionMode as PermissionMode,
  ClaudePermissionResult as PermissionResult,
  ClaudeUserMessage,
} from './claude-protocol.js';
import { readSessionTitle } from './session-title.js';
import type { QuestionItem, SessionMode } from '../types/index.js';
import type {
  EngineAdapter,
  EngineContext,
  EngineEvent,
  EngineInfo,
  EngineModel,
  EngineSlashCommand,
  InputDecision,
  InputRequest,
  MessageDraft,
  SubagentMeta,
} from './port.js';
import { ThinkTagFilter, splitLeadingThinkBlocks, type ThinkTagSegment } from './think-tags.js';

/** 结构化提问的内置工具名：它和工具权限询问都经 canUseTool 进来，靠工具名判别 */
const ASK_USER_QUESTION = 'AskUserQuestion';

/** 权限回调的第三参：CLI 词汇只许出现在本文件 */
type PermissionOptions = Parameters<CanUseTool>[2];

/** 内容块里读得懂的字段：按结构读，不依赖 CLI 内部的块类型名 */
interface ContentBlock {
  type: string;
  text?: string;
  thinking?: string;
  id?: string;
  name?: string;
  input?: unknown;
  tool_use_id?: string;
  content?: unknown;
  is_error?: boolean;
}

/** 从 CLI 的原始流事件里取出正文增量与所在块（事件体不累积，需要自己判断类型） */
function readTextDelta(message: ClaudeMessage): { text: string; index: number } | null {
  if (message.type !== 'stream_event') return null;

  const event = message.event as { type?: string; index?: number; delta?: { type?: string; text?: string } };
  if (event.type !== 'content_block_delta' || event.delta?.type !== 'text_delta' || typeof event.delta.text !== 'string') return null;
  // 没有块下标就没法按块归类：宁可原样当正文，也不猜一个过滤器
  if (typeof event.index !== 'number') return null;
  return { text: event.delta.text, index: event.index };
}

/** 思考阶段载荷：type 由调用方补上；text 只在 delta 出现 */
type ThinkingPhase = { phase: 'start' | 'stop' } | { phase: 'delta'; text: string };

/** 尚未收到 content_block_stop 的内容块：类型与所属流（子代理血缘）。 */
export interface OpenBlock {
  type: string;
  meta: SubagentMeta;
}

/** 块键：流（parent_tool_use_id）+ 流内 index。不同流都从 0 起编号，不分开会互相覆盖。 */
function openBlockKey(message: ClaudeMessage, index: number): string {
  const frame = message as { parent_tool_use_id?: unknown };
  const stream = typeof frame.parent_tool_use_id === 'string' ? frame.parent_tool_use_id : '';
  return `${stream}:${index}`;
}

/** 一个文本块里 think 段的流式状态：归类器 + 是否已发过 thinking start（还欠一个 stop）。 */
interface TextThinkState {
  filter: ThinkTagFilter;
  open: boolean;
  meta: SubagentMeta;
}

/**
 * 文本块的边界事件。start 只看 `content_block.type`，stop 要查块类型表，所以调用方
 * **必须在本条消息交给 thinkingPhaseOf 之前**调用它 —— 那边会把表项删掉。
 */
function textBlockBoundaryOf(
  message: ClaudeMessage,
  blocks: Map<string, OpenBlock>,
): { phase: 'start' | 'stop'; key: string; meta: SubagentMeta } | null {
  if (message.type !== 'stream_event') return null;

  const event = message.event as { type?: string; index?: number; content_block?: { type?: string } };
  if (typeof event.index !== 'number') return null;
  const key = openBlockKey(message, event.index);
  if (event.type === 'content_block_start') {
    return event.content_block?.type === 'text' ? { phase: 'start', key, meta: subagentMetaOf(message) } : null;
  }
  if (event.type === 'content_block_stop') {
    const block = blocks.get(key);
    return block?.type === 'text' ? { phase: 'stop', key, meta: block.meta } : null;
  }
  return null;
}

/**
 * 落库草稿的 think 拆分：文本开头是 `<think>` 段时，改成独立的思考消息 + 剩余正文。
 *
 * 草稿拿到的是完整文本，走与流式过滤器同一套口径（只认开头段，见 think-tags.ts）；
 * 拆除后正文为空就只落思考，避免留一条空文本消息。
 */
export function splitDraftThink(draft: MessageDraft): MessageDraft[] {
  if (draft.type !== 'text') return [draft];
  const content = draft.content as { text?: unknown };
  const text = typeof content.text === 'string' ? content.text : '';
  const split = splitLeadingThinkBlocks(text);
  if (split.thinking.length === 0) return [draft];

  const drafts: MessageDraft[] = split.thinking.map((thinking) => ({
    role: draft.role,
    type: 'thinking',
    content: { text: thinking },
  }));
  if (split.text !== '') drafts.push({ role: draft.role, type: 'text', content: { text: split.text } });
  return drafts;
}

/**
 * 流事件 → 思考块阶段。
 * `content_block_stop` 本身不带块类型，按「流 + index」记录 start 时的类型与血缘，
 * 才能判断该 stop 是不是思考块、以及该把 stop 归位到哪条流。
 */
export function thinkingPhaseOf(message: ClaudeMessage, blocks: Map<string, OpenBlock>): ThinkingPhase | null {
  if (message.type !== 'stream_event') return null;

  const event = message.event as {
    type?: string;
    index?: number;
    content_block?: { type?: string };
    delta?: { type?: string; thinking?: string };
  };
  if (event.type === 'content_block_start') {
    if (typeof event.index !== 'number') return null;
    const blockType = event.content_block?.type;
    if (typeof blockType === 'string') {
      blocks.set(openBlockKey(message, event.index), { type: blockType, meta: subagentMetaOf(message) });
    }
    return blockType === 'thinking' ? { phase: 'start' } : null;
  }
  if (event.type === 'content_block_delta' && event.delta?.type === 'thinking_delta' && typeof event.delta.thinking === 'string') {
    return { phase: 'delta', text: event.delta.thinking };
  }
  if (event.type === 'content_block_stop' && typeof event.index === 'number') {
    const key = openBlockKey(message, event.index);
    const block = blocks.get(key);
    blocks.delete(key);
    return block?.type === 'thinking' ? { phase: 'stop' } : null;
  }
  return null;
}

/** 流收尾时仍未关闭的思考块 → 合成 stop 事件；带开启时的血缘，子代理的 stop 才能归位到子 run。 */
export function openThinkingStops(blocks: Map<string, OpenBlock>): Extract<EngineEvent, { type: 'thinking' }>[] {

  const stops = [...blocks.values()]
    .filter((block) => block.type === 'thinking')
    .map((block): Extract<EngineEvent, { type: 'thinking' }> => ({ type: 'thinking', phase: 'stop', ...block.meta }));
  blocks.clear();
  return stops;
}

/** API 重试消息 → 重试事件；只有 system/api_retry 带这组字段。 */
export function apiRetryOf(message: ClaudeMessage): Extract<EngineEvent, { type: 'api_retry' }> | null {
  if (message.type !== 'system' || message.subtype !== 'api_retry') return null;
  return {
    type: 'api_retry',
    attempt: typeof message.attempt === 'number' ? message.attempt : 0,
    maxRetries: typeof message.max_retries === 'number' ? message.max_retries : 0,
    errorStatus: message.error_status ?? null,
    error: typeof message.error === 'string' ? message.error : null,
  };
}

/** 助手块的落库草稿：文本 / 思考 / 工具调用各一条；AskUserQuestion 另有 tool_interactive 消息承载，跳过 */
function assistantDraftOf(block: ContentBlock, questionToolCallIds: Set<string>): MessageDraft | null {
  if (block.type === 'text' && typeof block.text === 'string') {
    // 空 / 只有空白的文本块不落库：它对用户没有任何内容，投影到对话流就是一条只剩头像的空行，
    // 还会顶掉会话列表按「最后一条 text」取的摘要
    if (block.text.trim() === '') return null;
    return { role: 'assistant', type: 'text', content: { text: block.text } };
  }
  if (block.type === 'thinking' && typeof block.thinking === 'string') {
    return { role: 'assistant', type: 'thinking', content: { text: block.thinking } };
  }
  if (block.type !== 'tool_use' || typeof block.id !== 'string' || typeof block.name !== 'string') return null;

  if (block.name === ASK_USER_QUESTION) {
    questionToolCallIds.add(block.id);
    return null;
  }
  return { role: 'assistant', type: 'tool_use', content: { toolCallId: block.id, toolName: block.name, input: block.input } };
}

/** 用户块的落库草稿：只认工具结果，且跳过 AskUserQuestion 的结果（同样已由 tool_interactive 消息承载） */
function userDraftOf(block: ContentBlock, questionToolCallIds: Set<string>): MessageDraft | null {
  if (block.type !== 'tool_result' || typeof block.tool_use_id !== 'string') return null;
  if (questionToolCallIds.has(block.tool_use_id)) return null;

  return {
    role: 'assistant',
    type: 'tool_result',
    content: { toolCallId: block.tool_use_id, output: block.content, isError: block.is_error === true },
  };
}

/** 块数组 → 草稿数组：内容不是块数组、或块认不出，都当没有 */
function draftsFrom(content: unknown, toDraft: (block: ContentBlock) => MessageDraft | null): MessageDraft[] {
  if (!Array.isArray(content)) return [];
  return content
    .map((block) => toDraft(block as ContentBlock))
    .filter((draft): draft is MessageDraft => draft !== null);
}

/**
 * CLI 消息 → 落库草稿（纯函数，便于不连真实 CLI 单测）。
 *
 * 只认承载会话历史的完整消息：assistant 的 text / thinking / tool_use 与 user 的 tool_result。
 * `questionToolCallIds` 由调用方在整轮内保持同一实例：跳过 AskUserQuestion 的调用时登记其 id，
 * 它的结果块靠这套 id 对号跳过，避免同一次提问落两条。
 */
export function draftsOf(message: ClaudeMessage, questionToolCallIds: Set<string> = new Set()): MessageDraft[] {
  if (message.type === 'assistant') return draftsFrom(message.message?.content, (block) => assistantDraftOf(block, questionToolCallIds));
  if (message.type === 'user') return draftsFrom(message.message?.content, (block) => userDraftOf(block, questionToolCallIds));
  return [];
}

/**
 * result 消息 → 回合错误文本（纯函数）：null 表示正常成功。
 *
 * CLI 存在 subtype='success' 且 is_error=true 的情形（回合以 API 错误收尾），
 * 此时错误文本在 result 里，不判就会当成成功；非 success 子类型自带原因。
 */
export function resultErrorOf(message: ClaudeMessage): string | null {
  if (message.type !== 'result') return null;
  if (message.subtype !== 'success') return `模型调用未成功：${message.subtype}`;
  if (!message.is_error) return null;
  return message.result || '模型调用未成功';
}

/**
 * 权限回调 → 宿主侧请求（纯函数）：AskUserQuestion 走交互，其余一律按审批。
 *
 * 卡片文案优先用 CLI 已渲染好的 title / description，缺失才按工具名与输入拼装。
 */
export function toInputRequest(toolName: string, input: Record<string, unknown>, options: PermissionOptions): InputRequest {
  if (toolName === ASK_USER_QUESTION) {
    return {
      kind: 'tool_interactive',
      toolName,
      title: '需要澄清',
      toolCallId: options.toolUseID,
      agentId: options.agentID,
      questions: Array.isArray(input.questions) ? (input.questions as QuestionItem[]) : [],
    };
  }

  const detail = input as { command?: string; file_path?: string; description?: string };
  return {
    kind: 'approval',
    toolName,
    toolCallId: options.toolUseID,
    agentId: options.agentID,
    title: options.title ?? `允许执行 ${toolName}？`,
    description: options.description ?? detail.description ?? detail.command ?? detail.file_path,
    // 只有 CLI 明确禁止「全部允许」才带该字段：缺字段即表示可以提供
    ...(options.suppressAlwaysAllowRule === true ? { allowAll: false } : {}),
    input,
  };
}

/**
 * 用户答案 → CLI 问卷答案（纯函数）：key 是问题原文、多选以 ', ' 拼接。
 *
 * 以**被问的问题**为权威遍历，未被问到的 key 自然丢弃，取不到或空数组则跳过。
 */
export function sdkAnswers(questions: unknown, answers: Record<string, string[]>): Record<string, string> {
  const result: Record<string, string> = {};
  for (const item of Array.isArray(questions) ? (questions as QuestionItem[]) : []) {
    const question = item?.question;
    const choices = typeof question === 'string' ? answers[question] : undefined;
    if (!choices || choices.length === 0) continue;
    result[question] = choices.join(', ');
  }
  return result;
}

/** 放行载荷（纯函数）：AskUserQuestion 必须把 questions 原样带回，其余工具入参原样。 */
function updatedInputOf(toolName: string, input: Record<string, unknown>, answers?: Record<string, string[]>): Record<string, unknown> {
  if (toolName !== ASK_USER_QUESTION) return input;
  return { questions: input.questions, answers: sdkAnswers(input.questions, answers ?? {}) };
}

/**
 * 放行结果（纯函数）：全部允许只标永久分类，单次放行标临时。
 *
 * 权限只按会话级 `approvedAll` 生效：不回填 CLI 的 `options.suggestions`，
 * 否则 CLI 会把规则写进共享 cwd 的 settings，多会话并发时造成跨会话泄漏与读改写丢更新。
 */
function allowResult(permanent: boolean, toolName: string, input: Record<string, unknown>, decision: InputDecision, options: PermissionOptions): PermissionResult {
  return {
    behavior: 'allow' as const,
    updatedInput: updatedInputOf(toolName, input, decision.answers),
    toolUseID: options.toolUseID,
    decisionClassification: permanent ? ('user_permanent' as const) : ('user_temporary' as const),
  };
}

/**
 * 宿主决策 + 回调参数 → CLI 权限结果（纯函数）；拒绝一律带 toolUseID 与 reject 分类。
 *
 * 交互提问的应答路径只回 `answers`、不带 `decision`（见 session.service 的 respondMessage），
 * 而 `answers` 本身（含空对象 = 用户点「继续」）就表示放行：不单列这个分支，
 * 用户答完题会被当成「拒绝」，模型只会看到「用户拒绝了这次工具调用」。
 */
export function permissionOf(
  decision: InputDecision,
  toolName: string,
  input: Record<string, unknown>,
  options: PermissionOptions,
): PermissionResult {
  const answered =
    toolName === ASK_USER_QUESTION && decision.answers !== undefined && decision.decision !== 'aborted';
  if (decision.decision === 'approved' || decision.decision === 'approved_all' || answered) {
    return allowResult(decision.decision === 'approved_all', toolName, input, decision, options);
  }
  return { behavior: 'deny', message: '用户拒绝了这次工具调用', toolUseID: options.toolUseID, decisionClassification: 'user_reject' };
}

/**
 * 模型下发片段（纯函数）：`model` 承载主模型，端点、凭据与子代理模型名放进 `settings.env`。
 * 传输层把整个 `settings` 写成 0600 临时文件、经 `--settings` 下发（flag-settings 层，
 * 优先级高于 user settings），因此框架配置压过本机 `~/.claude/settings.json`。
 * 认证只用 ANTHROPIC_AUTH_TOKEN（Bearer）；密钥不进命令行、不进日志、不下发前端，
 * 进程退出即删临时文件。
 * settings 显式下发 disableAllHooks: false：user / project / local 与插件 hooks 照常运行，供 cosight-viewer 等本机观测端采集引擎会话事件；
 * 显式 false 可覆盖 user settings 里的 true，托管层（组织策略）的限制仍然优先。
 * `env` 只展开 process.env 保留 PATH / HOME / 代理等基础变量，并删除继承来的模型端点、凭据与模型名；
 * 模型配置经 `settings.env` 下发，不再经 `env`。
 *
 * 插件 / 子代理定义里常写 `model: sonnet` 这类**别名**。别名由引擎按自己的别名表解析成内置型号
 * （如 `claude-sonnet-5-5`），既不看 `options.model` 也不看 `CLAUDE_CODE_SUBAGENT_MODEL`，
 * 网关没有该型号就报 model_not_found。把引擎认的四个别名变量都指到本场模型，别名才不会绕开框架配置。
 */
export function modelOptionsOf(model: EngineModel): {
  model: string;
  settings: { disableAllHooks: boolean; env: Record<string, string> };
  env: NodeJS.ProcessEnv;
} {
  const env: NodeJS.ProcessEnv = { ...process.env };
  delete env.ANTHROPIC_API_KEY;
  delete env.ANTHROPIC_AUTH_TOKEN;
  delete env.ANTHROPIC_BASE_URL;
  delete env.ANTHROPIC_MODEL;
  delete env.CLAUDE_CODE_SUBAGENT_MODEL;
  delete env.ANTHROPIC_DEFAULT_OPUS_MODEL;
  delete env.ANTHROPIC_DEFAULT_SONNET_MODEL;
  delete env.ANTHROPIC_DEFAULT_HAIKU_MODEL;
  delete env.ANTHROPIC_DEFAULT_FABLE_MODEL;

  return {
    model: model.modelName,
    settings: {
      disableAllHooks: false,
      env: {
        ANTHROPIC_AUTH_TOKEN: model.apiKey,
        ANTHROPIC_BASE_URL: model.baseUrl ?? '',
        CLAUDE_CODE_SUBAGENT_MODEL: model.modelName,
        // 子代理 frontmatter 的 `model: sonnet|opus|haiku|fable` 按别名走这里解析
        ANTHROPIC_DEFAULT_OPUS_MODEL: model.modelName,
        ANTHROPIC_DEFAULT_SONNET_MODEL: model.modelName,
        ANTHROPIC_DEFAULT_HAIKU_MODEL: model.modelName,
        ANTHROPIC_DEFAULT_FABLE_MODEL: model.modelName,
      },
    },
    env,
  };
}

/** 会话审批模式 → CLI 权限模式（纯函数）：只读走计划模式，工作区可写自动接受编辑，完全放行跳过权限检查。 */
export function permissionModeOf(mode: SessionMode): PermissionMode {
  if (mode === 'read_only') return 'plan';
  if (mode === 'workspace_write') return 'acceptEdits';
  return 'bypassPermissions';
}

/**
 * `/` 菜单与引擎信息的探测：起一个不接 prompt 的 Claude Code 进程，只读它的 initialize 回执。
 *
 * 为什么不用扫盘：`/` 列表由引擎自己拼（内置命令 + user / project 技能 + 插件 + 动态命令），
 * 扫 `.claude/skills` 只能看到其中一部分，也还原不出别名、参数提示与内置项。
 *
 * 进程只活到回执返回：不发起模型调用，`persistSession: false` 不落会话，
 * `disableAllHooks: true` 不跑用户的 SessionStart hooks —— 否则每打开一次菜单就执行一次本机钩子。
 * `strictMcpConfig` 与真实会话一致：MCP 不参与，列表里也不会多出本机 MCP 的 prompt 命令。
 */
const PROBE_TIMEOUT_MS = 15_000;
const PROBE_CACHE_MS = 30_000;

/** README 约定的最低 Claude Code CLI 版本；control 协议以这套版本为准。 */
const MIN_CLAUDE_CLI_VERSION = [2, 1, 287] as const;

/**
 * 低于最低版本时直接给出可操作的升级提示。
 *
 * 老 CLI 不报 `claude_code_version` 时放行：此时无法判断版本，硬拦会让本来能用的
 * 环境也起不来；真正的协议错误会在调用界面暴露。
 */
export function assertClaudeCliVersion(init: ClaudeInitializeResponse): void {
  const raw = init.claude_code_version;
  if (typeof raw !== 'string') return;
  const match = /(\d+)\.(\d+)\.(\d+)/.exec(raw);
  if (match === null) return;
  const version = [Number(match[1]), Number(match[2]), Number(match[3])] as const;
  for (let index = 0; index < version.length; index += 1) {
    if (version[index] > MIN_CLAUDE_CLI_VERSION[index]) return;
    if (version[index] < MIN_CLAUDE_CLI_VERSION[index]) {
      throw new Error(
        `Claude Code CLI 版本过低（${raw}），需要 >= ${MIN_CLAUDE_CLI_VERSION.join('.')}；` +
          `请执行 ${CLAUDE_CLI_INSTALL_HINT}@latest 升级`,
      );
    }
  }
}

/**
 * 全局同时最多几个探测进程。缓存按 cwd 分，每个新目录都会另起一份进程（各 200MB+）；
 * 接口本身没有鉴权，光靠按目录缓存挡不住"换着目录请求"的放大，所以所有目录共用一个名额池，
 * 多出来的请求排队等名额，轮到了才 spawn。
 */
const PROBE_MAX_CONCURRENT = 2;

/** 同一 cwd 的探测结果短时复用：一次进程启动约 1–2 秒、200MB+ 内存，不能每次开菜单都起一个。 */
const probeCache = new Map<string, { expiresAt: number; value: Promise<ClaudeInitializeResponse> }>();

let probeSlotsInUse = 0;
const probeWaiters: Array<() => void> = [];

function acquireProbeSlot(): Promise<void> {
  if (probeSlotsInUse < PROBE_MAX_CONCURRENT) {
    probeSlotsInUse += 1;
    return Promise.resolve();
  }
  return new Promise<void>((resolve) => {
    probeWaiters.push(resolve);
  });
}

function releaseProbeSlot(): void {
  const next = probeWaiters.shift();
  if (next === undefined) {
    probeSlotsInUse -= 1;
  } else {
    // 名额直接转交给排队者，计数不变
    next();
  }
}

/** 排到名额再起进程：排队期间不占内存，只有轮到时才 spawn。 */
async function probeWithSlot(cwd: string): Promise<ClaudeInitializeResponse> {
  await acquireProbeSlot();
  try {
    return await spawnProbe(cwd);
  } finally {
    releaseProbeSlot();
  }
}

/**
 * 探测某个目录下的 initialize 回执。失败不进缓存，下一次请求重新起进程；
 * 同一 cwd 的并发请求共用同一个 Promise，且所有目录共用上面那组并发名额。
 */
function probeInitialization(cwd: string): Promise<ClaudeInitializeResponse> {
  const now = Date.now();
  const cached = probeCache.get(cwd);
  if (cached !== undefined && cached.expiresAt > now) return cached.value;

  const value = probeWithSlot(cwd);
  const entry = { expiresAt: now + PROBE_CACHE_MS, value };
  // 失败不进缓存。只删自己这一条：旧探针在本目录被新一次探测覆盖后才收尾时，
  // 不能把新条目一起删掉（否则新探测的结果白跑，下个请求又起一个进程）。
  value.catch(() => {
    if (probeCache.get(cwd) === entry) probeCache.delete(cwd);
  });
  // 顺手清掉过期项：每个目录一条，不清理的话长期运行会随请求过的目录数增长
  for (const [key, expired] of probeCache) {
    if (expired.expiresAt <= now) probeCache.delete(key);
  }
  probeCache.set(cwd, entry);
  return value;
}

/** 起进程、等 initialize、关进程。超时或异常都走 finally 收尾，不留孤儿进程。 */
async function spawnProbe(cwd: string): Promise<ClaudeInitializeResponse> {
  let releaseInput!: () => void;
  const inputDone = new Promise<void>((resolve) => {
    releaseInput = resolve;
  });
  // 输入迭代器永不产出：只要初始化，不产生回合；close() 杀掉进程后挂起的迭代随之结束
  const session = new ClaudeCliQuery({
    prompt: (async function* () {
      await inputDone;
    })(),
    options: {
      cwd,
      binary: config.claudeCodePath,
      // 只读探测不做事：计划模式不执行工具，也不会触发 canUseTool
      permissionMode: 'plan',
      persistSession: false,
      strictMcpConfig: true,
      settings: { disableAllHooks: true },
    },
  });

  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      session.initializationResult(),
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(
          () => reject(new Error(`Claude Code 在 ${PROBE_TIMEOUT_MS}ms 内没有返回初始化结果`)),
          PROBE_TIMEOUT_MS,
        );
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
    releaseInput();
    session.close();
  }
}

/** initialize 回执 → `/` 菜单条目（纯函数）。名字、说明与参数提示原样透传，不做来源归类。 */
export function slashCommandsOf(init: ClaudeInitializeResponse): EngineSlashCommand[] {
  if (!Array.isArray(init.commands)) return [];
  return init.commands.map((command) => ({
    name: command.name,
    description: typeof command.description === 'string' ? command.description : '',
    argumentHint: typeof command.argumentHint === 'string' ? command.argumentHint : '',
    ...(Array.isArray(command.aliases) && command.aliases.length > 0 ? { aliases: [...command.aliases] } : {}),
    ...(command.builtin === true ? { builtin: true } : {}),
  }));
}

/**
 * initialize 回执 → 引擎信息（纯函数）。只留版本与菜单条数：整表由 `/engine/commands/list` 给，
 * 模型 / 账号由 Cosight 框架配置（`/models/list`），不在这里重复。
 *
 * `commandCount` 与列表端点同一口径：**不含**引擎自带命令（`builtin`），前端拿到的数字与菜单条数一致。
 */
export function engineInfoOf(init: ClaudeInitializeResponse, cwd: string): EngineInfo {
  const commands = Array.isArray(init.commands) ? init.commands : [];
  return {
    engine: 'claude-cli',
    cwd,
    version: typeof init.claude_code_version === 'string' ? init.claude_code_version : '',
    commandCount: commands.filter((command) => command.builtin !== true).length,
    available: true,
  };
}

/** 任务生命周期事件：task_started 与 task_notified 两支 */
type TaskEvent = Extract<EngineEvent, { type: 'task_started' | 'task_notified' }>;

/**
 * 内容消息 → 子代理来源（纯函数）：assistant 帧带 agent_id，user 与 stream_event 只有 parent_tool_use_id。
 * 缺字段一律归 null；宿主按 agentId、parentToolUseId 的顺序把内容归位到子 run。
 */
export function subagentMetaOf(message: ClaudeMessage): SubagentMeta {
  const frame = message as { parent_tool_use_id?: unknown; agent_id?: unknown };
  return {
    parentToolUseId: typeof frame.parent_tool_use_id === 'string' ? frame.parent_tool_use_id : null,
    agentId: typeof frame.agent_id === 'string' ? frame.agent_id : null,
  };
}

/** CLI run_id → 事件字段：缺省不落键，宿主按 task_id 最近一次运行归位。 */
function runIdOf(value: unknown): { runId?: string } {
  return typeof value === 'string' && value !== '' ? { runId: value } : {};
}

/**
 * system 任务消息 → 任务事件（纯函数）。
 *
 * task_started 只认 local_agent 或带 subagent_type 的任务，spawn_depth 缺省记 0 交由宿主按父深度补齐；
 * task_notification 的 error 只在 failed 时给出，缺 summary 时用固定文案兜底。
 * 两者都原样透传 CLI 的可选 run_id：resume 后 task_id 不变、run_id 变。
 */
export function taskEventOf(message: ClaudeMessage): TaskEvent | null {
  if (message.type !== 'system') return null;

  if (message.subtype === 'task_started') {
    if (typeof message.task_id !== 'string') return null;
    const subagentType = typeof message.subagent_type === 'string' ? message.subagent_type : null;
    if (message.task_type !== 'local_agent' && subagentType === null) return null;
    return {
      type: 'task_started',
      taskId: message.task_id,
      ...runIdOf(message.run_id),
      toolUseId: typeof message.tool_use_id === 'string' ? message.tool_use_id : null,
      parentTaskId: typeof message.parent_task_id === 'string' ? message.parent_task_id : null,
      subagentType,
      delegationDepth: typeof message.spawn_depth === 'number' ? message.spawn_depth : 0,
      description: typeof message.description === 'string' ? message.description : '',
    };
  }

  if (message.subtype === 'task_notification') {
    if (
      typeof message.task_id !== 'string' ||
      (message.status !== 'completed' && message.status !== 'failed' && message.status !== 'stopped')
    ) {
      return null;
    }
    const summary = typeof message.summary === 'string' ? message.summary : null;
    return {
      type: 'task_notified',
      taskId: message.task_id,
      ...runIdOf(message.run_id),
      status: message.status,
      summary,
      error: message.status === 'failed' ? summary || '子任务失败' : null,
    };
  }

  return null;
}

/**
 * 仍在跑的后台任务 id（纯函数）：`background_tasks_changed` 是 REPLACE 语义，载荷即变更后的全量存活任务。
 * 其余消息返回 null，表示「集合不动」。老 CLI 不发这一帧时集合恒空，退化成旧行为。
 *
 * ambient 任务（看门狗 / 跳过进对话流的内务任务）不计入：它们不是模型在等的活，
 * 算进来会把 run 一直挂到兜底收口。
 */
export function backgroundTasksOf(message: ClaudeMessage): readonly string[] | null {
  if (message.type !== 'system' || message.subtype !== 'background_tasks_changed') return null;
  const tasks = (message as { tasks?: unknown }).tasks;
  if (!Array.isArray(tasks)) return [];
  return tasks.flatMap((task) => {
    if ((task as { ambient?: unknown }).ambient === true) return [];
    const id = (task as { task_id?: unknown }).task_id;
    return typeof id === 'string' && id !== '' ? [id] : [];
  });
}

/** 后台任务未收尾时 result 之后的兜底收口时长：与 CLI 自己的 runEndCeilingMs 同量级 */
const LATE_RELEASE_CEILING_MS = 600_000;

/**
 * Claude Code CLI 适配器：协议翻译与事件归类；子进程与 control 通道见 `claude-cli.ts`。
 *
 * 三条硬约束（都来自 CLI 实测）：
 * 1. stdin 必须保持打开（`prompt` 传 AsyncIterable），否则 `interrupt` / `can_use_tool` 无从下发；
 * 2. 输入迭代器在运行结束前不能返回，否则子进程 stdin 被关，审批回写会失败；
 * 3. `canUseTool` 只在权限流程落到「询问」时触发，且**必须**给出 allow / deny（返回 null 会让该工具调用永久挂起）。
 */
/** 单次 run 的进程内状态：查询句柄、输入放行句柄与内容累积。 */
interface RunState {
  abortController: AbortController;
  inputDone: Promise<void>;
  releaseInput: () => void;
  output: string;
  sessionIdReported: boolean;
  pending: Record<'text' | 'thinking', string>;
  questionToolCallIds: Set<string>;
  /** 流 + index → 内容块类型与血缘；content_block_stop 靠它判断是否思考块、归位到哪条流 */
  blockTypes: Map<string, OpenBlock>;
  /** 文本块键 → `<think>` 归类状态；块结束与 run 收尾时清理（见 think-tags.ts） */
  textThink: Map<string, TextThinkState>;
  /** 仍在跑的后台任务：非空时 result 只是「等通知」，这一回合结束后进程不会退出 */
  liveBackgroundTasks: Set<string>;
  /** 后台任务久不收尾时的兜底收口定时器；有新的模型活动即取消 */
  lateReleaseTimer: ReturnType<typeof setTimeout> | null;
}

export class ClaudeAdapter implements EngineAdapter {
  readonly engine = 'claude-cli';

  /**
   * 读 Claude Code 给这场会话的标题：优先 /rename 的自定义名，其次自动摘要。
   *
   * 本地读该会话的 JSONL 元数据，不发起模型调用；会话文件不存在 / 尚无摘要时返回 null。
   */
  async sessionTitle(resumeSessionId: string, cwd: string): Promise<string | null> {
    return readSessionTitle(resumeSessionId, cwd);
  }

  /** `/` 菜单：与终端里输入 `/` 看到的自动补全同一份（内置命令 + 技能 + 插件 + 动态命令）。 */
  async commands(cwd: string): Promise<EngineSlashCommand[]> {
    const init = await probeInitialization(cwd);
    assertClaudeCliVersion(init);
    return slashCommandsOf(init);
  }

  /** 引擎信息：版本、可用模型、登录身份、输出风格；与 `commands` 共用一次探测。 */
  async info(cwd: string): Promise<EngineInfo> {
    const init = await probeInitialization(cwd);
    assertClaudeCliVersion(init);
    return engineInfoOf(init, cwd);
  }

  async run(ctx: EngineContext): Promise<{ output: string }> {
    // 已中止：不建会话、不联网，空手返回（终态由驱动链按 aborted 收口）
    if (ctx.signal.aborted) return { output: '' };

    // 模型配置由驱动链在起跑前解析好且必填；modelOptionsOf 把模型、端点与凭据交给传输层
    // （凭据走 flag settings 临时文件），压过本机配置但不限制 settings 源
    const state = this.createState();
    const session = this.openQuery(ctx, state);
    const detachAbort = this.bindAbort(ctx, session, state.abortController);
    try {
      // 先等 initialize：既做版本门禁，也确保 control 通道在第一条用户消息前就绪
      assertClaudeCliVersion(await session.initializationResult());
      await this.consume(ctx, session, state);
    } finally {
      detachAbort();
      this.clearLateRelease(state);
      state.releaseInput();
      // 中止或异常都可能留下未关闭的思考块：stop 在 finally 里补，非 abort 的异常也要收掉流式态
      for (const event of openThinkingStops(state.blockTypes)) await ctx.emit(event);
      await this.flushTextThink(ctx, state);
    }
    await this.flushPending(ctx, state.pending);
    return { output: state.output };
  }

  private createState(): RunState {
    let releaseInput!: () => void;
    const inputDone = new Promise<void>((resolve) => {
      releaseInput = resolve;
    });
    return {
      abortController: new AbortController(),
      inputDone,
      releaseInput,
      output: '',
      sessionIdReported: false,
      // 增量只做瞬态广播，这里另攒一份：流收尾时终稿还没到，就靠它补落半截内容
      pending: { text: '', thinking: '' },
      questionToolCallIds: new Set(),
      blockTypes: new Map(),
      textThink: new Map(),
      liveBackgroundTasks: new Set(),
      lateReleaseTimer: null,
    };
  }

  private openQuery(ctx: EngineContext, state: RunState): ClaudeCliQuery {
    return new ClaudeCliQuery({
      prompt: this.heldPrompt(ctx.prompt, state.inputDone),
      options: {
        cwd: ctx.cwd,
        binary: config.claudeCodePath,
        ...modelOptionsOf(ctx.model),
        ...(ctx.resumeSessionId !== null ? { resume: ctx.resumeSessionId } : {}),
        permissionMode: permissionModeOf(ctx.mode),
        ...(ctx.mode === 'full_access' ? { allowDangerouslySkipPermissions: true } : {}),
        effort: ctx.effort,
        // 只认本适配器显式下发的 MCP 服务器（当前为空）：操作者本机与插件带的 MCP 不得进产品运行的工具集
        strictMcpConfig: true,
        includePartialMessages: true,
        persistSession: true,
        canUseTool: this.canUseToolOf(ctx),
        abortController: state.abortController,
      },
    });
  }

  private canUseToolOf(ctx: EngineContext): CanUseTool {
    return async (toolName, input, options) => {
      const decision = await ctx.requestInput(toInputRequest(toolName, input, options));
      return permissionOf(decision, toolName, input, options);
    };
  }

  private bindAbort(ctx: EngineContext, session: ClaudeCliQuery, abortController: AbortController): () => void {
    const onAbort = (): void => {
      void session.interrupt().catch(() => undefined);
      abortController.abort();
    };
    ctx.signal.addEventListener('abort', onAbort, { once: true });
    // addEventListener 不补发已发生的 abort：注册间隙内中止的信号在此复查补一次
    if (ctx.signal.aborted) onAbort();
    return () => ctx.signal.removeEventListener('abort', onAbort);
  }

  private async consume(ctx: EngineContext, session: ClaudeCliQuery, state: RunState): Promise<void> {
    try {
      for await (const message of session) {
        // 已中止：不再消费剩余消息，终态与残留子 run 由驱动链收口
        if (ctx.signal.aborted) break;
        await this.handleMessage(ctx, message, state);
      }
    } catch (error) {
      // 中止会让流以异常收尾：半截内容照落，run 的终态由驱动链按 aborted 收口
      if (!ctx.signal.aborted) throw error;
    }
  }

  private async handleMessage(ctx: EngineContext, message: ClaudeMessage, state: RunState): Promise<void> {
    // 首条携带 session_id 的消息即引擎会话标识：只回传一次，后续消息重复携带同一值
    const sessionId = (message as { session_id?: unknown }).session_id;
    if (!state.sessionIdReported && typeof sessionId === 'string' && sessionId !== '') {
      state.sessionIdReported = true;
      await ctx.onSessionId?.(sessionId);
    }

    // 有了新的模型活动：后台任务已经把会话唤醒，兜底收口让位给真实回合
    if (message.type !== 'result') this.clearLateRelease(state);

    const taskEvent = taskEventOf(message);
    if (taskEvent !== null) await ctx.emit(taskEvent);

    const liveTasks = backgroundTasksOf(message);
    if (liveTasks !== null) state.liveBackgroundTasks = new Set(liveTasks);

    const retry = apiRetryOf(message);
    if (retry !== null) await ctx.emit(retry);

    const meta = subagentMetaOf(message);

    // 文本块结束：把缓冲的 think 残留吐完、补上还欠的 stop。
    // 必须在 thinkingPhaseOf 之前调用 —— 那边会删掉块类型表，之后就分不清 stop 属于哪种块
    const boundary = textBlockBoundaryOf(message, state.blockTypes);
    if (boundary?.phase === 'stop') {
      const entry = state.textThink.get(boundary.key);
      if (entry !== undefined) {
        state.textThink.delete(boundary.key);
        await this.emitThinkSegments(ctx, entry, entry.filter.endBlock());
        if (entry.open) {
          entry.open = false;
          await ctx.emit({ type: 'thinking', phase: 'stop', ...entry.meta });
        }
      }
    }

    const thinking = thinkingPhaseOf(message, state.blockTypes);
    if (thinking !== null) {
      if (thinking.phase === 'delta') state.pending.thinking += thinking.text;
      await ctx.emit({ type: 'thinking', ...thinking, ...meta });
    }

    const delta = readTextDelta(message);
    if (delta !== null) {
      const key = openBlockKey(message, delta.index);
      let entry = state.textThink.get(key);
      if (entry === undefined) {
        entry = { filter: new ThinkTagFilter(), open: false, meta };
        state.textThink.set(key, entry);
      }
      state.pending.text += delta.text;
      await this.emitThinkSegments(ctx, entry, entry.filter.push(delta.text));
    }

    for (const draft of draftsOf(message, state.questionToolCallIds)) {
      if (draft.type === 'text' || draft.type === 'thinking') state.pending[draft.type] = '';
      for (const piece of splitDraftThink(draft)) await ctx.emit({ type: 'message', draft: piece, ...meta });
    }

    if (message.type === 'result') this.handleResult(message, state);
  }

  /**
   * 归类后的正文增量按类型发事件：进入思考段补 start，离开补 stop。
   * 思考增量不推给渲染层（见 useLiveSession 的缓冲策略），这里只保证事件成对。
   */
  private async emitThinkSegments(ctx: EngineContext, entry: TextThinkState, segments: ThinkTagSegment[]): Promise<void> {
    for (const segment of segments) {
      if (segment.kind === 'thinking') {
        if (!entry.open) {
          entry.open = true;
          await ctx.emit({ type: 'thinking', phase: 'start', ...entry.meta });
        }
        await ctx.emit({ type: 'thinking', phase: 'delta', text: segment.text, ...entry.meta });
        continue;
      }
      if (entry.open) {
        entry.open = false;
        await ctx.emit({ type: 'thinking', phase: 'stop', ...entry.meta });
      }
      await ctx.emit({ type: 'delta', messageType: 'text', delta: segment.text, ...entry.meta });
    }
  }

  /** 流收尾：把每个文本块缓冲的尾巴（未闭合的 think、被截断的标签）吐完并收口 */
  private async flushTextThink(ctx: EngineContext, state: RunState): Promise<void> {
    for (const entry of state.textThink.values()) {
      await this.emitThinkSegments(ctx, entry, entry.filter.endBlock());
      if (entry.open) {
        entry.open = false;
        await ctx.emit({ type: 'thinking', phase: 'stop', ...entry.meta });
      }
    }
    state.textThink.clear();
  }

  /**
   * result 消息：没挂后台任务才释放输入迭代器，并把回合错误转成宿主异常。
   *
   * 还有后台任务在跑时，这一回合只是「等通知」：CLI 进程不会退出，稍后自己唤醒开下一回合。
   * 此时若关掉输入流，下一回合的审批（canUseTool / hooks）就再也递不进去，
   * 所有需要审批的工具都回 `Tool permission request failed: AbortError: Stream closed`。
   * 这种结果留给下一回合的 result 收口；久无活动由兜底定时器强制收口，避免 run 永不结束。
   */
  private handleResult(message: ClaudeMessage, state: RunState): void {
    if (state.liveBackgroundTasks.size === 0) {
      // 顶层回合结束：释放输入迭代器，消息流才会收尾（否则两边互等）
      this.clearLateRelease(state);
      state.releaseInput();
    } else {
      this.armLateRelease(state);
    }
    const resultError = resultErrorOf(message);
    if (resultError !== null) throw new Error(resultError);
    // 错误已被拦下，走到这里只可能是正常成功回合。
    // 终稿同样可能带 `<think>` 段（chat.final 与评估读的就是它），按正文口径剥掉
    if (message.subtype === 'success') state.output = splitLeadingThinkBlocks(message.result ?? '').text;
  }

  /** 后台任务在跑时 result 不是终点：挂兜底收口，防止后台任务永不结束把 run 一起拖住。 */
  private armLateRelease(state: RunState): void {
    this.clearLateRelease(state);
    state.lateReleaseTimer = setTimeout(() => {
      state.lateReleaseTimer = null;
      state.releaseInput();
    }, LATE_RELEASE_CEILING_MS);
    // 兜底计时不拖住进程退出：关服时不该为了这个定时器多等
    state.lateReleaseTimer.unref?.();
  }

  private clearLateRelease(state: RunState): void {
    if (state.lateReleaseTimer === null) return;
    clearTimeout(state.lateReleaseTimer);
    state.lateReleaseTimer = null;
  }

  /** 半截内容补落一条终稿：不补的话，中止后刷新只看得见那条 user 消息 */
  private async flushPending(ctx: EngineContext, pending: Record<'text' | 'thinking', string>): Promise<void> {
    for (const type of ['text', 'thinking'] as const) {
      // 只有空白等同没有（与 assistantDraftOf 同一口径；否则中止后会补落一条空文本）
      if (pending[type].trim() === '') continue;
      const draft: MessageDraft = { role: 'assistant', type, content: { text: pending[type] } };
      // 中止时攒下的是原始增量（含 `<think>` 标签），与正常落库同一口径拆开
      for (const piece of splitDraftThink(draft)) await ctx.emit({ type: 'message', draft: piece });
    }
  }

  /** 首条消息之后保持不返回：链路一关，审批与控制方法就都失效。 */
  private async *heldPrompt(text: string, runFinished: Promise<void>): AsyncGenerator<ClaudeUserMessage> {
    yield { type: 'user', message: { role: 'user', content: text }, parent_tool_use_id: null };
    await runFinished;
  }
}

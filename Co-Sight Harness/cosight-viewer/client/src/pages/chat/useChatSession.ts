// SPDX-License-Identifier: Apache-2.0
/**
 * @file useChatSession.ts
 * @description `/chat` 页面的会话逻辑 hook。
 *
 * 与 `pages/RunPage.tsx` 的关系:本文件的**行为**照搬自 RunPage(WS 事件注册、
 * 首轮发送、会话级 switch、续聊、审批/交互回写、中止),但组织成一个 hook,
 * 并补上 RunPage 缺失的卸载清理。RunPage 本身不做任何修改,两者独立共存。
 *
 * 协议(开源版按 smart-factory 面):
 * - 首帧 `send`:`{ prompt, agentId, modelId? }` —— 服务端建会话并起第一轮
 * - 续聊 `send`:`{ prompt, sessionId }` —— **不带模型**
 * - 不再有 `versionId`;run 结束后切模型走 `model.switch`,`mode/effort.switch` 仍不支持
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchAgentDetail, fetchAgentPickerPage, fetchModels } from "../../api/agent-api";
import type { Agent, AgentCommand, AgentSkill, AgentVersion } from "../../api/agent-api";
import {
  getChatSocket,
  type ChatSocket,
  type ConnectionState,
  type EventMessage,
} from "../../api/chat-socket";
import type { DropdownOption } from "../../components/Dropdown";
import { toWire } from "../../attachments/wire";
import type { AttachmentRef, MessageFile } from "../../attachments/types";
import {
  fetchAgentRuntimeSessionOutcome,
  fetchRunDetail,
  fetchSessionIdByResumeSessionId,
  fetchSessionMessages,
} from "./session-api";
import type { ServiceMessage } from "./session-api";
import { localizeRunReason } from "./run-reasons";
import { answerDraftOf, answerValuesOf } from "../../lib/tool-answers";
import type { ToolAnswerValue } from "../../lib/tool-answers";

export type { ToolAnswerValue } from "../../lib/tool-answers";

// ─── 公开类型 ───

/** 消息流里的一条消息。tool 角色承载工具调用与结果。 */
export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  timestamp: number;
  toolName?: string;
  toolInput?: Record<string, unknown>;
  toolOutput?: unknown;
  toolError?: boolean;
  /** 历史里只有 tool_use、没有配对结果（如 run 被中止）：卡片显示 pending。 */
  toolPending?: boolean;
  /** 这条消息带的附件；`name` 是服务端返回的绝对路径。 */
  files?: MessageFile[];
  /**
   * 系统事件（连接断开/恢复、上一轮终止原因、run 失败）。
   *
   * 连接类事件只存在内存；run 失败来自服务端落库的 `system/error` 消息，
   * 恢复会话时由 `messages/list` 重新渲染。
   */
  system?: boolean;
  /** `system` 中的错误变体：对话流内红框展示，而不是灰色状态提示。 */
  systemError?: boolean;
  /** 该消息所属 run；run 失败时 `message` 帧与 `chat.error` 帧靠它去重。 */
  runId?: string;
}

/** 正在执行中的工具调用。 */
export interface ToolExecution {
  toolCallId: string;
  toolName: string;
  input: Record<string, unknown>;
  status: "executing" | "executed";
  output?: unknown;
  isError?: boolean;
}

/** 审批请求。 */
export interface ApprovalRequest {
  approvalId: string;
  sessionId: string;
  runId: string;
  toolName: string;
  title: string;
  description: string;
  input: Record<string, unknown>;
  options: Array<{ value: string; label: string; enLabel?: string }>;
  expiresAt?: number;
}

/** 交互式工具(如 AskUserQuestion)抛出的问题。 */
export interface InteractiveQuestion {
  question: string;
  header?: string;
  multiSelect: boolean;
  options: Array<{ label: string; description?: string }>;
}

/** 交互式工具请求。 */
export interface InteractiveTool {
  toolCallId: string;
  toolName: string;
  input: { questions: InteractiveQuestion[] };
  timeout?: number;
}

/** composer 上展示的已选智能体(含解析出的版本)。单选,重选即替换。 */
/**
 * 选择智能体时前端已经拿到的摘要（列表 / 搜索结果）。
 *
 * 首屏只有前 N 个，搜索选中的智能体可能不在 `agents` 里；把摘要一起传进来，
 * chip 可以直接显示名称/图标，不用先闪一下 `agt_…` 再等详情返回。
 */
export type AgentChoice = Pick<
  Agent,
  "id" | "name" | "icon" | "dir" | "runtimeDir" | "workspaceId" | "source"
>;

export interface SelectedAgent {
  id: string;
  name: string;
  icon?: string;
  description?: string;
  /** 解析中或不可用时为 null;为 null 时禁止发送 */
  versionId: string | null;
  versionName?: string;
  /** 正在拉取版本列表 */
  resolving: boolean;
  /** 智能体根目录;用于定位本次对话的 runtime 产物目录 */
  dir?: string;
  /** 运行时工作目录(会话 cwd);会话内相对路径的解析根,优先于 `dir` 推导 */
  runtimeDir?: string;
  /** 所属工作区 id;`dir` 反推不出工作区时用它向框架查目录 */
  workspaceId?: string;
  /** `builtin` 表示内置智能体:runtime cwd 就是 `dir` */
  source?: string;
  /** 详情接口带回的斜杠命令（列表项没有，解析完成后补齐） */
  commands?: AgentCommand[];
  /** 详情接口带回的技能；同样以 `/<name>` 调用 */
  skills?: AgentSkill[];
}

// ─── 常量 ───

/** 智能体二级面板在无搜索词时展示的数量。 */
export const AGENT_PICKER_LIMIT = 5;

/** 需要注册到 socket 的全部事件方法。顺序不影响行为。 */
const HANDLER_METHODS = [
  "chat.delta",
  "message",
  "chat.final",
  "chat.error",
  "chat.aborted",
  "interactive.timeout",
  "approval.request",
  "tool.interactive",
  "tool.executing",
  "tool.executed",
  "session.status",
  // 会话设置变更（model.switch 成功、其他窗口或 REST 更新）
  "settings.changed",
  // 连接状态（connected / connecting / disconnected / error），用于断线横幅与重连后自愈
  "stateChange",
] as const;

// ─── 纯函数 ───

/**
 * 从版本列表里挑出要用的版本:URL 指定的优先(须属于该智能体),
 * 否则取第一个。开源版通常只有一个版本;多个也取第一个。
 */
export function resolveVersion(
  versions: AgentVersion[],
  preferredId?: string | null,
): AgentVersion | null {
  if (versions.length === 0) return null;
  if (preferredId) {
    const preferred = versions.find((version) => version.id === preferredId);
    if (preferred) return preferred;
  }
  return versions[0] ?? null;
}

/** 把 unknown 收窄成可展示的错误文案。 */
function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * 取服务端错误的 messageKey。
 *
 * `ChatSocketError` 保留了这个字段；这里用鸭子类型判定，测试里构造的普通错误对象也能识别。
 */
function errorMessageKeyOf(error: unknown): string | null {
  if (typeof error !== "object" || error === null) return null;
  const key = (error as { messageKey?: unknown }).messageKey;
  return typeof key === "string" ? key : null;
}

/** 构造一条本地乐观消息。 */
function localMessage(
  role: ChatMessage["role"],
  content: string,
  files?: MessageFile[],
): ChatMessage {
  return {
    id: `msg_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
    role,
    content,
    timestamp: Date.now(),
    ...(files !== undefined && files.length > 0 ? { files } : {}),
  };
}

/** `content.files` → 消息附件；形状不对的条目直接跳过。 */
function messageFilesOf(value: unknown): MessageFile[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const files: MessageFile[] = [];
  for (const item of value) {
    if (typeof item !== "object" || item === null) continue;
    const id = (item as { id?: unknown }).id;
    const name = (item as { name?: unknown }).name;
    if (typeof id !== "string" || typeof name !== "string") continue;
    files.push({ id, name });
  }
  return files.length > 0 ? files : undefined;
}

/** 附件集合的稳定 key：用于判断服务端回执是不是自己这条乐观消息。 */
function filesKey(files?: MessageFile[]): string {
  return (files ?? [])
    .map((file) => file.name)
    .sort()
    .join("\u0000");
}

/**
 * 按服务端消息 id upsert 一条助手正文。
 *
 * 实时链路里同一段正文会先以 `chat.delta` 流式展示，再以原生 `message` 落库；
 * `chat.final` 还可能带同一个 `messageId` 再确认一次。统一按 id 覆盖，
 * 才不会出现同一段正文两份气泡。已存在的消息保留原时间戳。
 */
function upsertAssistantText(
  messages: ChatMessage[],
  id: string,
  content: string,
  timestamp: number,
): ChatMessage[] {
  const index = messages.findIndex((message) => message.id === id);
  if (index === -1) {
    // 空正文又没有可覆盖的消息：没有可展示的内容，不制造空气泡
    return content === "" ? messages : [...messages, { id, role: "assistant", content, timestamp }];
  }
  const existing = messages[index]!;
  const next = [...messages];
  // 终稿 content 异常为空时保留已有正文，避免把已展示的内容清掉
  next[index] = {
    ...existing,
    content: content === "" ? existing.content : content,
  };
  return next;
}

/**
 * 按 id upsert 一条挂起请求（审批 / 交互）。
 *
 * 服务端支持多条挂起并存，且每次订阅握手后都会补发当前全部挂起（4.06 §4.1），
 * 同一条请求可能重复到达：按 id 覆盖而不是无脑追加，重放不会产生重复卡。
 * 新到的请求追加在队尾，未结算的旧请求不会被挤掉。
 */
function upsertByKey<T>(list: T[], item: T, keyOf: (item: T) => string): T[] {
  const key = keyOf(item);
  const index = list.findIndex((entry) => keyOf(entry) === key);
  if (index === -1) return [...list, item];
  const next = [...list];
  next[index] = item;
  return next;
}

/** 按 id 移除一条挂起（应答 / 被其它窗口结算 / run 终态）；无匹配时返回原数组，避免无谓重渲染。 */
function removeByKey<T>(list: T[], key: string, keyOf: (item: T) => string): T[] {
  const next = list.filter((entry) => keyOf(entry) !== key);
  return next.length === list.length ? list : next;
}

/** 把历史里的 `tool_result` 按 `toolCallId` 建索引，供 `tool_use` 配对。 */
function pairToolResults(
  raw: ServiceMessage[],
): Map<string, { output: unknown; isError: boolean }> {
  const results = new Map<string, { output: unknown; isError: boolean }>();
  for (const message of raw) {
    if (message.type !== "tool_result") continue;
    const content = message.content;
    const toolCallId = typeof content.toolCallId === "string" ? content.toolCallId : "";
    if (toolCallId === "") continue;
    results.set(toolCallId, {
      output: content.output,
      isError: content.isError === true,
    });
  }
  return results;
}

/** 历史工具结果统一转成展示字符串（与实时 `tool.edited` 的落库口径一致）。 */
function toolOutputText(output: unknown): string {
  return typeof output === "string" ? output : JSON.stringify(output ?? "", null, 2);
}

/**
 * 把 REST `messages/list` 的消息转成消息流用的形状。
 *
 * - `text` → 普通气泡
 * - `tool_use` → 工具卡（id 用 `tool_<toolCallId>`，与实时 `tool.edited` 同 id，
 *   订阅期间重复到达时可天然去重）；结果按 `toolCallId` 配对合并进同一张卡
 * - `system` + `error` → 对话流内的错误卡片（服务端 `failRun` 落库并广播的那条）；
 *   恢复会话时必须渲染，否则只能看到用户输入、看不到上一轮为什么失败
 * - `thinking` / `approval` / `tool_interactive` 暂不渲染
 *   （实时链路同样不占位；挂起的审批由 subscribe 补发后单独渲染）
 * - 孤立的 `tool_result`（找不到对应调用）直接跳过，不制造假卡片
 */
function historyToChatMessages(raw: ServiceMessage[]): ChatMessage[] {
  const results = pairToolResults(raw);
  const messages: ChatMessage[] = [];

  for (const message of raw) {
    const timestamp = Date.parse(message.createdAt);
    const time = Number.isFinite(timestamp) ? timestamp : Date.now();

    if (message.role === "system" && message.type === "error") {
      const text = message.content.message;
      if (typeof text !== "string" || text === "") continue;
      messages.push({
        id: message.id,
        role: "assistant",
        system: true,
        systemError: true,
        ...(message.runId !== null ? { runId: message.runId } : {}),
        content: text,
        timestamp: time,
      });
      continue;
    }

    if (message.type === "text") {
      const text = message.content.text;
      if (typeof text !== "string") continue;
      const files = messageFilesOf(message.content.files);
      messages.push({
        id: message.id,
        role: message.role === "user" ? "user" : "assistant",
        content: text,
        timestamp: time,
        ...(files !== undefined ? { files } : {}),
      });
      continue;
    }

    if (message.type === "tool_use") {
      const content = message.content;
      const toolCallId = typeof content.toolCallId === "string" ? content.toolCallId : "";
      if (toolCallId === "") continue;
      const result = results.get(toolCallId);
      messages.push({
        id: `tool_${toolCallId}`,
        role: "tool",
        content: result ? toolOutputText(result.output) : "",
        timestamp: time,
        toolName: typeof content.toolName === "string" ? content.toolName : "tool",
        toolInput:
          content.input && typeof content.input === "object"
            ? (content.input as Record<string, unknown>)
            : {},
        toolOutput: result?.output,
        toolError: result?.isError ?? false,
        toolPending: result === undefined,
      });
    }
  }

  return messages;
}

/**
 * 合并历史与"查询期间已到达的实时消息"。
 *
 * 订阅早于历史查询，因此实时事件可能先把消息写进列表。历史作为基底，
 * 实时消息中 id 不在历史里的追加在后；同 id 以历史为准（内容相同，只保留一份）。
 */
function mergeHistoryWithLive(history: ChatMessage[], live: ChatMessage[]): ChatMessage[] {
  if (live.length === 0) return history;
  const ids = new Set(history.map((message) => message.id));
  const extra = live.filter((message) => !ids.has(message.id));
  return extra.length === 0 ? history : [...history, ...extra];
}

/** 实时 user/text 消息 → 列表项；形状不对返回 null。 */
function toUserChatMessage(payload: Record<string, unknown>): ChatMessage | null {
  const id = typeof payload.id === "string" ? payload.id : "";
  const content = payload.content;
  // 实时事件里 content 是 { text }；兼容历史那种拍平后的字符串，避免形状变化时静默丢消息
  const contentObject =
    typeof content === "object" && content !== null
      ? (content as Record<string, unknown>)
      : undefined;
  const text = typeof content === "string" ? content : contentObject?.text;
  if (id === "" || typeof text !== "string") return null;
  const parsed = typeof payload.createdAt === "string" ? Date.parse(payload.createdAt) : NaN;
  const files = messageFilesOf(contentObject?.files);
  return {
    id,
    role: "user",
    content: text,
    timestamp: Number.isFinite(parsed) ? parsed : Date.now(),
    ...(files !== undefined ? { files } : {}),
  };
}

/**
 * 把服务端用户消息并入列表：
 * 1. 发送方有本地乐观消息 → 原地替换（保持位置，换成服务端 id）；
 * 2. 服务端 id 已存在 → 幂等跳过（事件与响应重复到达都不会多一条）；
 * 3. 其它窗口 → 追加。
 */
function reconcileUserMessage(
  prev: ChatMessage[],
  message: ChatMessage,
  pendingId: string | null,
): ChatMessage[] {
  if (pendingId !== null) {
    const index = prev.findIndex((item) => item.id === pendingId);
    if (index !== -1) {
      const next = prev.slice();
      next[index] = message;
      return next;
    }
  }
  if (prev.some((item) => item.id === message.id)) return prev;
  return [...prev, message];
}

/**
 * 恢复会话时拉取的历史条数。
 *
 * 历史里包含 tool_use / tool_result（可能一条工具调用就占两条），
 * 取 50 会让恢复后能看到的对话轮次明显变少，所以按服务端上限取 200。
 */
const HISTORY_LIMIT = 200;

/**
 * 连续重连多少次后判定为"无法连接"。
 *
 * 退避 0.5/1/2/4/5…s，10 次约 40–50s；到点后 UI 切到离线态并给出手动入口，
 * 后台仍保持 5s 慢重试，服务恢复后会自动接回。
 */
const RECONNECT_OFFLINE_ATTEMPTS = 10;

/**
 * 列表刷新的节流窗口。
 *
 * 只约束**连续的 refresh**（打开下拉 / 恢复焦点可能连着触发），不约束首载：
 * 刚挂载完立刻打开下拉仍然要拉一次——那正是“宿主的设置弹窗刚改过模型”的场景。
 * 在途请求另有合并（见 `loadModels` / `loadAgents`），这一层只挡“刚拉过又拉”。
 */
const CATALOG_REFRESH_INTERVAL_MS = 1000;

// ─── Hook ───

export interface UseChatSessionResult {
  /** 全部智能体(带 icon,供 chip 与选择器用) */
  agents: Agent[];
  loadingAgents: boolean;
  /** 激活状态的模型 */
  models: DropdownOption[];
  loadingModels: boolean;
  selectedAgent: SelectedAgent | null;
  selectAgent: (
    agentId: string,
    preferredVersionId?: string | null,
    knownAgent?: AgentChoice,
  ) => Promise<void>;
  clearAgent: () => void;
  /**
   * 会话是否已建立。一旦建立就复用该会话,换智能体不会再生效 ——
   * 因此 UI 应在 `hasSession` 为 true 时禁用智能体选择,避免 chip 与后端不一致。
   */
  hasSession: boolean;

  modelId: string;
  /** 选择模型：新会话只改本地；已有会话在 run 结束后走 `model.switch`。 */
  setModelId: (id: string) => void;
  /** 已有会话的模型切换是否在途（悲观更新：确认前界面仍显示旧模型）。 */
  switchingModel: boolean;
  /**
   * 重新拉取智能体列表。
   *
   * 打开 `+` 的「智能体」二级菜单时调用：智能体是在别的页面/窗口里增删的，
   * 而对话 iframe 不会因此重建，列表只能在这里对齐。
   */
  refreshAgents: () => Promise<void>;
  /**
   * 重新拉取模型列表。
   *
   * 打开模型下拉时调用；页面重新获得焦点时也会自动调用一次（见 hook 内的
   * focus / visibilitychange 监听）。默认模型变化后靠它把预选值带过来。
   */
  refreshModels: () => Promise<void>;
  /** 模型列表后台刷新是否在途；只用于空列表时把「暂无数据」换成「加载中」。 */
  refreshingModels: boolean;

  messages: ChatMessage[];
  /** 恢复的历史是否已就绪（非恢复场景恒为 true） */
  historyReady: boolean;
  streamingContent: string;
  toolExecutions: ToolExecution[];
  /**
   * 当前挂起、尚未应答的审批，按到达顺序排列。
   *
   * 服务端可同时挂起多条（并行工具调用 / 子代理），因此这里必须是队列：
   * 只保留一条会让先到的审批丢失应答入口，引擎永远等不到放行。
   */
  pendingApprovals: ApprovalRequest[];
  /** 当前挂起的交互式提问，规则同 `pendingApprovals`。 */
  interactiveTools: InteractiveTool[];
  /** 交互答案：toolCallId → 问题原文 → 答案，多张交互卡互不干扰。 */
  toolAnswers: Record<string, Record<string, ToolAnswerValue>>;
  setToolAnswer: (toolCallId: string, question: string, value: ToolAnswerValue) => void;

  /** 会话已建立(已进入对话态) */
  isRunning: boolean;
  /**
   * 对话通道连接状态。非 `connected` 时 UI 应提示"正在重连"；
   * 重连成功后 hook 会自动重新订阅并补齐历史。
   */
  connectionState: ConnectionState;
  /** 已连续安排的重连次数；成功连接后归零。 */
  reconnectAttempts: number;
  /** 重连次数达到阈值：UI 显示"无法连接"并给出手动重连入口。 */
  isOffline: boolean;
  /** 手动立即重连（跳过退避等待）。 */
  reconnect: () => void;
  /** 一轮 run 进行中 */
  isLoading: boolean;
  error: string | null;
  clearError: () => void;
  /** 智能体与版本都就绪,可以发送 */
  canSend: boolean;

  /** 真正发出了才返回 true;被拒绝(未选智能体、空文本且无附件、重入)返回 false */
  send: (prompt: string, attachments?: AttachmentRef[]) => Promise<boolean>;
  stop: () => Promise<void>;
  respondApproval: (approvalId: string, decision: string) => void;
  respondTool: (toolCallId: string) => void;
}

export interface UseChatSessionParams {
  /** 入口参数:?agentId= */
  initialAgentId?: string | null;
  /** 与 agentId 搭配;缺省时取该智能体的第一个版本 */
  initialVersionId?: string | null;
  /** 恢复已有会话:?agentRuntimeSessionId=(会话菜单 / 会话详情跳转过来) */
  initialSessionId?: string | null;
  /** 反查入口:?resumeSessionId= —— 只有引擎 resume 标识时,先反查 sessionId 再恢复 */
  initialResumeSessionId?: string | null;
}

export function useChatSession({
  initialAgentId,
  initialVersionId,
  initialSessionId,
  initialResumeSessionId,
}: UseChatSessionParams = {}): UseChatSessionResult {
  const { t } = useTranslation();

  // ─── 数据 ───
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loadingAgents, setLoadingAgents] = useState(true);
  const [models, setModels] = useState<DropdownOption[]>([]);
  const [loadingModels, setLoadingModels] = useState(true);
  /** 后台刷新的在途标记：与首载的 `loadingModels` 分开，避免整块 UI 闪烁。 */
  const [refreshingModels, setRefreshingModels] = useState(false);

  // ─── 选择 ───
  const [selectedAgent, setSelectedAgent] = useState<SelectedAgent | null>(null);
  const [modelId, setModelId] = useState("");
  /**
   * 已有会话的模型切换是否在途。
   *
   * 切换采用悲观更新：服务端确认前界面仍显示旧模型，期间锁住模型下拉与发送按钮，
   * 避免用户抢在新的 `model.switch` 生效前用旧模型发下一轮。
   */
  const [switchingModel, setSwitchingModel] = useState(false);

  // ─── 对话 ───
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streamingContent, setStreamingContent] = useState("");
  const [toolExecutions, setToolExecutions] = useState<ToolExecution[]>([]);
  const [pendingApprovals, setPendingApprovals] = useState<ApprovalRequest[]>([]);
  const [interactiveTools, setInteractiveTools] = useState<InteractiveTool[]>([]);
  const [toolAnswers, setToolAnswers] = useState<Record<string, Record<string, ToolAnswerValue>>>(
    {},
  );
  const [isRunning, setIsRunning] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /**
   * 对话通道连接状态。
   *
   * socket 断开时 UI 要明确提示"正在重连"，而不是等用户发送后只看到一句发送失败；
   * ChatSocket 会在未主动断开的前提下自动重连，重连成功由 `handleStateChange`
   * 触发重新订阅与历史补齐。
   */
  const [connectionState, setConnectionState] = useState<ConnectionState>(
    () => getChatSocket().state,
  );
  const [reconnectAttempts, setReconnectAttempts] = useState(
    () => getChatSocket().reconnectAttempts,
  );

  // ─── 稳定的“最新值”refs(供恒等稳定的回调读取) ───
  const tRef = useRef(t);
  const selectedAgentRef = useRef(selectedAgent);
  const modelIdRef = useRef(modelId);
  const pendingApprovalsRef = useRef(pendingApprovals);
  const interactiveToolsRef = useRef(interactiveTools);
  const toolAnswersRef = useRef(toolAnswers);
  const sessionIdRef = useRef<string | null>(null);
  const attachedSocketRef = useRef<ChatSocket | null>(null);
  /** 与 `switchingModel` 同步的同步值：回调里判重入，避免状态尚未来得及渲染时发第二条 switch。 */
  const switchingModelRef = useRef(false);
  /**
   * 用户是否在模型下拉里**手动选过**。
   *
   * 决定刷新时怎么处理 `modelId`：
   * - 没选过 → 跟随服务端最新的默认模型（改默认后能自动变）；
   * - 选过 → 保持用户的选择，只有该模型被删除时才回退到默认。
   *
   * 恢复会话时写入的 `detail.modelId` 不算“手选”，走内部 setter，不置这个标记。
   */
  const modelTouchedRef = useRef(false);
  /** 列表刷新的请求序号：慢响应回来时据此丢弃，避免盖掉新结果。 */
  const agentsRequestSeqRef = useRef(0);
  const modelsRequestSeqRef = useRef(0);
  /** 在途请求：同一列表的并发刷新合并成一次。 */
  const agentsInFlightRef = useRef<Promise<void> | null>(null);
  const modelsInFlightRef = useRef<Promise<void> | null>(null);
  /** 最近一次 **refresh** 的时间（首载不计），用于节流。 */
  const lastAgentsRefreshAtRef = useRef(0);
  const lastModelsRefreshAtRef = useRef(0);
  const preselectionDoneRef = useRef(false);
  /** 恢复会话只触发一次(StrictMode 双跑也不重复) */
  const resumeDoneRef = useRef(false);
  /** 组件是否仍挂载:跨 await 后据此放弃注册处理器 */
  const isMountedRef = useRef(true);
  /** 发送重入锁:同步置位,挡住同一 tick 内的重复点击 */
  const isSendingRef = useRef(false);
  /**
   * 发送方本地乐观消息：{ 本地 id, 正文 }。
   *
   * 服务端 user message 事件（或 send 响应里的 message）到达后据此原地替换；
   * 正文用于识别"这条事件是不是自己发的"，另一个窗口的提问不能吞掉自己的乐观消息。
   */
  const pendingUserMessageRef = useRef<{
    id: string;
    content: string;
    filesKey: string;
  } | null>(null);
  /** 会话已建立(用于驱动 hasSession) */
  const [hasSession, setHasSession] = useState(false);
  /**
   * 最近一次服务端给出的运行态（订阅快照 + 后续事件）。
   *
   * 恢复时 subscribe 的快照可能很快过时：查历史期间另一窗口起了新 run、
   * 或 run 进入审批，都会通过事件更新这里。收尾时以最新值为准，
   * 避免用旧快照把正在等的审批/运行错误解锁。
   */
  const runActiveRef = useRef(false);
  /**
   * 恢复的历史是否已就绪。
   *
   * 恢复时先订阅、后查历史：审批/交互事件可能先到，此时历史还是空的，
   * 直接渲染会让用户看到"空白 + 突兀的审批卡"。UI 用这个标志等到历史落位，
   * 再在同一帧里渲染历史与挂起卡片。非恢复场景恒为 true。
   */
  const [historyReady, setHistoryReady] = useState(true);
  /** 是否成功连接过：区分"首连失败"与"已建立的连接断了"，后者才插系统事件。 */
  const everConnectedRef = useRef(false);
  /** 当前是否处于"断线后尚未恢复"的区间：避免同一段断线重复插事件。 */
  const disconnectedNoticeRef = useRef(false);
  /** 已经提示过终态的 runId：重连/恢复重复触发时不重复插入。 */
  const lastRunNoticeRef = useRef<string | null>(null);
  /**
   * 已经渲染过 `system/error` 消息的 run。
   *
   * 服务端的顺序是「先广播落库的 message(system/error)，再广播 chat.error」；
   * 两帧都带同一个 runId，后者只负责收口，不能再追加一条重复错误。
   */
  const errorRunsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    tRef.current = t;
    selectedAgentRef.current = selectedAgent;
    modelIdRef.current = modelId;
    pendingApprovalsRef.current = pendingApprovals;
    interactiveToolsRef.current = interactiveTools;
    toolAnswersRef.current = toolAnswers;
  }, [t, selectedAgent, modelId, pendingApprovals, interactiveTools, toolAnswers]);

  const clearError = useCallback(() => setError(null), []);

  // ─── 列表加载:首载 + 可重复的刷新 ───

  /**
   * 应用一次模型列表结果。
   *
   * 会话已建立时模型是会话级属性（由 `detail.modelId` 还原并锁定），后台刷新
   * 只更新可选项，不能覆盖当前值。
   *
   * 未手选过时**始终跟随最新默认**：默认换了（或变成 null）就跟着换。原来的
   * `prev || defaultModelId` 是“只填空”，会让人改了默认模型之后一直看到旧值。
   */
  const applyModelOptions = useCallback(
    (result: { options: DropdownOption[]; defaultModelId: string | null }) => {
      setModels(result.options);
      if (sessionIdRef.current !== null) return;
      setModelId((prev) => {
        const stillExists = result.options.some((option) => option.id === prev);
        if (modelTouchedRef.current) {
          // 手选优先：还在就保留；被删了才回退到默认
          return stillExists ? prev : (result.defaultModelId ?? "");
        }
        // 没手选过：跟随默认；没有默认时留空，不回落第一项
        return result.defaultModelId ?? "";
      });
    },
    [],
  );

  /**
   * 拉取智能体首屏（前 `AGENT_PICKER_LIMIT` 个）。
   *
   * - `initial`：挂载首载，失败清空并结束 `loadingAgents`；
   * - `refresh`：打开「智能体」二级菜单时触发，失败**保留旧列表**（清空会让用户
   *   误以为智能体都没了），1 秒内重复触发只发一次，并复用已在途的请求。
   *
   * 搜索不再依赖这份列表：`+` 菜单的搜索词由 `ComposerMenu` 直接带 `keyword`
   * 查服务端，这里只负责默认展示的前 N 个。
   */
  const loadAgents = useCallback(async (mode: "initial" | "refresh" = "refresh") => {
    if (mode === "refresh") {
      if (agentsInFlightRef.current !== null) return agentsInFlightRef.current;
      if (Date.now() - lastAgentsRefreshAtRef.current < CATALOG_REFRESH_INTERVAL_MS) return;
      lastAgentsRefreshAtRef.current = Date.now();
    }
    const seq = ++agentsRequestSeqRef.current;

    const task = (async () => {
      try {
        const { items } = await fetchAgentPickerPage(
          { pageSize: AGENT_PICKER_LIMIT, status: "completed" },
          1,
        );
        // 只在仍是最后一次请求时落地：慢响应不能盖掉新结果
        if (seq !== agentsRequestSeqRef.current || !isMountedRef.current) return;
        setAgents(items);
      } catch (err) {
        /*
         * 失败也要守序号：首载可能挂到 10 秒才超时，期间用户打开菜单的刷新可能
         * 已经成功。旧请求的失败若照常清空，会把刚拿到的列表又抹掉（用户看到
         * “闪一下又没了”）。只有仍是最新一次请求，失败才有资格改状态。
         */
        if (seq !== agentsRequestSeqRef.current) return;
        if (mode === "initial") {
          if (isMountedRef.current) setAgents([]);
        } else {
          console.warn("[useChatSession] failed to refresh agents:", err);
        }
      } finally {
        if (mode === "initial" && isMountedRef.current) setLoadingAgents(false);
      }
    })();

    if (mode === "refresh") {
      agentsInFlightRef.current = task;
      void task.then(() => {
        if (agentsInFlightRef.current === task) agentsInFlightRef.current = null;
      });
    }
    await task;
  }, []);

  /**
   * 拉取模型列表。语义同 `loadAgents`，额外维护 `refreshingModels`：空列表时
   * 下拉用它显示「加载中」而不是一闪而过的「暂无数据」。
   */
  const loadModels = useCallback(
    async (mode: "initial" | "refresh" = "refresh") => {
      if (mode === "refresh") {
        if (modelsInFlightRef.current !== null) return modelsInFlightRef.current;
        if (Date.now() - lastModelsRefreshAtRef.current < CATALOG_REFRESH_INTERVAL_MS) return;
        lastModelsRefreshAtRef.current = Date.now();
        setRefreshingModels(true);
      }
      const seq = ++modelsRequestSeqRef.current;

      const task = (async () => {
        try {
          const result = await fetchModels();
          if (seq !== modelsRequestSeqRef.current || !isMountedRef.current) return;
          applyModelOptions(result);
        } catch (err) {
          // 同 loadAgents：旧请求的失败不能覆盖更新后的结果
          if (seq !== modelsRequestSeqRef.current) return;
          if (mode === "initial") {
            if (isMountedRef.current) setModels([]);
          } else {
            console.warn("[useChatSession] failed to refresh models:", err);
          }
        } finally {
          if (isMountedRef.current) {
            if (mode === "initial") setLoadingModels(false);
            else setRefreshingModels(false);
          }
        }
      })();

      if (mode === "refresh") {
        modelsInFlightRef.current = task;
        void task.then(() => {
          if (modelsInFlightRef.current === task) modelsInFlightRef.current = null;
        });
      }
      await task;
    },
    [applyModelOptions],
  );

  const refreshAgents = useCallback(() => loadAgents("refresh"), [loadAgents]);
  const refreshModels = useCallback(() => loadModels("refresh"), [loadModels]);

  /**
   * UI 的手动选择入口。
   *
   * - 新会话（首帧尚未发出）：只更新本地值，随首帧 `modelId` 下发；
   * - 已有会话且 run 已结束：悲观切换 —— 等服务端 `model.switch` 确认后才更新；
   * - run 进行中：忽略（下拉已锁，这里是防御）。
   *
   * 记录“用户已手选”，之后的默认值变化不再覆盖它；hook 内部（恢复会话）仍用
   * 原始 setter，不会被当成手选。
   */
  const selectModel = useCallback(
    (id: string) => {
      modelTouchedRef.current = true;
      if (id === modelIdRef.current) return;

      // 首帧尚未发出：模型随首帧下发，无需 switch。
      if (sessionIdRef.current === null) {
        modelIdRef.current = id;
        setModelId(id);
        return;
      }

      // 对话进行中不允许切换（UI 已禁用；防止事件/快捷键等旁路触发）。
      if (runActiveRef.current || switchingModelRef.current) return;

      const sessionId = sessionIdRef.current;
      switchingModelRef.current = true;
      setSwitchingModel(true);
      void (async () => {
        const socket = getChatSocket();
        try {
          if (socket.state !== "connected") await socket.connect();
          const response = await socket.switchModel(sessionId, id);
          const applied =
            typeof response.payload?.modelId === "string" && response.payload.modelId
              ? response.payload.modelId
              : id;
          modelIdRef.current = applied;
          setModelId(applied);
        } catch (err) {
          // 悲观切换：失败保持旧模型，用户可重新选择。
          setError(tRef.current("errors.switchModelFailed", { message: messageOf(err) }));
          // 模型可能已被删除/失去密钥，刷新列表让下拉反映真实可选项。
          void loadModels("refresh");
        } finally {
          switchingModelRef.current = false;
          setSwitchingModel(false);
        }
      })();
    },
    [loadModels],
  );

  /** 丢弃某张交互卡的草稿答案（卡被结算 / 移除时）。 */
  const forgetToolAnswers = useCallback((toolCallId: string) => {
    setToolAnswers((prev) => {
      if (!(toolCallId in prev)) return prev;
      const next = { ...prev };
      delete next[toolCallId];
      return next;
    });
  }, []);

  /**
   * 清空全部挂起与草稿答案。
   *
   * run 进入终态（完成 / 失败 / 中止）时统一走这里：挂起已经不可能再被应答，
   * 留着只会变成无入口的死卡。集中一处，新增终态分支时不会再漏。
   */
  const clearPendingResponses = useCallback(() => {
    setPendingApprovals([]);
    setInteractiveTools([]);
    setToolAnswers({});
  }, []);

  /** 往消息流追加一条本地系统事件（只存内存，不落服务端）。 */
  const appendSystemNotice = useCallback(
    (content: string, options: { systemError?: boolean; runId?: string } = {}) => {
      setMessages((prev) => [
        ...prev,
        {
          id: `sys_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
          role: "assistant",
          system: true,
          ...(options.systemError === true ? { systemError: true } : {}),
          ...(options.runId !== undefined ? { runId: options.runId } : {}),
          content,
          timestamp: Date.now(),
        },
      ]);
    },
    [],
  );

  /**
   * 重连/恢复后解释上一轮 run 的终态。
   *
   * 服务重启会把活跃 run 直接判 `failed / 服务重启`，但这条终态不会以事件或消息
   * 补发；普通失败则已经有 `system/error` 落库（服务端 `failRun`）。这里只补
   * "没有落过消息、且确实 failed"的那一种：
   * - 从最后一条消息拿到的 runId 可能属于子代理，要沿 `parentRunId` 走到顶层，
   *   否则子 run 被取消会被误报成"上一轮已终止"；
   * - `aborted` 是用户主动中止，`handleChatAborted` 已经提示过，不重复解释；
   * - 成功的 run 也记入去重表，避免每次重连都多查一次 `runs/detail`。
   */
  const noticeRunTerminal = useCallback(
    async (runId: string, history: ServiceMessage[]) => {
      if (runId === "" || lastRunNoticeRef.current === runId) return;

      // 子代理 run → 顶层 run：一次 run 的"是否完成"只由顶层决定
      let detail = await fetchRunDetail(runId);
      for (let depth = 0; detail?.parentRunId && depth < 8; depth += 1) {
        detail = await fetchRunDetail(detail.parentRunId);
      }
      if (!detail) return;

      // 无论成功/失败都记下来，重复重连不再查
      lastRunNoticeRef.current = detail.id;
      if (detail.status !== "failed") return;

      const alreadyReported = history.some(
        (message) =>
          (message.runId === detail!.id || message.runId === runId) &&
          message.role === "system" &&
          message.type === "error",
      );
      if (alreadyReported) return;

      const reason =
        localizeRunReason(detail.error, tRef.current) ?? tRef.current("common:unknown");
      appendSystemNotice(tRef.current("run.runTerminated", { reason }), {
        systemError: true,
        runId: detail.id,
      });
    },
    [appendSystemNotice],
  );

  /**
   * 重新订阅当前会话，用服务端状态校准本地运行态。
   *
   * 多窗口同一会话、或发送/应答撞上冲突之后，本地状态可能已经和服务端不一致；
   * 以 subscribe 返回的 status 为准，顺带会把仍在挂起的审批/交互补发回来。
   */
  const resyncRunState = useCallback(async () => {
    const sessionId = sessionIdRef.current;
    if (!sessionId) return;
    try {
      const response = await getChatSocket().subscribe(sessionId);
      setIsLoading(response?.payload?.status === "in_progress");
    } catch (err) {
      console.warn("[useChatSession] failed to resync session state:", err);
    }
  }, []);

  /**
   * 重连成功后的自愈：重新订阅 + 拉一次历史。
   *
   * - 先清空挂起集合：`subscribe` 只补发**当前仍 pending** 的请求，断线期间被别的
   *   窗口结算、或被服务端重启置 aborted 的条目不会出现在补发里，旧集合必须先丢；
   * - `subscribe` 保证挂起中的审批/提问被补发（协议 4.06 §4.1），断线时卡在审批的
   *   run 才能继续；
   * - `messages/list` 补齐断线期间已经落库的消息（按 id 去重合并，不覆盖实时到达的）；
   * - `status === "in_progress"` 时保持输入锁定，直到终态事件到达；否则用
   *   `runs/detail` 解释上一轮为何终止。
   *
   * 并发调用复用同一个 Promise：`stateChange` 与「发送前兜底重连」可能同时触发。
   */
  const resyncAfterReconnectRef = useRef<Promise<void> | null>(null);
  const resyncAfterReconnect = useCallback((): Promise<void> => {
    if (resyncAfterReconnectRef.current) return resyncAfterReconnectRef.current;

    const sessionId = sessionIdRef.current;
    const socket = getChatSocket();
    if (!sessionId || socket.state !== "connected") return Promise.resolve();

    // 断线期间的工具结果与半截流式文本已经不可信：工具行不能继续转圈。
    // 挂起集合不在这里清：订阅失败时要保留旧卡，用户仍可应答。
    setToolExecutions([]);
    setStreamingContent("");

    const task = (async () => {
      try {
        let status: unknown;
        try {
          const response = await socket.subscribe(sessionId);
          status = response?.payload?.status;
          runActiveRef.current = status === "in_progress";
          // 订阅成功后才清空挂起集合：`subscribe` 只补发**当前仍 pending** 的请求，
          // 断线期间被别的窗口结算、或被服务端重启置 aborted 的条目不会回来。
          // 清空发生在 subscribe 响应落定的微任务里，早于随后的补发帧事件。
          setPendingApprovals([]);
          setInteractiveTools([]);
          setToolAnswers({});
        } catch (err) {
          console.warn("[useChatSession] failed to replay pending requests after reconnect:", err);
        }

        let raw: ServiceMessage[] = [];
        let lastRunId: string | null = null;
        try {
          const page = await fetchSessionMessages(sessionId, HISTORY_LIMIT);
          raw = page?.items ?? [];
          setMessages((prev) => mergeHistoryWithLive(historyToChatMessages(raw), prev));
          lastRunId =
            raw.reduce<string | null>((found, message) => message.runId ?? found, null) ??
            socket.runId;
          if (lastRunId) socket.runId = lastRunId;
        } catch (err) {
          console.warn("[useChatSession] failed to refresh history after reconnect:", err);
        }

        // 先解锁输入，再解释终态：runs/detail 慢（最长 10s）不能拖住 composer
        setIsLoading(runActiveRef.current);
        // 订阅成功且会话已空闲才解释终态；in_progress / 订阅失败都等事件或下次恢复
        if (lastRunId && status === "completed") {
          void noticeRunTerminal(lastRunId, raw);
        }
      } finally {
        resyncAfterReconnectRef.current = null;
      }
    })();

    resyncAfterReconnectRef.current = task;
    return task;
  }, [noticeRunTerminal]);

  /** 应答失败：已被别处结算视为成功（弹窗已关），其余提示并重新校准运行态。 */
  const handleRespondFailure = useCallback(
    async (err: unknown) => {
      if (errorMessageKeyOf(err) === "error.conflict.message_settled") {
        // 另一个窗口已经处理过这条审批/交互：不报错，只把运行态校准回来
        await resyncRunState();
        return;
      }
      setError(tRef.current("errors.respondFailed", { message: messageOf(err) }));
      await resyncRunState();
    },
    [resyncRunState],
  );

  /**
   * 服务端已落库的用户消息：事件与 send 响应共用同一条归并逻辑。
   *
   * 只有正文与本地乐观消息一致时才消费它——内容不一致说明是另一个窗口发的提问，
   * 不能误删本窗口还在等回执的乐观消息。
   */
  const applyServerUserMessage = useCallback((message: ChatMessage) => {
    const pending = pendingUserMessageRef.current;
    // 正文与附件都相同才算「自己这条」：同一句话带不同文件时不能被误认。
    const consumePending =
      pending !== null &&
      pending.content === message.content &&
      pending.filesKey === filesKey(message.files);
    if (consumePending) pendingUserMessageRef.current = null;
    setMessages((prev) => reconcileUserMessage(prev, message, consumePending ? pending.id : null));
  }, []);

  // ─── WS 事件处理器(全部恒等稳定,便于 attach/detach 精确配对) ───

  const handleChatDelta = useCallback((event: EventMessage) => {
    const delta = (event.payload?.delta as string) || "";
    setStreamingContent((prev) => prev + delta);
  }, []);

  /**
   * 原生 `message` 事件：每段助手正文落库后到达（协议 §5.6）。
   *
   * 用整条内容提交该段、并结束当前流式段；下一段的 `chat.delta` 会重新开始累加。
   * 只处理 assistant + text：thinking 没有展示位，工具消息由 tool.* 事件负责。
   */
  const handleMessage = useCallback(
    (event: EventMessage) => {
      const payload = event.payload as Record<string, unknown> | undefined;
      if (!payload) return;

      /*
       * run 失败：服务端 `failRun` 先落库并广播 `system/error` 消息，再广播
       * `chat.error`。这条消息是恢复会话后唯一能看到失败原因的地方，必须进消息流；
       * 否则历史里只剩用户输入，错误只在一闪而过的横幅里。
       */
      if (payload.role === "system" && payload.type === "error") {
        const content = payload.content as { message?: unknown } | undefined;
        const text =
          typeof content?.message === "string"
            ? content.message
            : typeof payload.message === "string"
              ? payload.message
              : "";
        const runId = typeof payload.runId === "string" ? payload.runId : "";
        if (runId !== "") errorRunsRef.current.add(runId);

        if (text !== "") {
          const id =
            typeof payload.id === "string" && payload.id !== ""
              ? payload.id
              : `error_${runId !== "" ? runId : String(Date.now())}`;
          const parsed =
            typeof payload.createdAt === "string" ? new Date(payload.createdAt).getTime() : NaN;
          const timestamp = Number.isFinite(parsed) ? parsed : Date.now();
          setMessages((prev) =>
            prev.some((message) => message.id === id)
              ? prev
              : [
                  ...prev,
                  {
                    id,
                    role: "assistant",
                    system: true,
                    systemError: true,
                    ...(runId !== "" ? { runId } : {}),
                    content: text,
                    timestamp,
                  },
                ],
          );
        }

        runActiveRef.current = false;
        setIsLoading(false);
        setToolExecutions([]);
        clearPendingResponses();
        return;
      }

      // 审批 / 交互的**结算**事件：服务端在任意窗口应答后都会广播 settled 消息。
      // 本窗口据此关闭弹窗，多窗口同一会话时不会留下永远停在 pending 的弹窗。
      // pending 本身仍由 approval.request / tool.interactive 兼容帧负责，这里不重复处理。
      if (payload.type === "approval" || payload.type === "tool_interactive") {
        if (payload.status === "pending") return;
        // 用函数式更新而不是读 ref：同一 tick 内先收到 pending、再收到 settled 时，
        // ref 可能还没跟上渲染，只有基于最新 state 才能正确移除刚出现的卡片。
        // 只移除与消息类型对应的那一条：审批的 content 也带 toolCallId（血缘用），
        // 不能顺带改交互队列；反之亦然。
        const settledId = typeof payload.id === "string" ? payload.id : "";
        if (payload.type === "approval") {
          if (settledId !== "") {
            setPendingApprovals((prev) =>
              removeByKey(prev, settledId, (approval) => approval.approvalId),
            );
          }
        } else {
          const content = payload.content as { toolCallId?: unknown } | undefined;
          const settledToolCallId =
            typeof content?.toolCallId === "string" ? content.toolCallId : "";
          if (settledToolCallId !== "") {
            setInteractiveTools((prev) =>
              removeByKey(prev, settledToolCallId, (tool) => tool.toolCallId),
            );
            // 该交互已结算：连同它的草稿答案一起清掉
            forgetToolAnswers(settledToolCallId);
          }
        }
        return;
      }

      // 用户提问：服务端落库后广播给所有订阅者（发送方也收得到）。
      // 发送方据此把本地乐观消息替换成带服务端 id 的版本；其它窗口直接追加。
      if (payload.role === "user" && payload.type === "text") {
        const message = toUserChatMessage(payload);
        if (message) applyServerUserMessage(message);
        return;
      }

      if (payload.role !== "assistant" || payload.type !== "text") return;

      const id = typeof payload.id === "string" ? payload.id : "";
      const text = (payload.content as { text?: unknown } | undefined)?.text;
      if (id === "" || typeof text !== "string") return;

      const parsed =
        typeof payload.createdAt === "string" ? new Date(payload.createdAt).getTime() : NaN;
      const timestamp = Number.isFinite(parsed) ? parsed : Date.now();

      setMessages((prev) => upsertAssistantText(prev, id, text, timestamp));
      // 这段已经是整条消息，收掉流式占位；后续 delta 属于下一段
      setStreamingContent("");
    },
    [applyServerUserMessage, clearPendingResponses, forgetToolAnswers],
  );

  /**
   * 会话状态：服务端会广播 `in_progress` / `completed`。
   *
   * 它是"有没有活跃 run"的权威信号之一 —— 恢复会话、另一窗口起停 run 时都靠它
   * 驱动输入锁定，不能只看本地是否正在流式输出。
   */
  const handleSessionStatus = useCallback(
    (event: EventMessage) => {
      const status = event.payload?.status;
      if (status === "in_progress") {
        runActiveRef.current = true;
        setIsLoading(true);
        return;
      }
      if (status === "completed") {
        runActiveRef.current = false;
        setIsLoading(false);
        clearPendingResponses();
      }
    },
    [clearPendingResponses],
  );

  /**
   * 会话设置变更：本窗口的 `model.switch`、其他窗口或 REST 更新都会广播到同一会话。
   *
   * 只同步模型：`mode/effort` 在开源版不可改。用内部 setter，不置“手选”标记 ——
   * 这是服务端权威值，不是用户在当前下拉里的新选择。
   */
  const handleSettingsChanged = useCallback((event: EventMessage) => {
    const sessionId = event.payload?.sessionId;
    if (typeof sessionId !== "string" || sessionId !== sessionIdRef.current) return;
    const settings = event.payload?.settings as { modelId?: unknown } | undefined;
    const nextModelId = settings?.modelId;
    if (typeof nextModelId !== "string" || nextModelId === "") return;
    modelIdRef.current = nextModelId;
    setModelId(nextModelId);
  }, []);

  /**
   * 连接状态变化：断开时点亮"正在重连"横幅，重连成功后自动补订阅与历史。
   *
   * 只在已有会话时补数据：新建会话的首连由 `send` 自己完成，不需要多一次 subscribe。
   * 连接事件会记入消息流（本地系统事件）：已建立过的连接断开、恢复各记一条，
   * 首连失败不记（离线横幅已经说明问题，不需要在对话里制造噪音）。
   */
  const handleStateChange = useCallback(
    (event: EventMessage) => {
      const state = event.payload?.state;
      if (
        state !== "connecting" &&
        state !== "connected" &&
        state !== "disconnected" &&
        state !== "error"
      ) {
        return;
      }
      const socket = getChatSocket();
      setConnectionState(state);
      setReconnectAttempts(socket.reconnectAttempts);

      if (state === "connected") {
        if (everConnectedRef.current && disconnectedNoticeRef.current) {
          appendSystemNotice(tRef.current("run.reconnectedNotice"));
        }
        everConnectedRef.current = true;
        disconnectedNoticeRef.current = false;
        if (sessionIdRef.current) {
          void resyncAfterReconnect();
        }
        return;
      }

      if (state === "disconnected" || state === "error") {
        if (everConnectedRef.current && !disconnectedNoticeRef.current) {
          disconnectedNoticeRef.current = true;
          appendSystemNotice(tRef.current("run.connectionLost"));
        }
      }
    },
    [appendSystemNotice, resyncAfterReconnect],
  );

  const handleChatFinal = useCallback((event: EventMessage) => {
    const content = (event.payload?.content as string) || "";
    const messageId = typeof event.payload?.messageId === "string" ? event.payload.messageId : "";
    setStreamingContent("");

    setMessages((prev) => {
      // 终稿对应的落库消息：按 id 覆盖，不能追加第二份正文
      if (messageId !== "") return upsertAssistantText(prev, messageId, content, Date.now());
      // 纯工具回合：messageId 为 null，content 可能为空，不制造空气泡
      if (content === "") return prev;
      return [...prev, localMessage("assistant", content)];
    });

    runActiveRef.current = false;
    setIsLoading(false);
    // 一轮对话结束,清空工具执行状态
    setToolExecutions([]);
  }, []);

  const handleError = useCallback(
    (event: EventMessage) => {
      const payload = (event.payload ?? {}) as Record<string, unknown>;
      const code = typeof payload.code === "string" ? payload.code : "";
      const runId = typeof payload.runId === "string" ? payload.runId : "";
      const errMsg =
        event.error?.message ||
        (typeof payload.message === "string" ? payload.message : "") ||
        "Unknown error";
      console.error("[useChatSession] error event:", errMsg);

      runActiveRef.current = false;
      setIsLoading(false);
      // 与 final/aborted 保持一致：失败的 run 不会再有 tool.executed，执行中行必须收掉
      setToolExecutions([]);
      // run 失败时服务端会结算全部挂起；这里同步清空，避免结算事件丢失后留下死卡
      clearPendingResponses();

      /*
       * run 失败已经有落库的 `system/error` 消息（通常在本帧之前到达）：
       * 对话流里已经能看到错误，这里不再叠加顶部横幅。
       * 若消息帧丢失，则在消息流里补一条兜底错误，仍保证可见、可追溯。
       */
      if (code === "RUN_ERROR") {
        if (runId !== "" && errorRunsRef.current.has(runId)) return;

        const id = runId !== "" ? `error_${runId}` : `error_${String(Date.now())}`;
        if (runId !== "") errorRunsRef.current.add(runId);
        setMessages((prev) =>
          prev.some((message) => message.id === id)
            ? prev
            : [
                ...prev,
                {
                  id,
                  role: "assistant",
                  system: true,
                  systemError: true,
                  ...(runId !== "" ? { runId } : {}),
                  content: errMsg,
                  timestamp: Number.isFinite(event.timestamp) ? event.timestamp : Date.now(),
                },
              ],
        );
        return;
      }

      setError(tRef.current("errors.errorOccurred", { message: errMsg }));
    },
    [clearPendingResponses],
  );

  const handleChatAborted = useCallback(
    (event: EventMessage) => {
      const payload = event.payload as Record<string, unknown>;
      const reason =
        localizeRunReason(payload?.reason, tRef.current) ?? tRef.current("errors.runAborted");
      setStreamingContent("");
      runActiveRef.current = false;
      setIsLoading(false);
      setToolExecutions([]);
      clearPendingResponses();
      setMessages((prev) => [
        ...prev,
        localMessage("assistant", `[${tRef.current("common:errors.aborted")}] ${reason}`),
      ]);
    },
    [clearPendingResponses],
  );

  const handleInteractiveTimeout = useCallback(
    (event: EventMessage) => {
      const payload = event.payload as Record<string, unknown>;
      const toolName = payload?.toolName as string;
      const timedOutId = typeof payload?.toolCallId === "string" ? payload.toolCallId : "";
      console.warn("[useChatSession] interactive timeout:", toolName);
      if (timedOutId === "") {
        // 事件不带 id：无法定位是哪一张，只能整体收口
        clearPendingResponses();
        runActiveRef.current = false;
        setIsLoading(false);
      } else {
        // 只收掉超时的那一张：并行提问时其它卡仍在等服务端应答
        const remaining = removeByKey(
          interactiveToolsRef.current,
          timedOutId,
          (tool) => tool.toolCallId,
        );
        setInteractiveTools(remaining);
        forgetToolAnswers(timedOutId);
        // 仍有挂起（其它提问或审批）说明 run 没结束，不能解锁输入
        const stillPending = remaining.length > 0 || pendingApprovalsRef.current.length > 0;
        runActiveRef.current = stillPending;
        setIsLoading(stillPending);
      }
      setError(
        tRef.current("errors.toolTimeout", {
          toolName: toolName || tRef.current("unknown"),
        }),
      );
    },
    [clearPendingResponses, forgetToolAnswers],
  );

  const handleApprovalRequest = useCallback((event: EventMessage) => {
    const approval = event.payload as unknown as ApprovalRequest;
    if (!approval?.approvalId) return;
    // 追加到队列，不覆盖：同时挂起的多条审批各自都需要应答入口
    setPendingApprovals((prev) => upsertByKey(prev, approval, (entry) => entry.approvalId));
    // 有挂起就说明 run 还活着：恢复会话等场景下本地 isLoading 可能是 false，必须补上
    runActiveRef.current = true;
    setIsLoading(true);
  }, []);

  const handleToolInteractive = useCallback((event: EventMessage) => {
    const tool = event.payload as unknown as InteractiveTool;
    if (!tool?.toolCallId) return;
    setInteractiveTools((prev) => upsertByKey(prev, tool, (entry) => entry.toolCallId));
    runActiveRef.current = true;
    setIsLoading(true);
  }, []);

  const handleToolExecuting = useCallback((event: EventMessage) => {
    const payload = event.payload as Record<string, unknown>;
    setToolExecutions((prev) => [
      ...prev,
      {
        toolCallId: payload?.toolCallId as string,
        toolName: payload?.toolName as string,
        input: payload?.input as Record<string, unknown>,
        status: "executing",
      },
    ]);
  }, []);

  const handleToolExecuted = useCallback((event: EventMessage) => {
    const payload = event.payload as Record<string, unknown>;
    const toolCallId = payload?.toolCallId as string;
    const output = payload?.output;

    // 从执行中列表移除,改为落到消息流
    setToolExecutions((prev) => prev.filter((item) => item.toolCallId !== toolCallId));
    setMessages((prev) => [
      ...prev,
      {
        id: `tool_${toolCallId}`,
        role: "tool",
        content: typeof output === "string" ? output : JSON.stringify(output, null, 2),
        timestamp: Date.now(),
        toolName: payload?.toolName as string,
        toolInput: payload?.input as Record<string, unknown>,
        toolOutput: output,
        toolError: payload?.isError as boolean,
      },
    ]);
  }, []);

  const handlers = useMemo(
    () => ({
      "chat.delta": handleChatDelta,
      message: handleMessage,
      "chat.final": handleChatFinal,
      "chat.error": handleError,
      "chat.aborted": handleChatAborted,
      "interactive.timeout": handleInteractiveTimeout,
      "approval.request": handleApprovalRequest,
      "tool.interactive": handleToolInteractive,
      "tool.executing": handleToolExecuting,
      "tool.executed": handleToolExecuted,
      "session.status": handleSessionStatus,
      "settings.changed": handleSettingsChanged,
      stateChange: handleStateChange,
    }),
    [
      handleChatDelta,
      handleMessage,
      handleChatFinal,
      handleError,
      handleChatAborted,
      handleInteractiveTimeout,
      handleApprovalRequest,
      handleToolInteractive,
      handleToolExecuting,
      handleToolExecuted,
      handleSessionStatus,
      handleSettingsChanged,
      handleStateChange,
    ],
  );

  /** 注册处理器(先 off 再 on,防止重复)。 */
  const attach = useCallback(
    (socket: ChatSocket) => {
      attachedSocketRef.current = socket;
      // 首连的 stateChange 早于 attach 发出（connect → attach），这里补一次当前状态，
      // 否则页面会一直显示"正在重连"横幅；同时补上 everConnected 标记，否则恢复会话
      // 后的第一次断线不会记系统事件。
      setConnectionState(socket.state);
      setReconnectAttempts(socket.reconnectAttempts);
      if (socket.state === "connected") everConnectedRef.current = true;
      for (const method of HANDLER_METHODS) {
        socket.off(method, handlers[method]);
        socket.on(method, handlers[method]);
      }
    },
    [handlers],
  );

  /** 注销本 hook 注册的处理器。 */
  const detachAttached = useCallback(() => {
    const socket = attachedSocketRef.current;
    if (!socket) return;
    for (const method of HANDLER_METHODS) {
      socket.off(method, handlers[method]);
    }
    attachedSocketRef.current = null;
  }, [handlers]);

  // 卸载时注销。刻意不调 resetChatSocket():那会掐断 RunPage 正要接管的会话。
  // 同时落下 isMountedRef,让仍在 await 中的 send 放弃注册处理器 —— 否则卸载后才
  // 执行的 attach 会把处理器挂在单例上,而清理已经跑过了,永远注销不掉。
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      detachAttached();
    };
  }, [detachAttached]);

  /**
   * 挂载时就订阅连接状态，而不是等 `attach`（send / resume 之后才调用）。
   *
   * 共享的 socket 可能在上一个页面就已经建好、正在后台重连：如果只等 attach，
   * 新开的 `/chat` 会拿到一个过期的离线快照，自动重连成功后也不会刷新，
   * 首屏发送按钮会一直禁用。这里只订阅 `stateChange`，不接管其它事件
   * （避免收到上一个会话的业务事件）。
   */
  useEffect(() => {
    const socket = getChatSocket();
    setConnectionState(socket.state);
    setReconnectAttempts(socket.reconnectAttempts);
    if (socket.state === "connected") everConnectedRef.current = true;
    socket.on("stateChange", handleStateChange);
    return () => socket.off("stateChange", handleStateChange);
  }, [handleStateChange]);

  // ─── 数据加载(幂等,StrictMode 双跑无副作用) ───
  // 序号守卫让先发后到的首载响应自动作废,不需要再维护一个 cancelled 标志。
  useEffect(() => {
    void loadAgents("initial");
    void loadModels("initial");
  }, [loadAgents, loadModels]);

  /**
   * 页面重新获得焦点 / 从后台回到前台时刷新模型列表。
   *
   * 宿主里的「模型设置」是弹窗，不换路由、不重建 iframe，模块拿不到变更事件；
   * 用户点回对话页时补拉一次，默认模型才能跟着变。
   *
   * 只在还没开聊时刷：会话建立后模型已锁定，没必要为锁定的列表发请求。
   * 智能体列表**不跟焦点刷**——它按 60/页翻完全部，代价远高于一次模型查询；
   * 改为打开 `+` 的智能体子菜单时拉（见 `refreshAgents`）。
   */
  useEffect(() => {
    const refresh = () => {
      if (sessionIdRef.current !== null) return;
      void loadModels("refresh");
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") refresh();
    };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [loadModels]);

  // ─── 选择智能体:立即出 chip,再异步解析版本 ───
  const selectAgent = useCallback(
    async (agentId: string, preferredVersionId?: string | null, knownAgent?: AgentChoice) => {
      setError(null);
      const listed =
        knownAgent?.id === agentId ? knownAgent : agents.find((item) => item.id === agentId);
      setSelectedAgent({
        id: agentId,
        name: listed?.name ?? agentId,
        icon: listed?.icon,
        versionId: null,
        resolving: true,
        dir: listed?.dir,
        runtimeDir: listed?.runtimeDir,
        workspaceId: listed?.workspaceId,
        source: listed?.source,
      });

      try {
        // fetchAgentDetail 出错时返回 null(不抛异常)
        const detail = await fetchAgentDetail(agentId);
        if (!detail || detail.versions.length === 0) {
          setSelectedAgent((prev) =>
            prev && prev.id === agentId ? { ...prev, versionId: null, resolving: false } : prev,
          );
          setError(tRef.current("agentUi.noAvailableVersion"));
          return;
        }

        const version = resolveVersion(detail.versions, preferredVersionId);
        setSelectedAgent((prev) =>
          prev && prev.id === agentId
            ? {
                ...prev,
                name: detail.name || prev.name,
                icon: detail.icon ?? prev.icon,
                description: detail.description,
                versionId: version?.id ?? null,
                versionName: version?.version,
                resolving: false,
                dir: detail.dir ?? prev.dir,
                runtimeDir: detail.runtimeDir ?? prev.runtimeDir,
                workspaceId: detail.workspaceId ?? prev.workspaceId,
                source: detail.source ?? prev.source,
                commands: detail.commands ?? prev.commands,
                skills: detail.skills ?? prev.skills,
              }
            : prev,
        );
      } catch (err) {
        console.error("[useChatSession] failed to resolve version:", err);
        setSelectedAgent((prev) =>
          prev && prev.id === agentId ? { ...prev, versionId: null, resolving: false } : prev,
        );
        setError(tRef.current("agentUi.noAvailableVersion"));
      }
    },
    [agents],
  );

  const clearAgent = useCallback(() => {
    setSelectedAgent(null);
  }, []);

  // 入口参数预选(只跑一次,StrictMode 双跑也不重复)
  useEffect(() => {
    if (preselectionDoneRef.current || !initialAgentId) return;
    preselectionDoneRef.current = true;
    void selectAgent(initialAgentId, initialVersionId);
  }, [initialAgentId, initialVersionId, selectAgent]);

  // ─── 恢复已有会话:?agentRuntimeSessionId= ───
  // 与 /run 的行为对齐:连上 socket、把 sessionId 装上、拉历史消息、进入对话态。
  // 「恢复的核心是能继续发消息」,所以历史或详情的失败都不阻断。
  const resumeSession = useCallback(
    async (sessionId: string) => {
      setError(null);
      setIsLoading(true);
      setMessages([]);
      setStreamingContent("");
      setIsRunning(true);
      setHistoryReady(false);
      runActiveRef.current = false;

      try {
        const socket = getChatSocket();
        if (socket.state !== "connected") {
          await socket.connect();
        }
        // 连接是异步的:期间组件可能已卸载,此时绝不能注册处理器
        if (!isMountedRef.current) return;

        attach(socket);
        sessionIdRef.current = sessionId;
        setHasSession(true);
        socket.sessionId = sessionId;

        // **先订阅再查历史**：订阅一生效，事件就不会丢；否则查询/连接的空窗里
        // 产生的 message / tool.* / approval.* 都没有补发渠道。
        // 服务端在 subscribe.result 之后会把该会话当前**已挂起**的
        // approval / tool_interactive 以兼容帧补发（4.06 §4.1），正在等应答的
        // 审批只能靠这一帧拿到；否则后端 run 卡住、再发消息会吃 CONFLICT。
        // 响应里的 status 是权威运行态：in_progress = 还有活跃 run（可能在等审批，
        // 也可能正在执行），必须保持输入锁定直到收到终态事件。
        let sessionStatus: unknown;
        try {
          const subscribed = await socket.subscribe(sessionId);
          sessionStatus = subscribed?.payload?.status;
          runActiveRef.current = sessionStatus === "in_progress";
        } catch (subscribeError) {
          console.warn("[useChatSession] failed to replay pending requests:", subscribeError);
        }

        // 还原智能体与模型,让锁定后的展示是真实的而不是默认值。
        // 404 说明会话已被清理：不能继续挂着一个空会话，否则界面看起来
        // “恢复了但什么都没有”。网络/5xx 只是暂时读不到，沿用旧行为继续恢复。
        const outcome = await fetchAgentRuntimeSessionOutcome(sessionId);
        if (outcome.status === "missing") {
          setError(tRef.current("errors.resumeSessionGone"));
          sessionIdRef.current = null;
          setHasSession(false);
          setIsRunning(false);
          runActiveRef.current = false;
          return;
        }
        if (outcome.status === "ok") {
          if (outcome.detail.modelId) setModelId(outcome.detail.modelId);
          if (outcome.detail.agentId) await selectAgent(outcome.detail.agentId);
        }

        try {
          // 历史走 REST messages/list：WS history 把 content 拍平成字符串，
          // 丢掉了 toolName / toolCallId / isError，无法还原工具卡。
          const page = await fetchSessionMessages(sessionId, HISTORY_LIMIT);
          const raw = page?.items ?? [];
          // 订阅早于查询，这段时间实时事件可能已经写进 messages：按 id 去重后追加，
          // 不能直接覆盖，否则会吞掉刚到达的消息。
          setMessages((prev) => mergeHistoryWithLive(historyToChatMessages(raw), prev));
          // 历史消息都带 runId:拾回最后一个,这样刷新前就开跑的 run 仍可被中止
          const lastRunId = raw.reduce<string | null>(
            (found, message) => message.runId ?? found,
            null,
          );
          if (lastRunId) socket.runId = lastRunId;
          // 恢复时上一轮可能已经被服务重启杀掉：终态不会补发，用 runs/detail 补解释。
          // 不 await：解释是锦上添花，不能拖慢 historyReady / 输入解锁。
          if (lastRunId && sessionStatus === "completed") {
            void noticeRunTerminal(lastRunId, raw);
          }
        } catch (historyError) {
          // 历史拉取失败不阻断恢复
          console.warn("[useChatSession] failed to load history:", historyError);
        }
      } catch (err) {
        console.error("[useChatSession] failed to resume session:", err);
        setError(tRef.current("errors.resumeFailed", { message: messageOf(err) }));
        sessionIdRef.current = null;
        setHasSession(false);
        setIsRunning(false);
        runActiveRef.current = false;
      } finally {
        // 历史失败也要放行：否则占位/隐藏的审批卡会一直卡住，用户无法继续。
        setHistoryReady(true);
        // 用最新运行态而非 subscribe 快照：查询期间到来的 session.status /
        // approval.request 已经把它刷新过。
        setIsLoading(runActiveRef.current);
      }
    },
    [attach, noticeRunTerminal, selectAgent],
  );

  // 只跑一次(StrictMode 双跑也不重复)
  useEffect(() => {
    if (resumeDoneRef.current || !initialSessionId) return;
    resumeDoneRef.current = true;
    void resumeSession(initialSessionId);
  }, [initialSessionId, resumeSession]);

  // 反查入口:只有引擎 resume 标识时,先按 `sessions/list?resumeSessionId=` 找 sessionId
  // (实际路径见 `session-api.ts`)。
  //
  // 反查为空时必须给出提示：看板里能看到很多**不是 cosight-harness 发起**的会话
  // （直接在 Claude Code CLI 里跑的），它们没有对应的 `sess_…`，若只是停在空态，
  // 用户会以为“点了恢复但没反应”。
  useEffect(() => {
    if (resumeDoneRef.current || initialSessionId || !initialResumeSessionId) return;
    resumeDoneRef.current = true;
    void (async () => {
      const sessionId = await fetchSessionIdByResumeSessionId(initialResumeSessionId);
      if (!isMountedRef.current) return;
      if (sessionId) {
        await resumeSession(sessionId);
        return;
      }
      // `resumeSessionId` 入口主要来自宿主侧栏「最近」：会话本身应存在，
      // 查不到多半是已被清理，不能用“是否由 cosight-harness 创建”的提示。
      setError(tRef.current("errors.resumeSessionGone"));
    })();
  }, [initialSessionId, initialResumeSessionId, resumeSession]);

  /**
   * 首轮:建会话并立即起第一个 run。返回是否已建立会话。
   *
   * 没有选中智能体时走 smart-factory 的**自由对话**：不传 `agentId`，
   * 服务端建一条目录会话（cwd = 当前工作区或 chatRoot），其余链路一致。
   */
  const startSession = useCallback(
    async (prompt: string, attachments: AttachmentRef[] = []): Promise<boolean> => {
      const agent = selectedAgentRef.current;
      // 首帧的 modelId 是服务端必填项:没有模型就别发出去,否则只会拿到一句 VALIDATION
      if (!modelIdRef.current) {
        setError(tRef.current("agentUi.selectModel"));
        return false;
      }
      setError(null);
      setIsLoading(true);
      setIsRunning(true);
      // 首轮 run 已起跑：模型切换要等它结束
      runActiveRef.current = true;
      const wire = toWire(attachments);
      const optimisticFiles = attachments.map<MessageFile>((file, index) => ({
        id: `local-${index}-${Date.now()}`,
        name: file.path ?? file.name,
      }));
      const optimistic = localMessage("user", prompt, optimisticFiles);
      pendingUserMessageRef.current = {
        id: optimistic.id,
        content: prompt,
        filesKey: filesKey(optimisticFiles),
      };
      setMessages([optimistic]);

      try {
        const socket = getChatSocket();
        if (socket.state !== "connected") {
          await socket.connect();
        }
        // 连接是异步的:期间组件可能已卸载,此时绝不能注册处理器
        if (!isMountedRef.current) return false;

        attach(socket);

        // 首帧:有智能体才传 agentId，否则是自由对话；模型只在这一帧传
        const response = await socket.createInstanceAndSend({
          ...(agent ? { agentId: agent.id } : {}),
          ...(modelIdRef.current ? { modelId: modelIdRef.current } : {}),
          prompt,
          ...(wire.length > 0 ? { attachments: wire } : {}),
        });

        const sessionId = response.payload?.sessionId as string | undefined;
        if (!sessionId) {
          throw new Error("no sessionId in send.result");
        }

        sessionIdRef.current = sessionId;
        setHasSession(true);
        socket.sessionId = sessionId;
        socket.runId = (response.payload?.runId as string) ?? null;

        // 正常情况 user 事件已先到；响应里的同一条消息作为兜底，按 id 幂等
        const persisted = response.payload?.message as Record<string, unknown> | undefined;
        const serverMessage = persisted ? toUserChatMessage(persisted) : null;
        if (serverMessage) applyServerUserMessage(serverMessage);

        return true;
      } catch (err) {
        console.error("[useChatSession] failed to start session:", err);
        const stillPending = pendingUserMessageRef.current?.id === optimistic.id;
        if (stillPending) {
          pendingUserMessageRef.current = null;
          // 消息没发出去：撤掉乐观消息，界面不留下一条实际不存在的用户发言
          setMessages((prev) => prev.filter((message) => message.id !== optimistic.id));
        }
        setError(tRef.current("errors.startFailed", { message: messageOf(err) }));
        setIsLoading(false);
        runActiveRef.current = false;
        // 会话没建起来就别留在对话态,否则只留一条孤立的用户消息
        if (!sessionIdRef.current) setIsRunning(false);
        return false;
      }
    },
    [applyServerUserMessage, attach],
  );

  /** 续聊:复用已有会话。 */
  const continueSession = useCallback(
    async (prompt: string, attachments: AttachmentRef[] = []): Promise<boolean> => {
      const socket = getChatSocket();
      const sessionId = sessionIdRef.current;
      if (!sessionId) {
        setError(tRef.current("agentUi.startSessionFirst"));
        return false;
      }

      // 断线后先自愈一次再发：重连 + 重新订阅（补挂起审批），而不是让用户回观测页恢复。
      // 重连本身是幂等的；失败才提示，避免把"连接断了"误报成"会话没建立"。
      if (socket.state !== "connected") {
        try {
          await socket.connect();
        } catch {
          setError(tRef.current("errors.reconnectFailed"));
          return false;
        }
        await resyncAfterReconnect();
      }

      setError(null);
      setIsLoading(true);
      // 新一轮 run 已起跑：模型切换要等它结束
      runActiveRef.current = true;
      const wire = toWire(attachments);
      const optimisticFiles = attachments.map<MessageFile>((file, index) => ({
        id: `local-${index}-${Date.now()}`,
        name: file.path ?? file.name,
      }));
      const optimistic = localMessage("user", prompt, optimisticFiles);
      pendingUserMessageRef.current = {
        id: optimistic.id,
        content: prompt,
        filesKey: filesKey(optimisticFiles),
      };
      setMessages((prev) => [...prev, optimistic]);

      try {
        const response = await socket.sendMessage({
          prompt,
          sessionId,
          ...(wire.length > 0 ? { attachments: wire } : {}),
        });
        // 每次发送后端可能生成新的 runId
        const newRunId = response.payload?.runId as string | undefined;
        if (newRunId) {
          socket.runId = newRunId;
        }

        // 正常情况 user 事件已先到；响应里的同一条消息作为兜底，按 id 幂等
        const persisted = response.payload?.message as Record<string, unknown> | undefined;
        const serverMessage = persisted ? toUserChatMessage(persisted) : null;
        if (serverMessage) applyServerUserMessage(serverMessage);

        return true;
      } catch (err) {
        console.error("[useChatSession] failed to send message:", err);
        const stillPending = pendingUserMessageRef.current?.id === optimistic.id;
        if (stillPending) {
          pendingUserMessageRef.current = null;
          // 消息没发出去：撤掉乐观消息，界面不留下一条实际不存在的用户发言
          setMessages((prev) => prev.filter((message) => message.id !== optimistic.id));
        }

        if (errorMessageKeyOf(err) === "error.conflict.active_run") {
          // 服务端还有活跃 run（例如审批刚放行、引擎仍在执行）：以服务端状态为准锁住输入
          setError(tRef.current("errors.sessionBusy"));
          void resyncRunState();
        } else if (!stillPending) {
          // 事件回执已到、消息其实发出去了，只是响应丢了：不判失败，只校准运行态
          console.warn("[useChatSession] send response lost after server accepted the message");
          void resyncRunState();
        } else {
          setError(tRef.current("errors.sendFailed", { message: messageOf(err) }));
          setIsLoading(false);
          runActiveRef.current = false;
        }
        return false;
      }
    },
    [applyServerUserMessage, resyncAfterReconnect, resyncRunState],
  );

  const send = useCallback(
    async (rawPrompt: string, attachments: AttachmentRef[] = []): Promise<boolean> => {
      const prompt = rawPrompt.trim();
      // 正文可以为空**当且仅当**带了附件（与服务端契约一致）
      if (prompt === "" && attachments.length === 0) return false;

      // 重入锁:同步置位,挡住同一 tick 内的双击/双回车,
      // 否则首轮会建出两个会话。isLoading 是渲染态值,挡不住这种情况。
      if (isSendingRef.current) return false;
      isSendingRef.current = true;
      try {
        return sessionIdRef.current
          ? await continueSession(prompt, attachments)
          : await startSession(prompt, attachments);
      } finally {
        isSendingRef.current = false;
      }
    },
    [continueSession, startSession],
  );

  /** 中止当前 run,保留会话以便继续对话。 */
  const stop = useCallback(async () => {
    const socket = getChatSocket();
    // 断线时不能"本地假停止"：服务端 run 可能还活着，解锁输入会让用户误以为已中止。
    // UI 在非 connected 时会禁用停止按钮，这里再兜一次底。
    if (socket.state !== "connected") {
      setError(tRef.current("errors.stopOffline"));
      return;
    }
    const runId = socket.runId;
    if (runId) {
      try {
        await socket.sendRequest("run.abort", { runId });
      } catch (err) {
        // 运行可能已结束,忽略
        console.warn("[useChatSession] run.abort failed:", err);
      }
    }
    runActiveRef.current = false;
    setIsLoading(false);
  }, []);

  const respondApproval = useCallback(
    (approvalId: string, decision: string) => {
      if (!approvalId) return;
      // 先移除本卡（只移除这一条，其余挂起仍留在队列里等用户应答）：
      // 应答是幂等的，真正的状态以服务端广播 / 重订阅结果为准
      setPendingApprovals((prev) =>
        removeByKey(prev, approvalId, (approval) => approval.approvalId),
      );
      void (async () => {
        try {
          await getChatSocket().sendRequest("approval.respond", {
            approvalId,
            decision,
          });
          // 审批放行 = 引擎继续跑这一轮，保持输入锁定直到终态事件
          setIsLoading(true);
        } catch (err) {
          console.warn("[useChatSession] approval.respond failed:", err);
          await handleRespondFailure(err);
        }
      })();
    },
    [handleRespondFailure],
  );

  /** 记录某张交互卡的答案（按 toolCallId 隔离，多张卡互不覆盖）。 */
  const setToolAnswer = useCallback(
    (toolCallId: string, question: string, value: ToolAnswerValue) => {
      setToolAnswers((prev) => ({
        ...prev,
        [toolCallId]: { ...prev[toolCallId], [question]: value },
      }));
    },
    [],
  );

  const respondTool = useCallback(
    (toolCallId: string) => {
      const tool = interactiveToolsRef.current.find((entry) => entry.toolCallId === toolCallId);
      if (!tool) return;
      const answers = toolAnswersRef.current[toolCallId] ?? {};
      // 只移除这一张：其它交互卡继续等待应答
      setInteractiveTools((prev) => removeByKey(prev, toolCallId, (entry) => entry.toolCallId));
      void (async () => {
        try {
          await getChatSocket().sendRequest("tool.respond", {
            toolCallId,
            // 未回答的题直接不带（空数组 = 没答案），不伪造空字符串
            answers: tool.input.questions.flatMap((question) => {
              const values = answerValuesOf(
                question,
                answerDraftOf(answers[question.question]),
              );
              return values.length === 0
                ? []
                : [{ question: question.question, answer: values }];
            }),
          });
          // 成功后才丢草稿：发送失败时卡片会被重订阅补发回来，答案还在
          forgetToolAnswers(toolCallId);
          setIsLoading(true);
        } catch (err) {
          console.warn("[useChatSession] tool.respond failed:", err);
          await handleRespondFailure(err);
        }
      })();
    },
    [forgetToolAnswers, handleRespondFailure],
  );

  // 首帧必须带 modelId(服务端必填)；智能体可选：没选就走自由对话。
  // 模型切换在途时也不能发 —— 否则下一轮可能仍用旧模型起跑。
  const canSend = modelId !== "" && !switchingModel;

  /** 重连次数达到阈值：UI 从"正在重连"切到"无法连接 + 手动入口"。 */
  const isOffline =
    connectionState !== "connected" && reconnectAttempts >= RECONNECT_OFFLINE_ATTEMPTS;

  /** 手动重连：跳过退避等待立即尝试一次（后台慢重试仍在继续）。 */
  const reconnect = useCallback(() => {
    getChatSocket().retryNow();
  }, []);

  return {
    agents,
    loadingAgents,
    models,
    loadingModels,
    refreshingModels,
    selectedAgent,
    selectAgent,
    clearAgent,
    hasSession,
    modelId,
    switchingModel,
    setModelId: selectModel,
    refreshAgents,
    refreshModels,
    messages,
    historyReady,
    streamingContent,
    toolExecutions,
    pendingApprovals,
    interactiveTools,
    toolAnswers,
    setToolAnswer,
    isRunning,
    connectionState,
    reconnectAttempts,
    isOffline,
    reconnect,
    isLoading,
    error,
    clearError,
    canSend,
    send,
    stop,
    respondApproval,
    respondTool,
  };
}

/**
 * 会话 / 消息 / 运行的数据入口（REST 那一半）。实时那一半在 `shared/live/live-client.ts`。
 *
 * 契约正本：`server/docs/04-api/4.03-会话.md`、`4.04-消息.md`、`4.05-运行.md`；
 * 类型以 `server/src/shared/types/index.ts` 为准（**文档落后于代码**，不一致时以代码为准）。
 *
 * 这里的类型是后端 DTO 的**逐字段镜像**（照 `agents.ts` 里 `Agent` 的做法：接口形状长在
 * 消费它的 api 模块旁，不塞进 `shared/types/index.ts` —— 那个文件的定位是「跨接口的最小共享」）。
 *
 * 分工只有一条（4.06 实时通道开篇）：**WS 只做实时**（上行动作 + 下行事件），
 * **一切查询与历史走 REST**。所以「进会话」是 REST 拉历史 + WS 订阅并行，缺一不可。
 */

import type { PageResult } from '../types';
import { API_BASE_URL, createApiClient } from './client';
import { isBackendDown } from './agents';

/**
 * 「后端没起」的判据是共享的（`agents.ts:isBackendDown` 的注释声明过「判据只有这一处」）。
 * 它住在 agents.ts 只是历史原因，这里直接复用，别再抄一份 —— 两边措辞可以不同，
 * 判据必须一致。
 */
export { isBackendDown };
export { backendDownHint } from './agents';

// ── 领域类型（镜像 server/src/shared/types/index.ts） ──────────────────────

/**
 * 四个**界面**阶段，取值与后端 `InstanceStage` **逐字一致**（目录名就是 stage 名）：
 *
 * - `development`：开发目录，创建向导与后续开发会话的 cwd；
 * - `preview`：预览沙箱，每次 run 前按开发产物物化；
 * - `runtime`：运行目录，直接跑开发产物（原地，不拷贝）；
 * - `evaluation`：评估沙箱，与 preview 同规则物化。
 *
 * stage 不是「运行状态」：一次 run 是会话里发生的事（见 `Run`），每个会话都落在某个 stage 上。
 * 创建页的步骤条只展示 development / preview / evaluation 三段，runtime 没有对应面板。
 */
export type InstanceStage = 'development' | 'preview' | 'runtime' | 'evaluation';
export const INSTANCE_STAGES: readonly InstanceStage[] = [
  'development',
  'preview',
  'runtime',
  'evaluation',
];

/** 会话状态迁移只有三条：not_started --起 run--> in_progress --无活跃 run--> completed（可复活） */
export type SessionStatus = 'not_started' | 'in_progress' | 'completed';

export type RunStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'aborted';

export type MessageRole = 'user' | 'assistant' | 'system';

export type MessageType =
  | 'text'
  | 'thinking'
  | 'tool_use'
  | 'tool_result'
  | 'approval'
  | 'tool_interactive'
  | 'error'
  | 'status';

/** 只有 `approval` / `tool_interactive` 会非 null，其余消息恒为 null */
export type MessageStatus = 'pending' | 'approved' | 'approved_all' | 'rejected' | 'answered' | 'aborted';

/** `decision` 客户端只能传前三个；`aborted` 是服务端内部值（中止/重启时写入） */
export type ApprovalDecision = 'approved' | 'approved_all' | 'rejected';
export type DecisionSource = 'user' | 'approved_all_auto' | 'abort' | 'restart';

export interface QuestionOption {
  label: string;
  description?: string;
}

export interface QuestionItem {
  header: string;
  question: string;
  options?: QuestionOption[];
  multiSelect?: boolean;
}

/** `type='approval'`：挂起时只有前半部分，结算后追加 `decision` / `decisionSource` */
export interface ApprovalContent {
  toolCallId?: string;
  toolName?: string;
  title: string;
  description?: string;
  input?: unknown;
  /** 只有引擎明确禁止「本会话全部允许」时才出现且为 false；**字段缺失表示可以** */
  allowAll?: boolean;
  decision?: ApprovalDecision | 'aborted';
  decisionSource?: DecisionSource;
}

/** `type='tool_interactive'`：`answers` 的 key 是 `questions[].question` 的**原文** */
export interface InteractiveContent {
  toolCallId?: string;
  toolName?: string;
  questions: QuestionItem[];
  answers?: Record<string, string[]>;
}

export type MessageContent = ApprovalContent | InteractiveContent | Record<string, unknown>;

export interface Instance {
  id: string;
  /**
   * 智能体实例非空；目录实例为 null。
   *
   * 「目录 vs 智能体」只看这一列：工坊（目录实例）跑在 `development`，
   * runtime 会话虽然是智能体实例，起 run 的 cwd 也是一个目录。
   */
  agentId: string | null;
  stage: InstanceStage;
  /** 目录实例的绝对 cwd（创建时 realpath 后落库）；智能体实例恒为 null，cwd 每次起 run 前推导 */
  cwd: string | null;
  /** 引擎适配器注册表 key，如 claude-cli / fake */
  engine: string;
  createdAt: string;
  updatedAt: string;
}

/** 会话 DTO：内联 instance。**目录与引擎只从 `session.instance` 取**，前端不要自己拼 */
export interface Session {
  id: string;
  instanceId: string;
  name: string;
  status: SessionStatus;
  /**
   * 会话级模型 id（模型管理组件的 id），落库后恒非空，起 run 时原样下发给 Claude Code CLI。
   * 建会话时必须显式传入；预览 / 评估首次建会话的默认值由前端解析
   * （`shared/api/default-model.ts`）。可经 sessions/:id/update 切换。
   */
  modelId: string;
  instance: Instance;
  /** 派生字段：第一条 `role='user'` 且 `type='text'` 消息的正文；仅列表填充，详情 / 创建 / 更新恒为 null */
  firstUserMessage: string | null;
  /** 派生字段：最新一条 `type='text'` 消息的正文；仅列表填充，详情 / 创建 / 更新恒为 null */
  lastMessage: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface Run {
  id: string;
  sessionId: string;
  instanceId: string;
  /** 父 run id；顶层 run 为 null */
  parentRunId?: string | null;
  /** 触发本次委派的父工具调用 id；顶层 run 为 null */
  parentToolUseId?: string | null;
  /** 子 agent 类型；顶层 run 为 null */
  subagentType?: string | null;
  /** 委派深度；顶层 run 为 0，子 run 为父 run 深度 + 1 */
  delegationDepth?: number;
  /** 引擎 task id；顶层 run 为 null */
  taskId?: string | null;
  status: RunStatus;
  error: string | null;
  /** 「允许所有」只挂顶层 run：子 run 的审批应答向上写入顶层 run */
  approvedAll: boolean;
  startedAt: string | null;
  finishedAt: string | null;
  createdAt: string;
  /** 派生字段：该 run 挂起中的审批/交互条数与最早一条的时间；无挂起为 null */
  waiting: { count: number; since: string } | null;
}

export interface Message {
  id: string;
  sessionId: string;
  runId: string | null;
  /** 会话内单调递增，**排序权威键**（不要用 createdAt：更新不刷新它） */
  seq: number;
  role: MessageRole;
  type: MessageType;
  status: MessageStatus | null;
  content: MessageContent;
  createdAt: string;
}

/** `messages/list` 的响应：`items` 恒为 seq 升序；`nextAfterSeq` 仅在条数 === limit 时非 null */
export interface MessagePage {
  items: Message[];
  nextAfterSeq: number | null;
}

// ── 请求载荷 ──────────────────────────────────────────────────────────────

export interface SessionListQuery {
  agentId?: string;
  /**
   * 会话阶段。
   *
   * **不传时服务端默认只返回 `runtime`**（界面上的「历史运行会话」）。设计页按当前步骤
   * 显式传；工坊历史是目录实例会话，传 `development`（与 `cwd` 一起用，见下）。
   *
   * 服务端对 `cwd` / `instanceId` / `id` / `resumeSessionId` 也会自动取消默认，
   * 这里显式写出来是为了读代码时不用记那条兜底规则。
   */
  stage?: InstanceStage;
  /**
   * 目录会话按 `cwd` **精确**过滤（技能工坊的历史）。与 agentId / stage 取交集；
   * 相对路径是 400，不是 404。
   */
  cwd?: string;
  /**
   * 按会话状态过滤（`status=<值>`，服务端按 IN 匹配）。
   *
   * 工坊裸进页面时用它一次捞出 `in_progress` 的会话，提示「还有任务在跑」——
   * 客户端只传单个值就够；多值形态见 `4.03-会话.md`（逗号分隔）。
   */
  status?: SessionStatus;
  /** 引擎 resume 标识；支持逗号分隔多值，用于反查 sessionId。 */
  resumeSessionId?: string;
  page?: number;
  pageSize?: number;
}

export interface SessionCreateInput {
  /** 智能体形态必填；**与 `cwd` 恰好给一个**（都给或都不给是 400） */
  agentId?: string;
  /**
   * 目录形态必填：绝对路径，创建时服务端 `realpath` 后落库。stage 恒为 `dir`，
   * 不接受调用方指定（技能工坊的会话就落在技能库根 `{skillsRoot}`）。
   */
  cwd?: string;
  stage?: InstanceStage;
  name?: string;
  /**
   * 会话级模型 id（模型管理组件的 id）。服务端要求非空且可运行 —— 不传直接 400，
   * 服务端不猜模型。预览 / 评估首次建会话时由 `shared/api/default-model.ts`
   * 按「工作区默认 → 框架生效 → 模型列表第一项」解析后传入。候选清单来自模型管理接口。
   */
  modelId?: string;
  /**
   * 建会话前先清空该阶段的沙箱（「重新开始预览」/「重新评估」用），只支持
   * `preview` / `evaluation`，其它阶段 `400`。评估的旧报告在沙箱根下，会一起删掉；
   * 下一次 run 前的物化再按最新产物整体重拷。
   * 同阶段已有活跃 run 仍是 `409`（删不到正在用的沙箱），交给「退回最近一场」处理。
   */
  resetSandbox?: boolean;
}

export interface SessionUpdateInput {
  /**
   * 新的会话级模型 id（模型管理组件的 id，非模型名）。
   * 必须非空且可运行；空串 `400`，不支持清空。
   */
  modelId: string;
}

export interface MessageListQuery {
  /** 与 `runId` **必给且只给一个**（都给或都不给都是 400） */
  sessionId?: string;
  runId?: string;
  /** 与 `beforeSeq` 互斥：`afterSeq` 向下续拉、`beforeSeq` 向上翻页 */
  afterSeq?: number;
  beforeSeq?: number;
  limit?: number;
  status?: MessageStatus;
}

export interface SendResult {
  message: Message;
  run: Run;
}

// ── 端点 ──────────────────────────────────────────────────────────────────

const BASE_URL = import.meta.env.VITE_SESSIONS_API_BASE_URL ?? `${API_BASE_URL}/smart-factory/v1`;

/** 出错时把地址说出来，用户才知道该去检查哪个服务 */
export const SESSIONS_API_BASE_URL = BASE_URL;

const client = createApiClient(BASE_URL);

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

export const sessionsApi = {
  /**
   * 列表。排序固定 `updatedAt` **降序**（最近有活动的在最前；改名 / 状态变更都会刷新它），
   * 同毫秒按 `id` 升序。契约写死，前端不要自己重排。空串参数视为未传。
   */
  list(input: SessionListQuery = {}): Promise<PageResult<Session>> {
    return client.get<PageResult<Session>>(
      `/sessions/list${query({
        agentId: input.agentId,
        stage: input.stage,
        cwd: input.cwd,
        status: input.status,
        resumeSessionId: input.resumeSessionId,
        page: input.page,
        pageSize: input.pageSize,
      })}`,
    );
  },

  /**
   * 建会话。
   *
   * ⚠️ **get-or-create 只发生在 Instance 上，会话是每次新建一行**。
   * 未知 `agentId` 是 404（`agents` 表是智能体存在的唯一权威）；
   * 该 `(agentId, stage)` 已有活跃 run 是 409（名额在 **instance** 上，与是哪个会话在跑无关）。
   * `stage` 缺省 `development`；建会话不物化沙箱、不碰磁盘 —— preview / evaluation 的重拷
   * 发生在每次 run 之前（源未变则跳过）。
   */
  create(input: SessionCreateInput): Promise<Session> {
    return client.post<Session>('/sessions/create', input);
  },

  detail(sessionId: string): Promise<Session> {
    return client.get<Session>(`/sessions/detail${query({ sessionId })}`);
  },

  /**
   * 切换会话模型（`sessions/:sessionId/update`，契约 4.03 §9）。
   *
   * 会话唯一可变字段就是 `modelId`；身份在路径上。**run 间隙生效**：正在跑的 run
   * 用的是启动时读到的值，不受影响；而会话有活跃 run 时这次更新会被 `409 CONFLICT`
   * 挡下（服务端不想让「这轮用的哪个模型」说不清）。
   */
  update(sessionId: string, patch: SessionUpdateInput): Promise<Session> {
    return client.post<Session>(`/sessions/${encodeURIComponent(sessionId)}/update`, patch);
  },

  /** 有活跃 run 的会话删不掉（409），须先 abort。删除不触碰磁盘 */
  async remove(sessionId: string): Promise<void> {
    await client.post<unknown>('/sessions/delete', { sessionId });
  },

  /** 会话粒度中止：等价于中止它当前的活跃 run。没有活跃 run 是 409 */
  abort(sessionId: string): Promise<Run> {
    return client.post<Run>('/sessions/abort', { sessionId });
  },
};

export const messagesApi = {
  /**
   * 取消息。
   *
   * 游标语义（4.04 §4）：不带游标 = 最近 `limit` 条；`beforeSeq=N` 取 `seq<N` 的最大 `limit` 条；
   * `afterSeq=N` 取 `seq>N` 的最小 `limit` 条。**结果一律 seq 升序**。
   * 向上翻页的续页游标是 `items[0].seq`。
   *
   * ⚠️ **不要只按 `afterSeq` 增量续拉**：`messages` 不是 append-only，挂起会变结算，
   * 增量会拉到旧行、界面就永远显示「等待审批」。重连与收尾都重拉当前页，或至少 `status=pending`。
   */
  list(input: MessageListQuery): Promise<MessagePage> {
    return client.get<MessagePage>(
      `/messages/list${query({
        sessionId: input.sessionId,
        runId: input.runId,
        afterSeq: input.afterSeq,
        beforeSeq: input.beforeSeq,
        limit: input.limit,
        status: input.status,
      })}`,
    );
  },

  /**
   * 发一条用户消息并起 run（**REST 等价物**）。
   *
   * ⚠️ 前端主路径不走这里：真会话用 WS 的 `send`（见 `shared/live/useLiveSession.ts`），
   * 会话既然已经订阅在通道上，发送就不另开一条 HTTP 连接。这里保留是为了契约完整，
   * 以及脚本 / 调试时不必先开 WS。
   *
   * 响应里的 `run.status` 恒为 `pending`（落库初值）—— **不要据此判断「没跑起来」**，
   * run 真的开跑由 WS 的 `run.started` 事件确认。
   * `CONFLICT` 的含义是「该 **instance** 已有活跃 run」，即同 agent 同 stage 的**其它会话**
   * 在跑也会挡（文案应是「该智能体正在运行」而不是「本会话正在运行」）。
   */
  send(sessionId: string, prompt: string): Promise<SendResult> {
    return client.post<SendResult>('/messages/send', { sessionId, prompt });
  },

  /**
   * 结算一条挂起的审批或交互。只有这一个结算接口，传什么由目标消息的 `type` 决定。
   * 已结算 / 两个端同时应答 → 409 `CONFLICT`，那不是失败（按「别人已经处理了」走）。
   */
  respondApproval(messageId: string, decision: ApprovalDecision): Promise<Message> {
    return client.post<Message>('/messages/respond', { messageId, decision });
  },

  respondAnswers(messageId: string, answers: Record<string, string[]>): Promise<Message> {
    return client.post<Message>('/messages/respond', { messageId, answers });
  },
};

export const runsApi = {
  list(sessionId: string, page = 1, pageSize = 20): Promise<PageResult<Run>> {
    return client.get<PageResult<Run>>(`/runs/list${query({ sessionId, page, pageSize })}`);
  },

  detail(runId: string): Promise<Run> {
    return client.get<Run>(`/runs/detail${query({ runId })}`);
  },

  /** 已落终态的 run 是 409 `CONFLICT` —— 不是「服务端忙」，不要重试 */
  abort(runId: string): Promise<Run> {
    return client.post<Run>('/runs/abort', { runId });
  },
};

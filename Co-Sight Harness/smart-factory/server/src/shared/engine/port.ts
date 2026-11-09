import type {
  Instance,
  MessageContent,
  MessageRole,
  MessageStatus,
  MessageType,
  QuestionItem,
  RunRow,
  SessionEffort,
  SessionMode,
  SessionRow,
} from '../types/index.js';

/** 引擎向宿主提的请求：审批与交互走同一个通道，用 kind 区分。 */
export interface InputRequest {
  kind: 'approval' | 'tool_interactive';
  toolCallId?: string;
  toolName?: string;
  title: string;
  description?: string;
  input?: unknown;
  questions?: QuestionItem[];
  /** 触发本次请求的子代理 task_id；顶层请求不带 */
  agentId?: string;
  /** UI 是否可以提供「本会话全部允许」；仅当引擎明确禁止时给 false，缺省表示可以 */
  allowAll?: boolean;
}

export interface InputDecision {
  decision?: 'approved' | 'approved_all' | 'rejected' | 'aborted';
  answers?: Record<string, string[]>;
}

/** 起 run 时下发给引擎的模型运行配置；会话模型恒非空，没有跟随本机的分支。 */
export interface EngineModel {
  modelName: string;
  baseUrl: string | null;
  apiKey: string;
}

/**
 * `/` 菜单里的一条命令，形状取自引擎自己登记的清单。
 *
 * 技能也以命令形态出现（`/<name>`、`/<plugin>:<skill>`），所以这里**不区分**技能与命令：
 * 引擎给的是一张扁平表，前端按名字前缀展示即可。
 */
export interface EngineSlashCommand {
  /** 不带前导 `/` 的命令名；插件技能 / 命令形如 `plugin:skill` */
  name: string;
  /** 引擎给的一句话说明（可能带 `(user)` / `(project)` 之类的来源后缀） */
  description: string;
  /** 参数提示（如 `--mode optimize`）；没有则空串 */
  argumentHint: string;
  /** 能解析到同一条命令的别名（不带 `/`）；没有则省略 */
  aliases?: string[];
  /** 引擎自带命令；用户 / 项目 / 插件 / MCP 提供的命令不带此字段 */
  builtin?: boolean;
}

/**
 * 引擎自身的信息，供前端展示「当前是哪套引擎、什么版本、在哪个目录探的、菜单里有多少条」。
 *
 * 刻意**不报模型、账号与输出风格**：产品起 run 的模型与凭据由 Cosight Harness 配置
 * （`/models/list` 与 `modelId`），Claude Code 本机的 model / account 配置与真实运行无关。
 */
export interface EngineInfo {
  /** 适配器标识（`claude-cli` / `fake`） */
  engine: string;
  /** 探测时用的工作目录：项目级技能 / 命令按它发现 */
  cwd: string;
  /** 引擎版本（Claude Code 的 `claude_code_version`）；老版本不报时为空串 */
  version: string;
  /** `/` 菜单里可见的条目数（不含引擎自带命令，与列表端点同口径） */
  commandCount: number;
  /** CLI 是否可用；缺省视为可用（兼容旧响应）。 */
  available?: boolean;
  /** 不可用原因（探测失败、CLI 未安装等）。 */
  reason?: string;
  /** 安装 / 升级指引。 */
  installHint?: string;
}

/** 引擎产出的消息只是草稿：id / seq / 落库由宿主负责。 */
export interface MessageDraft {
  role: MessageRole;
  type: MessageType;
  content: MessageContent;
  status?: MessageStatus | null;
}

/** 内容消息的子代理来源；顶层消息两者皆为 null 或省略 */
export interface SubagentMeta {
  parentToolUseId?: string | null;
  agentId?: string | null;
}

/** 引擎产出的事件：内容增量、完整消息与子任务生命周期。 */
export type EngineEvent =
  | ({ type: 'delta'; messageType: 'text'; delta: string } & SubagentMeta)
  | ({ type: 'thinking'; phase: 'start' | 'stop' } & SubagentMeta)
  | ({ type: 'thinking'; phase: 'delta'; text: string } & SubagentMeta)
  | {
      type: 'api_retry';
      attempt: number;
      maxRetries: number;
      errorStatus: number | null;
      error: string | null;
    }
  | ({ type: 'message'; draft: MessageDraft } & SubagentMeta)
  | {
      type: 'task_started';
      taskId: string;
      /** CLI 的 run_id：resume 后 task_id 不变、run_id 变，宿主据此区分同一任务的新旧子 run */
      runId?: string;
      toolUseId: string | null;
      parentTaskId: string | null;
      subagentType: string | null;
      /** 0 = 引擎未给 spawn_depth，宿主按父 run 深度加一补齐 */
      delegationDepth: number;
      description: string;
    }
  | {
      type: 'task_notified';
      taskId: string;
      /** CLI 的 run_id：与 task_started 配对定位子 run；缺省按 task_id 最近一次运行归位 */
      runId?: string;
      status: 'completed' | 'failed' | 'stopped';
      summary: string | null;
      error: string | null;
    };

export interface EngineContext {
  session: SessionRow;
  run: RunRow;
  instance: Instance;
  cwd: string;
  /** 本次运行的输入：起 run 时那条用户消息的正文 */
  prompt: string;
  /** 本次运行的模型配置：起 run 时由会话 modelId 解析，任何会话都非空 */
  model: EngineModel;
  /** 引擎接续标识；null = 开新引擎会话 */
  resumeSessionId: string | null;
  /** 会话级审批模式 */
  mode: SessionMode;
  /** 会话级推理强度 */
  effort: SessionEffort;
  /** 引擎首次产出 resume 标识时回调；宿主负责落库 */
  onSessionId?: (resumeSessionId: string) => void | Promise<void>;
  /** 落库与广播由 session 层做，引擎不碰 DB、不碰 HTTP */
  emit(ev: EngineEvent): void | Promise<void>;
  /** 引擎问、宿主答；挂起多久由宿主决定（本设计不超时） */
  requestInput(req: InputRequest): Promise<InputDecision>;
  signal: AbortSignal;
}

export interface EngineAdapter {
  readonly engine: string;
  /**
   * 引擎侧的会话标题（Claude Code 的自动摘要或用户 /rename 的标题）。
   *
   * 宿主只在会话名为空时调用，用它补 `sessions.name`；不支持的引擎不实现。
   * `cwd` 是该项目目录，用于定位引擎会话文件。
   */
  sessionTitle?(resumeSessionId: string, cwd: string): Promise<string | null>;
  /**
   * `/` 菜单里的全部命令（技能也以命令形态出现）。
   *
   * 只读探测：不发起模型调用、不落会话；`cwd` 决定项目级技能 / 命令的发现范围。
   * 不支持的引擎不实现。
   */
  commands?(cwd: string): Promise<EngineSlashCommand[]>;
  /**
   * 引擎自身的信息：引擎标识、探测目录、版本、可见命令数（形状见 `EngineInfo`）。
   *
   * 刻意**不报模型、账号与输出风格**：起 run 用的模型与凭据由 Cosight Harness 配置，
   * 引擎本机的 model / account 与真实运行无关（理由见 `EngineInfo`）。
   * 与 `commands` 共用同一次探测；`cwd` 语义相同。不支持的引擎不实现。
   */
  info?(cwd: string): Promise<EngineInfo>;
  run(ctx: EngineContext): Promise<{ output: string }>;
}

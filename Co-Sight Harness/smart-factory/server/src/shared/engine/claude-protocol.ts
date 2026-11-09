/**
 * Claude Code CLI 的 stream-json / control 协议形状（本地定义）。
 *
 * 这里只描述我们自己读写的字段，**不依赖任何 Anthropic 包**。协议来源是
 * `claude --input-format stream-json --output-format stream-json` 的 stdio 消息，
 * 以及 `--permission-prompt-tool=stdio` 触发的 control 往返。
 *
 * 形状刻意保持宽松：CLI 的协议会随版本增加字段，多出来的字段不影响解析，
 * 缺字段的分支由调用方按 `typeof` 判定。
 */

/** CLI stdout 的一帧。`type` 决定后续分支，其余字段按需窄化。 */
export interface ClaudeMessage {
  type: string;
  subtype?: string;
  message?: { role?: string; content?: unknown };
  event?: unknown;
  session_id?: string;
  parent_tool_use_id?: string | null;
  agent_id?: string | null;
  attempt?: number;
  max_retries?: number;
  error_status?: number | null;
  error?: unknown;
  result?: string;
  is_error?: boolean;
  task_type?: string;
  subagent_type?: string;
  task_id?: string;
  run_id?: string;
  tool_use_id?: string | null;
  parent_task_id?: string | null;
  spawn_depth?: number;
  description?: string;
  summary?: string;
  status?: 'completed' | 'failed' | 'stopped';
  tasks?: unknown;
  claude_code_version?: string;
  commands?: ClaudeSlashCommand[];
  [key: string]: unknown;
}

/** initialize 回执里的 `/` 菜单条目。 */
export interface ClaudeSlashCommand {
  name: string;
  description?: string;
  argumentHint?: string;
  aliases?: string[];
  builtin?: boolean;
}

/** `initialize` control 请求的成功载荷（只列我们用到的字段）。 */
export interface ClaudeInitializeResponse {
  commands?: ClaudeSlashCommand[];
  claude_code_version?: string;
  [key: string]: unknown;
}

/** 写进 stdin 的用户消息。 */
export interface ClaudeUserMessage {
  type: 'user';
  message: { role: 'user'; content: unknown };
  parent_tool_use_id: string | null;
}

/** CLI 认的权限模式；适配器只产出 plan / acceptEdits / bypassPermissions。 */
export type ClaudePermissionMode = 'default' | 'acceptEdits' | 'bypassPermissions' | 'plan' | 'dontAsk' | 'delegate';

/** `can_use_tool` 的回执：与 Claude Code 的 PermissionResult 同形。 */
export type ClaudePermissionResult =
  | {
      behavior: 'allow';
      updatedInput: Record<string, unknown>;
      toolUseID?: string;
      decisionClassification?: string;
    }
  | {
      behavior: 'deny';
      message: string;
      toolUseID?: string;
      decisionClassification?: string;
    };

/** `can_use_tool` 请求里可用的上下文（第三参）。 */
export interface ClaudePermissionOptions {
  signal?: AbortSignal;
  suggestions?: unknown;
  toolUseID?: string;
  agentID?: string;
  title?: string;
  displayName?: string;
  description?: string;
  blockedPath?: string;
  decisionReason?: string;
  decisionReasonType?: string;
  suppressAlwaysAllowRule?: boolean;
  requestId?: string;
}

export type ClaudeCanUseTool = (
  toolName: string,
  input: Record<string, unknown>,
  options: ClaudePermissionOptions,
) => Promise<ClaudePermissionResult | null>;

/**
 * 起一次 CLI 会话的选项。
 *
 * `settings`（含 `settings.env` 里的凭据）写进 0600 临时设置文件，经
 * `--settings <path>` 下发；不进命令行、不进日志，进程退出即删。
 */
export interface ClaudeQueryOptions {
  cwd: string;
  /** 显式指定的 claude 可执行件；缺省按 PATH 解析。 */
  binary?: string;
  model?: string;
  settings?: { disableAllHooks?: boolean; env?: Record<string, string>; [key: string]: unknown };
  env?: NodeJS.ProcessEnv;
  resume?: string;
  permissionMode?: ClaudePermissionMode;
  allowDangerouslySkipPermissions?: boolean;
  effort?: string;
  strictMcpConfig?: boolean;
  includePartialMessages?: boolean;
  persistSession?: boolean;
  canUseTool?: ClaudeCanUseTool;
  abortController?: AbortController;
}

export interface ClaudeQueryInput {
  prompt: AsyncIterable<ClaudeUserMessage> | string;
  options: ClaudeQueryOptions;
}

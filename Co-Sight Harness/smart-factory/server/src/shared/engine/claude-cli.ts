/**
 * Claude Code CLI 的 stdio 传输层。
 *
 * 这里只做一件事：把一次会话翻译成
 * `claude --input-format stream-json --output-format stream-json` 子进程，
 * 处理 JSONL 读写、control 往返（initialize / can_use_tool / interrupt）与进程收尾。
 *
 * 不依赖任何 Anthropic 包：CLI 由用户在运行机上自行安装。
 */

import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createInterface, type Interface } from 'node:readline';

import type {
  ClaudeInitializeResponse,
  ClaudeMessage,
  ClaudePermissionResult,
  ClaudeQueryInput,
  ClaudeQueryOptions,
  ClaudeUserMessage,
} from './claude-protocol.js';

/** 运行机没装 claude 时抛这个，调用方据此给出安装指引而不是泛化 502。 */
export class ClaudeCliNotFoundError extends Error {
  constructor(binary: string) {
    super(`未找到 Claude Code CLI（${binary}）。请安装：${CLAUDE_CLI_INSTALL_HINT}`);
    this.name = 'ClaudeCliNotFoundError';
  }
}

export const CLAUDE_CLI_INSTALL_HINT = 'npm install -g @anthropic-ai/claude-code';

const INIT_TIMEOUT_MS = 60_000;
const INTERRUPT_TIMEOUT_MS = 5_000;
const EXIT_GRACE_MS = 5_000;
const STDERR_LIMIT = 8 * 1024;

/** 这些 control 请求由“持有工具的机器”处理；本端没有远程工具，静默忽略（与官方 CLI 客户端同口径）。 */
const IGNORED_CONTROL_SUBTYPES = new Set([
  'remote_tool_call',
  'remote_plumbing_call',
  'remote_tools_probe',
  'remote_tools_reannounce',
]);

interface PendingControl {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

/** 一个 CLI 会话：构造即 spawn，close() 收尾。 */
export class ClaudeCliQuery implements AsyncIterable<ClaudeMessage> {
  private readonly options: ClaudeQueryOptions;
  private readonly child: ChildProcessWithoutNullStreams;
  private readonly reader: Interface;
  private readonly queue = new MessageQueue();
  private readonly pending = new Map<string, PendingControl>();
  private readonly permissionSignals = new Map<string, AbortController>();
  private readonly initPromise: Promise<ClaudeInitializeResponse>;
  private readonly onAbort = (): void => {
    void this.interrupt().finally(() => {
      const timer = setTimeout(() => this.close(), EXIT_GRACE_MS);
      timer.unref?.();
    });
  };

  private settingsDir: string | null;
  private stderr = '';
  private exited = false;
  private closing = false;
  private killTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(input: ClaudeQueryInput) {
    this.options = input.options;
    const spawnSpec = buildSpawn(input.options);
    this.settingsDir = spawnSpec.settingsDir;
    this.child = spawn(spawnSpec.command, spawnSpec.args, {
      cwd: input.options.cwd,
      env: spawnSpec.env,
      windowsHide: true,
      windowsVerbatimArguments: spawnSpec.windowsVerbatimArguments,
    });

    this.child.on('error', (error: NodeJS.ErrnoException) => {
      if (error.code === 'ENOENT') {
        this.fail(new ClaudeCliNotFoundError(spawnSpec.binary));
        return;
      }
      this.fail(error);
    });
    this.child.on('exit', (code, signal) => this.handleExit(code, signal));
    // 进程提前退出时写 stdin 会 EPIPE；错误由 exit 收口，这里只防止未处理事件。
    this.child.stdin.on('error', () => undefined);

    this.reader = createInterface({ input: this.child.stdout, crlfDelay: Infinity });
    this.reader.on('line', (line) => this.handleLine(line));
    this.child.stderr.on('data', (chunk: Buffer) => {
      this.stderr = appendCapped(this.stderr, chunk.toString('utf8'));
    });

    this.initPromise = this.requestControl({ subtype: 'initialize' }, INIT_TIMEOUT_MS).then(
      (payload) => (payload ?? {}) as ClaudeInitializeResponse,
    );
    // 调用方不一定 await 初始化（例如 run 直接消费消息流）；失败仍由后续步骤暴露。
    void this.initPromise.catch(() => undefined);

    void this.pumpInput(input.prompt);

    const signal = input.options.abortController?.signal;
    if (signal !== undefined) {
      if (signal.aborted) this.onAbort();
      else signal.addEventListener('abort', this.onAbort, { once: true });
    }
  }

  /** 一次只读探测 / 一次 run 共用的初始化回执。 */
  initializationResult(): Promise<ClaudeInitializeResponse> {
    return this.initPromise;
  }

  /** 中止当前回合：只发 control 请求，不杀进程（后台任务可能还要继续）。 */
  async interrupt(): Promise<void> {
    if (this.exited) return;
    try {
      await this.requestControl({ subtype: 'interrupt' }, INTERRUPT_TIMEOUT_MS);
    } catch {
      // 进程已经退出，或 CLI 不支持 interrupt：交给 close / exit 收口。
    }
  }

  /** 关进程并清掉临时设置文件；可重复调用。 */
  close(): void {
    if (this.closing) return;
    this.closing = true;
    this.options.abortController?.signal.removeEventListener('abort', this.onAbort);
    if (!this.child.stdin.writableEnded) {
      try {
        this.child.stdin.end();
      } catch {
        // 已关闭
      }
    }
    if (!this.exited) {
      try {
        this.child.kill('SIGTERM');
      } catch {
        // 已退出
      }
      const timer = setTimeout(() => {
        if (!this.exited) {
          try {
            this.child.kill('SIGKILL');
          } catch {
            // 已退出
          }
        }
      }, 2_000);
      timer.unref?.();
    }
    this.queue.end();
    this.cleanupSettings();
  }

  [Symbol.asyncIterator](): AsyncIterator<ClaudeMessage> {
    return this.queue[Symbol.asyncIterator]();
  }

  private handleLine(line: string): void {
    const trimmed = line.trim();
    if (trimmed === '') return;
    let message: ClaudeMessage;
    try {
      message = JSON.parse(trimmed) as ClaudeMessage;
    } catch {
      // stream-json 模式下 stdout 应当全是 JSON；不是的行大概率是调试输出，忽略。
      return;
    }

    if (message.type === 'control_response') {
      this.handleControlResponse(message);
      return;
    }
    if (message.type === 'control_request') {
      void this.handleControlRequest(message);
      return;
    }
    if (message.type === 'control_cancel_request') {
      this.handleControlCancelRequest(message);
      return;
    }
    this.queue.push(message);
  }

  private handleControlResponse(message: ClaudeMessage): void {
    const response = message.response as
      | { subtype?: string; request_id?: string; response?: unknown; error?: string }
      | undefined;
    if (response === undefined || typeof response.request_id !== 'string') return;

    const pending = this.pending.get(response.request_id);
    if (pending === undefined) return;
    this.pending.delete(response.request_id);
    clearTimeout(pending.timer);

    if (response.subtype === 'success') pending.resolve(response.response);
    else pending.reject(new Error(typeof response.error === 'string' ? response.error : 'Claude Code control 请求失败'));
  }

  private async handleControlRequest(message: ClaudeMessage): Promise<void> {
    const request = message.request as
      | {
          subtype?: string;
          tool_name?: string;
          input?: Record<string, unknown>;
          permission_suggestions?: unknown;
          tool_use_id?: string;
          agent_id?: string;
          title?: string;
          display_name?: string;
          description?: string;
          blocked_path?: string;
          decision_reason?: string;
          decision_reason_type?: string;
          suppress_always_allow_rule?: boolean;
        }
      | undefined;
    const requestId = typeof message.request_id === 'string' ? message.request_id : null;
    if (request === undefined || requestId === null) return;

    if (request.subtype !== 'can_use_tool') {
      // 与官方 CLI 客户端同口径：这几类属于“由持有工具的机器处理”，本端没有远程工具，不回复。
      if (request.subtype !== undefined && IGNORED_CONTROL_SUBTYPES.has(request.subtype)) return;
      // 当前不注册 hooks / MCP，理论上不会走到这里；回错误，避免 CLI 一直等。
      this.respondError(requestId, `不支持的 control 请求：${request.subtype ?? 'unknown'}`);
      return;
    }

    const canUseTool = this.options.canUseTool;
    if (canUseTool === undefined) {
      this.respondError(requestId, '当前会话没有注册权限回调');
      return;
    }

    const permissionController = new AbortController();
    this.permissionSignals.set(requestId, permissionController);
    const runSignal = this.options.abortController?.signal;
    const forwardAbort = (): void => permissionController.abort();
    if (runSignal !== undefined) {
      if (runSignal.aborted) permissionController.abort();
      else runSignal.addEventListener('abort', forwardAbort, { once: true });
    }

    try {
      const result = await canUseTool(request.tool_name ?? '', request.input ?? {}, {
        signal: permissionController.signal,
        suggestions: request.permission_suggestions,
        toolUseID: request.tool_use_id,
        agentID: request.agent_id,
        title: request.title,
        displayName: request.display_name,
        description: request.description,
        blockedPath: request.blocked_path,
        decisionReason: request.decision_reason,
        decisionReasonType: request.decision_reason_type,
        suppressAlwaysAllowRule: request.suppress_always_allow_rule,
        requestId,
      });
      if (result === null) {
        this.respondError(requestId, '权限请求没有给出结论');
        return;
      }
      this.respond(requestId, result as ClaudePermissionResult);
    } catch (error) {
      this.respondError(requestId, error instanceof Error ? error.message : String(error));
    } finally {
      runSignal?.removeEventListener('abort', forwardAbort);
      this.permissionSignals.delete(requestId);
    }
  }

  private handleControlCancelRequest(message: ClaudeMessage): void {
    const requestId = typeof message.request_id === 'string' ? message.request_id : null;
    if (requestId !== null) this.permissionSignals.get(requestId)?.abort();
  }

  private requestControl(request: Record<string, unknown>, timeoutMs: number): Promise<unknown> {
    return new Promise<unknown>((resolve, reject) => {
      if (this.exited) {
        reject(new Error('Claude Code 已退出'));
        return;
      }
      const request_id = randomUUID();
      const timer = setTimeout(() => {
        this.pending.delete(request_id);
        reject(new Error(`Claude Code 在 ${timeoutMs}ms 内没有响应 ${String(request.subtype)}`));
      }, timeoutMs);
      this.pending.set(request_id, { resolve, reject, timer });
      try {
        this.write({ type: 'control_request', request_id, request });
      } catch (error) {
        this.pending.delete(request_id);
        clearTimeout(timer);
        reject(error instanceof Error ? error : new Error(String(error)));
      }
    });
  }

  private respond(requestId: string, payload: unknown): void {
    try {
      this.write({ type: 'control_response', response: { subtype: 'success', request_id: requestId, response: payload } });
    } catch {
      // 进程已退出
    }
  }

  private respondError(requestId: string, error: string): void {
    try {
      this.write({ type: 'control_response', response: { subtype: 'error', request_id: requestId, error } });
    } catch {
      // 进程已退出
    }
  }

  private write(message: unknown): void {
    if (this.child.stdin.destroyed || this.child.stdin.writableEnded) {
      throw new Error('Claude Code 的输入流已关闭');
    }
    this.child.stdin.write(`${JSON.stringify(message)}\n`);
  }

  private async pumpInput(prompt: AsyncIterable<ClaudeUserMessage> | string): Promise<void> {
    try {
      if (typeof prompt === 'string') {
        this.write({ type: 'user', message: { role: 'user', content: prompt }, parent_tool_use_id: null });
        this.endInput();
        return;
      }
      for await (const message of prompt) {
        this.write(message);
      }
      this.endInput();
    } catch (error) {
      if (!this.closing) this.fail(error instanceof Error ? error : new Error(String(error)));
    }
  }

  private endInput(): void {
    if (!this.child.stdin.writableEnded) {
      try {
        this.child.stdin.end();
      } catch {
        // 已关闭
      }
    }
    this.killTimer ??= setTimeout(() => {
      if (!this.exited) {
        try {
          this.child.kill('SIGTERM');
        } catch {
          // 已退出
        }
      }
    }, EXIT_GRACE_MS);
    this.killTimer.unref?.();
  }

  private handleExit(code: number | null, signal: NodeJS.Signals | null): void {
    if (this.exited) return;
    this.exited = true;
    if (this.killTimer !== null) {
      clearTimeout(this.killTimer);
      this.killTimer = null;
    }
    this.options.abortController?.signal.removeEventListener('abort', this.onAbort);
    this.reader.close();
    this.cleanupSettings();

    const suffix = this.stderr.trim() === '' ? '' : `：${this.stderr.trim()}`;
    const reason = `Claude Code ${this.closing || code === 0 ? '已退出' : '异常退出'}（code ${code ?? 'null'}，signal ${signal ?? 'null'}）${suffix}`;
    // 异常退出必须先 fail 再收尾：先 end 的话，正在等待的消费方会拿到 done，
    // 把一次失败当成正常结束，run 会带着半截内容“成功”返回。
    if (!this.closing && code !== 0) {
      this.queue.fail(new Error(reason));
    } else {
      this.queue.end();
    }
    for (const [id, pending] of this.pending) {
      clearTimeout(pending.timer);
      pending.reject(new Error(reason));
      this.pending.delete(id);
    }
  }

  private fail(error: Error): void {
    for (const [id, pending] of this.pending) {
      clearTimeout(pending.timer);
      pending.reject(error);
      this.pending.delete(id);
    }
    this.queue.fail(error);
    this.close();
  }

  private cleanupSettings(): void {
    if (this.settingsDir === null) return;
    try {
      rmSync(this.settingsDir, { recursive: true, force: true });
    } catch {
      // 临时目录清理失败不影响主流程
    }
    this.settingsDir = null;
  }
}

/** 把选项翻译成子进程 argv 与 env。 */
function buildSpawn(options: ClaudeQueryOptions): {
  command: string;
  args: string[];
  env: NodeJS.ProcessEnv;
  binary: string;
  settingsDir: string | null;
  windowsVerbatimArguments: boolean;
} {
  const args = ['--output-format', 'stream-json', '--input-format', 'stream-json', '--verbose'];
  if (options.includePartialMessages === true) args.push('--include-partial-messages');
  if (options.model !== undefined && options.model !== '') args.push('--model', options.model);
  if (options.resume !== undefined && options.resume !== '') args.push('--resume', options.resume);
  if (options.permissionMode !== undefined) args.push('--permission-mode', options.permissionMode);
  // 有权限回调才走 stdio 审批；没有就让 CLI 按 permissionMode 自己决定。
  if (options.canUseTool !== undefined) args.push('--permission-prompt-tool=stdio');
  if (options.strictMcpConfig === true) args.push('--strict-mcp-config');
  if (options.effort !== undefined && options.effort !== '') args.push('--effort', options.effort);
  if (options.allowDangerouslySkipPermissions === true) args.push('--allow-dangerously-skip-permissions');
  if (options.persistSession === false) args.push('--no-session-persistence');

  const settingsDir = writeSettingsFile(options.settings);
  if (settingsDir !== null) args.push('--settings', join(settingsDir, 'settings.json'));

  // 凭据走 `--settings` 临时文件（flag-settings 层，优先级高于 user settings），
  // 与原来的适配器语义一致；子进程环境只保留基础变量。
  const env: NodeJS.ProcessEnv = { ...(options.env ?? process.env) };

  const binary = resolveBinary(options, env);
  const spawnSpec = buildSpawnSpec(binary, args);
  return { ...spawnSpec, env, binary, settingsDir };
}

/**
 * 设置写临时文件（目录 0700、文件 0600），进程退出即删。
 *
 * 凭据放在这里而不是命令行：`ps` 看不到、日志里也没有；flag-settings 层的优先级
 * 又能压过 user settings，保证框架下发的模型配置生效。
 */
function writeSettingsFile(settings: ClaudeQueryOptions['settings']): string | null {
  if (settings === undefined || Object.keys(settings).length === 0) return null;

  const dir = mkdtempSync(join(tmpdir(), 'cosight-claude-'));
  writeFileSync(join(dir, 'settings.json'), `${JSON.stringify(settings)}\n`, { mode: 0o600 });
  return dir;
}

/** 显式路径优先；Windows 下按 PATH 找 .exe / .cmd，避免 `spawn('claude')` 找不到。 */
function resolveBinary(options: ClaudeQueryOptions, env: NodeJS.ProcessEnv): string {
  if (options.binary !== undefined && options.binary !== '') return options.binary;
  if (process.platform !== 'win32') return 'claude';

  const pathValue = env.PATH ?? env.Path ?? '';
  for (const dir of pathValue.split(';')) {
    if (dir === '') continue;
    for (const name of ['claude.exe', 'claude.cmd', 'claude.bat']) {
      const candidate = join(dir, name);
      if (existsSync(candidate)) return candidate;
    }
  }
  return 'claude.exe';
}

const SAFE_CMD_ARG = /^[A-Za-z0-9_@.,:+=/\\-]+$/;

/** 与 framework/scripts/lib/cli-exec.mjs 同一套 cmd.exe 规则。 */
function quoteForCmd(value: string): string {
  if (/[\0\r\n]/.test(value)) throw new Error(`参数里含换行或 NUL：${JSON.stringify(value)}`);
  if (value.includes('"')) throw new Error(`参数里含双引号：${value}`);
  if (value.includes('%')) throw new Error(`参数里含 %：${value}`);
  if (value === '') return '""';
  return SAFE_CMD_ARG.test(value) ? value : `"${value}"`;
}

function buildSpawnSpec(
  executable: string,
  args: string[],
): { command: string; args: string[]; windowsVerbatimArguments: boolean } {
  if (process.platform === 'win32' && /\.(cmd|bat)$/i.test(executable)) {
    const comspec = process.env.ComSpec ?? process.env.COMSPEC ?? 'cmd.exe';
    const line = [quoteForCmd(executable), ...args.map(quoteForCmd)].join(' ');
    return { command: comspec, args: ['/d', '/s', '/c', `"${line}"`], windowsVerbatimArguments: true };
  }
  return { command: executable, args: [...args], windowsVerbatimArguments: false };
}

function appendCapped(text: string, chunk: string): string {
  const next = text + chunk;
  return next.length <= STDERR_LIMIT ? next : next.slice(next.length - STDERR_LIMIT);
}

/** 把异步产出转成 AsyncIterable：stdout 是生产者，适配器是消费者。 */
class MessageQueue implements AsyncIterable<ClaudeMessage> {
  private readonly values: ClaudeMessage[] = [];
  private readonly waiters: Array<{
    resolve: (result: IteratorResult<ClaudeMessage>) => void;
    reject: (error: Error) => void;
  }> = [];
  private done = false;
  private error: Error | null = null;

  push(value: ClaudeMessage): void {
    const waiter = this.waiters.shift();
    if (waiter !== undefined) {
      waiter.resolve({ value, done: false });
      return;
    }
    this.values.push(value);
  }

  end(): void {
    if (this.done) return;
    this.done = true;
    if (this.error === null) {
      for (const waiter of this.waiters.splice(0)) waiter.resolve({ value: undefined, done: true });
    }
  }

  fail(error: Error): void {
    if (this.error === null) this.error = error;
    this.values.length = 0;
    for (const waiter of this.waiters.splice(0)) waiter.reject(error);
  }

  [Symbol.asyncIterator](): AsyncIterator<ClaudeMessage> {
    return {
      next: () => {
        const value = this.values.shift();
        if (value !== undefined) return Promise.resolve({ value, done: false });
        if (this.error !== null) return Promise.reject(this.error);
        if (this.done) return Promise.resolve({ value: undefined, done: true });
        return new Promise<IteratorResult<ClaudeMessage>>((resolve, reject) => {
          this.waiters.push({ resolve, reject });
        });
      },
      return: () => {
        this.done = true;
        return Promise.resolve({ value: undefined, done: true });
      },
    };
  }
}

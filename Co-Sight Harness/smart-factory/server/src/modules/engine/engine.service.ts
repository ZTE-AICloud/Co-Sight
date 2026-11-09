import { realpathSync } from 'node:fs';
import { homedir } from 'node:os';
import { config } from '../../config/index.js';
import { CLAUDE_CLI_INSTALL_HINT, ClaudeCliNotFoundError } from '../../shared/engine/claude-cli.js';
import { resolveEngineAdapter } from '../../shared/engine/registry.js';
import type { EngineAdapter, EngineInfo, EngineSlashCommand } from '../../shared/engine/port.js';
import { AppError, BadGatewayError } from '../../shared/errors.js';
import { resolveLocalTarget } from '../../shared/workspace/local-path.js';

/**
 * 当前引擎（Claude Code）的 `/` 菜单与自身信息。
 *
 * 清单**不扫盘**：`/` 菜单由引擎自己拼（内置命令 + user / project 技能 + 插件 + 动态命令），
 * 扫 `.claude/skills` 只能看到其中一部分。所以这里经适配器起一个只读探测进程，
 * 拿引擎的 initialize 回执 —— 与终端里敲 `/` 的自动补全同源。
 *
 * `cwd` 决定「项目级」那部分：会话目录会带上该目录 `.claude` 下的技能与命令；
 * 不传时用主目录，即「本机用户级配置」的范围（`~/.claude` 的技能 / 命令 / 插件）。
 */

export interface EngineCommandsResponse {
  /** 适配器标识（`claude-cli` / `fake`） */
  engine: string;
  /** 实际探测的目录（已解 symlink） */
  cwd: string;
  items: EngineSlashCommand[];
}

/**
 * 产品菜单只展示**用户 / 项目 / 插件**提供的条目。
 *
 * Claude Code 自带的命令（CLI 标 `builtin`）是终端 / 会话管理（model、mcp、clear、compact、
 * config、usage…）与官方内置技能（code-review、security-review、dataviz…），在产品前端里的
 * 语义与执行方式都不对，整类不下发。适配器仍返回全量，过滤是产品口径，放在这里而不是适配器里。
 */
function visibleCommands(items: EngineSlashCommand[]): EngineSlashCommand[] {
  return items.filter((item) => item.builtin !== true);
}

/**
 * 默认探测目录：主目录。
 *
 * 主目录是「本机用户级配置」的范围，与终端里直接敲 `/` 看到的内容最接近；
 * 给了 cwd（会话 / 智能体产物目录）就按那个目录再叠上项目级条目。
 */
function defaultCwd(): string {
  const home = homedir();
  try {
    return realpathSync(home);
  } catch {
    return home;
  }
}

/** cwd 入参：缺省用主目录；给了就必须是存在的绝对路径（可带 `~/`），与 `/fs/*` 同一份校验。 */
function readCwd(value: unknown): string {
  if (value === undefined || value === null || value === '') return defaultCwd();
  return resolveLocalTarget(value, 'dir');
}

/** 适配器没实现这项能力属于部署问题，按 502 报，不降级成空清单。 */
function unsupported(adapter: EngineAdapter, what: string): AppError {
  return new BadGatewayError(`当前引擎 ${adapter.engine} 不提供${what}`);
}

/** 探测失败（进程起不来、超时、回执异常）统一收口成 502，原始 message 带进响应方便排障。 */
function probeFailure(error: unknown): AppError {
  if (error instanceof AppError) return error;
  return new BadGatewayError(`读取 Claude Code 失败：${error instanceof Error ? error.message : String(error)}`);
}

export const engineService = {
  /** `/` 菜单里对产品可见的条目：技能也以命令形态出现，形状由引擎决定。 */
  async commands(input: { cwd?: unknown }): Promise<EngineCommandsResponse> {
    const cwd = readCwd(input.cwd);
    const adapter = resolveEngineAdapter(config.engine)();
    if (adapter.commands === undefined) throw unsupported(adapter, '命令清单');
    try {
      const items = await adapter.commands(cwd);
      return { engine: adapter.engine, cwd, items: visibleCommands(items) };
    } catch (error) {
      throw probeFailure(error);
    }
  },

  /** 引擎信息：版本、可用模型、登录身份、输出风格。与命令清单共用同一次探测缓存。 */
  async detail(input: { cwd?: unknown }): Promise<EngineInfo> {
    const cwd = readCwd(input.cwd);
    const adapter = resolveEngineAdapter(config.engine)();
    if (adapter.info === undefined) throw unsupported(adapter, '引擎信息');
    try {
      return await adapter.info(cwd);
    } catch (error) {
      if (error instanceof ClaudeCliNotFoundError) {
        return {
          engine: adapter.engine,
          cwd,
          version: '',
          commandCount: 0,
          available: false,
          reason: error.message,
          installHint: CLAUDE_CLI_INSTALL_HINT,
        };
      }
      throw probeFailure(error);
    }
  },
};

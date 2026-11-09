/**
 * Claude Code CLI 的版本判定与"能不能用"探测。
 *
 * 为什么版本要卡一道：`claude plugin install/update/uninstall`、`--scope user`、
 * `--json` 都是 2.1.x 才稳定的接口。更老的版本上，安装会以"插件没装上"
 * 这种看起来像我们打包坏了的方式失败。
 *
 * 版本常量只放这一处（D45）。解析失败时还有一条兜底：只要
 * `claude plugin list --json` 能跑通，就按"版本行格式变了、能力还在"放行。
 */

import os from 'node:os';
import path from 'node:path';

import {
  buildSpawnSpec,
  lastLine,
  resolveExecutable,
  runProcess,
} from './cli-exec.mjs';

/**
 * 最低可用版本。
 *
 * 取值依据：产品方要求的最低版本是 2.1.287（2026-10-21 更新，旧的 2.1.0 已作废）；
 * 本机基线实测 2.1.304。版本再低时接口形状没有保证，宁可让用户升级。
 */
export const MIN_CLAUDE_VERSION = '2.1.287';

/** `claude --version` 必须在这个时间内返回（首次运行可能卡在引导界面）。 */
export const VERSION_TIMEOUT_MS = 5_000;

/** `plugin list --json` 的兜底探测超时。 */
export const PROBE_TIMEOUT_MS = 15_000;

/**
 * 从版本输出里取 `x.y.z`。
 *
 * 实测输出是 `2.1.304 (Claude Code)`；也兼容带 `v` 前缀与前后多余行。
 *
 * @param {string} text
 * @returns {string|null}
 */
export function parseVersion(text) {
  if (typeof text !== 'string') {
    return null;
  }
  const match = /(?:^|[^\d])(\d+)\.(\d+)\.(\d+)(?![\d.])/.exec(text);
  if (match === null) {
    return null;
  }
  return `${Number(match[1])}.${Number(match[2])}.${Number(match[3])}`;
}

/**
 * 当前版本是否不低于最低要求。任一侧解析不了都返回 false——无法判断时
 * 不应假装满足。
 *
 * @param {string} current
 * @param {string} minimum
 */
export function isVersionAtLeast(current, minimum) {
  const left = parseVersion(current);
  const right = parseVersion(minimum);
  if (left === null || right === null) {
    return false;
  }
  const a = left.split('.').map(Number);
  const b = right.split('.').map(Number);
  for (let index = 0; index < 3; index += 1) {
    if (a[index] !== b[index]) {
      return a[index] > b[index];
    }
  }
  return true;
}

/** `--version` 的输出里应当出现产品名，防止把同名的别的工具当成 Claude Code。 */
export function looksLikeClaudeCode(text) {
  return typeof text === 'string' && /claude\s*code/i.test(text);
}

/**
 * 找不到 `claude` 时再找这些位置。
 *
 * 覆盖两类安装方式：原生安装器（`~/.local/bin`、`~/.claude/local`）与 npm 全局
 * （`%APPDATA%\npm`、`%ProgramFiles%\nodejs`）。Windows 的 `PATH` 经常因为
 * 安装顺序或终端缓存而没有刷新，兜底能救回一部分"明明装了却说没装"。
 *
 * @param {{platform?: string, homeDir?: string, env?: NodeJS.ProcessEnv}} [options]
 */
export function claudeFallbackPaths(options = {}) {
  const platform = options.platform ?? process.platform;
  const homeDir = options.homeDir ?? os.homedir();
  const env = options.env ?? process.env;

  if (platform === 'win32') {
    const candidates = [
      path.join(homeDir, '.local', 'bin', 'claude.exe'),
      path.join(homeDir, '.local', 'bin', 'claude.cmd'),
      path.join(homeDir, '.claude', 'local', 'claude.exe'),
      path.join(homeDir, '.claude', 'local', 'claude.cmd'),
    ];
    const appData = env['APPDATA'] ?? env['AppData'];
    if (appData !== undefined && appData !== '') {
      candidates.push(path.join(appData, 'npm', 'claude.cmd'));
    }
    const programFiles = env['ProgramFiles'];
    if (programFiles !== undefined && programFiles !== '') {
      candidates.push(path.join(programFiles, 'nodejs', 'claude.cmd'));
    }
    return candidates;
  }

  return [
    path.join(homeDir, '.local', 'bin', 'claude'),
    path.join(homeDir, '.claude', 'local', 'claude'),
    '/usr/local/bin/claude',
    '/opt/homebrew/bin/claude',
  ];
}

/**
 * 解析 `claude` 可执行文件。参数与返回值见 `resolveExecutable`。
 *
 * @param {{explicit?: string|null, env?: NodeJS.ProcessEnv, platform?: string,
 *   homeDir?: string, fallbacks?: string[]}} [options]
 */
export function resolveClaudeExecutable(options = {}) {
  return resolveExecutable('claude', {
    ...options,
    fallbacks: options.fallbacks ?? claudeFallbackPaths(options),
  });
}

/**
 * 跑一次 `claude --version` 并判读。
 *
 * 返回 `reason` 而不是抛错：报告里要分五类说清楚（没找到是上一层的事）——
 * `spawn-error` / `timeout` / `exit` / `unparsable` / `not-claude` / `too-old`。
 *
 * @param {{executable: string, platform?: string, run?: Function, timeoutMs?: number}} options
 */
export async function readClaudeVersion(options) {
  const { executable } = options;
  const platform = options.platform ?? process.platform;
  const run = options.run ?? runProcess;
  const timeoutMs = options.timeoutMs ?? VERSION_TIMEOUT_MS;

  const spec = buildSpawnSpec(executable, ['--version'], { platform });
  const result = await run(spec, { timeoutMs });
  const raw = [result.stdout, result.stderr]
    .filter((text) => typeof text === 'string' && text.trim() !== '')
    .join('\n')
    .trim();

  if (result.error !== null && result.error !== undefined) {
    return { ok: false, reason: 'spawn-error', raw, message: result.error.message };
  }
  if (result.timedOut) {
    return { ok: false, reason: 'timeout', raw, timeoutMs };
  }
  if (result.code !== 0) {
    return { ok: false, reason: 'exit', raw, code: result.code };
  }

  const version = parseVersion(raw);
  if (version === null) {
    return { ok: false, reason: 'unparsable', raw };
  }
  if (!looksLikeClaudeCode(raw)) {
    return { ok: false, reason: 'not-claude', raw, version };
  }
  if (!isVersionAtLeast(version, MIN_CLAUDE_VERSION)) {
    return { ok: false, reason: 'too-old', raw, version, minimum: MIN_CLAUDE_VERSION };
  }

  return { ok: true, version, raw };
}

/**
 * 兜底探测：`claude plugin list --json` 能否跑通。
 *
 * 只用于"版本行解析不出来"这一种情况。它是只读命令（不安装、不改状态），
 * 可以在 preflight 阶段调用。
 *
 * @param {{executable: string, platform?: string, run?: Function, timeoutMs?: number}} options
 */
export async function probePluginList(options) {
  const { executable } = options;
  const platform = options.platform ?? process.platform;
  const run = options.run ?? runProcess;
  const timeoutMs = options.timeoutMs ?? PROBE_TIMEOUT_MS;

  const spec = buildSpawnSpec(executable, ['plugin', 'list', '--json'], { platform });
  const result = await run(spec, { timeoutMs });

  if (result.error !== null && result.error !== undefined) {
    return { ok: false, reason: 'spawn-error', message: result.error.message };
  }
  if (result.timedOut) {
    return { ok: false, reason: 'timeout' };
  }
  if (result.code !== 0) {
    return { ok: false, reason: 'exit', code: result.code, detail: lastLine(result.stderr) };
  }
  try {
    JSON.parse(result.stdout);
  } catch (error) {
    return { ok: false, reason: 'unparsable-json', detail: lastLine(result.stdout) || error.message };
  }
  return { ok: true };
}

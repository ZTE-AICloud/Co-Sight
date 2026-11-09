/**
 * 与外部 CLI 打交道的最小工具集：找可执行文件、拼 Windows 的 cmd 调用、带超时地跑。
 *
 * 单独成文件而不是塞进 `claude-cli.mjs`：Python 3 的检查也要找可执行文件、
 * 也要带超时跑 `--version`，两处各写一遍必然会在"Windows 上 .cmd 怎么调"
 * 这种细节上分叉。
 *
 * ── Windows 上为什么要特殊处理 ─────────────────────────────────────────
 *
 * `claude` 由 npm 全局安装时是 `claude.cmd`，而 Node 的 `spawn` **不能直接执行
 * `.cmd`**（必须经 `cmd.exe`）。这里按 `.cmd/.bat` 分两路：
 *   - 原生可执行文件 → 直接 spawn，参数按数组传；
 *   - 批处理 → `cmd.exe /d /s /c "…"`，命令行由 `quoteForCmd` 自行拼。
 *
 * POSIX 侧永远直接 spawn、参数按数组传，不做任何字符串拼接。
 */

import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';

/** 默认超时。插件安装这类命令在本机实测都在秒级，120s 只用来兜住"卡死"。 */
export const DEFAULT_RUN_TIMEOUT_MS = 120_000;

/** 子进程输出最多留这么多字符（保留**尾部**：报错信息通常在最后）。 */
const CAPTURE_LIMIT = 64 * 1024;

/**
 * 在 cmd.exe 下无需引号即可安全传递的字符。
 *
 * 刻意不含 `%`：即使加了双引号，cmd 仍会展开 `%VAR%`，拼进命令行的路径会
 * 被悄悄改写。宁可拒绝（见 `quoteForCmd`），也不要发出一个打错目标的命令。
 */
const SAFE_CMD_ARG = /^[A-Za-z0-9_@.,:+=/\\-]+$/;

const BATCH_FILE = /\.(cmd|bat)$/i;
const WINDOWS_EXTENSIONS = ['.exe', '.cmd', '.bat'];

/** @param {string} filePath */
export function isBatchFile(filePath) {
  return BATCH_FILE.test(filePath);
}

/**
 * 把一个参数转成 cmd.exe 命令行里的安全片段。
 *
 * 规则：
 *   - 只含安全字符 → 原样；
 *   - 含空格、中文、`&`、`^`、`|` 等 → 用双引号包住（引号内这些元字符不再生效）；
 *   - 含 `"` / `%` / 换行 / NUL → 抛错。它们无法在 cmd 命令行里可靠转义，
 *     静默拼进去只会得到一条"看起来执行了、其实目标错了"的命令。
 *
 * @param {string} value
 * @returns {string}
 */
export function quoteForCmd(value) {
  if (typeof value !== 'string') {
    throw new TypeError(`命令行参数必须是字符串，收到 ${typeof value}`);
  }
  if (/[\0\r\n]/.test(value)) {
    throw new Error(`参数里含换行或 NUL，无法在 cmd.exe 下安全传递：${JSON.stringify(value)}`);
  }
  if (value.includes('"')) {
    throw new Error(`参数里含双引号，无法在 cmd.exe 下安全传递：${value}`);
  }
  if (value.includes('%')) {
    throw new Error(`参数里含 %，cmd.exe 会把它当变量展开：${value}`);
  }
  if (value === '') {
    return '""';
  }
  return SAFE_CMD_ARG.test(value) ? value : `"${value}"`;
}

/**
 * 把一个可执行文件 + 参数翻译成 `spawn` 需要的形状。
 *
 * `windowsVerbatimArguments` 只在批处理那一路为 true：那条命令行的引号由
 * 我们自己拼，若再让 Node 转义一遍会得到 `\"`，而 cmd 不认识它。
 *
 * @param {string} executable
 * @param {string[]} args
 * @param {{platform?: string, comspec?: string}} [options]
 * @returns {{command: string, args: string[], windowsVerbatimArguments: boolean}}
 */
export function buildSpawnSpec(executable, args = [], options = {}) {
  const platform = options.platform ?? process.platform;

  if (platform === 'win32' && isBatchFile(executable)) {
    const comspec = options.comspec ?? process.env['ComSpec'] ?? process.env['COMSPEC'] ?? 'cmd.exe';
    const line = [quoteForCmd(executable), ...args.map(quoteForCmd)].join(' ');
    // `/s` 让 cmd 去掉最外层引号、其余原样保留；外层引号是必须的（路径可能带空格）。
    return {
      command: comspec,
      args: ['/d', '/s', '/c', `"${line}"`],
      windowsVerbatimArguments: true,
    };
  }

  return { command: executable, args: [...args], windowsVerbatimArguments: false };
}

/** 保留尾部：报错在最后，截头部。 */
function appendCapped(text, chunk) {
  const next = text + chunk;
  return next.length <= CAPTURE_LIMIT ? next : next.slice(next.length - CAPTURE_LIMIT);
}

/**
 * 执行一条命令，带超时与输出捕获。**不抛错**：所有失败都放进返回值，
 * 由调用方翻成报告里的"处理 / 影响"。
 *
 * @param {{command: string, args: string[], windowsVerbatimArguments?: boolean}} spec
 * @param {{timeoutMs?: number, cwd?: string, env?: NodeJS.ProcessEnv}} [options]
 * @returns {Promise<{code: number|null, signal: string|null, stdout: string, stderr: string,
 *   timedOut: boolean, error: Error|null}>}
 */
export function runProcess(spec, options = {}) {
  const timeoutMs = options.timeoutMs ?? DEFAULT_RUN_TIMEOUT_MS;

  return new Promise((resolve) => {
    let settled = false;
    const finish = (result) => {
      if (!settled) {
        settled = true;
        resolve(result);
      }
    };

    let child;
    try {
      child = spawn(spec.command, spec.args, {
        cwd: options.cwd,
        env: options.env,
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
        windowsVerbatimArguments: spec.windowsVerbatimArguments === true,
      });
    } catch (error) {
      finish({ code: null, signal: null, stdout: '', stderr: '', timedOut: false, error });
      return;
    }

    let stdout = '';
    let stderr = '';
    let timedOut = false;
    let killTimer = null;

    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGTERM');
      // SIGTERM 可能被忽略；再等 2 秒强杀，避免安装流程假死。
      killTimer = setTimeout(() => child.kill('SIGKILL'), 2_000);
      killTimer.unref?.();
    }, timeoutMs);
    timer.unref?.();

    child.stdout?.setEncoding('utf8');
    child.stderr?.setEncoding('utf8');
    child.stdout?.on('data', (chunk) => {
      stdout = appendCapped(stdout, chunk);
    });
    child.stderr?.on('data', (chunk) => {
      stderr = appendCapped(stderr, chunk);
    });

    child.on('error', (error) => {
      clearTimeout(timer);
      if (killTimer !== null) {
        clearTimeout(killTimer);
      }
      finish({ code: null, signal: null, stdout, stderr, timedOut, error });
    });

    child.on('close', (code, signal) => {
      clearTimeout(timer);
      if (killTimer !== null) {
        clearTimeout(killTimer);
      }
      finish({ code, signal, stdout, stderr, timedOut, error: null });
    });
  });
}

/**
 * 子进程是否是一个"能直接执行的文件"。
 *
 * Windows 上没有可执行位，文件存在即可；POSIX 上必须带 X 位——否则
 * `resolveExecutable` 会挑中一个 chmod 掉权限的残留文件，然后在 spawn 时
 * 报一句难懂的 EACCES。
 *
 * @param {string} filePath
 * @param {string} [platform]
 */
export function isExecutableFile(filePath, platform = process.platform) {
  let stat;
  try {
    stat = fs.statSync(filePath);
  } catch {
    return false;
  }
  if (!stat.isFile()) {
    return false;
  }
  if (platform === 'win32') {
    return true;
  }
  try {
    fs.accessSync(filePath, fs.constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

/** PATH 在 Windows 上可能以 PATH / Path / path 三种键出现（注入的 env 不一定是代理）。 */
function pathValue(env, platform) {
  if (platform === 'win32') {
    return env['PATH'] ?? env['Path'] ?? env['path'] ?? '';
  }
  return env['PATH'] ?? env['Path'] ?? '';
}

/**
 * 一个命令名在目标平台上的候选文件名（按尝试顺序）。
 *
 * Windows 只认 `.exe/.cmd/.bat`——`claude.com` 之类不在我们的假设里，猜错会把
 * 别的东西当成 Claude Code。`.exe` 永远先试（原生安装器），其余按 `PATHEXT`
 * 的实际顺序（npm 的 `.cmd` 通常在 `.bat` 前）。
 *
 * @param {string} name
 * @param {{platform?: string, pathext?: string, env?: NodeJS.ProcessEnv}} [options]
 */
export function executableNames(name, options = {}) {
  const platform = options.platform ?? process.platform;
  if (platform !== 'win32') {
    return [name];
  }

  const source = options.pathext ?? options.env?.['PATHEXT'] ?? '';
  const fromPathExt = source
    .split(';')
    .map((extension) => extension.trim().toLowerCase())
    .filter((extension) => WINDOWS_EXTENSIONS.includes(extension));
  const extensions = ['.exe', ...new Set(fromPathExt.filter((extension) => extension !== '.exe'))];
  if (!extensions.includes('.cmd')) {
    extensions.push('.cmd');
  }
  if (!extensions.includes('.bat')) {
    extensions.push('.bat');
  }

  return extensions.map((extension) => `${name}${extension}`);
}

/**
 * 按 `--claude` → PATH → 已知位置 的顺序找一个可执行文件。
 *
 * 显式指定的路径**找不到就返回失败**，不再回退到 PATH：用户明确说了"用这个"，
 * 悄悄换用另一个 claude 会让后面的版本检查与安装都落在一份他没选的环境上。
 *
 * @param {string} name
 * @param {{explicit?: string|null, env?: NodeJS.ProcessEnv, platform?: string,
 *   homeDir?: string, fallbacks?: string[], pathext?: string}} [options]
 * @returns {{path: string|null, source: 'explicit'|'path'|'fallback'|null,
 *   checked: {explicitPath: string|null, pathDirs: string[], fallbacks: string[]}}}
 */
export function resolveExecutable(name, options = {}) {
  const platform = options.platform ?? process.platform;
  const env = options.env ?? process.env;
  const explicit = options.explicit === undefined || options.explicit === null
    ? null
    : path.resolve(options.explicit);
  const fallbacks = options.fallbacks ?? [];
  const separator = platform === 'win32' ? ';' : ':';

  const pathDirs = pathValue(env, platform)
    .split(separator)
    .map((dir) => dir.trim())
    .filter((dir) => dir !== '');
  const names = executableNames(name, { platform, env, pathext: options.pathext });

  const checked = { explicitPath: explicit, pathDirs, fallbacks };
  const seen = new Set();
  const consider = (candidate, source) => {
    const key = platform === 'win32' ? candidate.toLowerCase() : candidate;
    if (seen.has(key)) {
      return null;
    }
    seen.add(key);
    return isExecutableFile(candidate, platform) ? { path: candidate, source, checked } : null;
  };

  if (explicit !== null) {
    return consider(explicit, 'explicit') ?? { path: null, source: null, checked };
  }

  for (const dir of pathDirs) {
    for (const candidateName of names) {
      const hit = consider(path.join(dir, candidateName), 'path');
      if (hit !== null) {
        return hit;
      }
    }
  }

  for (const fallback of fallbacks) {
    const hit = consider(fallback, 'fallback');
    if (hit !== null) {
      return hit;
    }
  }

  return { path: null, source: null, checked };
}

/** 输出里的最后一行（报错通常在那），限制长度，避免把整段日志塞进报告。 */
export function lastLine(text, limit = 200) {
  if (typeof text !== 'string') {
    return '';
  }
  const line = text
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter((item) => item !== '')
    .at(-1) ?? '';
  return line.length > limit ? `${line.slice(0, limit)}…` : line;
}

/**
 * 把 `runProcess` 的失败翻成一句人话，供报告的 `处理 / 影响` 使用。
 *
 * @param {{code: number|null, stderr: string, stdout: string, timedOut: boolean,
 *   error: Error|null}} result
 * @param {number} timeoutMs
 */
export function describeRunFailure(result, timeoutMs) {
  if (result.error !== null && result.error !== undefined) {
    return `无法启动：${result.error.message}`;
  }
  if (result.timedOut) {
    return `${Math.round(timeoutMs / 1000)} 秒内没有返回`;
  }
  const tail = lastLine(result.stderr, 200) || lastLine(result.stdout, 200);
  return tail === '' ? `退出码 ${result.code}` : `退出码 ${result.code}：${tail}`;
}

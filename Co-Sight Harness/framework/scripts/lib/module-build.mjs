/**
 * 模块产物的"陈旧判定"与"重建执行"。
 *
 * ── 它解决的是哪种故障 ────────────────────────────────────────────────
 * 有的模块的开发态入口**就是产物**：cosight-viewer 的 server 静态托管 `client/dist`，
 * 而 `dist/` 是 gitignore 的。于是 `git pull` 拉到新源码之后，页面还是旧的——
 * 人会得出"功能没做"的结论，而真相是"本机这份产物是几天前打的"。
 * 实测踩到过：同事合进来的对话页在本机 404，因为旧包里连那条 hash 路由都没有。
 *
 * 这类故障的共性是**不报错**：产物旧了不会有人告诉你，只会安静地骗你。
 * 所以把"启动前刷一遍产物"变成清单里的 `build` 字段（见 `module-launch.mjs` 的说明），
 * 由本文件在启动前落实。
 *
 * ── 判据 ──────────────────────────────────────────────────────────────
 *   输入（`inputs`）中最新的一个 > 产物（`outputs`）中最旧的一个 → 陈旧，要重建。
 * 保守方向是**宁可多建一次**：判错的代价是白等一次构建，而不是被骗一次。
 * 目录产物取其树里最新的文件时间（"最后一次写产物"的时刻）。
 *
 * 刻意不做的事：不删产物目录再重建（`vite build` 自己会清 `dist`），
 * 不读产物内容算哈希（那把"快"这件事也一起丢了）。
 */

import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

import { pumpPrefixed } from './runtime.mjs';

/**
 * 遍历输入目录时跳过的目录名。
 *
 * `node_modules` / `.git` / `.run` 是"与源码无关"（依赖、版本库元数据、模块自己的运行时数据，
 * 后者每次跑都会变，留着会让判定永远陈旧）；`dist` / `build` / `out` 是"本身就是产物"
 * （除非它就是被声明的产物，否则把产物当输入只会自我循环）。
 * 点开头的目录一律跳过，覆盖 `.vite` / `.husky` / `.cache` 这些工具目录。
 */
const SKIPPED_DIR_NAMES = new Set(['node_modules', 'dist', 'build', 'out']);

function shouldSkipDir(name) {
  return name.startsWith('.') || SKIPPED_DIR_NAMES.has(name);
}

/** 一个条目的 mtime；符号链接看链接本身（不跟随，避免指到产物外面去）。 */
function mtimeOf(absPath) {
  try {
    return fs.lstatSync(absPath).mtimeMs;
  } catch {
    return null;
  }
}

/**
 * 一棵目录树里最新的文件时间。
 * @returns {{mtimeMs: number, path: string}|null} 空目录或读不到时返回 null
 */
function newestMtimeInTree(rootAbs, isExcluded) {
  let newest = null;
  const stack = [rootAbs];

  while (stack.length > 0) {
    const current = stack.pop();
    let dirents;
    try {
      dirents = fs.readdirSync(current, { withFileTypes: true });
    } catch {
      // 读不动（权限、竞态删除）就当它没有内容，不让一次 stat 失败掀翻启动。
      continue;
    }

    for (const dirent of dirents) {
      const absolute = path.join(current, dirent.name);
      if (isExcluded(absolute)) {
        continue;
      }
      if (dirent.isDirectory()) {
        if (!shouldSkipDir(dirent.name)) {
          stack.push(absolute);
        }
        continue;
      }
      const mtimeMs = mtimeOf(absolute);
      if (mtimeMs !== null && (newest === null || mtimeMs > newest.mtimeMs)) {
        newest = { mtimeMs, path: absolute };
      }
    }
  }

  return newest;
}

/**
 * 一个被声明的路径的"时间"：文件取自己的 mtime，目录取树里最新的那个文件——
 * 也就是"最后一次写它的时刻"。
 *
 * @returns {{exists: boolean, mtimeMs: number|null}}
 */
function timestampOf(absPath, isExcluded) {
  let stat;
  try {
    stat = fs.lstatSync(absPath);
  } catch {
    return { exists: false, mtimeMs: null };
  }

  if (!stat.isDirectory()) {
    return { exists: true, mtimeMs: stat.mtimeMs };
  }

  const newest = newestMtimeInTree(absPath, isExcluded);
  // 目录存在但里面一个文件都没有（或全被跳过）时用目录自己的 mtime。
  return { exists: true, mtimeMs: newest === null ? stat.mtimeMs : Math.max(newest.mtimeMs, stat.mtimeMs) };
}

function relativeTo(base, absolute) {
  const relative = path.relative(base, absolute);
  return relative === '' ? '.' : relative;
}

/** 两位补零，`2026-10-16 09:19:18` 里的每一段都靠它。 */
function pad2(value) {
  return String(value).padStart(2, '0');
}

/**
 * 把毫秒时间戳写成 `YYYY-MM-DD HH:mm:ss`，给人看的。
 *
 * 用**本地时间**而不是 `toISOString()`：这行字是要和 `ls -l` 的输出去对照的
 * （"哪个文件比哪个新"），而 `ls` 给的是本地时间。差 8 小时的时间戳只会让人
 * 以为判据算错了——判据本身是对的，错的是显示。
 */
function formatTime(mtimeMs) {
  const date = new Date(mtimeMs);
  return (
    `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ` +
    `${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}`
  );
}

/**
 * 判定产物是否需要重建。
 *
 * @param {{cwd: string, inputs: string[], outputs: string[]}} spec
 * @returns {{stale: boolean, reason: string, detail: string|null}}
 *   `reason` 是给总表/日志用的一行短句；`detail` 是"为什么"那半句，可空。
 * @throws {Error} 清单里声明的路径不存在——这类错误**不**降级为"就当它陈旧"：
 *   写错的 `inputs` 会让"改了源码却不重建"，那正是这个字段要防的故障，必须当场说清。
 */
export function inspectBuild(spec) {
  const outputs = spec.outputs.map((relative) => ({
    relative,
    absolute: path.resolve(spec.cwd, relative),
  }));

  // 产物自身不算输入：否则 `inputs: ["."]` 会把刚打完的产物当"更新的输入"，永远陈旧。
  const outputAbsolutes = outputs.map((output) => output.absolute);
  const isInsideOutput = (absolute) =>
    outputAbsolutes.some(
      (output) => absolute === output || absolute.startsWith(`${output}${path.sep}`),
    );

  const missing = [];
  let oldest = null;
  for (const output of outputs) {
    const stamp = timestampOf(output.absolute, isInsideOutput);
    if (!stamp.exists) {
      missing.push(output.relative);
      continue;
    }
    if (oldest === null || stamp.mtimeMs < oldest.mtimeMs) {
      oldest = { relative: output.relative, mtimeMs: stamp.mtimeMs };
    }
  }

  if (missing.length > 0) {
    const shown = missing.slice(0, 2).join('、');
    const more = missing.length > 2 ? ` 等 ${missing.length} 个` : '';
    return { stale: true, reason: '产物不存在', detail: `${shown}${more}（首次构建或产物被清掉了）` };
  }

  let newestInput = null;
  for (const relative of spec.inputs) {
    const absolute = path.resolve(spec.cwd, relative);

    let stat;
    try {
      stat = fs.lstatSync(absolute);
    } catch {
      throw new Error(
        `build.inputs 里的 "${relative}" 不存在（在 ${spec.cwd} 下）——写错一个输入会让"改了源码却不重建"，请改清单。`,
      );
    }

    const found = stat.isDirectory()
      ? newestMtimeInTree(absolute, isInsideOutput)
      : { mtimeMs: stat.mtimeMs, path: absolute };

    if (found !== null && (newestInput === null || found.mtimeMs > newestInput.mtimeMs)) {
      newestInput = found;
    }
  }

  if (newestInput === null) {
    return { stale: false, reason: '产物是最新的（输入里没有可比对的文件）', detail: null };
  }

  if (newestInput.mtimeMs > oldest.mtimeMs) {
    return {
      stale: true,
      reason: '源码比产物新',
      detail: `${relativeTo(spec.cwd, newestInput.path)}（${formatTime(newestInput.mtimeMs)}）比 ${oldest.relative}（${formatTime(oldest.mtimeMs)}）新`,
    };
  }

  return {
    stale: false,
    reason: '产物是最新的',
    detail: `最新输入 ${relativeTo(spec.cwd, newestInput.path)}（${formatTime(newestInput.mtimeMs)}）不晚于产物`,
  };
}

/** Windows 上 `npm` / `pnpm` 是 `.cmd`，`spawn` 直接调用会 ENOENT / EINVAL。 */
const WINDOWS_SHIM_PROGRAMS = /^(?:npm|npx|pnpm|yarn)$/i;

function quoteWindowsArg(value) {
  return /[\s"&|<>^]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
}

/**
 * 清单一的「程序 + 参数」→ `spawn` 的调用形式。
 *
 * POSIX 原样返回。Windows 上 npm 家族是批处理垫片，必须经过 `cmd.exe`；
 * 参数里的空格与 `&` 之类由这里加引号，不能指望清单写全。
 */
function buildInvocation(command) {
  const [program, ...args] = command;
  if (process.platform !== 'win32' || !WINDOWS_SHIM_PROGRAMS.test(program)) {
    return { program, args, shell: false };
  }
  const commandLine = [program, ...args].map(quoteWindowsArg).join(' ');
  return { program: process.env.ComSpec ?? 'cmd.exe', args: ['/d', '/s', '/c', commandLine], shell: false };
}

/**
 * 跑一次重建，输出带前缀转发。
 *
 * `detached: true` 与服务的处理一致：这样超时或收尾时能对**整个进程组**发信号。
 * 构建命令都是包一层的（`npm run build` → `tsc -b` / `vite build`），只杀直接子进程
 * 会留下真正在干活的孙进程继续写产物——那比不重建更糟，产物会停在半路。
 *
 * `spec.env` 是构建期追加的环境变量（例如前端需要 `VITE_*`）；它在调用方给的
 * 基础环境之上覆盖。
 *
 * @param {{command: string[], cwd: string, timeoutMs: number, env?: Record<string, string>}} spec
 * @param {{label: string, width?: number, env: Record<string, string>, register?: (child: import('node:child_process').ChildProcess) => void}} options
 * @returns {Promise<{ok: boolean, code: number|null, signal: string|null, timedOut: boolean, elapsedMs: number}>}
 */
export function runBuild(spec, options) {
  return new Promise((resolve) => {
    const startedAt = Date.now();
    const invocation = buildInvocation(spec.command);
    const child = spawn(invocation.program, invocation.args, {
      cwd: spec.cwd,
      env: { ...options.env, ...spec.env },
      detached: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    pumpPrefixed(child, { label: options.label, width: options.width ?? options.label.length });
    // 交给调用方登记：Ctrl-C 时收尾路径按进程组把它一起收掉（同服务的处理）。
    options.register?.(child);

    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      killGroup(child);
    }, spec.timeoutMs);

    const finish = (code, signal) => {
      clearTimeout(timer);
      resolve({ ok: code === 0, code, signal, timedOut, elapsedMs: Date.now() - startedAt });
    };

    child.on('error', (error) => {
      clearTimeout(timer);
      resolve({
        ok: false,
        code: null,
        signal: null,
        timedOut: false,
        elapsedMs: Date.now() - startedAt,
        // 起不来的原因（ENOENT 之类）比"失败"本身有用得多。
        spawnError: error.message,
      });
    });
    child.on('exit', (code, signal) => {
      finish(code, signal);
    });
  });
}

/** 对整个进程组发 SIGKILL；组不在了就退回单进程。 */
function killGroup(child) {
  if (child.pid === undefined) {
    return;
  }
  try {
    process.kill(-child.pid, 'SIGKILL');
  } catch {
    try {
      child.kill('SIGKILL');
    } catch {
      // 已经退出了。
    }
  }
}

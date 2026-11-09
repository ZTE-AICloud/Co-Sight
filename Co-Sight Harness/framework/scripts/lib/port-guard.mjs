/**
 * 端口占用的检测、归因与回收。
 *
 * 总启动脚本要起五个服务，任何一个端口被占都会让那一半"看起来启动了、其实没起来"。
 * 而且最常见的占用者不是别人，是**上一次运行没停干净的自己**——`detached` 起的
 * vite / tsx watch 在父进程被 SIGKILL 时会活下来继续占端口。所以这里做三件事：
 *
 *  1. **检测**：两个回环地址都探。vite 未设 `server.host` 时只绑 `[::1]`，
 *     只探 `127.0.0.1` 会把"已经被占"漏报成"空闲"，紧接着就是一次 EADDRINUSE。
 *  2. **归因**：拿状态文件（`<framework>/.run/dev-all.json`）把占用者分成三类——
 *     本脚本上一次的**残留**（应当回收）、上一次**仍在运行**（不该动它）、**外来进程**
 *     （更不该动）。三类的处理方式完全不同，分不清就只能瞎猜。
 *  3. **回收**：TERM → 宽限 → KILL，并**按进程组**回收（自己的子进程是 detached 的组长，
 *     `pnpm` 的孙进程 vite 只有整组杀才死得掉）。
 */

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';

import { sleep } from './runtime.mjs';

/** 单次连接探测的超时。本机连接被拒是毫秒级返回，这只是兜底。 */
const PORT_PROBE_TIMEOUT_MS = 1500;
/** 回收占用的宽限：先 TERM，这么久还没释放就 KILL。 */
const FREE_GRACE_MS = 5000;

function tryConnect(host, port) {
  return new Promise((resolve) => {
    const socket = net.connect({ host, port });
    let settled = false;
    const finish = (result) => {
      if (settled) {
        return;
      }
      settled = true;
      socket.destroy();
      resolve(result);
    };

    socket.setTimeout(PORT_PROBE_TIMEOUT_MS);
    socket.once('connect', () => {
      finish(true);
    });
    socket.once('timeout', () => {
      finish(false);
    });
    socket.once('error', () => {
      finish(false);
    });
  });
}

/** @returns {Promise<boolean>} 端口上有人在监听 */
export async function isPortOpen(port) {
  for (const host of ['127.0.0.1', '::1']) {
    if (await tryConnect(host, port)) {
      return true;
    }
  }
  return false;
}

function runQuietly(command, args) {
  const result = spawnSync(command, args, { encoding: 'utf8', timeout: 2000 });
  if (result.error || typeof result.stdout !== 'string' || result.stdout.length === 0) {
    return null;
  }
  return result.stdout;
}

/**
 * 找出监听某个端口的进程。**尽力而为**：拿不到进程信息不是错误，
 * 报不出占用者也不该让预检本身失败。
 *
 * @returns {{pid: number, command: string, port: number}|null}
 */
export function findPortOwner(port) {
  const pattern = new RegExp(`[:.]${port}\\b`);

  const fromSs = runQuietly('ss', ['-ltnp']);
  if (fromSs !== null) {
    const line = fromSs.split('\n').find((item) => pattern.test(item));
    if (line !== undefined) {
      const users = /\(\("([^"]+)",pid=(\d+)/.exec(line);
      if (users !== null) {
        return { pid: Number.parseInt(users[2], 10), command: users[1], port };
      }
      // 行匹配上了但读不到 pid：端口确实被占（可能是别人的进程），如实说"未知"。
      return { pid: 0, command: '未知', port };
    }
  }

  const fromLsof = runQuietly('lsof', ['-nP', `-iTCP:${port}`, '-sTCP:LISTEN']);
  if (fromLsof !== null) {
    const line = fromLsof.split('\n').slice(1).find((item) => item.trim().length > 0);
    if (line !== undefined) {
      const fields = line.trim().split(/\s+/);
      const pid = Number.parseInt(fields[1] ?? '', 10);
      if (Number.isInteger(pid) && pid > 0) {
        return { pid, command: fields[0], port };
      }
    }
  }

  return null;
}

// ── 运行状态文件 ────────────────────────────────────────────────────────

/**
 * 记录"本次运行起了哪些进程"，用于区分残留与仍在运行。
 *
 * 为什么必须落盘：`detached` 的子进程在父进程被 SIGKILL 时会活下来，而父进程已经
 * 无从知晓它们的存在。只有上一次自己写下的记录能把它们认回来。
 */
export function readRunState(file) {
  try {
    const parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (parsed === null || typeof parsed !== 'object' || !Array.isArray(parsed.services)) {
      return null;
    }
    return parsed;
  } catch {
    // 文件不存在或坏了都当成"没有记录"：宁可不回收，也不要凭一个读不懂的文件去杀进程。
    return null;
  }
}

export function writeRunState(file, state) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, `${JSON.stringify(state, null, 2)}\n`);
}

export function clearRunState(file) {
  fs.rmSync(file, { force: true });
}

/**
 * 进程是否还在。对外导出是因为调用方（`dev-all.mjs`）也要用它来决定收尾后
 * 状态文件的去留：还有活着的就留着当线索，全死了才删。
 */
export function isPidAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) {
    return false;
  }
  try {
    // 信号 0 = 只检查存活与权限，不真的发信号。
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

/**
 * 读一个进程的进程组 id（`/proc/<pid>/stat` 的第 5 个字段）。
 *
 * 为什么需要它：直接子进程是 `pnpm` / `npm` 包装器，真正**监听端口**的是它的孙进程
 * （tsx watch / vite），而那个孙进程未必和包装器同组——实测 `pnpm run dev` 起的 tsx
 * 落在一个中间组里。要把它和它的 esbuild 子进程一起收掉，只能读它**自己的**组号。
 *
 * @returns {number|null}
 */
function readProcessGroup(pid) {
  try {
    const stat = fs.readFileSync(`/proc/${pid}/stat`, 'utf8');
    // comm 字段可能含空格和括号，所以从最后一个 ')' 之后开始切，位置才稳定。
    const fields = stat.slice(stat.lastIndexOf(')') + 2).split(' ');
    const pgrp = Number.parseInt(fields[2] ?? '', 10);
    return Number.isInteger(pgrp) ? pgrp : null;
  } catch {
    // 进程不在了，或不是 Linux（没有 /proc）。
    return null;
  }
}

/**
 * 判断占用者是谁。
 *
 * 匹配用的是**监听者的 pid**，所以要同时看 `listenerPid`（就绪后探到的实际监听者）
 * 和 `pid`（spawn 出来的进程组组长）。只看后者的话，`pnpm` / `npm` 包一层就会全部
 * 匹配不上——实测最开始的版本就是这样，五个服务里有四个被误报成"别人的进程"，
 * 于是"自动回收自己的残留"对它们完全失效。
 *
 * @returns {Promise<{kind: 'free'|'own-leftover'|'own-running'|'foreign',
 *                    owner: {pid: number, command: string, port: number}|null,
 *                    recorded: object|null}>}
 *   `own-leftover` 本脚本上一次的残留（上次的监督进程已不在，可以回收）
 *   `own-running`  本脚本上一次仍在运行（上次的监督进程还活着，**不能**动它）
 *   `foreign`      别人的进程（要动必须显式授权）
 *   `recorded`     命中时给出状态文件里的那条记录，回收时要用它的组长 pid
 */
export async function classifyPort(port, state) {
  if (!(await isPortOpen(port))) {
    return { kind: 'free', owner: null, recorded: null };
  }

  const owner = findPortOwner(port);
  if (owner === null || owner.pid <= 0) {
    return { kind: 'foreign', owner, recorded: null };
  }

  const recorded = state?.services?.find(
    (service) => service.port === port && (service.pid === owner.pid || service.listenerPid === owner.pid),
  );
  if (recorded === undefined) {
    return { kind: 'foreign', owner, recorded: null };
  }

  const supervisorAlive = isPidAlive(state?.supervisorPid);
  return { kind: supervisorAlive ? 'own-running' : 'own-leftover', owner, recorded };
}

/**
 * 回收一个占用者：TERM → 宽限 → KILL。
 *
 * 要停的**不是一个进程，是一棵树**：占用端口的可能是 `pnpm` → `tsx watch` → `esbuild`
 * 这样三层，而记录里只有其中一两个 pid。所以这里把能确定的几个目标都发一遍，
 * 全都尽力而为（进程已经不在就吞掉 ESRCH）：
 *
 *   · `owner.pid` 的**自己的进程组**——覆盖监听者（tsx / vite）及其子进程（esbuild）；
 *   · `owner.pid` 本身——不是组长时的兜底；
 *   · `groupLeaderPid` 的进程组——`detached` 起的包装器，覆盖整棵子树。
 *
 * **两道保险不能省**：组号 0 和 1 绝对不能发（`kill(-1)` 会打穿整台机器），
 * 以及绝不发自己的进程组（否则回收残留会把自己也一起收掉）。
 *
 * @param {{pid: number, command: string, port: number}} owner 实际监听该端口的进程
 * @param {{graceMs?: number, groupLeaderPid?: number|null}} options
 *        `groupLeaderPid`：状态文件里记的那个进程组组长（spawn 出来、`detached: true` 的直接子进程）。
 * @returns {Promise<boolean>} 端口是否已经释放
 */
export async function freePort(owner, options = {}) {
  const graceMs = options.graceMs ?? FREE_GRACE_MS;
  const groupLeaderPid = options.groupLeaderPid ?? null;
  // 自己的进程组也要读 /proc：Node 没有 `process.getpgrp()`（只有 POSIX 绑定里有）。
  const ownGroup = readProcessGroup(process.pid);

  const signal = (name) => {
    const pgrp = readProcessGroup(owner.pid);
    const groups = [pgrp, groupLeaderPid];
    const targets = new Set();
    for (const group of groups) {
      if (Number.isInteger(group) && group > 1 && group !== ownGroup) {
        targets.add(-group);
      }
    }
    targets.add(owner.pid);

    for (const target of targets) {
      try {
        process.kill(target, name);
      } catch {
        // 已经退出了 / 组不存在 / 没权限。继续试下一个目标。
      }
    }
  };

  signal('SIGTERM');

  const deadline = Date.now() + graceMs;
  while (Date.now() < deadline) {
    if (!(await isPortOpen(owner.port))) {
      return true;
    }
    await sleep(200);
  }

  signal('SIGKILL');

  const killDeadline = Date.now() + 2000;
  while (Date.now() < killDeadline) {
    if (!(await isPortOpen(owner.port))) {
      return true;
    }
    await sleep(200);
  }

  return false;
}

#!/usr/bin/env node
/**
 * 总体启动脚本（开发态）：一条命令起 framework 的前后端 + 各模块的前后端。
 *
 * ── 它在四条命令里的位置（先读这段，它决定了本脚本不做什么）────────────────
 *
 *   `pnpm dev`          框架自己的开发态（D27=A 唯一认可的开发入口），只起框架的三个包
 *   `pnpm start`        装配态，走 `start.mjs`（服务端 + 已构建的前端产物）；产物布局下
 *                       它会按 `docs/modules/<id>.artifact.json` **拉起模块**（D41）
 *   模块自带脚本        `node smart-factory/scripts/dev.mjs start`、`co-sight-viewer start`——单独跑某个模块时用
 *   `pnpm dev:all`      本脚本：一条命令起全部，**只服务开发态**，不替代上面三个
 *
 * 与 `start.mjs` 的边界是分开的，不是放宽的：
 * `start.mjs` 服务的是"装配好的产物能不能跑起来"，产物布局下它按装配态清单拉起模块并探活；
 * 本脚本服务的是"我坐在开发机上，一条命令把整套
 * 调起来"，所以它需要知道每个模块怎么启动。这件事**没有**写进运行时契约
 * （`shared/src/contracts/module.ts` 里仍然只有 entry / capability / healthcheck），
 * 而是登记在同目录的旁挂清单 `<id>.launch.json` 里，由 `lib/module-launch.mjs` 读取。
 *
 * ── 启动顺序 ──────────────────────────────────────────────────────────
 *
 * 框架前后端（写死在本文件里）→ 模块按 `priority` 升序 → 模块内按 services 数组顺序。
 * 每一步都**等就绪才走下一步**：后起的服务往往依赖前面的在监听
 * （smart-factory 的 vite proxy 依赖它的后端；框架前端依赖框架后端），抢跑只会得到一屏
 * "连接被拒绝"，然后人以为脚本坏了。
 *
 * ── 故障策略 ──────────────────────────────────────────────────────────
 *
 *   框架服务意外退出  → 停掉全部、退出码 1（宿主没了，"保证框架可用"这个目标已经不存在，
 *                      继续挂着一堆模块只会让人以为还在跑）
 *   模块服务意外退出  → 只标注，不拖垮整体（开发态刻意比 start.mjs 的失败即停宽松：
 *                      改代码时模块崩了还要能继续看其余部分）
 *   就绪超时          → 只标注（慢或报错都该让人看日志，日志就在终端上带前缀滚过）
 */

import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { buildSpawnSpec, resolveExecutable } from './lib/cli-exec.mjs';
import { inspectBuild, runBuild } from './lib/module-build.mjs';
import { listIsolatedDirs, scanLaunchEntries } from './lib/module-launch.mjs';
import { formatProbeReport, probeModules, scanModuleManifests } from './lib/module-probe.mjs';
import {
  clearRunState,
  classifyPort,
  findPortOwner,
  freePort,
  isPidAlive,
  readRunState,
  writeRunState,
} from './lib/port-guard.mjs';
import { MODULE_ROOT, REPO_ROOT } from './lib/project.mjs';
import { pumpPrefixed, superviseAll, waitForAnyHttpOk } from './lib/runtime.mjs';

/** 五个服务里最低的门槛是 20；框架自身更严（根 package.json 的 engines），由 pnpm 把关。 */
const NODE_MIN_MAJOR = 20;
const SHUTDOWN_GRACE_MS = 10_000;
const DEFAULT_HOME = path.join(os.homedir(), '.cosight-harness');

/** 宿主前端的源。模块清单里写的 entry 都在别的源上（D24=A 的跨源要求）。 */
const HOST_ORIGIN = 'http://localhost:4310';

/** 仓库里的模块清单真源；`<id>.launch.json` 与 `<id>.module.json` 都放在这儿。 */
const MODULES_DIR = path.join(MODULE_ROOT, 'docs', 'modules');

/**
 * 本次运行起了哪些进程的记录。落盘是为了**下一次**能认出自己的残留：
 * detached 的子进程在父进程被 SIGKILL 时会活下来继续占端口，而父进程已经无从知晓它们。
 */
const RUN_STATE_FILE = path.join(MODULE_ROOT, '.run', 'dev-all.json');

/**
 * 框架自己的两个服务，写死在这里而不是走 launch.json。
 *
 * 理由：不存在"第三方登记"的问题——宿主就是本仓库自己。给框架也造一份清单文件，
 * 只会多一层"改框架要先改配置"的绕路。
 */
const FRAMEWORK_SERVICES = [
  {
    label: 'framework:server',
    kind: 'framework',
    cwd: REPO_ROOT,
    depsDir: path.join(MODULE_ROOT, 'server'),
    command: ['pnpm', '--filter', 'harness-server', 'run', 'dev'],
    port: 4300,
    readyPath: '/api/health',
    readyTimeoutMs: 30_000,
    stripEnvPrefixes: [],
  },
  {
    label: 'framework:web',
    kind: 'framework',
    cwd: REPO_ROOT,
    depsDir: path.join(MODULE_ROOT, 'web'),
    command: ['pnpm', '--filter', 'harness-web', 'run', 'dev'],
    port: 4310,
    readyPath: '/',
    readyTimeoutMs: 30_000,
    stripEnvPrefixes: [],
  },
];

const HELP = `用法：node framework/scripts/dev-all.mjs [选项]

开发态总启动：framework 前后端 → 按优先级依次起各模块的前后端，每步等就绪。
前台运行，Ctrl-C 按逆序停掉全部。一次没停干净时再按一次会强制结束。

启动前会把每个服务要用的端口都预检一遍（两个回环都探），并把占用者分成三种：
  · 上一次运行的残留（监督进程已不在）—— 自动回收，并打印它杀了谁
  · 上一次的运行仍在进行（监督进程还活着）—— 不动它，提示你去那个终端 Ctrl-C
  · 别人的进程 —— 默认不动，报给你；要停它得显式加 --kill-ports

选项：
  --live          不隔离模块的数据目录（例如让观测模块看你真实的 ~/.claude）；
                  会改动仓库外的用户级配置，默认关闭
  --home <dir>    框架数据目录（等价 COSIGHT_HOME，默认 ${DEFAULT_HOME}）
                  同时也是模块清单的落地目录 <home>/modules
  --reuse         端口被占用时复用已有实例，不报错。
                  注意：复用的实例不归本脚本管，Ctrl-C 不会停它
  --kill-ports    授权本脚本停掉占用端口的进程（TERM → 宽限 → KILL）。
                  只在确认那些进程是你自己的、可以杀的时候用
  --rebuild       无条件重建所有声明了 build 的模块产物（默认只在产物比源码旧时重建）
  --no-build      完全不碰模块产物，用本机现状启动（排查构建本身的问题时用）
  -h, --help      显示本帮助

模块的启动方式登记在 framework/docs/modules/<id>.launch.json，
新增模块不需要改本脚本。详见 framework/docs/dev-all.md。

模块产物：清单里声明了 build 的模块（例如 cosight-viewer 的 client/dist）会在它的服务
启动前比对源码与产物的时间，只重建旧的那一份。产物是 gitignore 的，git pull 不会更新它，
不刷就永远是旧的——页面缺了同事刚合的功能，而你只会以为"功能没做"。
构建失败、或 inputs 路径写错时，该模块的服务不会启动：宁可少起一个，也不拿旧产物骗你；
确实要用当前产物启动，就显式加 --no-build。
--rebuild 与 --no-build 互斥：一个要求"都重建"，一个要求"都别碰"。
`;

function writeLine(line = '') {
  process.stdout.write(`${line}\n`);
}

function writeWarn(line) {
  process.stderr.write(`[dev-all] ${line}\n`);
}

// ── 参数 ────────────────────────────────────────────────────────────────

function parseArgs(argv) {
  const options = {
    live: false,
    reuse: false,
    killPorts: false,
    rebuild: false,
    noBuild: false,
    home: path.resolve(process.env['COSIGHT_HOME'] ?? DEFAULT_HOME),
    help: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const [flag, inlineValue] = arg.startsWith('--') && arg.includes('=')
      ? [arg.slice(0, arg.indexOf('=')), arg.slice(arg.indexOf('=') + 1)]
      : [arg, null];
    const takeValue = () => {
      if (inlineValue !== null) {
        return inlineValue;
      }
      index += 1;
      const next = argv[index];
      if (next === undefined) {
        throw new Error(`${flag} 需要一个值`);
      }
      return next;
    };

    switch (flag) {
      case '--live':
        options.live = true;
        break;
      case '--reuse':
        options.reuse = true;
        break;
      case '--kill-ports':
        options.killPorts = true;
        break;
      case '--rebuild':
        options.rebuild = true;
        break;
      case '--no-build':
        options.noBuild = true;
        break;
      case '--home':
        options.home = path.resolve(takeValue());
        break;
      case '-h':
      case '--help':
        options.help = true;
        break;
      default:
        throw new Error(`未知参数 ${arg}`);
    }
  }

  // 一个说"都重建"、一个说"都别碰"：同时给出来只能猜哪个优先，不如直接报错。
  if (options.rebuild && options.noBuild) {
    throw new Error('--rebuild 与 --no-build 互斥，只能选一个');
  }

  return options;
}

// ── 前置检查 ────────────────────────────────────────────────────────────

function checkRuntime() {
  const major = Number.parseInt(process.versions.node.split('.')[0], 10);
  if (!Number.isFinite(major) || major < NODE_MIN_MAJOR) {
    throw new Error(`需要 Node.js >= ${NODE_MIN_MAJOR}，当前 ${process.version}`);
  }

  for (const tool of ['pnpm', 'npm']) {
    // 裸名字 spawnSync 在 Windows 上必然失败：pnpm / npm 实际是 `.cmd`，而 Node 22
    // 既不会按 PATHEXT 补后缀（ENOENT），也不允许在 `shell: false` 下执行 `.cmd`（EINVAL）。
    // 走与包构建 / 插件安装相同的解析 + `cmd.exe` 拼装，两个平台只有一条路径。
    const resolved = resolveExecutable(tool);
    if (resolved.path === null) {
      throw new Error(`找不到可用的 ${tool}（框架自身用 pnpm，模块有的用 npm，两者都需要）`);
    }
    const spec = buildSpawnSpec(resolved.path, ['--version']);
    const result = spawnSync(spec.command, spec.args, {
      encoding: 'utf8',
      timeout: 5000,
      windowsVerbatimArguments: spec.windowsVerbatimArguments,
    });
    if (result.error || result.status !== 0) {
      throw new Error(`找不到可用的 ${tool}（框架自身用 pnpm，模块有的用 npm，两者都需要）`);
    }
  }
}

/**
 * 依赖缺失时给出指引，而不是让 npm/tsx 报一屏找不到模块。
 *
 * **刻意不代替用户安装**：有的模块的 postinstall / prepare 会改动仓库或用户级配置，
 * 一个"顺手帮你装一下"的启动脚本是最容易埋雷的地方。
 */
function checkDeps(plan) {
  const missing = plan.filter(
    (service) => !service.reused && !fs.existsSync(path.join(service.depsDir, 'node_modules')),
  );
  if (missing.length === 0) {
    return;
  }

  const lines = ['以下服务缺依赖：'];
  for (const service of missing) {
    lines.push(`  ${service.label}  ← ${path.join(service.depsDir, 'node_modules')} 不存在`);
  }
  lines.push('请在各自的目录里装依赖（安装方式见该模块自己的 README）。');
  lines.push('本脚本不代替安装：有的模块在安装阶段会改动仓库或你的全局配置。');
  throw new Error(lines.join('\n'));
}

// ── 模块清单同步 ────────────────────────────────────────────────────────

/**
 * 把仓库里的清单真源同步到运行时目录 `$COSIGHT_HOME/modules/<id>/module.json`。
 *
 * 少了这一步，iframe 会因为清单缺失或过期而白屏——而这一步在手工流程里是"记得 cp 一下"，
 * 最容易忘。内容逐字节相同则跳过，所以重复跑不会有任何多余写入。
 *
 * **只搬 `<id>.module.json`**：`<id>.launch.json` 是开发编排，属于仓库，永不该进运行时目录。
 */
function syncManifests(home) {
  const targetRoot = path.join(home, 'modules');

  let names;
  try {
    names = fs.readdirSync(MODULES_DIR);
  } catch (error) {
    throw new Error(`读不到模块清单目录 ${MODULES_DIR}：${error.message}`, { cause: error });
  }

  const manifests = names.filter((name) => name.endsWith('.module.json')).toSorted();
  writeLine(`模块清单  ${MODULES_DIR}`);
  writeLine(`      →   ${targetRoot}`);

  for (const name of manifests) {
    const id = name.replace(/\.module\.json$/, '');
    const source = path.join(MODULES_DIR, name);
    const target = path.join(targetRoot, id, 'module.json');
    const content = fs.readFileSync(source);

    if (fs.existsSync(target) && Buffer.compare(fs.readFileSync(target), content) === 0) {
      writeLine(`     =   ${id}（已是最新）`);
      continue;
    }

    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, content);
    writeLine(`     →   ${id}（已同步）`);
  }
}

// ── 启动计划 ────────────────────────────────────────────────────────────

function buildPlan(options) {
  const framework = FRAMEWORK_SERVICES.map((service) => ({
    ...service,
    env: { COSIGHT_HOME: options.home },
    reused: false,
  }));

  const entries = scanLaunchEntries(MODULES_DIR, { repoRoot: REPO_ROOT, live: options.live });
  const modules = [];
  const builds = [];

  for (const entry of entries) {
    if (!fs.existsSync(entry.moduleRoot)) {
      // 本地没检出这个模块不是错误——但必须说出来，否则"怎么少起了一个"要靠猜。
      writeWarn(`模块 ${entry.id} 的目录不存在（${entry.moduleRoot}），跳过`);
      continue;
    }

    if (!options.live) {
      for (const dir of listIsolatedDirs(entry)) {
        fs.mkdirSync(dir, { recursive: true });
      }
    }

    // 产物重建登记在**模块**上而不是每个服务上：一个模块只有一份产物，
    // 挂到服务上就会出现"两个服务各建一次"。
    if (entry.build !== null) {
      builds.push({ moduleId: entry.id, label: `${entry.id}:build`, build: entry.build });
    }

    for (const service of entry.services) {
      modules.push({
        ...service,
        kind: 'module',
        moduleId: entry.id,
        depsDir: service.cwd,
        reused: false,
      });
    }
  }

  const plan = [...framework, ...modules];

  // 同端口只会表现为"第二个起不来，报 EADDRINUSE"，而这个错误要等前一个就绪之后
  // 才会出现——排查时人已经在看一屏日志了。清单是静态的，这里一次性说清楚。
  const byPort = new Map();
  for (const service of plan) {
    const seen = byPort.get(service.port);
    if (seen !== undefined) {
      throw new Error(
        `端口 ${service.port} 被两个服务同时声明：${seen} 与 ${service.label}。` +
          '请改其中一个的端口（模块的端口写在 framework/docs/modules/<id>.launch.json）。',
      );
    }
    byPort.set(service.port, service.label);
  }

  return { plan, builds };
}

// ── 端口占用 ────────────────────────────────────────────────────────────

function describeOwner(owner) {
  if (owner === null || owner.pid <= 0) {
    return '占用者未知（进程信息不可读）';
  }
  return `pid ${owner.pid}（${owner.command}）`;
}

/** 只认 24 小时以内的记事本：更久远的记录里那个 pid 可能早被系统分配给别的进程了。 */
const RUN_STATE_MAX_AGE_MS = 24 * 60 * 60 * 1000;

/**
 * 收掉上一次运行的残留——**按记事本，不按端口**。
 *
 * 为什么不能只看端口：`tsx watch` / `vite` 这类监视进程在**程序崩了之后仍然活着**
 * （它们的工作就是等文件变化再重跑）。实测：`smart-factory:server` 因为缺依赖启动即崩，
 * 但它的 `npm run dev` → `tsx watch` 留在原地；那次监督进程被 `kill -9` 之后没人收它，
 * 而后续每次启动都看不到它（4100 端口是空的），于是它就一直在那儿——
 * **一旦它哪天重跑成功，会把端口从新起的服务手里抢走。**
 *
 * 所以：上次的监督进程已经不在，就照记事本把上次起的每个服务连组一起收掉。
 * 上次的监督进程还活着则一个都不碰（那是另一套正在跑的服务）。
 */
async function reapPreviousRun(previousRun) {
  if (previousRun === null || isPidAlive(previousRun.supervisorPid)) {
    return;
  }

  const startedAt = Date.parse(previousRun.startedAt ?? '');
  if (!Number.isFinite(startedAt) || Date.now() - startedAt > RUN_STATE_MAX_AGE_MS) {
    writeWarn(`${RUN_STATE_FILE} 里的记录超过 24 小时，不按它回收（pid 可能已被复用），仅作参考`);
    return;
  }

  for (const service of previousRun.services ?? []) {
    if (!isPidAlive(service.pid) && !isPidAlive(service.listenerPid)) {
      continue;
    }
    writeWarn(`清理上一次运行的残留：${service.label}（pid ${service.pid}），端口 ${service.port}`);
    await freePort(
      { pid: service.pid, command: '上一次运行的残留', port: service.port },
      { groupLeaderPid: service.pid, graceMs: 3000 },
    );
  }
}

/**
 * 启动前把所有端口预检一遍，并就地处理已知的三类占用。
 *
 * **一次性全查完再动手**，不是起一个查一个：端口冲突是"能不能开始"的前置条件，
 * 不该先起了两个服务再在第三个上失败——那样退出时会留下一半在跑的服务。
 */
async function precheckPorts(plan, options, previousRun) {
  const conflicts = [];

  for (const service of plan) {
    const verdict = await classifyPort(service.port, previousRun);
    if (verdict.kind === 'free') {
      continue;
    }

    if (verdict.kind === 'own-leftover') {
      // 上一次没停干净的残留。这是最常见的占用来源，直接回收——它就是本脚本欠下的。
      writeWarn(`端口 ${service.port} 被上一次运行的残留占着（${describeOwner(verdict.owner)}），回收`);
      const released = await freePort(verdict.owner, {
        groupLeaderPid: verdict.recorded?.pid ?? null,
      });
      if (!released) {
        throw new Error(
          `端口 ${service.port} 回收失败，占用者 ${describeOwner(verdict.owner)} 还在。手工处理：kill -9 ${verdict.owner.pid}`,
        );
      }
      continue;
    }

    if (options.reuse) {
      service.reused = true;
      writeWarn(
        `端口 ${service.port} 已被占用，--reuse：复用已有实例（${service.label}）。` +
          '该实例不归本脚本管，Ctrl-C 不会停它。',
      );
      continue;
    }

    conflicts.push({ service, ...verdict });
  }

  if (conflicts.length === 0) {
    return;
  }

  if (options.killPorts) {
    for (const { service, owner } of conflicts) {
      if (owner === null || owner.pid <= 0) {
        throw new Error(`端口 ${service.port} 被占用但查不到占用者，--kill-ports 无从下手，请手工处理。`);
      }
      writeWarn(`--kill-ports：停止 ${describeOwner(owner)}（端口 ${service.port}）`);
      const released = await freePort(owner);
      if (!released) {
        throw new Error(`端口 ${service.port} 仍未释放（${describeOwner(owner)}）。手工处理：kill -9 ${owner.pid}`);
      }
    }
    return;
  }

  const lines = ['以下端口已被占用，本脚本不会主动接管别人的进程：'];
  for (const { service, kind, owner } of conflicts) {
    const why = kind === 'own-running' ? '上一次的启动仍在运行' : '不是本脚本起的进程';
    lines.push(
      `  ${String(service.port).padEnd(6)} ${service.label.padEnd(22)} ${describeOwner(owner)}   ${why}`,
    );
  }
  lines.push('三选一：');
  lines.push('  去那个终端 Ctrl-C（残留进程可直接 kill <pid>）');
  lines.push('  pnpm dev:all --reuse       复用已在跑的实例，本脚本不碰它们');
  lines.push('  pnpm dev:all --kill-ports  授权本脚本停掉占用者');
  throw new Error(lines.join('\n'));
}

// ── 模块产物 ────────────────────────────────────────────────────────────

/** 产物状态 → 总表里的记号。 */
const BUILD_MARKS = { rebuilt: '✓', fresh: '=', skipped: '-', blocked: '⇲' };

/**
 * 一个模块的产物准备（该模块的服务启动之前跑）。
 *
 * 陈旧才重建的理由、以及"失败就不起这个模块"这条硬边界，都写在 `lib/module-build.mjs`
 * 的开头。这里只负责编排：判据 → （必要时）跑构建 → 把结论交给调用方。
 *
 * @param {{moduleId: string, label: string, build: object}} item
 * @returns {Promise<{moduleId: string, label: string, status: string, detail: string|null, elapsedMs: number|null}>}
 */
async function prepareModuleBuild(item, options, state, labelWidth) {
  const outcome = (status, detail, elapsedMs = null) => ({
    moduleId: item.moduleId,
    label: item.label,
    status,
    detail,
    elapsedMs,
  });

  if (options.noBuild) {
    writeLine(`产物跳过  ${item.label}   --no-build：用本机现状启动`);
    return outcome('skipped', '--no-build');
  }

  let inspection;
  try {
    inspection = options.rebuild
      ? { stale: true, reason: '--rebuild', detail: '强制重建' }
      : inspectBuild(item.build);
  } catch (error) {
    // 清单写错（inputs 里的路径不存在）不走"产物旧了"这条路：不猜、也不降级，
    // 直接判这个模块不可用——写错的 inputs 恰恰会让"改了源码却不重建"。
    const detail = error instanceof Error ? error.message : String(error);
    writeWarn(`${item.label} 的陈旧判据算不出来：${detail}`);
    return outcome('blocked', detail);
  }

  if (!inspection.stale) {
    writeLine(`产物跳过  ${item.label}   ${inspection.reason}${inspection.detail === null ? '' : `（${inspection.detail}）`}`);
    return outcome('fresh', inspection.detail);
  }

  // 缺依赖时不代装（同 `checkDeps` 的理由），也不硬着头皮跑——直接判这个模块不可用。
  const depsDir = path.join(item.build.cwd, 'node_modules');
  if (!fs.existsSync(depsDir)) {
    const detail = `${depsDir} 不存在，无法重建产物（装依赖后重试，或加 --no-build 用当前产物启动）`;
    writeWarn(`${item.label} 需要重建但缺依赖：${detail}`);
    return outcome('blocked', detail);
  }

  writeLine(
    `准备产物  ${item.label}   ${item.build.command.join(' ')}   （${inspection.reason}${
      inspection.detail === null ? '' : `：${inspection.detail}`
    }）`,
  );

  const result = await runBuild(item.build, {
    label: item.label,
    width: labelWidth,
    // 构建命令和外层一样是"包一层"跑起来的（我们自己多半就是被 `pnpm dev:all` 起的），
    // npm_* 那批变量会让嵌套的 npm 认错项目根——模块对服务用 stripEnvPrefixes 处理同一件事。
    // 这里的 `env: {}` 是**刻意**的：清单里的 `env` 是服务的运行时变量，把 `VITE_*` 那类
    // 喂给一次 `vite build` 会把运行期配置打进产物。见 dev-all.md 的同名小节。
    env: buildChildEnv({ stripEnvPrefixes: ['npm_'], env: {} }),
    // 登记进 `state.entries`：Ctrl-C 时按进程组一起收掉，别让 `tsc -b` / `vite build`
    // 变成孤儿继续往产物目录里写。
    register: (child) => {
      state.entries.push({ label: item.label, child });
    },
  });

  if (result.ok) {
    writeLine(`产物完成  ${item.label}   ${(result.elapsedMs / 1000).toFixed(1)}s`);
    return outcome('rebuilt', null, result.elapsedMs);
  }

  const detail =
    result.spawnError ??
    (result.timedOut
      ? `超过 ${Math.round(item.build.timeoutMs / 1000)}s 未完成，已强制结束`
      : `构建失败（${result.signal === null ? `退出码 ${result.code}` : `被 ${result.signal} 终止`}）`);
  writeWarn(`${item.label} ${detail}。该模块的服务不会启动；确要用当前产物启动请加 --no-build`);
  return outcome('blocked', detail, result.elapsedMs);
}

// ── 启动 ────────────────────────────────────────────────────────────────

function candidateUrls(service) {
  const suffix = service.readyPath === '/' ? '/' : service.readyPath;
  return [
    `http://127.0.0.1:${service.port}${suffix}`,
    `http://localhost:${service.port}${suffix}`,
    `http://[::1]:${service.port}${suffix}`,
  ];
}

function buildChildEnv(service) {
  const env = { ...process.env };

  for (const prefix of service.stripEnvPrefixes ?? []) {
    for (const key of Object.keys(env)) {
      if (key.startsWith(prefix)) {
        delete env[key];
      }
    }
  }

  Object.assign(env, service.env ?? {});

  // 子进程的 stdout 被我们接管成管道，工具会据此认为"不是终端"并关掉颜色。
  // 我们自己是有 TTY 的，所以在 TTY 下显式打开，别让总脚本的输出比 pnpm dev 素一半。
  if (process.stdout.isTTY === true && env['FORCE_COLOR'] === undefined) {
    env['FORCE_COLOR'] = '1';
  }

  return env;
}

/**
 * 起一个服务并等它就绪。
 *
 * `detached: true` 是刻意的：子进程自成进程组，收尾时按组回收（见 `superviseAll`），
 * 否则会留下 vite / tsx watch 的孙进程继续占着端口。
 */
async function startService(service, options, state, labelWidth) {
  const urls = candidateUrls(service);

  if (service.reused) {
    const ready = await waitForAnyHttpOk(urls, { timeoutMs: service.readyTimeoutMs });
    return {
      service,
      status: ready.ready ? 'reused' : 'unreachable',
      url: ready.url,
      elapsedMs: 0,
      lastError: ready.lastError,
    };
  }

  // 预检到现在可能过了十几秒（前面的服务在等就绪），这里补一次。
  // 抢跑的话子进程只会抛 EADDRINUSE，与其让它带着一屏栈退出，不如在这里说清楚。
  const recheck = await classifyPort(service.port, null);
  if (recheck.kind !== 'free') {
    writeWarn(
      `端口 ${service.port} 在启动前被占用（${describeOwner(recheck.owner)}），跳过 ${service.label}`,
    );
    return {
      service,
      status: 'unreachable',
      url: null,
      elapsedMs: 0,
      lastError: `端口 ${service.port} 已被占用`,
    };
  }

  const startedAt = Date.now();
  // Windows 上 pnpm/npm 实际是 `.cmd`，裸名字 spawn 只会 ENOENT/EINVAL。
  // 与 package / 插件安装走同一条解析 + cmd.exe 拼装路径。
  const resolvedCommand = resolveExecutable(service.command[0]);
  const spawnSpec = buildSpawnSpec(
    resolvedCommand.path ?? service.command[0],
    service.command.slice(1),
  );
  const child = spawn(spawnSpec.command, spawnSpec.args, {
    cwd: service.cwd,
    env: buildChildEnv(service),
    detached: true,
    // stdin 接到空设备：这些服务都不需要交互输入，接了 TTY 反而会让它们抢键。
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsVerbatimArguments: spawnSpec.windowsVerbatimArguments,
  });

  service.child = child;
  state.entries.push({ label: service.label, child });
  pumpPrefixed(child, { label: service.label, width: labelWidth });

  // 每起一个就落一次盘，不是最后统一写：进程被 SIGKILL 时没有"最后"。
  // 这条记录是下一次运行能认出"这是我自己的残留"的唯一依据。
  //
  // 这里先只记 `pid`（spawn 出来的进程组组长）。**能立刻写下的只有它**——
  // 真正监听端口的孙进程（tsx / vite）此刻还没起来，pid 还无从得知。
  let record = null;
  if (child.pid !== undefined) {
    record = { label: service.label, port: service.port, pid: child.pid, listenerPid: null };
    state.runState.services.push(record);
    state.persistRunState();
  }

  // 'error' 与 'exit' 可能都来（spawn 失败时 Node 只发 'error'），这里自己保证只报一次。
  const noteExit = (detail) => {
    if (service.gone === true || state.shuttingDown) {
      return;
    }
    service.gone = true;
    state.onServiceGone(service, detail);
  };

  child.on('error', (error) => {
    noteExit(`无法启动：${error.message}`);
  });
  child.on('exit', (code, signal) => {
    noteExit(signal !== null ? `被 ${signal} 终止` : `退出码 ${code}`);
  });

  const ready = await waitForAnyHttpOk(urls, { timeoutMs: service.readyTimeoutMs });
  const elapsedMs = Date.now() - startedAt;

  // 就绪之后补记**真正的监听者**。
  //
  // 为什么必须补这一笔：被 `pnpm` / `npm` 包一层的服务（五个里有四个），监听的孙进程
  // 和记下的组长不是同一个 pid。下一次启动时 `classifyPort` 拿 `ss` 看到的监听 pid
  // 去比对，只认组长就会**全部匹配不上**，于是自己的残留被当成"别人的进程"——
  // 那意味着崩溃之后的端口再也不会被自动回收。实测踩到过，不是理论风险。
  if (record !== null && ready.ready) {
    const owner = findPortOwner(service.port);
    if (owner !== null && owner.pid > 0) {
      record.listenerPid = owner.pid;
      state.persistRunState();
    }
  }

  return {
    service,
    status: ready.ready ? 'ready' : 'unreachable',
    url: ready.url,
    elapsedMs,
    lastError: ready.lastError,
  };
}

// ── 输出 ────────────────────────────────────────────────────────────────

function readMounts(moduleId) {
  try {
    const raw = JSON.parse(fs.readFileSync(path.join(MODULES_DIR, `${moduleId}.module.json`), 'utf8'));
    if (!Array.isArray(raw.mounts)) {
      return [];
    }
    return raw.mounts
      .filter((mount) => typeof mount?.path === 'string')
      .map((mount) => ({ capability: mount.capability, path: mount.path }));
  } catch {
    return [];
  }
}

/** 一个服务的结果 → 总表里的记号。`⊘` 是"刻意没起"，与失败的 `✗` 分开。 */
function serviceMark(status) {
  if (status === 'ready' || status === 'reused') {
    return '✓';
  }
  return status === 'blocked' ? '⊘' : '✗';
}

/** 一行"模块产物"的说明。 */
function describeBuildVerdict(item) {
  switch (item.status) {
    case 'rebuilt':
      return `已重建（${((item.elapsedMs ?? 0) / 1000).toFixed(1)}s）`;
    case 'fresh':
      return '已是最新（源码不比产物新）';
    case 'skipped':
      return '跳过（--no-build），用本机现状启动';
    default:
      // 用破折号而不是括号：`detail` 自己多半带括号（"构建失败（退出码 1）"），
      // 套起来会变成 "没准备好（构建失败（退出码 1））"。
      return `没准备好——${item.detail ?? '未知'}`;
  }
}

function printSummary(results, options, buildVerdicts) {
  const width = Math.max(...results.map((item) => item.service.label.length), 0);

  writeLine();
  writeLine('就绪总表');
  for (const item of results) {
    const { service } = item;
    const timing = item.status === 'reused'
      ? '复用已有实例'
      : item.status === 'ready'
        ? `${(item.elapsedMs / 1000).toFixed(1)}s`
        : item.status === 'blocked'
          ? '未启动（产物没准备好，见下）'
          : `未就绪（${item.lastError ?? '未知'}）`;
    const address = `http://localhost:${service.port}${service.readyPath}`;
    writeLine(`  ${serviceMark(item.status)} ${service.label.padEnd(width)}  ${address.padEnd(38)} ${timing}`);
  }

  if (buildVerdicts.length > 0) {
    const buildWidth = Math.max(...buildVerdicts.map((item) => item.label.length), 0);
    writeLine();
    writeLine('模块产物');
    for (const item of buildVerdicts) {
      const mark = BUILD_MARKS[item.status] ?? '?';
      writeLine(`  ${mark} ${item.label.padEnd(buildWidth)}  ${describeBuildVerdict(item)}`);
    }
  }

  writeLine();
  writeLine(`宿主页面    ${HOST_ORIGIN}/`);
  writeLine(`接口文档    ${HOST_ORIGIN}/api/docs`);

  const seen = new Set();
  for (const item of results) {
    const moduleId = item.service.moduleId;
    if (moduleId === undefined || seen.has(moduleId)) {
      continue;
    }
    seen.add(moduleId);
    for (const mount of readMounts(moduleId)) {
      writeLine(`模块页面    ${HOST_ORIGIN}${mount.path}    （${moduleId} · ${mount.capability}）`);
    }
  }

  if (options.live) {
    writeLine();
    writeLine('⚠️  --live：本次未隔离模块数据目录，模块可能已改动仓库外的用户级配置。');
  }
}

/** 复用 start.mjs 的探活报告：模块注册表是"页面能不能挂上"的唯一依据。 */
async function reportModules(home) {
  writeLine();
  writeLine(`模块注册表  ${path.join(home, 'modules')}`);
  try {
    const manifests = scanModuleManifests(path.join(home, 'modules'));
    const results = await probeModules(manifests);
    for (const line of formatProbeReport(results)) {
      writeLine(`  ${line}`);
    }
  } catch (error) {
    writeLine(`  探活未能完成（不影响服务运行）：${error.message}`);
  }
}

// ── 主流程 ──────────────────────────────────────────────────────────────

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    process.stdout.write(HELP);
    return;
  }

  // 这两个必须在 superviseAll 之前注册：Node 按注册顺序调用监听器，
  // 我们先把"正在收尾"的旗子插上，子进程的 exit 回调才不会把收尾误判成"服务挂了"。
  const state = {
    /** 交给 superviseAll 的**活**数组：启动过程中往里 push，它收尾时才读。 */
    entries: [],
    shuttingDown: false,
    onServiceGone: () => {},
    runStateFile: RUN_STATE_FILE,
    runState: { supervisorPid: process.pid, startedAt: new Date().toISOString(), services: [] },
    /**
     * 本次运行是否有权改写那个状态文件。
     *
     * 一个文件只能有一个主人：`--reuse` 起的那次只记录**它自己起的**服务（复用的不算），
     * 如果它照直覆写，就会把另一套正在运行的服务从记事本上抹掉——那套服务随后崩了，
     * 残留就再也认不出来。所以发现别的监督进程还活着时，本次就**不记账**，并说明原因。
     */
    ownsRunStateFile: true,
    persistRunState: () => {},
  };
  for (const signal of ['SIGINT', 'SIGTERM']) {
    process.on(signal, () => {
      state.shuttingDown = true;
    });
  }

  /**
   * 收尾完成后决定状态文件的去留。
   *
   * **先确认那个文件是我们写的**：本次运行可能在端口预检就失败了，一个服务都没起，
   * `state.runState.services` 还是空的。那种情况下如果照常"全死了就删掉"，删的是
   * **上一次运行**的记事本——而那正是下一次运行用来认出这些残留的唯一线索。
   * 实测踩到过：第二次启动撞端口退出后，第三次启动把三个自己的进程报成了"别人的进程"。
   *
   * 是自己写的才处置：全停干净了删掉（不留垃圾），还有活着的留着当线索。
   */
  const finalizeRunState = () => {
    const onDisk = readRunState(RUN_STATE_FILE);
    if (onDisk === null || onDisk.supervisorPid !== process.pid) {
      return;
    }

    const survivors = state.runState.services.filter(
      (service) => isPidAlive(service.pid) || isPidAlive(service.listenerPid),
    );
    if (survivors.length === 0) {
      clearRunState(RUN_STATE_FILE);
      return;
    }
    writeRunState(RUN_STATE_FILE, state.runState);
    writeWarn(`仍有 ${survivors.length} 个进程没停掉，已把它们的 PID 留在 ${RUN_STATE_FILE}，下次启动会自动回收`);
  };

  const supervisor = superviseAll(state.entries, {
    graceMs: SHUTDOWN_GRACE_MS,
    onAllStopped: (code) => {
      finalizeRunState();
      process.exit(code);
    },
  });

  state.onServiceGone = (service, detail) => {
    if (state.shuttingDown) {
      return;
    }
    if (service.kind === 'framework') {
      writeWarn(`${service.label} ${detail}。宿主已不可用，停止全部。`);
      void supervisor.stopAll(1);
      return;
    }
    writeWarn(`${service.label} ${detail}（不影响其余服务）`);
  };

  try {
    checkRuntime();

    writeLine('Co-Sight Harness 开发态总启动');
    writeLine(`  仓库      ${REPO_ROOT}`);
    writeLine(`  数据目录  ${options.home}`);
    writeLine(`  模式      ${options.live ? '模块不隔离数据目录（--live）' : '模块数据目录隔离'}`);
    writeLine();

    syncManifests(options.home);
    writeLine();

    const { plan, builds } = buildPlan(options);
    checkDeps(plan);

    const previousRun = readRunState(RUN_STATE_FILE);
    const previousOwnerAlive =
      previousRun !== null && previousRun.supervisorPid !== process.pid && isPidAlive(previousRun.supervisorPid);

    // 先按记事本收残留，再按端口预检：残留收掉之后端口就是干净的了，
    // 预检那边就不会再对同一批进程重复报一次。
    await reapPreviousRun(previousRun);
    await precheckPorts(plan, options, previousRun);
    if (previousOwnerAlive) {
      state.ownsRunStateFile = false;
      writeWarn(
        `另一套总启动（pid ${previousRun.supervisorPid}）还在运行，它的记事本保留不动；` +
          '本次起的服务不会被记进去（Ctrl-C 后如未停净，下次启动不会认作自己的残留）。',
      );
    } else {
      state.persistRunState = () => {
        if (state.ownsRunStateFile) {
          writeRunState(RUN_STATE_FILE, state.runState);
        }
      };
      state.persistRunState();
    }

    const labelWidth = Math.max(
      ...plan.map((service) => service.label.length),
      ...builds.map((item) => item.label.length),
      0,
    );

    // 产物的准备**挂在该模块的第一个服务前面**，不全部提到最前：提到最前会让 framework
    // 干等一个几十秒的全量前端构建才开始起，而挂在这里框架能先起来、模块边等边构建。
    const pendingBuilds = new Map(builds.map((item) => [item.moduleId, item]));
    const steps = [];
    for (const service of plan) {
      if (service.moduleId !== undefined) {
        const build = pendingBuilds.get(service.moduleId);
        if (build !== undefined) {
          pendingBuilds.delete(service.moduleId);
          steps.push({ kind: 'build', build });
        }
      }
      steps.push({ kind: 'service', service });
    }

    const results = [];
    const buildVerdicts = [];
    const blockedModules = new Map();

    for (const step of steps) {
      // 收尾中（Ctrl-C 恰好落在前一个服务的就绪等待里）：别再起新东西，起了也没人收。
      if (state.shuttingDown) {
        break;
      }

      if (step.kind === 'build') {
        const verdict = await prepareModuleBuild(step.build, options, state, labelWidth);
        buildVerdicts.push(verdict);
        if (verdict.status === 'blocked') {
          blockedModules.set(verdict.moduleId, verdict.detail ?? '未知原因');
        }
        continue;
      }

      const { service } = step;
      const blockedWhy = service.moduleId === undefined ? undefined : blockedModules.get(service.moduleId);
      if (blockedWhy !== undefined && !service.reused) {
        // 产物没准备好却照常起服务，就是拿一份已知是旧的产物骗人。宁可不起，并把原因说在总表里。
        writeWarn(`跳过 ${service.label}：模块产物没准备好——${blockedWhy}`);
        results.push({ service, status: 'blocked', url: null, elapsedMs: 0, lastError: blockedWhy });
        continue;
      }

      writeLine(`启动 ${service.label}   ${candidateUrls(service)[0]}`);
      results.push(await startService(service, options, state, labelWidth));
    }

    printSummary(results, options, buildVerdicts);
    await reportModules(options.home);

    writeLine();
    writeLine('全部就绪。Ctrl-C 停止全部。');

    // 前台阻塞：只由信号打断（stopAll 走完会自己 process.exit）。
    await new Promise(() => {});
  } catch (error) {
    // 启动期出错：先把已经起来的收干净再退出，别留一群孤儿占着端口。
    writeWarn(error instanceof Error ? error.message : String(error));
    await supervisor.stopAll(1);
  }
}

main().catch((error) => {
  process.stderr.write(`[dev-all] 启动失败：${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});

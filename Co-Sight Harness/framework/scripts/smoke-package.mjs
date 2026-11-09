#!/usr/bin/env node
/**
 * 打包冒烟：验证"产物真的能跑"，而不是"打包脚本没报错"。
 *
 * ── 为什么这条链路必须被真的跑一遍 ──────────────────────────────────────
 *
 * 打包脚本自己会读回归档做校验，但那用的是**我们自己写的读取器**。
 * 如果写入器和读取器共享同一个错误假设（比如对符号链接的处理都理解错了），
 * 读回校验会一致地通过，而产物在别人机器上是坏的。
 * 所以这里刻意换成**独立读取器**：系统的 `tar` 与 `unzip`。
 * 这一步是本任务里最重要的一条证据。
 *
 * ── 流程 ──────────────────────────────────────────────────────────────
 *
 *   打包 → 用系统 tar/unzip 分别解压到两个全新的临时目录 → 比对条目清单
 *        → **模拟一次真实安装**：跑本平台的安装入口 → 数据目录与配置就位
 *          → 往 cosight.env 里写一个非默认端口 → 用本平台的启动入口启动
 *          → 端口真的跟着配置文件走（证明配置生效，而不是"文件生成了没人读"）
 *        → 从 tar 解压的树启动（非默认端口 + 临时数据目录）
 *        → 轮询 /api/health → 确认首页拿到的是 HTML 而不是 API 的 JSON
 *        → **模块端到端**：清单可解析 → 进程被拉起 → 页面与 capability 路由可用
 *          → /api/modules 已注册 → 关停后框架与模块的端口都释放
 *        → 从 zip 解压的树再跑一遍同样的检查 → 清理
 *
 * ── 三个刻意的选择 ────────────────────────────────────────────────────
 *
 *  1. **端口不用默认值**：默认 4300 上通常正跑着开发服务。如果撞上，
 *     冒烟会拿到"别人的服务"的 200，从而变成一个假通过。所以启动前先确认
 *     端口是空的，被占用直接报错退出。
 *  2. **数据目录用临时目录**：绝不能让冒烟污染 `~/.cosight-harness`。
 *  3. **安装段跑平台自己的入口**：POSIX 上是 `sh install.sh` / `sh start.sh`，
 *     Windows 上是 `node start.mjs [--install]`——`.cmd` 只是包装，真正干活的是
 *     那行 node（见 `entryCommand`）。两边都不假装跑对方，`.cmd` 的编码/行尾另由
 *     打包期断言覆盖，双击流程见 `docs/packaging.md` 的 Windows 验收清单。
 */

import { spawn, spawnSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';

import { countMetadataOnlyUnzipWarnings } from './lib/archive/unzip-warnings.mjs';
import {
  readArtifactSpec,
  resolveSpecForRuntime,
  scanArtifactSpecs,
} from './lib/artifact-spec.mjs';
import { EXPECTED_PLUGIN_DIRS } from './lib/checks/plugins.mjs';
import { describePlugins } from './lib/plugin-index.mjs';
import {
  MODULE_ROOT,
  PACKAGE_DIR,
  humanSize,
  latestArtifactBase,
} from './lib/project.mjs';
import { httpGet, sleep, supervise, waitForHttpOk } from './lib/runtime.mjs';
import { stripBom } from './lib/text.mjs';

/** 刻意与默认 4300、前端 dev server 4310 都错开。 */
const DEFAULT_SMOKE_PORT = 4399;
const READY_TIMEOUT_MS = 60_000;
/** 关停后等端口释放的上限。 */
const SHUTDOWN_TIMEOUT_MS = 15_000;

/** 产物必须带上的内置专家（真源 smart-factory/server/builtin-agents/，缺了 boot 同步就登记不出来）。 */
const EXPECTED_BUILTIN_AGENT_IDS = ['software-rd-team'];

/** 步骤标签。**分母由它的长度派生**：加一步就加一行，不会再出现 `步骤 8/7`。 */
const STEP_LABELS = [
  '打包',
  '确认端口空闲（框架与产物里的模块）',
  '用系统 tar / unzip 解压（独立读取器交叉验证）',
  '模拟安装 → 改配置 → 按配置端口启动',
  '从 tar.gz 解压的树启动并断言 HTTP（含模块）',
  '从 zip 解压的树启动并断言 HTTP（含模块）',
  '清理临时目录',
];

class SmokeFailure extends Error {}

function parseArgs(argv) {
  const options = { port: DEFAULT_SMOKE_PORT, configPort: null, skipPackage: false, keepTemp: false };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const [flag, inline] = arg.includes('=') ? [arg.slice(0, arg.indexOf('=')), arg.slice(arg.indexOf('=') + 1)] : [arg, null];
    const takeValue = () => {
      if (inline !== null) {
        return inline;
      }
      index += 1;
      if (argv[index] === undefined) {
        throw new SmokeFailure(`${flag} 需要一个值`);
      }
      return argv[index];
    };

    switch (flag) {
      case '--port':
        options.port = Number.parseInt(takeValue(), 10);
        break;
      case '--config-port':
        options.configPort = Number.parseInt(takeValue(), 10);
        break;
      case '--skip-package':
        options.skipPackage = true;
        break;
      case '--keep-temp':
        // 失败现场保留下来便于排查；默认清理，避免临时目录越积越多。
        options.keepTemp = true;
        break;
      case '-h':
      case '--help':
        process.stdout.write(
          '用法：node framework/scripts/smoke-package.mjs [--port <n>] [--config-port <n>] [--skip-package] [--keep-temp]\n' +
            '  --port         常规冒烟用的端口（默认 4399）\n' +
            '  --config-port  验证 cosight.env 生效用的端口（默认 --port + 1）\n',
        );
        process.exit(0);
        break;
      default:
        throw new SmokeFailure(`未知参数 ${arg}`);
    }
  }

  // 两个端口都必须与默认 4300、前端 dev server 4310 错开，且彼此不同：
  // 配置段要证明"端口确实来自配置文件"，用同一个端口就证明不了。
  if (options.configPort === null) {
    options.configPort = options.port + 1;
  }

  for (const [name, value] of [
    ['--port', options.port],
    ['--config-port', options.configPort],
  ]) {
    if (!Number.isInteger(value) || value < 1 || value > 65_535) {
      throw new SmokeFailure(`${name} 非法：${value}`);
    }
  }
  if (options.port === options.configPort) {
    throw new SmokeFailure(`--port 与 --config-port 不能相同（都是 ${options.port}），否则证明不了配置生效。`);
  }

  return options;
}

function run(command, args, options = {}) {
  const { tolerate = null, ...spawnOptions } = options;
  const result = spawnSync(command, args, {
    encoding: 'utf8',
    maxBuffer: 256 * 1024 * 1024,
    ...spawnOptions,
  });
  if (result.error) {
    throw new SmokeFailure(`执行 ${command} 失败：${result.error.message}`);
  }
  // `tolerate` 只在"非零退出但可接受"这一种情况生效：调用方给出判定函数，
  // 由它决定这份输出算不算失败。没有它时仍按非零即失败处理。
  if (result.status !== 0 && (tolerate === null || !tolerate(result))) {
    throw new SmokeFailure(
      `${command} ${args.join(' ')} 退出码 ${result.status}\n--- stdout ---\n${result.stdout}\n--- stderr ---\n${result.stderr}`,
    );
  }
  return result.stdout;
}

function assert(condition, message) {
  if (!condition) {
    throw new SmokeFailure(message);
  }
}

/** 端口必须是空的：否则后面的 200 可能来自别人的服务，冒烟变成假通过。 */
async function assertPortFree(port, probePath = '/api/health') {
  const probe = await httpGet(`http://127.0.0.1:${port}${probePath}`, 1500);
  assert(
    probe.status === 0,
    `端口 ${port} 上已经有服务在响应（HTTP ${probe.status}）。` +
      '冒烟必须用独立端口，否则可能把别人的服务当成自己的产物判为通过。请用 --port 换一个。',
  );
}

/**
 * 仓库里的装配态清单声明了哪些模块端口。
 *
 * 冒烟开始前要确认它们也是空的：占着的那个模块会被 `start.mjs` 当成
 * "已经在跑"而复用，关停时它不归我们管，于是"端口已释放"这条断言会误报。
 */
function declaredModulePorts() {
  const dir = path.join(MODULE_ROOT, 'docs', 'modules');
  const ports = new Set();

  for (const name of fs.readdirSync(dir).filter((item) => item.endsWith('.artifact.json')).toSorted()) {
    for (const service of readArtifactSpec(path.join(dir, name)).services) {
      ports.add(service.port);
    }
  }

  return [...ports].toSorted((left, right) => left - right);
}

/** 当前平台标识，与清单 `platforms` 里的写法（`<os>-<arch>`）对齐。 */
const TARGET_PLATFORM = `${process.platform}-${process.arch}`;

/**
 * 列出清单里**不支持当前平台**的模块。
 *
 * `start.mjs` 启动时会跳过它们（`docs/packaging.md` §6），所以冒烟不能把它们
 * 算进"应该就绪"的集合——否则在 Windows 上会去探一个设计上就不会起来的
 * linux-only 服务，把"按设计跳过"报成故障。跳过的模块要**打印出来**：
 * 一次启动里少了哪个模块，读日志的人必须看得见，不能悄悄少验一半。
 */
function platformSkippedModules(root) {
  const { specs } = scanArtifactSpecs(path.join(root, 'modules'));
  return specs
    .filter((spec) => spec.platforms !== null && !spec.platforms.includes(TARGET_PLATFORM))
    .map((spec) => `${spec.id}（platforms=${spec.platforms.join(', ')}）`);
}

/**
 * 从解压出来的树里读出模块的探活地址。
 *
 * 刻意**从产物自己的清单读**，而不是照抄仓库里的数字：这样既验证了
 * `artifact.json` 真的进包且可解析，又保证断言盯着的端口就是 `start.mjs` 要起的端口。
 */
function moduleProbes(root, dataDir, frameworkUrl) {
  const modulesRoot = path.join(root, 'modules');
  const { specs } = scanArtifactSpecs(modulesRoot);

  return specs.filter((spec) => spec.platforms === null || spec.platforms.includes(TARGET_PLATFORM)).flatMap((spec) =>
    resolveSpecForRuntime(spec, { moduleDir: path.join(modulesRoot, spec.id), dataDir, frameworkUrl }).services.map(
      (service) => ({
        id: spec.id,
        name: service.name,
        label: `${spec.id}:${service.name}`,
        port: service.port,
        readyPath: service.readyPath,
        healthUrl: `http://127.0.0.1:${service.port}${service.readyPath}`,
        baseUrl: `http://127.0.0.1:${service.port}`,
      }),
    ),
  );
}

/**
 * 直接发一次 WebSocket 升级握手，返回状态码（101 表示代理链路通了）。
 *
 * 用裸 socket 而不是 `ws` 客户端：这里要验的是**代理有没有把 Upgrade 转给
 * 上游**，不是协议栈是否完整。裸 socket 也不会像客户端库那样"失败后重试"，
 * 一次结果就是真实结果。
 */
function probeWebSocket(url, timeoutMs = 10_000) {
  const parsed = new URL(url);
  return new Promise((resolve, reject) => {
    const socket = net.connect(Number(parsed.port === '' ? 80 : parsed.port), parsed.hostname, () => {
      socket.write(
        `GET ${parsed.pathname}${parsed.search} HTTP/1.1\r\n` +
          `Host: ${parsed.host}\r\n` +
          'Upgrade: websocket\r\n' +
          'Connection: Upgrade\r\n' +
          `Sec-WebSocket-Key: ${randomBytes(16).toString('base64')}\r\n` +
          'Sec-WebSocket-Version: 13\r\n\r\n',
      );
    });

    let buffer = '';
    const finish = (error, status) => {
      clearTimeout(timer);
      socket.destroy();
      if (error === null) {
        resolve(status);
      } else {
        reject(error);
      }
    };
    const timer = setTimeout(
      () => finish(new SmokeFailure(`WebSocket ${url} 握手超时；已收到：${JSON.stringify(buffer.slice(0, 120))}`)),
      timeoutMs,
    );

    socket.on('data', (chunk) => {
      buffer += chunk.toString('latin1');
      const match = /^HTTP\/1\.1 (\d{3})/.exec(buffer);
      if (match !== null) {
        finish(null, Number(match[1]));
      }
    });
    socket.on('error', (error) => finish(new SmokeFailure(`WebSocket ${url} 握手失败：${error.message}`)));
  });
}

/**
 * 用系统工具解压。刻意不用我们自己的读取器——这里要的就是"另一个实现"。
 * @returns {{root: string, listing: string[]}}
 */
/**
 * 选用哪个 tar。
 *
 * Windows 的 PATH 里，`tar` 常常先命中 Git for Windows 附带的 **MSYS 版 GNU tar**：
 * 它会对命令行里的 Windows 绝对路径做 MSYS 路径转换，`-C C:\Users\103332~1…`
 * 里的 `\103` 被当成八进制转义吃掉（变成 `C332…`），报一句"路径不存在"。
 * 系统自带的 `%SystemRoot%\System32\tar.exe` 是原生 bsdtar，直接认 Windows 路径，
 * 所以优先用它；找不到时退回 PATH——Linux / macOS 上本来就只有一种 tar。
 */
function resolveTarCommand() {
  return systemTool('tar.exe', 'tar');
}

/**
 * Windows 系统目录下的原生工具（`tar.exe`、`taskkill.exe`…）。
 *
 * 统一走绝对路径：PATH 里排在前面的往往是 MSYS / Git 附带的同名工具，行为与
 * 系统原生的那份不同（见 `resolveTarCommand`）。非 Windows 上原样返回命令名。
 */
function systemTool(windowsName, fallback) {
  if (process.platform !== 'win32') {
    return fallback;
  }
  const native = path.join(process.env.SystemRoot ?? 'C:\\Windows', 'System32', windowsName);
  return fs.existsSync(native) ? native : fallback;
}

function extractWithSystemTool(kind, archivePath, targetDir, base) {
  const tool = kind === 'tar' ? 'tar' : 'unzip';
  const command = kind === 'tar' ? resolveTarCommand() : 'unzip';
  // 归档一律**切到它所在目录、只传文件名**，不传绝对路径：GNU tar 会把 Windows
  // 路径里的盘符冒号当成远程主机（`host:path`），报 "Cannot execute remote shell"。
  // 换 cwd 对两种 tar 实现（GNU / bsdtar）和两个平台都成立，比加 `--force-local`
  // 更稳——后者只有 GNU tar 认，bsdtar 会当成未知选项。
  const archiveDir = path.dirname(archivePath);
  const archiveName = path.basename(archivePath);

  let toleratedWarnings = 0;
  if (kind === 'tar') {
    run(command, ['-xzf', archiveName, '-C', targetDir], { cwd: archiveDir });
  } else {
    // Info-ZIP 的退出码语义：0 = 干净，1 = **成功但有告警**，≥2 才是真失败。
    // 本机实测到的告警只有一类：解压后给某些目录设权限/时间戳时报
    // "No such file or directory"（Windows 文件系统语义 + 同时有杀毒软件在扫
    // 刚解出来的 350 MB 树时偶发），文件内容本身是完整的；同一个归档、同一个
    // 目标形态重跑一次就是 0 告警。所以这里放行这一类的退出码 1，
    // 但要求 stderr 里**只**有这一类——出现建不出文件、CRC 错、压缩算法不支持
    // 之类的字样仍按失败处理。完整性由后面的树结构断言负责，不在这里重复。
    run(command, ['-q', archiveName, '-d', targetDir], {
      cwd: archiveDir,
      tolerate: (result) => {
        const warnings = countMetadataOnlyUnzipWarnings(result.stderr);
        if (warnings === 0) {
          return false;
        }
        toleratedWarnings = warnings;
        return true;
      },
    });
  }

  const listing =
    kind === 'tar'
      ? run(command, ['-tzf', archiveName], { cwd: archiveDir }).split('\n')
      : // -Z1 是 unzip 的"只列名字"模式，直接给出换行分隔的清单，便于机器比对。
        run(command, ['-Z1', archiveName], { cwd: archiveDir }).split('\n');

  const raw = listing.map((line) => line.replace(/\r$/, '')).filter((line) => line !== '');
  // 目录条目在清单里以 `/` 结尾，这个前缀是唯一能区分"目录"与"同名文件"的信息，
  // 所以要在剥斜杠之前单独留一份——下面要拿它逐条核对解压结果。
  //
  // 关键：清单里的路径是**相对归档根**的（`cosight-harness-<时间戳>/modules/...`），
  // 而 `root` 已经指向那个顶层目录。直接 `path.join(root, 名字)` 会拼成
  // `<顶层>/<顶层>/modules/...`，于是**每一个**目录都"不存在"。所以这里先把
  // 顶层前缀剥掉，得到相对 `root` 的路径；不在顶层之下的条目原样保留（它会在
  // 检查时报出来，正是我们要的：那说明归档布局与 `base` 不一致）。
  const prefix = `${base}/`;
  const toRootRelative = (name) => {
    if (name === base) {
      return '';
    }
    return name.startsWith(prefix) ? name.slice(prefix.length) : name;
  };
  // 目录清单：两种工具的**清单形态不同**，不能共用一条规则。
  //
  //   - `unzip -Z1` 给目录条目加尾斜杠，按它筛即可；
  //   - `bsdtar -tzf` **不加**（实测 33883 条里 0 条以斜杠结尾；加斜杠是 GNU tar
  //     的行为，Linux 上的经验在 bsdtar 上不成立），所以 tar 必须另跑一次 `-tvzf`，
  //     按首列 `d` 取。
  //
  // 这里曾经两种都按"结尾斜杠"筛：tar 那棵树永远筛出 0 条，`every` 空转通过，
  // 小结还打印"0 个目录都在"，读起来像验过了。`dirs.length > 0` 的断言就是为了
  // 让这类回归在下次改清单格式时立刻炸掉，而不是又静默一次。
  const dirs =
    kind === 'tar'
      ? tarDirectories(command, archiveName, archiveDir, base)
          .map(toRootRelative)
          .filter((name) => name !== '')
      : raw
          .filter((line) => line.endsWith('/'))
          .map((line) => toRootRelative(unescapeListedName(line.replace(/\/$/, ''))));
  assert(dirs.length > 0, `${tool} 的清单里一条目录条目都没有——清单格式可能变了，目录断言会变成空转`);
  const names = raw
    .map((line) => unescapeListedName(line.replace(/\/$/, '')))
    .filter((line) => line !== '');
  assert(names.length > 0, `${tool} 列不出任何条目`);

  return { root: path.join(targetDir, base), listing: names, dirs, tool, toleratedWarnings };
}

/**
 * 还原 tar / unzip 在清单里对非 ASCII 字节做的八进制转义。
 *
 * 归档里有一个 npm 包的测试夹具叫 `snow ☃`。在这台 Windows 上（ANSI 代码页是
 * GBK，不是 UTF-8），`bsdtar` 把它的三个 UTF-8 字节展示成 `\342\230\203`，
 * 于是两边清单对不上——但这只是**打印层的转义**，条目本身没变，解压出来的
 * 文件名是正确的。设 `LC_ALL=C.UTF-8` 也不能让它改口，所以在比对前还原。
 *
 * 只处理 `\NNN`（三位八进制）与 `\\`：这是这类工具做转义时仅有的两种形态，
 * 不碰其他反斜杠，避免把一个真叫反斜杠的文件名越改越错。
 */
function unescapeListedName(name) {
  if (!/\\[0-7]{3}|\\\\/.test(name)) {
    return name;
  }

  const bytes = [];
  for (let index = 0; index < name.length; index += 1) {
    const char = name[index];
    if (char !== '\\') {
      bytes.push(...Buffer.from(char, 'utf8'));
      continue;
    }

    const octal = /^[0-7]{3}/.exec(name.slice(index + 1));
    if (octal !== null) {
      bytes.push(Number.parseInt(octal[0], 8));
      index += 3;
      continue;
    }

    bytes.push(...Buffer.from(name[index + 1] ?? '\\', 'utf8'));
    index += 1;
  }

  return Buffer.from(bytes).toString('utf8');
}

/**
 * 从 `tar -tvzf` 里取出目录条目（相对归档根的原始名字，转义已还原）。
 *
 * 一行长这样：
 * `drwxr-xr-x  0 root root 0 10月 26 23:07 cosight-harness-<ts>/modules/`
 *
 * 名字之前的几列**不能按空格切**：中文 Windows 上的日期列自带空格
 * （`10月 26 23:07`），名字自己也可能带空格（归档里有个夹具叫 `snow ☃`）。
 * 顶层目录名在每一行里唯一出现，所以按它截断取名字，比解析列稳。
 */
function tarDirectories(command, archiveName, archiveDir, base) {
  const verbose = run(command, ['-tvzf', archiveName], { cwd: archiveDir });
  return verbose
    .split('\n')
    .map((line) => line.replace(/\r$/, ''))
    .filter((line) => line.startsWith('d'))
    .map((line) => {
      const index = line.indexOf(base);
      assert(index >= 0, `tar 的 -tvzf 输出里找不到顶层目录名 ${base}：${line}`);
      return unescapeListedName(line.slice(index).replace(/\/$/, ''));
    });
}

/**
 * 把系统工具的清单和打包脚本留下的清单逐条比对。
 *
 * 这是"我们写的写入器 vs 独立读取器"的直接对照：条目数一致、集合一致，
 * 就说明长路径（GNU 长名条目）、符号链接、目录结尾斜杠这些细节，
 * 在第三方实现眼里和我们以为的一致。
 */
function compareListing(label, seen, expected) {
  const seenSet = new Set(seen);
  const expectedSet = new Set(expected);

  const missing = expected.filter((item) => !seenSet.has(item));
  const extra = seen.filter((item) => !expectedSet.has(item));

  if (missing.length > 0 || extra.length > 0) {
    throw new SmokeFailure(
      `${label} 与打包清单不一致：\n` +
        `  写入 ${expected.length} 条，读出 ${seen.length} 条\n` +
        `  读取方少看到 ${missing.length} 条，例如 ${missing.slice(0, 5).join(', ') || '（无）'}\n` +
        `  读取方多看到 ${extra.length} 条，例如 ${extra.slice(0, 5).join(', ') || '（无）'}`,
    );
  }

  return `${label}：条目 ${seen.length} 条与打包清单完全一致`;
}

/** 递归列出所有符号链接（相对 root 的路径）。 */
function findSymlinks(root) {
  const found = [];
  const pending = [''];

  while (pending.length > 0) {
    const relative = pending.pop();
    for (const dirent of fs.readdirSync(path.join(root, relative), { withFileTypes: true })) {
      const child = relative === '' ? dirent.name : `${relative}/${dirent.name}`;
      if (dirent.isSymbolicLink()) {
        found.push(child);
      } else if (dirent.isDirectory()) {
        pending.push(child);
      }
    }
  }

  return found;
}

/** 断言失败时描述一个目录的现状：不存在、是文件、还是列几个条目出来。 */
function describeDirectory(dir) {
  const stat = fs.statSync(dir, { throwIfNoEntry: false });
  if (stat === undefined) {
    return `根目录不存在（${dir}）`;
  }
  if (!stat.isDirectory()) {
    return `根路径不是目录（${dir}）`;
  }
  const all = fs.readdirSync(dir);
  if (all.length === 0) {
    return '根目录是空的';
  }
  const shown = all.slice(0, 8);
  return `共 ${all.length} 项，前 ${shown.length} 项：${shown.join('、')}`;
}

/**
 * 解压结果的结构检查。三条都是"解压后能不能直接跑"的命脉，而系统解压工具
 * 对它们的态度并不统一：
 *   1. 脚本的可执行位（Windows 上根本不存在这个概念，所以更要在这里守住）；
 *   2. **零符号链接**——依赖树是 hoisted 摊平的，任何一条链都是解压器漏出来的；
 *   3. 关键依赖入口是**实体目录且带着 package.json**。只断言"路径存在"没用：
 *      软链丢失后目录会变成 0 字节的占位文件，路径照样存在。
 */
function inspectExtractedTree(extracted) {
  const root = extracted.root;

  for (const relative of ['start.mjs', 'install.sh', 'start.sh']) {
    const target = path.join(root, relative);
    const stat = fs.statSync(target, { throwIfNoEntry: false });
    // 失败时把"我们到底在哪个目录下找"打出来：这条断言同时会因两种完全不同的
    // 原因触发——树解到了别处（顶层目录名与 `base` 不一致），或树本身不完整。
    // 只看原句"找不到 start.mjs"分不出是哪种，现场的人会先去怀疑杀毒软件。
    assert(
      stat !== undefined && stat.isFile() && stat.size > 0,
      `${extracted.tool} 解压后找不到 ${relative}（或它是空文件）\n` +
        `  查找位置：${target}\n` +
        `  实际根目录内容：${describeDirectory(root)}`,
    );
    // Windows 的 `fs.stat` 不携带执行位——一律报 0666，与 NTFS ACL 无关。
    // 在这里断言 `mode & 0o111` 只会得到一条与产物无关的误报，所以只在 POSIX 上做；
    // Windows 用户靠 `install.cmd` / `start.cmd` + `node start.mjs` 启动，不依赖这个位。
    // Linux 交付面要的 755 由打包期对归档条目的断言保证（`withExecutableModes`），
    // 与"解压器是否忠实还原"无关。
    if (process.platform !== 'win32') {
      const mode = stat.mode & 0o7777;
      assert(
        (mode & 0o111) !== 0,
        `${extracted.tool} 解压后 ${relative} 丢了可执行位（mode=${mode.toString(8)}），` +
          '使用者必须先 chmod 才能跑，这与"解压即用"的交付目标不符。',
      );
    }
  }

  // 上面可能放行过 unzip 的"设不上目录权限/时间戳"告警。属性设不上无所谓，
  // 但**目录没建出来就是坏包**，而空的 npm 包目录不会有下面任何一条断言替它兜底
  // （只查关键文件的话，缺一个空目录永远发现不了）。所以逐条核一遍。
  const missingDirs = extracted.dirs.filter(
    (relative) => !fs.existsSync(path.join(root, relative)),
  );
  assert(
    missingDirs.length === 0,
    `${extracted.tool} 解压后缺了 ${missingDirs.length} 个目录（共 ${extracted.dirs.length} 个），例如：\n  - ${missingDirs
      .slice(0, 5)
      .join('\n  - ')}`,
  );

  const symlinks = findSymlinks(root);
  assert(
    symlinks.length === 0,
    `${extracted.tool} 解压后出现了 ${symlinks.length} 条符号链接（打包时是 0 条）：\n  - ${symlinks
      .slice(0, 5)
      .join('\n  - ')}\n  Windows 上的自带解压器不会创建它们，依赖树会缺东西。`,
  );

  const packageDirs = ['tsx', 'harness-shared', 'fastify', '@libsql/client'];
  for (const name of packageDirs) {
    const manifestPath = path.join(root, 'server', 'node_modules', name, 'package.json');
    const stat = fs.lstatSync(manifestPath, { throwIfNoEntry: false });
    assert(stat !== undefined, `${extracted.tool} 解压后缺少 server/node_modules/${name}/package.json`);
    assert(
      stat.isFile() && stat.size > 0,
      `${extracted.tool} 解压后 server/node_modules/${name}/package.json 不是实体文件（大小 ${stat.size} 字节），` +
        '依赖入口已经损坏，服务端会启动失败。',
    );
  }

  const permissions = process.platform === 'win32' ? '（Windows 上不校验可执行位）' : '、可执行位在';
  return (
    `${extracted.tool}：入口与安装脚本齐全${permissions}、${extracted.dirs.length} 个目录都在、` +
    `零符号链接、${packageDirs.length} 个关键依赖入口均为实体`
  );
}

/**
 * 产物里的插件载荷：五个插件都在、index.json 与目录内容一致。
 *
 * 用运行期同一个 `describePlugins` 判定，而不是另写一套读法：解压/传输
 * 截断会把某个文件变成 0 字节，哈希对不上——这正是用户机器上启动前的
 * 第一道失败。让它在打包机上就暴露。
 */
function inspectBundledPlugins(extracted) {
  const pluginsRoot = path.join(extracted.root, 'plugins');
  assert(fs.existsSync(pluginsRoot), `${extracted.tool} 解压后没有 plugins/ 目录：插件载荷没有进包`);

  const report = describePlugins({ pluginsDir: pluginsRoot });
  assert(
    report.problems.length === 0,
    `${extracted.tool} 解压后的插件载荷不自洽：\n  - ${report.problems.join('\n  - ')}`,
  );

  const dirs = new Set(report.plugins.map((item) => item.dir));
  for (const expected of EXPECTED_PLUGIN_DIRS) {
    assert(dirs.has(expected), `${extracted.tool} 解压后缺少插件 plugins/${expected}`);
  }

  return `${extracted.tool}：${report.line}，内容哈希与 index.json 一致`;
}

/**
 * 产物里的模块位：清单可解析、运行时契约在、启动命令的入口文件在。
 *
 * 这四条正是 `start.mjs` 启动前会核对的东西。冒烟在这里先核一遍，是为了让
 * "模块没起来"的排查停在打包机这一侧——到了用户机器上，同样的现象只表现为
 * 一个 iframe 白屏。
 */
function inspectBundledModules(extracted) {
  const modulesRoot = path.join(extracted.root, 'modules');
  assert(fs.existsSync(modulesRoot), `${extracted.tool} 解压后没有 modules/ 目录：模块没有进包`);

  const { specs, problems } = scanArtifactSpecs(modulesRoot);
  assert(
    problems.length === 0,
    `${extracted.tool} 解压后模块清单有问题：\n${problems.map((item) => `  - ${item.id}：${item.message}`).join('\n')}`,
  );
  assert(specs.length > 0, `${extracted.tool} 的 modules/ 里没有任何可启动的模块`);

  for (const spec of specs) {
    const moduleDir = path.join(modulesRoot, spec.id);

    const manifestFile = path.join(moduleDir, 'module.json');
    assert(fs.existsSync(manifestFile), `${extracted.tool} 解压后缺少 modules/${spec.id}/module.json`);
    let manifest;
    try {
      manifest = JSON.parse(stripBom(fs.readFileSync(manifestFile, 'utf8')));
    } catch (error) {
      throw new SmokeFailure(`${extracted.tool} 解压后的 modules/${spec.id}/module.json 不是合法 JSON：${error.message}`);
    }
    assert(manifest.id === spec.id, `modules/${spec.id}/module.json 的 id 是 ${JSON.stringify(manifest.id)}`);

    // frameworkUrl 只是为了让清单里的 {{frameworkUrl}} 能解析；这里只核对
    // 路径与端口，真实值由 start.mjs 注入。给一个显然不会误用的本机地址即可。
    const runtime = resolveSpecForRuntime(spec, {
      moduleDir,
      dataDir: extracted.root,
      frameworkUrl: 'http://127.0.0.1:4300',
    });
    for (const service of runtime.services) {
      assert(
        fs.existsSync(service.cwd),
        `${extracted.tool} 解压后 modules/${spec.id} 的工作目录不存在：${service.cwd}`,
      );
      const [program, ...args] = service.command;
      if (program === process.execPath && args.length > 0 && !args[0].startsWith('-')) {
        const entry = path.resolve(service.cwd, args[0]);
        assert(fs.existsSync(entry), `${extracted.tool} 解压后 modules/${spec.id} 的启动入口不存在：${entry}`);
      }

      // 清单之间的端口必须对得上：`/api/modules` 把 entry 发给浏览器，
      // 而进程监听的端口来自 artifact.json。两边写岔了，表现是 iframe 打不开。
      // 只在单服务模块上比对：多服务时 entry 对不上号，硬比会产生假阳性。
      if (runtime.services.length === 1 && typeof manifest.entry === 'string') {
        let entryPort;
        try {
          const entryUrl = new URL(manifest.entry);
          entryPort = entryUrl.port || (entryUrl.protocol === 'https:' ? '443' : '80');
        } catch {
          throw new SmokeFailure(`modules/${spec.id}/module.json 的 entry 不是合法 URL：${manifest.entry}`);
        }
        assert(
          entryPort === String(service.port),
          `modules/${spec.id}：module.json 的 entry 端口是 ${entryPort}，` +
            `artifact.json 让进程监听 ${service.port}（浏览器会打开一个没人监听的端口）`,
        );
      }
    }
  }

  // bundle.required / executable 是打包时的承诺（"这些路径一定在产物里"）。
  // 用独立读取器解压之后再核一遍：打包脚本的读回校验和写入器可能共享同一个
  // 错误假设，这里隔开一层，才能证明承诺落在用户拿到的树上。
  let requiredCount = 0;
  let executableCount = 0;
  for (const spec of specs) {
    const moduleDir = path.join(modulesRoot, spec.id);

    for (const relative of spec.bundle.required ?? []) {
      const stat = fs.statSync(path.join(moduleDir, relative), { throwIfNoEntry: false });
      assert(
        stat !== undefined && stat.isFile() && stat.size > 0,
        `${extracted.tool} 解压后 modules/${spec.id}/${relative} 不存在或为空：` +
          '清单声明它是必需路径，服务会在启动时用到一个空文件/缺失文件。',
      );
      requiredCount += 1;
    }

    for (const relative of spec.bundle.executable ?? []) {
      const stat = fs.statSync(path.join(moduleDir, relative), { throwIfNoEntry: false });
      assert(
        stat !== undefined && stat.isFile(),
        `${extracted.tool} 解压后 modules/${spec.id}/${relative} 不是文件（可执行件丢失）`,
      );
      if (process.platform !== 'win32') {
        assert(
          (stat.mode & 0o111) !== 0,
          `${extracted.tool} 解压后 modules/${spec.id}/${relative} 丢了可执行位（mode=${(stat.mode & 0o777).toString(8)}）`,
        );
      }
      executableCount += 1;
    }
  }

  return (
    `${extracted.tool}：${specs.map((spec) => spec.id).join(', ')} 的清单与启动入口都在，端口一致；` +
    `必需路径 ${requiredCount} 条、可执行件 ${executableCount} 条均完整`
  );
}

/**
 * 模拟一次"用户拿到包之后"的真实动作：跑安装脚本，再改配置、用 start.sh 启动。
 *
 * 为什么值得单跑一段：安装脚本与启动脚本是**用户唯一会碰的东西**，
 * 而它们最容易出的问题是"静默无效"——配置生成了但没人读、`start.sh` 没带可执行位
 * 导致 `./start.sh` 报 Permission denied。
 *
 * 判定配置是否真的生效，用的是**端口**：往 `cosight.env` 里写一个非默认端口，
 * 启动时不带 `--port`。如果启动脚本或 start.mjs 没读那份文件，服务会落在 4300 上，
 * 而这里等的是配置文件里那个端口——等不到就报错。
 */
/**
 * 产物里"用户入口"对应的实际命令。
 *
 * POSIX 上是 `sh install.sh` / `sh start.sh`；Windows 上的 `install.cmd` /
 * `start.cmd` 只有几行包装，真正干活的是 `node start.mjs [--install]`
 * （两个 `.cmd` 自己也是这么写的）。冒烟在 Windows 上直接跑同一份 JS：
 *
 *  1. 那才是 Windows 用户真正会执行的代码。用 Git Bash 去跑 `start.sh` 测的是
 *     一个不受支持的组合——绿了不说明 Windows 交付能用，红了也不说明它不能用。
 *  2. 子进程就是 node 本身（POSIX 的 `start.sh` 也是 `exec node`），关停断言
 *     才有意义；否则杀掉的是 `sh`，node 会留在后台继续占着那个端口。
 *
 * @returns {{command: string, args: string[], label: string}}
 */
function entryCommand(action, args) {
  const isInstall = action === 'install';
  if (process.platform === 'win32') {
    const extra = isInstall ? ['--install', ...args] : args;
    return {
      command: process.execPath,
      args: ['start.mjs', ...extra],
      label: isInstall ? 'node start.mjs --install' : 'node start.mjs',
    };
  }
  const script = isInstall ? 'install.sh' : 'start.sh';
  return { command: 'sh', args: [script, ...args], label: `sh ${script}` };
}

async function installAndVerifyConfig(extracted, configPort) {
  const homeDir = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-smoke-install-')), 'home');
  const envFile = path.join(extracted.root, 'cosight.env');
  const baseUrl = `http://127.0.0.1:${configPort}`;
  const logs = [];
  let child = null;
  let supervision = null;
  let installLog = '';

  const diagnostics = () =>
    [
      `  来源      ${extracted.root}`,
      `  端口      ${configPort}（来自 cosight.env）`,
      `  数据目录  ${homeDir}`,
      '  --- 安装输出 ---',
      ...installLog.split('\n').map((line) => `  ${line}`),
      '  --- 子进程输出 ---',
      ...logs.join('').split('\n').map((line) => `  ${line}`),
    ].join('\n');

  try {
    assert(!fs.existsSync(envFile), `${extracted.tool} 产物里本来就有 cosight.env，会盖住这次要验的东西`);

    // `--skip-plugins` 是**测试隔离**，不是能力降级：插件安装会写
    // `$CLAUDE_CONFIG_DIR/plugins`，冒烟不能拿开发机真实的 `~/.claude` 当靶子，
    // 而依赖真实 `claude` 又会让没装 CLI 的机器跑不了冒烟。插件载荷本身
    // （四目录 + manifest + index 哈希）在前面的步骤里已经逐项断言过；
    // 安装行为由 `plugin-install.test.mjs` 用假状态机覆盖。
    const install = entryCommand('install', ['--home', homeDir, '--skip-plugins']);
    installLog = run(install.command, install.args, { cwd: extracted.root });
    assert(
      fs.existsSync(homeDir),
      `${install.label} 跑完却没建出数据目录 ${homeDir}\n${diagnostics()}`,
    );
    assert(fs.existsSync(envFile), `${install.label} 跑完却没生成配置文件 ${envFile}\n${diagnostics()}`);

    // 只加这两项——其余保持模板原样，行为与用户手工改一致。
    // 数据目录必须写进配置：`install.sh --home` 只影响安装那一次，`start.sh`
    // 不继承它；不写的话服务会落到 `~/.cosight-harness`，冒烟就污染了开发机。
    fs.writeFileSync(
      envFile,
      `${fs.readFileSync(envFile, 'utf8')}\nCOSIGHT_PORT=${configPort}\nCOSIGHT_HOME=${homeDir}\n`,
    );

    const start = entryCommand('start', ['--skip-plugins']);
    // 两个平台的入口都直接 spawn 一个可执行文件（`node` 或 `sh`），参数逐个传，
    // 不经过任何 shell，所以不需要 `windowsVerbatimArguments` 那种手工拼接。
    child = spawn(start.command, start.args, {
      cwd: extracted.root,
      env: process.env,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    child.stdout.on('data', (chunk) => logs.push(chunk.toString()));
    child.stderr.on('data', (chunk) => logs.push(chunk.toString()));
    supervision = supervise(child, { label: `${extracted.tool} 安装后的产物` });

    const ready = await waitForHttpOk(`${baseUrl}/api/health`, { timeoutMs: READY_TIMEOUT_MS });
    assert(
      ready.ready,
      `cosight.env 里写的端口 ${configPort} 上没有服务——配置很可能没有被读到。\n${diagnostics()}`,
    );

    return (
      `${install.label} 建出数据目录与 cosight.env，` +
      `且 ${start.label} 按配置文件里的端口 ${configPort} 起来了`
    );
  } finally {
    if (child !== null && supervision !== null) {
      await shutdown(child, supervision, [
        `${baseUrl}/api/health`,
        ...moduleProbes(extracted.root, homeDir, baseUrl).map((probe) => probe.healthUrl),
      ]);
    }
    fs.rmSync(path.dirname(homeDir), { recursive: true, force: true });
  }
}

/** 从解压出来的树启动，并完成 HTTP 断言，最后干净关停。 */
async function runExtractedServer(extracted, port) {
  const homeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-smoke-home-'));
  const baseUrl = `http://127.0.0.1:${port}`;
  const probes = moduleProbes(extracted.root, homeDir, baseUrl);
  // 模块"一个都不剩"有两种成因，必须分开：包里真的没模块（坏包），
  // 与所有模块都按 `platforms` 被跳过（设计如此，例如在 Windows 上跑时的
  // smart-factory）。只看 probes 是否为空，会把后者报成前者。
  const skippedModules = platformSkippedModules(extracted.root);
  assert(
    probes.length > 0 || skippedModules.length > 0,
    `${extracted.tool} 的 modules/ 里没有可探活的模块，也没有按平台跳过的模块：模块清单可能是空的`,
  );
  let smartFactoryVerified = false;
  const logs = [];

  const child = spawn(
    process.execPath,
    [path.join(extracted.root, 'start.mjs'), '--port', String(port), '--home', homeDir, '--skip-plugins'],
    { cwd: extracted.root, env: process.env, stdio: ['ignore', 'pipe', 'pipe'] },
  );
  child.stdout.on('data', (chunk) => logs.push(chunk.toString()));
  child.stderr.on('data', (chunk) => logs.push(chunk.toString()));

  const supervision = supervise(child, { label: `${extracted.tool} 产物` });
  const diagnostics = () =>
    [
      `  来源      ${extracted.root}`,
      `  端口      ${port}`,
      `  数据目录  ${homeDir}`,
      '  --- 子进程输出 ---',
      ...logs.join('').split('\n').map((line) => `  ${line}`),
    ].join('\n');

  try {
    const ready = await waitForHttpOk(`${baseUrl}/api/health`, { timeoutMs: READY_TIMEOUT_MS });
    assert(ready.ready, `等待 ${baseUrl}/api/health 就绪超时（${ready.attempts} 次，最后：${ready.lastError}）\n${diagnostics()}`);

    const health = await httpGet(`${baseUrl}/api/health`, 5000);
    assert(health.status === 200, `健康检查返回 HTTP ${health.status}（期望 200）`);
    assert(
      health.contentType.includes('application/json'),
      `健康检查的 content-type 是 ${health.contentType}，期望 JSON`,
    );

    const index = await httpGet(`${baseUrl}/`, 5000);
    assert(index.status === 200, `首页返回 HTTP ${index.status}（期望 200）\n${diagnostics()}`);
    // 两条断言缺一不可：只检查状态码的话，一个返回 JSON 错误的 200 也会通过。
    assert(
      index.contentType.includes('text/html'),
      `首页的 content-type 是 ${index.contentType}，期望 text/html——静态托管没生效，' /' 落到了 API 侧`,
    );
    assert(
      /<!doctype html>/i.test(index.body) && index.body.includes('id="root"'),
      `首页正文不是前端 HTML 骨架（前 120 字符：${JSON.stringify(index.body.slice(0, 120))}）\n${diagnostics()}`,
    );

    // 前端引用的构建产物必须真的在：HTML 返回了但 assets 404，是很典型的
    // "静态目录指对了、目录里没东西"的坏包。
    const assetMatch = /src="(\/assets\/[^"]+)"/.exec(index.body);
    assert(assetMatch !== null, '首页 HTML 里找不到 /assets/ 下的脚本引用，前端产物可能不完整');
    const asset = await httpGet(`${baseUrl}${assetMatch[1]}`, 5000);
    assert(asset.status === 200, `首页引用的脚本 ${assetMatch[1]} 返回 HTTP ${asset.status}`);

    // ── 模块：start.mjs 必须真的把它们拉起来 ──────────────────────────
    for (const probe of probes) {
      const moduleReady = await waitForHttpOk(probe.healthUrl, { timeoutMs: READY_TIMEOUT_MS });
      assert(
        moduleReady.ready,
        `模块 ${probe.label} 没有就绪（${probe.healthUrl}，最后：${moduleReady.lastError}）\n${diagnostics()}`,
      );

      // 只用 API 的服务（smart-factory:server）没有页面：探活成功后确认回的是 JSON。
      if (probe.readyPath !== '/') {
        const apiHealth = await httpGet(probe.healthUrl, 5000);
        assert(apiHealth.status === 200, `${probe.label} 的健康检查返回 HTTP ${apiHealth.status}（期望 200）`);
        assert(
          apiHealth.contentType.includes('application/json'),
          `${probe.label} 的健康检查 content-type 是 ${apiHealth.contentType}，期望 JSON`,
        );
        continue;
      }

      const moduleHome = await httpGet(`${probe.baseUrl}/`, 5000);
      assert(moduleHome.status === 200, `${probe.label} 的首页返回 HTTP ${moduleHome.status}`);
      assert(
        moduleHome.contentType.includes('text/html'),
        `${probe.label} 的首页 content-type 是 ${moduleHome.contentType}，期望 text/html`,
      );

      // cosight-viewer 的前端 bundle 必须带着 capability → 路由的映射：
      // 宿主只用清单里的 entry 拼 iframe 地址，模块自己按 `?capability=` 落页面。
      // 没有这个映射时，「新建对话」会落在模块的默认页——这正是这个断言要挡的回归。
      // smart-factory 没有这个参数，跳过（它的前端契约由下面的代理链路断言覆盖）。
      if (probe.id !== 'cosight-viewer') {
        continue;
      }
      const scriptMatch = /src="([^"]+\.js)"/.exec(moduleHome.body);
      assert(scriptMatch !== null, `${probe.label} 的首页里找不到脚本引用，前端产物可能不完整`);
      const scriptUrl = new URL(scriptMatch[1], `${probe.baseUrl}/`).href;
      const bundle = await httpGet(scriptUrl, 10_000);
      assert(bundle.status === 200, `${probe.label} 的脚本 ${scriptUrl} 返回 HTTP ${bundle.status}`);
      assert(
        bundle.body.includes('/chat'),
        `${probe.label} 的前端产物里没有 "/chat" 路由：?capability=conversation 会落到默认页。`,
      );
    }

    // ── smart-factory：静态页、同源 API 代理、WebSocket 升级、数据库 ────
    // 它的前端代码写死了根相对路径（`/api/smart-factory/v1/...`），
    // 所以在产物里必须由同一个端口同时提供静态页与代理；这四条缺一条，
    // 页面能打开但所有功能都不可用。
    const smartFactory = probes.find((probe) => probe.id === 'smart-factory' && probe.readyPath === '/');
    if (smartFactory !== undefined) {
      const proxied = await httpGet(`${smartFactory.baseUrl}/api/smart-factory/v1/health`, 5000);
      assert(
        proxied.status === 200,
        `smart-factory 的同源代理 /api/smart-factory/v1/health 返回 HTTP ${proxied.status}`,
      );
      assert(
        proxied.contentType.includes('application/json'),
        `smart-factory 的代理响应 content-type 是 ${proxied.contentType}，期望 JSON`,
      );
      let proxiedBody;
      try {
        proxiedBody = JSON.parse(proxied.body);
      } catch (error) {
        throw new SmokeFailure(`smart-factory 的代理响应不是 JSON：${error.message}`);
      }
      assert(
        proxiedBody.service === 'smart-factory-server',
        `smart-factory 的健康检查来自别的服务：${JSON.stringify(proxiedBody).slice(0, 160)}`,
      );

      // BrowserRouter 的深链接要回 index.html，否则刷新即 404。
      const deepLink = await httpGet(`${smartFactory.baseUrl}/agent-dev/evaluate/123`, 5000);
      assert(
        deepLink.status === 200 && deepLink.contentType.includes('text/html'),
        `smart-factory 的 SPA 深链接返回 HTTP ${deepLink.status}（${deepLink.contentType}），期望 HTML`,
      );

      const wsStatus = await probeWebSocket(`${smartFactory.baseUrl}/api/smart-factory/v1/ws`);
      assert(
        wsStatus === 101,
        `smart-factory 的 WebSocket 升级返回 HTTP ${wsStatus}（期望 101）：代理没有把 Upgrade 转给上游`,
      );

      // 首次启动必须由 prepare 步骤建出数据库；用户看到的"会话列表为空"
      // 与"数据库根本没建"在界面上无法区分。
      const databaseFile = path.join(homeDir, 'smart-factory.db');
      const databaseStat = fs.statSync(databaseFile, { throwIfNoEntry: false });
      assert(
        databaseStat !== undefined && databaseStat.isFile() && databaseStat.size > 0,
        `smart-factory 首次启动后没有建出 ${databaseFile}（prepare 步骤没生效）`,
      );

      // 内置专家必须由 boot 同步从包内定义根补进数据目录，再由 seed 登记。
      // 同步缺了是 include 或同步逻辑断了，登记缺了是 seed 断了——两者都要在冒烟里拦下。
      for (const id of EXPECTED_BUILTIN_AGENT_IDS) {
        const mirrored = path.join(homeDir, 'smart-factory', 'builtin-agents', id, 'agent.json');
        const mirroredStat = fs.statSync(mirrored, { throwIfNoEntry: false });
        assert(
          mirroredStat !== undefined && mirroredStat.isFile(),
          `内置专家 ${id} 没有同步到数据目录（缺 ${mirrored}，包内定义根或 boot 同步没生效）`,
        );
      }

      const agentsApi = await httpGet(`${smartFactory.baseUrl}/api/smart-factory/v1/agents`, 5000);
      assert(
        agentsApi.status === 200,
        `smart-factory 的 /api/smart-factory/v1/agents 返回 HTTP ${agentsApi.status}\n${diagnostics()}`,
      );
      let agentsBody;
      try {
        agentsBody = JSON.parse(agentsApi.body);
      } catch (error) {
        throw new SmokeFailure(`smart-factory 的 /agents 响应不是 JSON：${error.message}`);
      }
      const builtinItems = (agentsBody.items ?? []).filter((item) => item.source === 'builtin');
      for (const id of EXPECTED_BUILTIN_AGENT_IDS) {
        assert(
          builtinItems.some((item) => item.id === id),
          `内置专家 ${id} 没有以 source=builtin 登记进 /agents（实际 builtin：${builtinItems.map((item) => item.id).join(', ') || '空'}）\n${diagnostics()}`,
        );
      }
      smartFactoryVerified = true;
    }

    // ── 注册表：模块清单必须被同步进数据目录 ──────────────────────────
    // 这一步同时证明三件事：start.mjs 同步了 module.json、服务端从
    // $COSIGHT_HOME/modules 读到了它、清单通过了 schema 与跨源校验。
    const modulesApi = await httpGet(`${baseUrl}/api/modules`, 5000);
    assert(modulesApi.status === 200, `/api/modules 返回 HTTP ${modulesApi.status}\n${diagnostics()}`);
    let payload;
    try {
      payload = JSON.parse(modulesApi.body);
    } catch (error) {
      throw new SmokeFailure(`/api/modules 的响应不是 JSON：${error.message}\n${diagnostics()}`);
    }
    assert(payload.success === true, `/api/modules 的 success 不是 true：${JSON.stringify(payload.error)}`);
    assert(
      Array.isArray(payload.data?.invalid) && payload.data.invalid.length === 0,
      `/api/modules 报告了不合法的清单：${JSON.stringify(payload.data?.invalid)}`,
    );
    const registered = (payload.data?.modules ?? []).map((item) => item.id);
    for (const probe of probes) {
      assert(
        registered.includes(probe.id),
        `模块 ${probe.id} 没有出现在 /api/modules 里（实际：${registered.join(', ') || '空'}）\n${diagnostics()}`,
      );
    }

    // ── 默认工作区：首次启动就该有一条，且已经是「当前工作区」 ──────────
    // 没有工作区时 smart-factory 的前端连 /agents 都不请求，预置智能体一条也
    // 看不到，所以"建出来"和"设为当前"两件事都得在产物里真的生效。
    const workspacesApi = await httpGet(`${baseUrl}/api/workspaces`, 5000);
    assert(
      workspacesApi.status === 200,
      `/api/workspaces 返回 HTTP ${workspacesApi.status}\n${diagnostics()}`,
    );
    let workspacesBody;
    try {
      workspacesBody = JSON.parse(workspacesApi.body);
    } catch (error) {
      throw new SmokeFailure(`/api/workspaces 的响应不是 JSON：${error.message}\n${diagnostics()}`);
    }
    const defaultWorkspaces = workspacesBody.data;
    assert(
      Array.isArray(defaultWorkspaces) && defaultWorkspaces.length === 1,
      `首次启动应当正好有一个默认工作区，实际：${JSON.stringify(defaultWorkspaces)?.slice(0, 200)}`,
    );

    const activeWorkspace = await httpGet(`${baseUrl}/api/workspaces/active`, 5000);
    assert(
      activeWorkspace.status === 200,
      `/api/workspaces/active 返回 HTTP ${activeWorkspace.status}\n${diagnostics()}`,
    );
    let activeBody;
    try {
      activeBody = JSON.parse(activeWorkspace.body);
    } catch (error) {
      throw new SmokeFailure(`/api/workspaces/active 的响应不是 JSON：${error.message}\n${diagnostics()}`);
    }
    assert(
      activeBody.data?.id === defaultWorkspaces[0].id,
      `默认工作区没有被设为当前工作区（当前：${JSON.stringify(activeBody.data)?.slice(0, 160)}）`,
    );
    // 目录必须真的建在工作区根下：记录建了、目录没建，模块解析目录时会 502。
    assert(
      typeof defaultWorkspaces[0].directory === 'string'
        && fs.statSync(defaultWorkspaces[0].directory, { throwIfNoEntry: false })?.isDirectory() === true,
      `默认工作区的目录不存在：${defaultWorkspaces[0].directory}`,
    );
  } finally {
    // 无论断言成功与否都要把子进程收干净，否则会留下占着端口的孤儿进程。
    // 探活地址逐个复核：框架与模块是两组进程，只查一个证明不了进程组回收。
    await shutdown(child, supervision, [
      `${baseUrl}/api/health`,
      ...probes.map((probe) => probe.healthUrl),
    ]);
    fs.rmSync(homeDir, { recursive: true, force: true });
  }

  // 小结只写**真的验过**的：当前平台不支持的模块根本不会被拉起，
  // 这里就不能再声称它的静态/SPA/API/WebSocket/数据库链路可用。
  const verified = [
    '启动 → 框架 /api/health 就绪',
    '首页为 HTML 且脚本可取',
    `${probes.length} 个模块服务就绪并出现在 /api/modules`,
  ];
  if (smartFactoryVerified) {
    verified.push('smart-factory 的静态/SPA/API/WebSocket/数据库链路均可用');
  }
  verified.push('关停后框架与模块端口都释放');
  const skippedNote =
    skippedModules.length === 0 ? '' : `（跳过 ${skippedModules.join('、')}：清单未声明 ${TARGET_PLATFORM}）`;

  return `${extracted.tool}：${verified.join(' → ')}${skippedNote}`;
}

/**
 * 发 SIGINT，再逐个确认这些地址不再响应。
 *
 * 只看子进程退出码不够：服务端可能有残留的连接/句柄把端口占住，而
 * `start.mjs` 管的不止一个进程——框架退出不等于模块退出。所以要按
 * **启动时拿到的每一个探活地址**复核。
 */
/** 等子进程真的退出（或超时）。返回它最终是否已退出。 */
async function waitForChildExit(child, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child.exitCode !== null || child.signalCode !== null) {
      return true;
    }
    await sleep(200);
  }
  return child.exitCode !== null || child.signalCode !== null;
}

async function shutdown(child, supervision, probeUrls) {
  if (child.exitCode === null && child.signalCode === null) {
    if (process.platform === 'win32') {
      // Windows 没有 POSIX 信号：`child.kill('SIGINT')` 等价于 TerminateProcess，
      // `start.mjs` 的退出处理一行都跑不到，它拉起来的框架与模块（孙进程）留在
      // 原地继续占着端口——现象是"进程没了，端口还在响应"。
      //
      // 能触发真正 Ctrl-C 语义的是 GenerateConsoleCtrlEvent，但它要求调用方与
      // 子进程共享同一个控制台，冒烟没有。所以这里按**进程树**收：`taskkill /T`
      // 把 start.mjs 和全部后代一起终止，再照下面的循环断言端口释放。
      // 冒烟要证明的是"进程组被回收"，不是"某个进程收到了哪个信号"；Windows
      // 上用户按 Ctrl-C 走的是控制台路径，与这里无关。
      run(systemTool('taskkill.exe', 'taskkill'), ['/PID', String(child.pid), '/T', '/F'], {
        tolerate: () => true,
      });
      await waitForChildExit(child, SHUTDOWN_TIMEOUT_MS);
    } else {
      child.kill('SIGINT');
      await waitForChildExit(child, SHUTDOWN_TIMEOUT_MS);
      if (child.exitCode === null && child.signalCode === null) {
        child.kill('SIGKILL');
      }
    }
  }
  supervision.dispose();

  for (const url of probeUrls) {
    const deadline = Date.now() + SHUTDOWN_TIMEOUT_MS;
    let reached = false;
    while (Date.now() < deadline) {
      const probe = await httpGet(url, 1000);
      if (probe.status === 0) {
        reached = true;
        break;
      }
      await sleep(200);
    }
    if (!reached) {
      throw new SmokeFailure(`关停后 ${url} 仍在响应，进程没有干净退出。`);
    }
  }
}

/**
 * 打印一步的标题。**序号与分母都来自 `STEP_LABELS`**：原先写死的 `步骤 x/7`
 * 在加步骤时必然漏改一处，读到 `步骤 8/7` 的人会先怀疑脚本坏了。
 */
let stepIndex = 0;
function nextStep(note) {
  const label = STEP_LABELS[stepIndex];
  stepIndex += 1;
  process.stdout.write(
    `步骤 ${stepIndex}/${STEP_LABELS.length}  ${label}${note === undefined ? '' : `（${note}）`}\n`,
  );
}

async function main() {
  const options = parseArgs(process.argv.slice(2));

  nextStep(options.skipPackage ? '--skip-package，复用已有归档' : undefined);
  if (!options.skipPackage) {
    run(process.execPath, [path.join(MODULE_ROOT, 'scripts', 'package.mjs')], { stdio: 'inherit' });
  }

  // 产物名带时间戳，只有打包子进程退出后才知道它写了什么；这里按 manifest 的
  // mtime 取最新一份，而不是"再算一次名字"——后者会指向一个不存在的路径。
  const base = latestArtifactBase();
  const tarball = path.join(PACKAGE_DIR, `${base}.tar.gz`);
  const zip = path.join(PACKAGE_DIR, `${base}.zip`);
  process.stdout.write(`  产物 ${base}\n`);

  for (const archivePath of [tarball, zip]) {
    assert(fs.existsSync(archivePath), `找不到产物 ${archivePath}。先跑一次 node framework/scripts/package.mjs。`);
  }

  const manifestPath = path.join(PACKAGE_DIR, `${base}.manifest.txt`);
  assert(fs.existsSync(manifestPath), `找不到打包清单 ${manifestPath}，无法做独立读取器交叉比对。`);
  const manifest = fs
    .readFileSync(manifestPath, 'utf8')
    .split('\n')
    .filter((line) => line !== '');

  nextStep();
  // 模块端口也要空：占着的那个会被 start.mjs 当作"已经在跑"而复用，
  // 关停时它不归我们管，随后"端口已释放"的断言就会误报。
  const modulePorts = declaredModulePorts();
  await assertPortFree(options.port);
  await assertPortFree(options.configPort);
  for (const port of modulePorts) {
    await assertPortFree(port, '/health');
  }
  process.stdout.write(
    `  端口 ${options.port}（常规冒烟）、${options.configPort}（配置生效验证）` +
      `${modulePorts.length === 0 ? '' : `、模块端口 ${modulePorts.join(' / ')}`} 都空闲\n`,
  );

  const workDir = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-smoke-'));
  let failures = 0;

  try {
    nextStep();
    const tarDir = fs.mkdtempSync(path.join(workDir, 'tar-'));
    const zipDir = fs.mkdtempSync(path.join(workDir, 'zip-'));
    const extractedTar = extractWithSystemTool('tar', tarball, tarDir, base);
    const extractedZip = extractWithSystemTool('unzip', zip, zipDir, base);

    if (extractedZip.toleratedWarnings > 0) {
      process.stdout.write(
        `  注意：unzip 报了 ${extractedZip.toleratedWarnings} 条"设不上目录权限/时间戳"的告警，` +
          '按 Info-ZIP 的语义仍属成功（退出码 1）；文件内容由下面的树结构断言核对\n',
      );
    }

    process.stdout.write(`  ${compareListing('system tar', extractedTar.listing, manifest)}\n`);
    process.stdout.write(`  ${compareListing('system unzip', extractedZip.listing, manifest)}\n`);
    process.stdout.write(`  ${inspectExtractedTree(extractedTar)}\n`);
    process.stdout.write(`  ${inspectExtractedTree(extractedZip)}\n`);
    process.stdout.write(`  ${inspectBundledModules(extractedTar)}\n`);
    process.stdout.write(`  ${inspectBundledModules(extractedZip)}\n`);
    process.stdout.write(`  ${inspectBundledPlugins(extractedTar)}\n`);
    process.stdout.write(`  ${inspectBundledPlugins(extractedZip)}\n`);

    nextStep();
    process.stdout.write(`  ${await installAndVerifyConfig(extractedTar, options.configPort)}\n`);

    nextStep();
    process.stdout.write(`  ${await runExtractedServer(extractedTar, options.port)}\n`);

    nextStep();
    process.stdout.write(`  ${await runExtractedServer(extractedZip, options.port)}\n`);

    nextStep();
  } catch (error) {
    failures = 1;
    process.stderr.write(`\n冒烟失败：${error instanceof Error ? error.message : String(error)}\n`);
    process.stderr.write(`临时目录：${workDir}\n`);
    if (error instanceof SmokeFailure) {
      // 这里必须说清"会不会清"：`finally` 默认清（成功失败都清），只有 --keep-temp
      // 才留。以前这句写的是"已保留"，与 finally 的行为正好相反——真去翻目录
      // 的人只会看到"目录不存在"，然后把原因归结到解压或杀毒软件身上。
      process.stderr.write(
        options.keepTemp
          ? '（--keep-temp 生效，该目录已保留。）\n'
          : '（该目录默认已清理；要保留现场请加 --keep-temp 重跑。）\n',
      );
    }
  } finally {
    // 失败时默认也清理：现场（路径、子进程输出、清单差异）已经打进 stderr 了。
    // --keep-temp 是留给"要亲自翻目录"的场景。
    if (!options.keepTemp) {
      try {
        fs.rmSync(workDir, { recursive: true, force: true });
      } catch (error) {
        // 清理失败不该改写结论：Windows 上杀毒软件还在扫刚解出来的树、
        // 或某个句柄尚未释放时，rmSync 会抛 EBUSY（`force` 只吞 ENOENT）。
        // 那会把一次**已经通过**的冒烟变成"冒烟脚本自身出错"。
        process.stderr.write(
          `  注意：临时目录没清干净（${error.code ?? error.message}）：${workDir}\n`,
        );
      }
    }
    if (failures === 0) {
      process.stdout.write(
        [
          '',
          '冒烟通过。',
          `  tar.gz  ${humanSize(fs.statSync(tarball).size)}`,
          `  zip     ${humanSize(fs.statSync(zip).size)}`,
          '  两种归档都通过了独立读取器的解压、条目比对与"解压后真的能跑"的验证。',
          '',
        ].join('\n'),
      );
    }
  }

  process.exit(failures);
}

main().catch((error) => {
  process.stderr.write(`冒烟脚本自身出错：${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});

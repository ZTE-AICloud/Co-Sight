#!/usr/bin/env node
/**
 * Co-Sight Harness 启动入口（生产/装配态）。
 *
 * ── 边界（先读这段，它决定了本脚本为什么这么短）──────────────────────────
 *
 * **D27 = A：开发态唯一被认可的启动路径是根目录的 `pnpm dev`。**
 * 本脚本不提供、也不打算提供第二条开发态启动方式——多一条路径就多一套
 * "在我这儿能跑"的解释成本。它负责的是另一件事：把**装配好的**框架拉起来
 * （服务端 + 已构建的前端静态产物），既可以用来本地演练打包后的形态，
 * 也是发布产物里的那个入口文件。
 *
 * **模块：产物布局下拉起来，仓库布局下只探活。**
 *
 * 运行时契约（framework/shared/src/contracts/module.ts）里**没有启动命令字段**，
 * 而且不该有——那份清单会被 `/api/modules` 原样发给浏览器。启动方式登记在
 * **旁挂的装配态清单** `modules/<id>/artifact.json` 里（真源是
 * `docs/modules/<id>.artifact.json`，见 `lib/artifact-spec.mjs`）。
 *
 * 于是两条路径泾渭分明：
 *   产物布局：`modules/` 是包里带的，按清单把每个模块拉起来并监督；
 *   仓库布局：`modules/` 不存在，模块由 `pnpm dev:all` 负责（D27 不变），
 *             这里只按 healthcheck 探活并如实报告。
 *
 * 默认语义是**失败即停**（D45）：任一模块起不来、框架 30 秒内不就绪、框架端口
 * 试绑失败，都先按逆序停掉已起进程再退出 13——否则会留下占着端口的子进程，
 * 把真正的根因埋掉。`--keep-going` 恢复旧的"记一行、继续"。
 *
 * 另外，产物布局下会先把每个模块的 `module.json` 同步进
 * `$COSIGHT_HOME/modules/<id>/`：服务端只从那里读注册表，干净机器上那里是空的。
 *
 * ── 布局 ──────────────────────────────────────────────────────────────
 * 同一份脚本要在两种布局下工作，靠探测而非参数：
 *   产物布局（解压后）：<root>/start.mjs + <root>/server + <root>/web
 *   仓库布局（本仓库）：<repo>/framework/scripts/start.mjs + <repo>/framework/server + <repo>/framework/web/dist
 * 仓库布局下它等价于"用生产模式跑一遍源码"，用来在打包前发现
 * "dist 没构建 / 静态托管路径不对"这类只在生产模式才暴露的问题。
 *
 * ── 它还是"安装"的那一半（`--init` / `--self-check`）──────────────────────
 *
 * 产物里的 `install.sh` / `install.cmd` 都只是**找到 node 然后调本脚本**，
 * 真正的活（版本校验、建数据目录、生成配置）在这里做一次：
 *
 *   --self-check   只报告：Node 版本够不够、布局、数据目录、配置文件，退出码 0/1
 *   --init         在自检之上多做两件会写盘的事：建数据目录、缺配置就从模板生成
 *
 * 放在这里而不是放在两个平台各自的脚本里，是因为"同一件事有 sh 与 cmd 两份实现"
 * 一定会分叉，而且只在另一个平台上暴露。
 */

import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { applyEnvFile, parseEnvFile } from './lib/env-file.mjs';
import { claudeCheck, claudeConfigDir, claudeDirCheck, pythonCheck } from './lib/checks/claude.mjs';
import { describeModules, modulesCheck, partitionPlans } from './lib/checks/modules.mjs';
import { configCheck, dataDirCheck, diskSpaceCheck, webDistCheck } from './lib/checks/env.mjs';
import { nodeCheck } from './lib/checks/node.mjs';
import { platformCheck } from './lib/checks/platform.mjs';
import { pluginsCheck } from './lib/checks/plugins.mjs';
import { resolveClaudeExecutable } from './lib/claude-cli.mjs';
import { describePlugins } from './lib/plugin-index.mjs';
import { directorySize, retirePlugins } from './lib/plugin-uninstall.mjs';
import {
  acquireInstallLock,
  ensurePlugins,
  EXIT_PLUGINS,
  shouldInstallPlugins as shouldInstallPluginsPolicy,
} from './lib/plugin-install.mjs';
import { humanSize } from './lib/format.mjs';
import { formatProbeReport, probeModules, scanModuleManifests } from './lib/module-probe.mjs';
import { detailOf, exitCodeFor, renderReport, runChecks } from './lib/preflight.mjs';
import {
  checkTcpBind,
  forwardVerbatim,
  pumpPrefixed,
  superviseAll,
  waitForAnyHttpOk,
  waitForHttpOk,
} from './lib/runtime.mjs';

const DEFAULT_PORT = 4300;
/*
 * 默认绑所有网卡（与 server/src/config/env.ts 的 DEFAULT_HOST 一致），
 * 便于容器端口映射与局域网访问。只绑本机时显式传 `--host 127.0.0.1`。
 */
const DEFAULT_HOST = '0.0.0.0';
/** 等端口就绪的上限。编译型启动（tsx 首次转换全部源码）在本机约 1s，30s 是余量。 */
const READY_TIMEOUT_MS = 30_000;
/** 启动阶段失败（模块没起来、框架没就绪、端口被占）的退出码。 */
const EXIT_START = 13;
/** 配置文件：与 start.mjs 同目录，纯 KEY=VALUE（模板见产物里的 cosight.env.example）。 */
const ENV_FILE_NAME = 'cosight.env';
const EXAMPLE_ENV_FILE_NAME = 'cosight.env.example';
/**
 * 产物里的模块位目录名。与 `lib/project.mjs` 的 `ARTIFACT_LAYOUT.modulesSubdir`
 * 是同一个名字，但那份文件只服务于打包，不进产物，所以这里不能再引它。
 * 改动时两处一起（`scripts/tests/project.test.mjs` 会钉住这两个字符串相等）。
 */
const MODULES_DIR_NAME = 'modules';
/**
 * 产物里的插件载荷目录名。与 `ARTIFACT_LAYOUT.pluginsSubdir` 同源，理由同上：
 * project.mjs 不进产物。
 */
const PLUGINS_DIR_NAME = 'plugins';

const here = path.dirname(fileURLToPath(import.meta.url));

function parseArgs(argv) {
  const options = {
    host: process.env['COSIGHT_HOST'] ?? DEFAULT_HOST,
    port: process.env['COSIGHT_PORT'] ?? String(DEFAULT_PORT),
    home: process.env['COSIGHT_HOME'] ?? path.join(os.homedir(), '.cosight-harness'),
    logLevel: process.env['COSIGHT_LOG_LEVEL'] ?? null,
    appDir: null,
    webDir: null,
    help: false,
    selfCheck: false,
    init: false,
    noModules: false,
    claude: null,
    install: false,
    uninstall: false,
    purgeData: false,
    assumeYes: false,
    dryRun: false,
    skipPlugins: false,
    replaceMarketplace: false,
    keepGoing: false,
    skipModules: [],
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
      case '--host':
        options.host = takeValue();
        break;
      case '--port':
        options.port = takeValue();
        break;
      case '--home':
        options.home = takeValue();
        break;
      case '--log-level':
        options.logLevel = takeValue();
        break;
      case '--app-dir':
        options.appDir = path.resolve(takeValue());
        break;
      case '--web-dir':
        options.webDir = path.resolve(takeValue());
        break;
      case '--claude':
        // 原样保存：传进来的可能是 PATH 里的名字，也可能是相对/绝对路径。
        // 解析与"找不到就报错、不回退"的语义在 claudeCheck 里。
        options.claude = takeValue();
        break;
      case '--self-check':
        options.selfCheck = true;
        break;
      case '--init':
        options.init = true;
        break;
      case '--install':
        // 安装脚本调用它：自检 + 初始化 + 装插件，然后退出（不启动模块）。
        options.install = true;
        break;
      case '--uninstall':
        // 卸载脚本调用它：摘插件、摘市场，按需删数据目录，然后退出。
        options.uninstall = true;
        break;
      case '--purge-data':
        options.purgeData = true;
        break;
      case '--yes':
        // 与 --purge-data 配对：删数据目录是唯一不可撤销的一步，所以要点两次头。
        options.assumeYes = true;
        break;
      case '--dry-run':
        options.dryRun = true;
        break;
      case '--skip-plugins':
        options.skipPlugins = true;
        break;
      case '--replace-marketplace':
        options.replaceMarketplace = true;
        break;
      case '--no-modules':
        options.noModules = true;
        break;
      case '--keep-going':
        // 默认是"一个模块起不来就整体失败"；排查时用它先让框架与其余模块跑起来。
        options.keepGoing = true;
        break;
      case '--skip-module': {
        // 可重复，也可用逗号/空格分隔：`--skip-module a --skip-module b` 与
        // `--skip-module a,b` 等价，两种写法在脚本里都常见。
        const value = takeValue();
        options.skipModules.push(
          ...value
            .split(/[,\s]+/)
            .map((item) => item.trim())
            .filter((item) => item !== ''),
        );
        break;
      }
      // 这两个在 `resolveEnvFile` 的预扫描里已经生效，这里只是为了吃掉参数值不报"未知参数"。
      case '--config':
        takeValue();
        break;
      case '--no-config':
        break;
      case '-h':
      case '--help':
        options.help = true;
        break;
      default:
        throw new Error(`未知参数 ${arg}`);
    }
  }

  /*
   * 这三个开关只在卸载路径上有意义。静默忽略是最坏的处理方式：用户以为
   * `--dry-run` 让他"先看一眼"，实际却照删不误。
   */
  if ((options.dryRun || options.purgeData || options.assumeYes) && !options.uninstall) {
    throw new Error('--dry-run / --purge-data / --yes 只能与 --uninstall 一起使用');
  }

  const port = Number.parseInt(options.port, 10);
  const portIsValid = Number.isInteger(port) && port >= 1 && port <= 65_535;
  if (!portIsValid) {
    /*
     * 卸载不看端口，唯一用到它的是"数据目录还有没有进程在用"这道保险。
     * 所以卸载时给个坏端口只回落到默认值，不拿一句与卸载无关的报错拦住用户。
     */
    if (!options.uninstall) {
      throw new Error(`端口必须是 1..65535 的整数，收到 ${options.port}`);
    }
    return { ...options, port: DEFAULT_PORT };
  }

  return { ...options, port };
}

const HELP = `用法：node start.mjs [选项]

以生产模式启动 Co-Sight Harness 框架（服务端 + 已构建的前端静态产物）。
开发态请回到仓库根目录用 pnpm dev——本脚本不提供第二条开发启动路径。

安装相关：
  --self-check       只做检查并报告（Claude Code、插件载荷、Node 版本、布局、数据目录、配置文件），不启动
  --init             自检 + 建数据目录 + 缺少配置时从模板生成，不装插件
  --install          自检 + 初始化 + 把五个插件装进 Claude Code，然后退出（安装脚本调用的就是它）
  --skip-plugins     跳过插件安装（模块仍会启动，依赖插件的能力不可用）；
                     与 --uninstall 一起用时表示不动 Claude Code 那侧的插件
  --replace-marketplace
                     允许用产物里的本地市场覆盖同名的 git 市场（默认拒绝）

卸载相关：
  --uninstall        把五个插件与五个市场从 Claude Code 里摘掉，然后退出
  --dry-run          只打印将执行什么，什么都不改（配合 --uninstall）
  --purge-data       连数据目录一起删；会话、工作区与密钥都会没，需再给 --yes
  --yes              确认 --purge-data 真的要删（不可撤销，所以要点两次头）

选项：
  --port <n>         监听端口（等价 COSIGHT_PORT，默认 ${DEFAULT_PORT}）
  --host <addr>      监听地址（等价 COSIGHT_HOST，默认 ${DEFAULT_HOST}）
  --home <dir>       数据目录（等价 COSIGHT_HOME，默认 ${path.join('~', '.cosight-harness')}）
  --log-level <lvl>  日志级别（fatal|error|warn|info|debug|trace|silent）
  --app-dir <dir>    覆盖服务端目录（默认按布局探测）
  --web-dir <dir>    覆盖前端静态产物目录（默认按布局探测）
  --claude <path>    指定 Claude Code 可执行文件（默认按 PATH 与常见安装位置查找）
  --no-modules       只起框架，不拉起产物里打进包的模块（排查用）
  --keep-going       某个模块起不来时继续启动其余模块（默认整体失败并退出 13）
  --skip-module <id> 不启动指定模块，可重复或用逗号分隔（模块仍会出现在注册表里）
  --config <path>    指定配置文件（默认同目录的 ${ENV_FILE_NAME}）
  --no-config        不读配置文件，只用真实环境变量与命令行参数
  -h, --help         显示本帮助

优先级：命令行参数 > 真实环境变量 > ${ENV_FILE_NAME} > 内置默认值。

配置文件：与本脚本同目录的 ${ENV_FILE_NAME}（KEY=VALUE 纯文本，模板见 cosight.env.example）。
环境变量：除上述 COSIGHT_* 外，还支持 COSIGHT_DATABASE_URL、COSIGHT_WORKSPACES_ROOT、
COSIGHT_CORS_ORIGINS、COSIGHT_HOST_ORIGIN（含义见服务端 src/config/env.ts）。
`;

function hasServerPackage(dir) {
  return fs.existsSync(path.join(dir, 'package.json'));
}

function isDirectory(dir) {
  return fs.existsSync(dir);
}

/**
 * 按目录特征判断当前处在产物布局还是仓库布局。
 * 不用"是不是在 git 仓库里"之类的间接判断：那是猜测，而目录特征就是结论。
 */
function resolveLayout(options) {
  const artifactServer = path.join(here, 'server');
  const artifactWeb = path.join(here, 'web');
  const artifactModules = path.join(here, MODULES_DIR_NAME);
  // 仓库布局：本文件在 `framework/scripts/`，于是 `..` 就是模块根 `framework/`。
  const repoServer = path.join(here, '..', 'server');
  const repoWeb = path.join(here, '..', 'web', 'dist');

  let layout;
  if (options.appDir !== null) {
    layout = { mode: '显式指定', appDir: options.appDir };
  } else if (hasServerPackage(artifactServer)) {
    layout = { mode: '产物布局', appDir: artifactServer };
  } else if (hasServerPackage(repoServer)) {
    layout = { mode: '仓库布局', appDir: path.resolve(repoServer) };
  } else {
    throw new Error(`在 ${here} 附近找不到服务端目录。请用 --app-dir 指定，或确认产物未被裁剪。`);
  }

  const webDir =
    options.webDir ??
    (layout.mode === '产物布局' && isDirectory(artifactWeb)
      ? artifactWeb
      : layout.mode === '仓库布局'
        ? repoWeb
        : null);

  // 模块位只认产物布局：仓库布局下模块由 `pnpm dev:all` 负责，
  // 这里若也去拉一遍，同一条命令就有两条启动路径（D27 要避免的正是这个）。
  const modulesDir =
    layout.mode === '产物布局' && isDirectory(artifactModules) ? artifactModules : null;

  // 插件载荷同理：只认产物布局。仓库布局下的五个插件目录由开发者自己管，
  // 这里不去替他们安装（那份坐标清单在 scripts/artifact/plugins.json）。
  const artifactPlugins = path.join(here, PLUGINS_DIR_NAME);
  const pluginsDir =
    layout.mode === '产物布局' && isDirectory(artifactPlugins) ? artifactPlugins : null;

  return { ...layout, webDir, modulesDir, pluginsDir };
}

/* ── 配置文件（cosight.env）───────────────────────────────────────────── */

/**
 * 预扫描 argv，找配置文件在哪。
 *
 * 必须先于 `parseArgs` 跑：`parseArgs` 的默认值取自 `process.env`
 * （COSIGHT_PORT / COSIGHT_HOME …）。配置文件若在它之后再应用，
 * 文件里的值会被"解析阶段就已经取到的默认值"压掉——这种错很难从现象上看出来。
 *
 * 参数名叫 `--config` 而不是 `--env-file`：**`--env-file` 是 Node 自己的 CLI 选项**，
 * 实测（v24.13.1）它会连脚本名之后的参数一起认领，文件不存在时在脚本被执行之前
 * 就以 `node: <路径>: not found`、退出码 9 结束——用户看到的是一条和本程序无关的报错。
 * 文件存在时更阴：Node 先把它读进 process.env，于是"配置文件生效了几条"这个报告
 * 会显示 0。换个名字就没事：Node 不认识 `--config`，参数会原样到达这里。
 */
function resolveEnvFile(argv) {
  let filePath = path.join(here, ENV_FILE_NAME);
  let disabled = false;

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--no-config') {
      disabled = true;
    } else if (arg.startsWith('--config=')) {
      filePath = path.resolve(arg.slice('--config='.length));
    } else if (arg === '--config') {
      const next = argv[index + 1];
      if (next === undefined) {
        throw new Error('--config 需要一个值');
      }
      filePath = path.resolve(next);
    }
  }

  return { filePath, disabled };
}

/**
 * 读取并应用配置文件。**只填空缺**：真实环境变量与命令行参数优先级更高
 * （语义在 lib/env-file.mjs 里，两个平台的安装/启动脚本都不自己解析这份文件）。
 */
function loadConfigFile(plan) {
  if (plan.disabled || !fs.existsSync(plan.filePath)) {
    return { ...plan, exists: false, applied: [], entryCount: 0, error: null };
  }

  let entries;
  try {
    entries = parseEnvFile(fs.readFileSync(plan.filePath, 'utf8'), plan.filePath);
  } catch (error) {
    // **不在这里抛**：解析失败也要先把整张检查报告打完再退出。
    // 直接抛的话，用户只看到一句"启动失败：配置文件…"，而同一次运行里
    // Node、数据目录、模块的结论全都没打印出来——那些恰恰是接下来要看的。
    return {
      ...plan,
      exists: true,
      applied: [],
      entryCount: 0,
      error: new Error(`配置文件 ${plan.filePath} 解析失败：${error.message}`, { cause: error }),
    };
  }

  const applied = applyEnvFile(entries);
  return { ...plan, exists: true, applied, entryCount: entries.length, error: null };
}

/* ── 自检与初始化（--self-check / --init）─────────────────────────────── */

/**
 * 前置检查清单。
 *
 * 顺序就是报告里的顺序，也大致是依赖顺序：
 *   平台 → Node → Claude Code → Claude 目录 → Python 3 → 插件载荷
 *   → 数据目录 → 配置 → 前端 → 模块 → 磁盘。
 *
 * 前六项决定"插件能不能装、装进去能不能跑"；后面决定"跑起来是不是那套配置"。
 * 插件装不上时后续模块启动没有意义，所以它们排在数据目录之前。
 *
 * `--self-check` 与正常启动跑的是**同一个函数**——两条路径各写一份清单，
 * 迟早会出现"自检全绿、启动却报错"。
 *
 * @param {{options: object, layout: object, config: object,
 *   moduleReport: ReturnType<typeof describeModules>,
 *   pluginReport: ReturnType<typeof describePlugins>}} context
 */
function buildChecks(context) {
  return [
    platformCheck(),
    nodeCheck({ appDir: context.layout.appDir }),
    claudeCheck({ explicit: context.options.claude }),
    claudeDirCheck(),
    pythonCheck({ plugins: context.pluginReport.plugins }),
    pluginsCheck({
      pluginReport: context.pluginReport,
      // 产物布局下插件载荷是交付的一部分，缺了就是包不完整；
      // 仓库布局下由开发者自己管，没有也不算错。
      required: context.layout.mode === '产物布局',
    }),
    dataDirCheck({ home: context.options.home }),
    configCheck({ config: context.config }),
    webDistCheck({ webDir: context.layout.webDir }),
    modulesCheck({ moduleReport: context.moduleReport }),
    diskSpaceCheck({ home: context.options.home }),
  ];
}

/**
 * 插件坐标清单的位置（仓库布局用）。
 *
 * `here` 在仓库里是 `framework/scripts/`，所以清单在 `artifact/plugins.json`，
 * 而五个插件目录在仓库根。产物布局下走 `plugins/index.json`，这两个参数不会被用到。
 */
function pluginManifestLocation() {
  return {
    manifestPath: path.join(here, 'artifact', 'plugins.json'),
    sourceRoot: path.resolve(here, '..', '..'),
  };
}

/** 报告顶部的环境事实：排查时一定需要，但它们不是"检查结论"。 */
function reportContext(options, layout, config) {
  return [
    `布局      ${layout.mode}（服务端 ${layout.appDir}）`,
    `数据目录  ${options.home}`,
    `配置文件  ${config.disabled ? '（--no-config 已关闭）' : config.filePath}`,
  ];
}

/**
 * 尽力把权限收紧到 `mode`，返回一句**读回实际权限后**的说明。
 *
 * 不直接说"已按 0700 收紧"：Windows 上 chmod 只影响只读位，statSync 读回来是 0666，
 * 那句宣称就是假的。读回实际值再说，两个平台都不会说错话。
 * 失败也不抛：权限收紧是加固，不是安装能否完成的前提。
 */
function tightenPermissions(target, mode) {
  try {
    fs.chmodSync(target, mode);
  } catch (error) {
    return `（未能设置权限：${error.message}）`;
  }
  const actual = fs.statSync(target).mode & 0o777;
  return actual === mode ? `（权限 0${actual.toString(8)}）` : `（本平台按 0${actual.toString(8)} 处理，不影响使用）`;
}

/**
 * 配置模板在哪。两个候选是布局差异，不是"随便找找"：
 *   产物布局：模板被 package.mjs 拷到 start.mjs 旁边（这就是候选一）
 *   仓库布局：模板只在源目录 `scripts/artifact/` 里（候选二），
 *             这样开发态 `pnpm start --init` 与用户拿到的产物走同一条路。
 */
function findExampleConfig() {
  const candidates = [path.join(here, EXAMPLE_ENV_FILE_NAME), path.join(here, 'artifact', EXAMPLE_ENV_FILE_NAME)];
  return candidates.find((candidate) => fs.existsSync(candidate)) ?? null;
}

/** 建数据目录 + 缺配置就从模板生成。两件事都是幂等的，重复执行不会有副作用。 */
function runInit(options, config) {
  const done = [];

  // umask 只约束本进程之后新建的文件/目录；Node 没有读 umask 的 API，设一次即可。
  process.umask(0o077);
  fs.mkdirSync(options.home, { recursive: true, mode: 0o700 });
  done.push(`  数据目录  ${options.home}（已就绪）${tightenPermissions(options.home, 0o700)}`);

  if (config.disabled) {
    done.push('  配置文件  已用 --no-config 关闭，不生成');
  } else if (config.exists) {
    done.push(`  配置文件  ${config.filePath}（已存在，保持原样）`);
  } else {
    const examplePath = findExampleConfig();
    if (examplePath === null) {
      throw new Error(
        `找不到配置模板 ${EXAMPLE_ENV_FILE_NAME}（已查 ${here}、${path.join(here, 'artifact')}）。请重新获取完整的发布包。`,
      );
    }
    fs.copyFileSync(examplePath, config.filePath);
    // 生成的配置里可能写数据库口令之类，所以文件不留在模板的权限上（copyFile 会继承源权限）。
    done.push(
      `  配置文件  ${config.filePath}（已从 ${EXAMPLE_ENV_FILE_NAME} 生成，全部为注释，行为与现在一致）` +
        tightenPermissions(config.filePath, 0o600),
    );
  }

  process.stdout.write(`${done.join('\n')}\n\n`);
}

/* ── 插件安装 ─────────────────────────────────────────────────────────── */

/**
 * 这次启动要不要装插件。
 *
 * 产物布局默认装：插件是产品的一部分，专家页与多个模块依赖它们。
 * 仓库布局只在显式 `--install` 时装：开发机上 Claude Code 的状态归开发者自己，
 * 日常 `pnpm dev:all` 也不走这个入口。
 *
 * 判定本身在 `lib/plugin-install.mjs`（有单测），这里只负责把三个来源拼起来——
 * `--install` 与 `start` 两条路径必须用同一条判定，不能再各写一份。
 */
function shouldInstallPlugins(options, layout, pluginReport) {
  return shouldInstallPluginsPolicy({
    skipPlugins: options.skipPlugins,
    install: options.install,
    layoutMode: layout.mode,
    pluginMode: pluginReport.mode,
  });
}

async function runPluginInstall(options, pluginReport) {
  const found = resolveClaudeExecutable({ explicit: options.claude });
  if (found.path === null) {
    // 正常到这里说明前置检查已经拦住了；保留这条是为了不把 null 传下去。
    return {
      ok: false,
      steps: [],
      failure: {
        plugin: null,
        command: null,
        detail: '找不到 Claude Code 可执行文件',
        remedy: ['安装：npm install -g @anthropic-ai/claude-code', '或用 --claude <路径> 指定'],
      },
    };
  }

  process.stdout.write(
    [
      '插件：',
      `  载荷      ${pluginReport.line}（${pluginReport.mode === 'artifact' ? '产物' : '仓库'}）`,
      `  Claude    ${found.path}`,
      '',
    ].join('\n'),
  );

  let lock;
  try {
    lock = acquireInstallLock(options.home);
  } catch (error) {
    return {
      ok: false,
      steps: [],
      failure: {
        plugin: null,
        command: null,
        detail: error.message,
        remedy: [
          '确认没有其他安装进程正在运行',
          `若上次异常退出留下锁文件，确认后删除：${path.join(options.home, '.install.lock')}`,
        ],
      },
    };
  }

  try {
    return await ensurePlugins({
      plugins: pluginReport.plugins,
      executable: found.path,
      home: options.home,
      // 必须显式给 configDir：`options.home` 是 COSIGHT_HOME，不是用户主目录。
      // 让 ensurePlugins 自己按 homeDir 推，会推到 `<COSIGHT_HOME>/.claude`，
      // 而 Claude Code 根本不看那里。
      configDir: claudeConfigDir({}),
      platform: process.platform,
      replaceMarketplace: options.replaceMarketplace,
      log: (line) => process.stdout.write(`${line}\n`),
    });
  } finally {
    lock.release();
  }
}

/**
 * 插件阶段失败时的固定结构：插件 / 命令 / 原因 / 处理 / 影响。
 *
 * `title` 与 `impact` 由调用方给：安装与卸载的后果不是同一句话
 * ——装到一半失败是"模块起不来"，卸到一半失败是"机器上留着一半插件"。
 */
function renderPluginFailure(
  outcome,
  {
    title = '插件安装失败',
    impact = '插件没有全部就绪，模块未启动；已装好的插件保留，修好后重跑即可。',
  } = {},
) {
  const failure = outcome.failure ?? {};
  const lines = ['', title, ''];
  if (typeof failure.plugin === 'string' && failure.plugin !== '') {
    lines.push(`  插件      ${failure.plugin}`);
  }
  if (typeof failure.command === 'string' && failure.command !== '') {
    lines.push(`  命令      ${failure.command}`);
  }
  lines.push(`  原因      ${failure.detail ?? '未知错误'}`);
  if (Array.isArray(failure.remedy) && failure.remedy.length > 0) {
    lines.push('  处理');
    failure.remedy.forEach((item, index) => lines.push(`            ${index + 1}. ${item}`));
  }
  lines.push(`  影响      ${impact}`, '');
  return `${lines.join('\n')}\n`;
}

/* ── 卸载 ─────────────────────────────────────────────────────────────── */

/** 卸载路径上的正常输出。错误一律走 stderr，好让 `>/dev/null` 只吞掉进度。 */
function out(text) {
  process.stdout.write(text);
}

/**
 * 卸载的汇总。逐条明细已经由 `retirePlugins` 的日志打过了，这里只回答
 * "一共动了几个、还有什么没做"。
 */
function renderUninstallSummary(steps, { dryRun }) {
  const count = (kind, action) =>
    steps.filter((step) => step.kind === kind && step.action === action).length;
  const verb = dryRun ? '将' : '已';
  const done = dryRun ? 'planned' : 'removed';
  const purgedBytes = steps.reduce((sum, step) => sum + (step.purgedBytes ?? 0), 0);

  const lines = [
    `\n汇总：${verb}卸载插件 ${count('plugin', done)} 个（另有 ${count('plugin', 'absent')} 个本来就没装），` +
      `${verb}移除市场 ${count('marketplace', done)} 个（另有 ${count('marketplace', 'absent')} 个未注册）。`,
  ];
  if (purgedBytes > 0) {
    lines.push(
      `      顺带清掉 ${humanSize(purgedBytes)} 载荷副本（安装在 Claude 配置目录下复制的那几份）。`,
    );
  }
  for (const step of steps.filter((item) => item.action === 'kept-in-use')) {
    lines.push(`      市场 ${step.name} 保留：还有别的插件挂在上面（${step.foreign.join(', ')}）。`);
    lines.push(
      `        确认那些插件不要了再手动删：claude plugin marketplace remove ${step.name} --scope user`,
    );
  }
  return `${lines.join('\n')}\n`;
}

/**
 * 数据目录的处置。默认**不动**——那里是用户的会话、工作区与密钥。
 *
 * 删除要点两次头：`--purge-data` 表示意图，`--yes` 表示确认。中间那一步会把
 * 路径与体积打出来，让人有机会看清自己删的是什么。
 *
 * 真删之前还要确认框架没在跑：服务开着去删它的库，删的是一份正在被写的文件，
 * 用户随后看到的是"刚删完又冒出一个空库"。
 *
 * @returns {Promise<{code: number, lines: string[]}>} `code` 非 0 表示这一步没做完
 */
async function handleDataDirectory(options) {
  const home = options.home;
  if (!fs.existsSync(home)) {
    return { code: 0, lines: [`  不存在    ${home}（无需处理）`] };
  }

  const size = humanSize(directorySize(home));

  if (!options.purgeData) {
    return {
      code: 0,
      lines: [
        `  保留      ${home}（${size}）`,
        '            里面有会话、工作区与密钥；要一并删除：加 --purge-data --yes 重跑',
      ],
    };
  }

  if (options.dryRun) {
    return {
      code: 0,
      lines: [`  将删除    ${home}（${size}）`, '            --dry-run：没有真的删'],
    };
  }

  if (!options.assumeYes) {
    /*
     * 退出码非 0 是有意的：用户说了 --purge-data，数据目录却还在。回 0 会让脚本
     * 以为删干净了——"什么都没做但报成功"是卸载脚本最不该有的行为。
     */
    return {
      code: EXIT_START,
      lines: [
        `  待删除    ${home}（${size}）`,
        '            会话、工作区与密钥都会被删除，且无法恢复',
        '            确认后加 --yes 重跑：--purge-data 表示意图，--yes 表示确认',
      ],
    };
  }

  const bind = await checkTcpBind(probeHost(options.host), options.port);
  if (!bind.ok) {
    return {
      code: EXIT_START,
      lines: [
        `  未删除    ${home}（${size}）`,
        `            端口 ${options.port} 上还有进程在监听（${bind.detail ?? '无法确认'}），框架可能仍在运行`,
        '            先停掉框架（Ctrl-C 或结束 start.sh），再重跑 --purge-data --yes',
      ],
    };
  }

  try {
    fs.rmSync(home, { recursive: true, force: true });
  } catch (error) {
    return { code: EXIT_START, lines: [`  删除失败  ${home}`, `            ${error.message}`] };
  }
  return { code: 0, lines: [`  已删除    ${home}（释放 ${size}）`] };
}

/**
 * 卸载入口。
 *
 * 刻意**不走**前置检查那套报告：用户想卸载，往往正是因为启动不起来——这时候
 * 还要求 web 静态产物齐全、模块载荷完整，等于把人挡在卸载门外。
 */
async function runUninstall(options) {
  out('Co-Sight Harness 卸载\n\n');
  if (options.dryRun) {
    out('模式：--dry-run，只报告将要做什么，下面没有发生任何改动\n\n');
  }

  if (options.skipPlugins) {
    out('插件：已跳过（--skip-plugins）\n\n');
  } else {
    const found = resolveClaudeExecutable({ explicit: options.claude });
    if (found.path === null) {
      process.stderr.write(
        renderPluginFailure(
          {
            ok: false,
            steps: [],
            failure: {
              plugin: null,
              command: null,
              detail: '找不到 Claude Code 可执行文件，摘不掉已经装进去的插件',
              remedy: [
                '安装：npm install -g @anthropic-ai/claude-code',
                '或用 --claude <路径> 指定',
                '确实不需要处理插件时加 --skip-plugins',
              ],
            },
          },
          { title: '插件卸载失败', impact: '插件仍然装着，卸载没有完成。' },
        ),
      );
      return EXIT_PLUGINS;
    }

    out(`插件：\n  Claude    ${found.path}\n`);
    const outcome = await retirePlugins({
      executable: found.path,
      // 与安装同一个理由：`options.home` 是 COSIGHT_HOME，Claude Code 不看那里。
      configDir: claudeConfigDir({}),
      platform: process.platform,
      dryRun: options.dryRun,
      log: (line) => out(`${line}\n`),
    });
    if (!outcome.ok) {
      process.stderr.write(
        renderPluginFailure(outcome, {
          title: '插件卸载失败',
          impact: '卸载没有完成；已经卸掉的那几个不会自动装回来，修好后重跑即可。',
        }),
      );
      return EXIT_PLUGINS;
    }
    out(renderUninstallSummary(outcome.steps, { dryRun: options.dryRun }));
  }

  const data = await handleDataDirectory(options);
  out(`\n数据目录：\n${data.lines.join('\n')}\n`);

  if (hasServerPackage(path.join(here, 'server'))) {
    const lead = options.dryRun ? '最后一步：删除这个解压目录（--dry-run 下不必做）' : '最后一步：删除这个解压目录';
    out(`\n${lead}\n  ${here}\n`);
  } else {
    // 源码仓库里没有"删解压目录"这件事，说清楚免得用户去找一个不存在的目录。
    out(
      options.dryRun
        ? '\n当前在源码仓库里：--dry-run 下什么都没改，源码目录也不做改动。\n'
        : '\n当前在源码仓库里：插件已按上面的结果处理，源码目录不做任何改动。\n',
    );
  }

  return data.code;
}

/**
 * 启动阶段失败的固定结构：阶段 / 原因 / 处理 / 影响。
 *
 * 和插件失败分开写是因为读者不同：插件失败要改 Claude Code 那边的状态，
 * 启动失败要改模块或端口；混成一张表会让人先看错那一行。
 */
function renderStartFailure({ stage, reason, remedy, impact }) {
  const lines = ['', '启动失败', '', `  阶段      ${stage}`];
  const reasonLines = String(reason).split('\n');
  lines.push(`  原因      ${reasonLines[0]}`);
  for (const line of reasonLines.slice(1)) {
    lines.push(`            ${line}`);
  }
  if (remedy.length > 0) {
    lines.push('  处理');
    remedy.forEach((item, index) => lines.push(`            ${index + 1}. ${item}`));
  }
  lines.push(`  影响      ${impact}`, '');
  return `${lines.join('\n')}\n`;
}

/**
 * 定位 tsx 的 loader。
 *
 * 服务端**没有 JS 产物**（`build` 只是 `tsc --noEmit`），运行的就是 TypeScript 源码，
 * 因此运行时必须能加载 tsx。这里显式解析出 loader 的绝对路径再交给 `--import`，
 * 而不是写 `--import tsx`：后者依赖 cwd 上的解析，一旦有人从别的目录启动就会
 * 变成一个看不懂的 ERR_MODULE_NOT_FOUND。
 */
function resolveTsxLoader(appDir) {
  const requireFromApp = createRequire(path.join(appDir, 'package.json'));
  try {
    return pathToFileURL(requireFromApp.resolve('tsx')).href;
  } catch (error) {
    throw new Error(
      `在 ${appDir} 里找不到 tsx（服务端以 TypeScript 源码运行，运行时需要它）：${error.message}`,
      { cause: error },
    );
  }
}

function buildChildEnv(options, webDir) {
  const env = { ...process.env };
  // 生产模式：静态托管只在这个模式下启用（见 config/env.ts 的 readWebDist）。
  env['NODE_ENV'] = 'production';
  env['COSIGHT_PORT'] = String(options.port);
  env['COSIGHT_HOST'] = options.host;
  env['COSIGHT_HOME'] = options.home;
  if (options.logLevel !== null) {
    env['COSIGHT_LOG_LEVEL'] = options.logLevel;
  }
  // 显式给出静态产物目录，不依赖"cwd 下的 public"这一默认值——
  // 默认值是相对 cwd 求的，而 cwd 在两种布局下指向不同的地方。
  if (webDir !== null) {
    env['COSIGHT_WEB_DIST'] = webDir;
  }
  return env;
}

/** 监听 0.0.0.0 时不能拿 0.0.0.0 去请求，换成回环地址探活。 */
function probeHost(host) {
  return host === '0.0.0.0' || host === '::' ? '127.0.0.1' : host;
}

/**
 * 列出**其他机器**能用来打开框架的地址。
 *
 * `0.0.0.0` 只是监听通配地址，浏览器不能拿它当目的地（Chrome 直接拦截），
 * 真正可访问的是本机各块网卡上的地址。所以监听全部网卡时把非内部 IPv4
 * 逐个列出来；绑的是具体地址（含回环）时没有额外可列的，返回空数组。
 *
 * 只取 IPv4：局域网里给同事发一个 IPv6 链路本地地址（`fe80::`）基本没法用。
 */
function externalUrls(host, port) {
  if (host !== '0.0.0.0' && host !== '::') {
    return [];
  }
  const urls = [];
  for (const addresses of Object.values(os.networkInterfaces())) {
    for (const address of addresses ?? []) {
      if (address.internal || address.family !== 'IPv4') {
        continue;
      }
      urls.push(`http://${address.address}:${port}/`);
    }
  }
  return urls;
}

async function reportModules(homeDir, platformSkips = []) {
  const modulesDir = path.join(homeDir, 'modules');
  try {
    const manifests = scanModuleManifests(modulesDir);
    // 平台不支持的模块：留着这一行（用户要知道包里有这个模块），但不去探活——
    // 它本来就没被拉起，探活只会报一句 ECONNREFUSED，看起来像模块坏了。
    const platformSkipped = new Map(
      platformSkips.map((item) => [item.id, `本平台不适用（${item.note}），本次启动未拉起`]),
    );
    const results = await probeModules(manifests, { platformSkipped });
    // 装配态下模块刚被本脚本拉起，这里是对"拉起来了没有"的复核；
    // 仓库布局下模块由 dev:all 负责，这里只是探活报告。两种情况都只报告、不影响退出码。
    process.stdout.write('模块注册表：\n');
    for (const line of formatProbeReport(results)) {
      process.stdout.write(`${line}\n`);
    }
  } catch (error) {
    // 探活是附加信息，读目录失败不该把已经起来的服务带下水。
    process.stdout.write(`模块探活未能完成（不影响服务运行）：${error.message}\n`);
  }
}

/* ── 产物里的模块 ─────────────────────────────────────────────────────── */

/**
 * 探活候选地址。模块声明的是端口，绑哪个回环地址由模块自己决定：
 * 有的服务只绑 IPv6 回环，只试 127.0.0.1 会把"其实起来了"报成超时
 * （见 lib/runtime.mjs 里 waitForAnyHttpOk 的说明）。
 */
const LOOPBACK_HOSTS = ['127.0.0.1', 'localhost', '[::1]'];

function candidateUrls(service) {
  return LOOPBACK_HOSTS.map((host) => `http://${host}:${service.port}${service.readyPath}`);
}

function describeExit(code, signal) {
  return signal === null || signal === undefined ? `退出码 ${code ?? '未知'}` : `被 ${signal} 终止`;
}

/**
 * 把产物里每个模块的 `module.json` 同步进 `$COSIGHT_HOME/modules/<id>/`。
 *
 * 服务端的注册表**只从数据目录读**，而干净的机器上那里是空的。少了这一步，
 * 模块明明被拉起来了，`/api/modules` 却是空列表、前端 iframe 无处可指。
 * 逐字节相同就跳过，所以每次启动都跑也没有任何多余写入。
 *
 * @returns {string[]} 这次实际写了的模块 id
 */
function syncBundledManifests(modulesDir, homeDir) {
  const targetRoot = path.join(homeDir, 'modules');
  const synced = [];

  let dirents;
  try {
    dirents = fs.readdirSync(modulesDir, { withFileTypes: true });
  } catch (error) {
    throw new Error(`读不到产物里的模块目录 ${modulesDir}：${error.message}`, { cause: error });
  }

  for (const dirent of dirents.filter((item) => item.isDirectory())) {
    const source = path.join(modulesDir, dirent.name, 'module.json');
    if (!fs.existsSync(source)) {
      // 没有运行时契约的模块目录不可能是有效产物（打包脚本必定会写这份文件）。
      continue;
    }

    const target = path.join(targetRoot, dirent.name, 'module.json');
    const content = fs.readFileSync(source);
    if (fs.existsSync(target) && Buffer.compare(fs.readFileSync(target), content) === 0) {
      continue;
    }

    try {
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.writeFileSync(target, content);
    } catch (error) {
      throw new Error(`把模块清单写到 ${target} 失败：${error.message}`, { cause: error });
    }
    synced.push(dirent.name);
  }

  return synced;
}

/**
 * 跑一个模块的 prepare 步骤（建库、生成配置）。
 *
 * 这些步骤必须在服务的**任何**进程出现之前完成：服务一启动就会读库，
 * 库不在时它要么崩溃、要么自己建一份不完整的。步骤失败时调用方会跳过该模块
 * 的服务——带着"库没建好"去起服务，只会得到一段更难读的错误。
 *
 * 与构建命令一样用独立进程组：超时后要对整组发信号，否则模块脚本派生的
 * 子进程会继续占着文件。
 *
 * 子进程登记进 `entries`：它同样是 detached 的进程组，Ctrl-C 落在准备步骤执行
 * 期间时，只有被监督列表看到才能一起回收。
 */
function runPrepareStep(step, entries) {
  return new Promise((resolve) => {
    const [program, ...args] = step.command;
    const startedAt = Date.now();
    let settled = false;
    const child = spawn(program, args, {
      cwd: step.cwd,
      env: { ...process.env, ...step.env },
      detached: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    entries.push({ label: step.label, child });

    pumpPrefixed(child, { label: step.label, width: step.label.length });

    let timer = null;
    const finish = (result) => {
      if (settled) {
        return;
      }
      settled = true;
      if (timer !== null) {
        clearTimeout(timer);
      }
      resolve({ ...result, elapsedMs: Date.now() - startedAt });
    };

    timer = setTimeout(() => {
      try {
        process.kill(-child.pid, 'SIGKILL');
      } catch {
        child.kill('SIGKILL');
      }
      finish({ ok: false, detail: `超时（${step.timeoutMs}ms）` });
    }, step.timeoutMs);

    child.on('error', (error) => finish({ ok: false, detail: `进程起不来：${error.message}` }));
    child.on('exit', (code, signal) => {
      finish(
        code === 0
          ? { ok: true, detail: '' }
          : { ok: false, detail: describeExit(code, signal) },
      );
    });
  });
}

/**
 * 以独立进程组启动一个模块服务。
 *
 * `detached: true` 是 `superviseAll` 按进程组回收的前提（它发的是负 PID）。
 * 模块自己可能再派生进程（例如调起 CLI），只杀直接子进程会留下占着端口的孤儿，
 * 下一次启动就撞 EADDRINUSE。stdio 走管道而不是继承：多路日志要靠
 * `pumpPrefixed` 加 `[模块]` 前缀分开。
 */
function spawnService(service) {
  const [program, ...args] = service.command;
  const record = { error: null, child: null };

  record.child = spawn(program, args, {
    cwd: service.cwd,
    // 清单里声明的键优先：它们是这个模块的运行前提（端口、数据目录、NODE_ENV）。
    env: { ...process.env, ...service.env },
    detached: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  record.child.on('error', (error) => {
    record.error = error;
  });

  return record;
}

/**
 * 等模块的 readyPath 返回 2xx。
 *
 * 与"等服务端"的区别：模块可能**启动即退出**（端口被占、依赖缺、清单写错）。
 * 那种情况下按超时干等一分钟既慢又会把原因说成"未就绪"。
 * 所以把"进程已经没了"作为中止条件交给轮询。
 */
async function waitForService(record, service) {
  const result = await waitForAnyHttpOk(candidateUrls(service), {
    timeoutMs: service.readyTimeoutMs,
    shouldStop: () =>
      record.error !== null
      || record.child.exitCode !== null
      || record.child.signalCode !== null,
  });

  if (record.error !== null) {
    return { ok: false, detail: `进程起不来：${record.error.message}` };
  }
  if (result.ready) {
    return { ok: true, url: result.url };
  }
  if (result.stopped === true) {
    return {
      ok: false,
      detail: `启动即退出（${describeExit(record.child.exitCode, record.child.signalCode)}），日志见下方`,
    };
  }
  return {
    ok: false,
    detail: `等待 ${Math.round(service.readyTimeoutMs / 1000)}s 未就绪（${result.lastError ?? '未知原因'}）`,
  };
}

/**
 * 按 priority 升序逐个拉起模块服务，**并等它真的就绪**再起下一个。
 *
 * 串行是有意的：模块之间可能有依赖（先起的那个提供数据/接口），并行起会让
 * `priority` 这个字段失去意义。代价是启动时间相加，模块不多时可以接受。
 *
 * 默认语义是失败即停：任一准备步骤或服务起不来，立刻返回 `ok: false`，由调用方
 * 停掉已起进程并退出 13。`--keep-going` 时只记一行、继续起下一个（旧行为）。
 */
async function startModules(plans, entries, headline, options = {}) {
  const keepGoing = options.keepGoing === true;
  // 已经开始收尾就不要再起新进程。`stopAll` 在开始时对 entries 做了快照，快照之后
  // 才 spawn 的服务不会被它等（它只看快照），只会白起一次再被 exit 兜底杀掉——
  // 表现为终端里几行迟到的日志，以及关停后端口仍被占着的假象。返回 `aborted`
  // 而不是 `ok: false`：这不是启动失败，调用方不该打印失败报告。
  const isStopping = options.isStopping ?? (() => false);
  const failures = [];
  if (plans.length === 0) {
    return { ok: true, failures };
  }

  const labels = plans.flatMap((plan) => [
    ...plan.prepare.map((step) => step.label),
    ...plan.services.map((service) => service.label),
  ]);
  const width = Math.max(...labels.map((label) => label.length));

  process.stdout.write(`${headline}（${plans.length} 个，按 priority 升序）…\n`);

  for (const plan of plans) {
    let prepared = true;
    for (const step of plan.prepare) {
      if (isStopping()) {
        return { ok: false, failures, aborted: true };
      }
      const result = await runPrepareStep(step, entries);
      if (result.ok) {
        process.stdout.write(`  ✓ ${step.label} 已完成（${(result.elapsedMs / 1000).toFixed(1)}s）\n`);
      } else {
        // 准备失败时**不**起这个模块的服务：服务会去读一个不存在的库，
        // 报出来的错与真正的原因（建库失败）相距很远。
        process.stderr.write(`  ✗ ${step.label} 失败：${result.detail}；跳过 ${plan.id} 的服务\n`);
        failures.push({ module: plan.id, label: step.label, detail: result.detail });
        prepared = false;
        break;
      }
    }
    if (!prepared) {
      if (!keepGoing) {
        return { ok: false, failures };
      }
      continue;
    }

    for (const service of plan.services) {
      if (isStopping()) {
        return { ok: false, failures, aborted: true };
      }
      // 同一端口上已经有服务在响应：多半是开发态还开着。再拉一个只会撞端口，
      // 所以复用它并**明说**——不写这一行，"为什么日志里没有它"只能靠猜。
      const existing = await waitForAnyHttpOk(candidateUrls(service), {
        timeoutMs: 150,
        intervalMs: 50,
      });
      if (existing.ready) {
        process.stdout.write(`  = ${service.label} 已在 ${existing.url} 响应，跳过启动\n`);
        continue;
      }

      const record = spawnService(service);
      entries.push({ label: service.label, child: record.child });
      pumpPrefixed(record.child, { label: service.label, width });

      // 启动闸门只覆盖"起不来"。已经就绪之后再崩的模块只报警、不自动重启，
      // 也不把整次启动拖垮——框架自身同样如此。收尾时我们自己发的信号不刷屏。
      record.child.once('exit', (code, signal) => {
        if (signal === 'SIGTERM' || signal === 'SIGINT') {
          return;
        }
        process.stderr.write(
          `  ! 模块 ${service.label} 已退出（${describeExit(code, signal)}），框架继续运行\n`,
        );
      });

      const ready = await waitForService(record, service);
      if (ready.ok) {
        process.stdout.write(`  ✓ ${service.label} 已就绪（${ready.url}）\n`);
      } else {
        process.stderr.write(`  ✗ ${service.label} 未就绪：${ready.detail}\n`);
        failures.push({ module: plan.id, label: service.label, detail: ready.detail });
        if (!keepGoing) {
          return { ok: false, failures };
        }
      }
    }
  }

  process.stdout.write('\n');
  return { ok: failures.length === 0, failures };
}

async function main() {
  const argv = process.argv.slice(2);
  // 顺序是有意的：配置文件先落地到 process.env，parseArgs 取默认值时才看得到它。
  const config = loadConfigFile(resolveEnvFile(argv));
  const options = parseArgs(argv);

  if (options.help) {
    process.stdout.write(HELP);
    return;
  }

  // 卸载必须在 resolveLayout 之前分出去：它不碰模块载荷与 web 产物，
  // 而 resolveLayout 会因为这些缺失直接报错——那正是有人要卸载的原因。
  if (options.uninstall) {
    process.exitCode = await runUninstall(options);
    return;
  }

  const layout = resolveLayout(options);
  // 模块回调框架时用这个地址（`{{frameworkUrl}}`）。必须与下面真正监听的
  // 地址一致：`--host 0.0.0.0` 时回调不该发到 0.0.0.0，probeHost 会收到环回地址。
  const host = probeHost(options.host);
  const baseUrl = `http://${host}:${options.port}`;
  const moduleReport = describeModules({
    modulesDir: layout.modulesDir,
    home: options.home,
    noModules: options.noModules,
    frameworkUrl: baseUrl,
  });
  const pluginReport = describePlugins({
    pluginsDir: layout.pluginsDir,
    ...pluginManifestLocation(),
  });

  const title = options.selfCheck
    ? 'Co-Sight Harness 自检'
    : options.install
      ? 'Co-Sight Harness 安装前检查'
      : options.init
        ? 'Co-Sight Harness 初始化前检查'
        : 'Co-Sight Harness 启动前检查';
  const results = await runChecks(
    buildChecks({ options, layout, config, moduleReport, pluginReport }),
  );
  const report = renderReport(results, { title, context: reportContext(options, layout, config) });
  const preflightCode = exitCodeFor(results);

  if (options.selfCheck || options.init || options.install) {
    // 顺序有意：先出检查报告（改之前是什么状态），再列出这次实际写了什么。
    process.stdout.write(report);
    if (preflightCode !== 0) {
      // 有阻塞项就不写盘：带着"目录不可写 / Node 太老"去建目录，只会在
      // 另一个位置再失败一次，而那时报告已经不在了。
      process.exitCode = preflightCode;
      return;
    }
    if (options.init || options.install) {
      process.stdout.write('初始化：\n');
      runInit(options, config);
      if (layout.modulesDir !== null) {
        // 装完就已经有一份完整的注册表：用户随后启动时 /api/modules 不会是空的。
        const synced = syncBundledManifests(layout.modulesDir, options.home);
        process.stdout.write(
          `  模块清单  ${synced.length === 0 ? '已是最新' : `已同步 ${synced.length} 个到 ${path.join(options.home, 'modules')}`}\n\n`,
        );
      }
    }
    // `--install --skip-plugins` 必须真的跳过：这条分支曾经无条件装插件，
    // 用户明确说"别碰我的 Claude 环境"却仍然被写，是最不该出现的那种越界。
    if (options.install && shouldInstallPlugins(options, layout, pluginReport)) {
      const outcome = await runPluginInstall(options, pluginReport);
      if (!outcome.ok) {
        process.stderr.write(renderPluginFailure(outcome));
        process.exitCode = EXIT_PLUGINS;
        return;
      }
      process.stdout.write('插件已就绪。\n\n');
    } else if (options.install) {
      const reason = options.skipPlugins ? '--skip-plugins' : '没有可安装的插件载荷';
      process.stdout.write(`插件：已跳过（${reason}）。\n\n`);
    }
    return;
  }

  if (preflightCode !== 0) {
    // 失败路径的报告走 stderr：它和真正的日志属于同一个流，重定向时不会分家。
    process.stderr.write(report);
    process.exitCode = preflightCode;
    return;
  }

  // 插件阶段发生在任何模块进程出现之前：失败时没有进程要回收，直接退出 12。
  if (shouldInstallPlugins(options, layout, pluginReport)) {
    const outcome = await runPluginInstall(options, pluginReport);
    if (!outcome.ok) {
      process.stderr.write(renderPluginFailure(outcome));
      process.exitCode = EXIT_PLUGINS;
      return;
    }
  }

  const loader = resolveTsxLoader(layout.appDir);
  const env = buildChildEnv(options, layout.webDir);

  // 模块清单必须在服务端启动**之前**同步：注册表只从 `$COSIGHT_HOME/modules` 读，
  // 干净机器上那里是空的，晚一步 `/api/modules` 就会先返回一份空列表。
  // `--no-modules` 也同步——它关掉的是"拉起进程"，不是"模块出现在注册表里"。
  const synced = layout.modulesDir === null
    ? []
    : syncBundledManifests(layout.modulesDir, options.home);

  const external = externalUrls(options.host, options.port);
  process.stdout.write(
    [
      'Co-Sight Harness',
      `  Node      ${detailOf(results, 'node')}`,
      `  布局      ${layout.mode}（服务端 ${layout.appDir}）`,
      `  前端产物  ${layout.webDir ?? '（未指定，仅提供 API）'}`,
      `  数据目录  ${options.home}`,
      `  配置      ${config.disabled ? '（--no-config 已关闭）' : config.exists ? `${config.filePath}（生效 ${config.applied.length} 条）` : `${config.filePath}（不存在）`}`,
      `  模块      ${moduleReport.line}`,
      `  插件      ${pluginReport.line}`,
      `  监听      ${options.host}:${options.port}`,
      `  打开      ${baseUrl}/`,
      ...(external.length > 0 ? [`  外部访问  ${external.join('  ')}`] : []),
      `  接口文档  ${baseUrl}/api/docs`,
      '',
    ].join('\n'),
  );

  if (synced.length > 0) {
    process.stdout.write(`  模块清单  已同步 ${synced.length} 个到 ${path.join(options.home, 'modules')}\n\n`);
  }

  // 启动顺序：立即可起的模块 → 框架 → 声明了 startAfter 的模块。
  // 后者要回调框架（读工作区、读模型配置），框架没就绪时它们会启动失败，
  // 而失败信息看起来像模块自己的错。
  const { immediate: allImmediate, deferred: allDeferred } = partitionPlans(moduleReport.plans);

  // `--skip-module` 只影响"拉不拉起进程"，模块仍留在注册表里：
  // 前端能看到它、也能说明它为什么不在线。
  const skip = new Set(options.skipModules);
  const known = new Set([...allImmediate, ...allDeferred].map((plan) => plan.id));
  const unknown = [...skip].filter((id) => !known.has(id));
  if (unknown.length > 0) {
    process.stderr.write(`! --skip-module 没有匹配到模块：${unknown.join('、')}\n`);
  }
  const skipped = [...skip].filter((id) => known.has(id));
  if (skipped.length > 0) {
    process.stdout.write(`  跳过模块  ${skipped.join('、')}（--skip-module）\n`);
  }
  const immediate = allImmediate.filter((plan) => !skip.has(plan.id));
  const deferred = allDeferred.filter((plan) => !skip.has(plan.id));

  // entries 的顺序就是启动顺序，superviseAll 按逆序停。
  //
  // 监督在**第一个子进程出现之前**就装上：模块起不来时清理路径与运行期完全一致，
  // 不会出现"启动失败但已起的模块留在后台"。
  const entries = [];
  const supervision = superviseAll(entries);

  const failStart = async (stage, reason, remedy = []) => {
    process.stderr.write(
      renderStartFailure({
        stage,
        reason,
        remedy:
          remedy.length > 0
            ? remedy
            : [
                '看上面该模块 / 服务端的日志，修好后重跑启动脚本',
                '只是排查时想先看其余模块，可加 --keep-going',
                '不想要这个模块，可加 --skip-module <id>',
              ],
        impact: '启动中止；已经起来的进程已按逆序停止，退出码 13',
      }),
    );
    await supervision.stopAll(EXIT_START);
  };

  // 端口先试绑一次：绑不上时服务端只会打印一大段栈，而这里能直接说清楚。
  const portState = await checkTcpBind(options.host, options.port);
  if (!portState.ok) {
    await failStart('端口检查', `${options.host}:${options.port} ${portState.detail}`, [
      '换一个端口：--port <n>，或设置 COSIGHT_PORT',
      `查占用：lsof -i :${options.port}（Windows：netstat -ano | findstr :${options.port}）`,
    ]);
    return;
  }

  const immediateResult = await startModules(immediate, entries, '启动模块', {
    keepGoing: options.keepGoing,
    isStopping: supervision.isStopping,
  });
  // 收尾已经开始：不再往下走。停止流程会在自己那里打印结果并退出，
  // 这里再报一次"启动失败"只会误导用户以为自己点错了。
  if (immediateResult.aborted) {
    return;
  }
  if (!immediateResult.ok && !options.keepGoing) {
    await failStart(
      '模块启动',
      immediateResult.failures.map((item) => `${item.module}：${item.label} ${item.detail}`).join('\n'),
    );
    return;
  }
  if (!immediateResult.ok) {
    process.stderr.write(
      `! ${immediateResult.failures.length} 个模块没有起来（--keep-going），框架会继续启动\n`,
    );
  }

  const serverChild = spawn(process.execPath, ['--import', loader, path.join(layout.appDir, 'src', 'index.ts')], {
    cwd: layout.appDir,
    env,
    // detached：superviseAll 靠负 PID 回收整个进程组，非 detached 的子进程
    // 与父进程同组，负 PID 会误伤父进程自己。
    detached: true,
    // 不能用 `stdio: 'inherit'`：Windows 上新起的独立进程组拿不到可用的控制台句柄，
    // 服务端第一次写日志就 EBADF、以退出码 1 结束，而且**一个字都打不出来**——
    // 表现为"服务进程在就绪前退出（退出码 1），日志见上方"，而上方是空的。
    // 走管道再 `forwardVerbatim` 原样转发：日志依旧是日志，只是换成父进程代写。
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  entries.push({ label: '框架服务', child: serverChild });
  // 原样转发（不加 `[框架服务]` 前缀）：用户看到的就是服务端自己打的那份日志。
  forwardVerbatim(serverChild);

  // 就绪之前退出是"启动失败"，之后退出是"运行期结束"：两者退出码不同。
  let frameworkReady = false;
  // 'error' 之后必然还会收到 'exit'；只报一次，别让用户看到两段一样的失败。
  let fatalReported = false;

  serverChild.on('error', (error) => {
    fatalReported = true;
    process.stderr.write(
      renderStartFailure({
        stage: '框架服务',
        reason: `无法启动进程：${error.message}`,
        remedy: ['确认 --app-dir 指向的服务端目录里有 src/index.ts', '看上面的日志'],
        impact: '启动中止；已经起来的模块已停止，退出码 13',
      }),
    );
    void supervision.stopAll(EXIT_START);
  });

  serverChild.on('exit', (code, signal) => {
    if (fatalReported) {
      return;
    }
    if (!frameworkReady) {
      /*
       * 不能说死"日志见上方"：服务进程可能在**跑到应用代码之前**就退出（入口加载
       * 失败、被本机安全软件拦下、Node 自己拒绝启动），那种情况上方一条日志都没有。
       * 两种情况混在一句话里，用户会以为是自己漏看了日志，然后无从下手。
       * 脚本这边只做原样转发、不统计字节数，所以两种都说，并给出一条能单独跑出
       * 真实报错的命令。
       */
      process.stderr.write(
        renderStartFailure({
          stage: '框架服务',
          reason: `服务进程在就绪前退出（${describeExit(code, signal)}）`,
          remedy: [
            '先看上面的服务端报错；若上方一条服务端日志都没有，说明它还没跑到应用代码，在产物目录手工跑这条能把真实报错打出来：',
            `"${process.execPath}" --import "${loader}" "${path.join(layout.appDir, 'src', 'index.ts')}"`,
            '配置问题检查 cosight.env 与 COSIGHT_* 环境变量；端口冲突可换 --port <n>',
            '手工跑能起来、经脚本起不来时，多半是本机安全软件拦了子进程，把两次输出都留给维护者',
          ],
          impact: '启动中止；已经起来的模块已停止，退出码 13',
        }),
      );
      void supervision.stopAll(EXIT_START);
      return;
    }
    if (signal !== null) {
      process.stderr.write(`服务进程被 ${signal} 终止\n`);
      void supervision.stopAll(1);
      return;
    }
    void supervision.stopAll(code ?? 0);
  });

  // 先等端口真的通了再报"已就绪"：直接打印 URL 而不等，用户点开是连接被拒，
  // 会误以为启动失败。
  const ready = await waitForHttpOk(`${baseUrl}/api/health`, { timeoutMs: READY_TIMEOUT_MS });
  if (!ready.ready) {
    await failStart(
      '框架就绪',
      `${READY_TIMEOUT_MS / 1000}s 内 ${baseUrl}/api/health 没有返回成功（${ready.attempts} 次探活，最后失败：${ready.lastError ?? '未知'}）`,
    );
    return;
  }
  frameworkReady = true;
  process.stdout.write(`\n已就绪，浏览器打开 ${baseUrl}/ （Ctrl-C 退出）\n`);
  if (external.length > 0) {
    process.stdout.write(`其他机器打开 ${external.join('、')}\n`);
  }
  process.stdout.write('\n');

  // 框架就绪之后才起 startAfter=framework 的模块。
  if (deferred.length > 0) {
    const deferredResult = await startModules(deferred, entries, '启动依赖框架的模块', {
      keepGoing: options.keepGoing,
      isStopping: supervision.isStopping,
    });
    if (deferredResult.aborted) {
      return;
    }
    if (!deferredResult.ok && !options.keepGoing) {
      await failStart(
        '依赖框架的模块',
        deferredResult.failures.map((item) => `${item.module}：${item.label} ${item.detail}`).join('\n'),
      );
      return;
    }
    if (!deferredResult.ok) {
      process.stderr.write(
        `! ${deferredResult.failures.length} 个依赖框架的模块没有起来（--keep-going）\n`,
      );
    }
  }

  await reportModules(options.home, moduleReport.platformSkips);
}

main().catch((error) => {
  process.stderr.write(`启动失败：${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});

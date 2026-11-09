/**
 * 仓库布局与产物命名的唯一出处。
 *
 * 打包脚本和冒烟脚本都要知道"产物叫什么、放在哪、里面该有什么"，
 * 这些一旦分散在两处，就会出现"打包改了名字、冒烟还在找旧名字"这种
 * 只在跑冒烟时才暴露的错位。所以集中在这里。
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { SUPPORTED_PLATFORMS } from './preflight.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));

/** 仓库根目录（本文件是 framework/scripts/lib/project.mjs）。 */
export const REPO_ROOT = path.resolve(here, '..', '..', '..');

/**
 * 框架模块根目录（`framework/`）。服务端、前端、脚本、文档都收在它下面。
 *
 * 与 REPO_ROOT 分开是必要的：本文件被两类路径同时用到，而它们在目录改造后分了家——
 * `.package/` 与根 package.json 在仓库根（工作区根必须留在那里），
 * 而 `server/`、`web/`、`scripts/` 已经沉到模块里。混用一个根只会得到其中一个错答案。
 */
export const MODULE_ROOT = path.resolve(here, '..', '..');

/**
 * 产物前缀。刻意不用根 package.json 的 name（`cosight-harness-framework`）：
 * 那是仓库名，而这份产物是交付给使用者的产品包，用产品名更短也更好认。
 */
export const ARTIFACT_SLUG = 'cosight-harness';

/**
 * 打包中间物与产物的落盘目录（已随 .gitignore 忽略）。
 *
 * **必须落在仓库内**，不能换到 `/tmp` 之类的地方。pnpm 把依赖装进 node_modules 时优先走硬链接
 * （这就是它的 store 机制省钱的地方），而硬链接不能跨文件系统——本仓库与 `/tmp` 在实测环境里
 * 是两个设备（`stat -c %d`：64529 vs 64768），`ln` 会直接报 `EXDEV: 无效的跨设备链接`。
 * pnpm 遇到这种情况只能退回复制，等于把整棵依赖树重新写一遍。
 */
export const PACKAGE_DIR = path.join(REPO_ROOT, '.package');
/** `pnpm deploy` 的产出：服务端的生产依赖树。 */
export const STAGING_DIR = path.join(PACKAGE_DIR, 'staging');

export const SERVER_DIR = path.join(MODULE_ROOT, 'server');
export const WEB_DIST_DIR = path.join(MODULE_ROOT, 'web', 'dist');

export function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

/**
 * 产物版本取**仓库根** package.json 的 version。
 *
 * 理由：产物是"框架整体"的交付物，里面同时含服务端与前端，而前端没有独立
 * 的对外版本；用根版本号表达"这一整份框架是哪个版本"。harness-server 自身的
 * 版本另在产物 README 里列明，便于回溯。
 */
export function readVersion() {
  return readJson(path.join(REPO_ROOT, 'package.json')).version;
}

/**
 * 产物名里的时间戳，形如 `20261026-143015`（本地时间）。
 *
 * 文件名带时间戳是为了让同版本的多份构建**不会互相覆盖**：`.package/` 里
 * 留着的上一份产物既是回滚点，也是"两个构建差在哪"的对照物。
 * 时间戳会同时进入归档内的顶层目录名（两者共用 `artifactBaseName`），
 * 因此把多份产物解压到同一处也不会互相串。
 */
export function artifactTimestamp(date = new Date()) {
  return (
    `${date.getFullYear()}${pad2(date.getMonth() + 1)}${pad2(date.getDate())}` +
    `-${pad2(date.getHours())}${pad2(date.getMinutes())}${pad2(date.getSeconds())}`
  );
}

/** 两位补零：时间戳要能按字符串排序，`20261026-9305` 这种一定会在排序上出错。 */
function pad2(value) {
  return String(value).padStart(2, '0');
}

/**
 * 归档文件名与其中的顶层目录名共用同一个串，避免两者不一致。
 *
 * `stamp` 为空时保持旧的无时间戳形式，这是给"按版本号找产物"的调用方
 * （测试、历史路径）留的稳定入口；正式打包一律传时间戳。
 */
export function artifactBaseName(version = readVersion(), stamp = '') {
  return stamp === '' ? `${ARTIFACT_SLUG}-${version}` : `${ARTIFACT_SLUG}-${version}-${stamp}`;
}

export function artifactPaths(version = readVersion(), stamp = '') {
  const base = artifactBaseName(version, stamp);
  return {
    base,
    tarball: path.join(PACKAGE_DIR, `${base}.tar.gz`),
    zip: path.join(PACKAGE_DIR, `${base}.zip`),
  };
}

/**
 * 找出 `.package/` 里**最新一份**产物的 base 名。
 *
 * 带时间戳之后，冒烟不能再"照着版本号再算一次名字"——那样只会指向一个
 * 从未写出的路径。以 manifest 的 mtime 为准，是因为 manifest 与归档在
 * 同一次打包里写出，且 `--skip-package` 复用的也是它。
 *
 * 找不到任何 manifest 时回落到无时间戳名，让调用方的报错仍然指向
 * "先跑一次打包"，而不是在这里抛一个更难懂的错。
 */
export function latestArtifactBase() {
  if (!fs.existsSync(PACKAGE_DIR)) {
    return artifactBaseName();
  }

  const suffix = '.manifest.txt';
  const newest = fs
    .readdirSync(PACKAGE_DIR)
    .filter((name) => name.startsWith(`${ARTIFACT_SLUG}-`) && name.endsWith(suffix))
    .map((name) => ({ name, mtime: fs.statSync(path.join(PACKAGE_DIR, name)).mtimeMs }))
    .toSorted((left, right) => right.mtime - left.mtime)[0];

  return newest === undefined ? artifactBaseName() : newest.name.slice(0, -suffix.length);
}

/**
 * 归档内布局：顶层目录 / server（服务端运行时包）/ web（前端静态产物）/ 用户侧的脚本。
 *
 * 脚本类条目（安装、启动、配置模板）都是**从 `framework/scripts/artifact/` 原样复制**的，
 * 与 `start.mjs` 同一个口径：产物里放的永远是仓库那份的拷贝，不存在"打包时另写一版"。
 */
export const ARTIFACT_LAYOUT = {
  serverSubdir: 'server',
  webSubdir: 'web',
  /**
   * 模块位：每个进包的模块占一个 `modules/<id>/`，里面自带运行时契约
   * （`module.json`）与装配态启动清单（`artifact.json`）。`start.mjs` 扫这个目录
   * 把模块拉起来；仓库布局下没有它，因此开发态行为不变（D27）。
   */
  modulesSubdir: 'modules',
  /**
   * 插件载荷：五个 Claude Code 插件的源码目录 + 生成的 `index.json`。
   *
   * 放进产物是为了"离线可装"：用户机器上不需要再访问 marketplaces，也不需要在
   * 仓库里额外拉五个仓库。`index.json` 带内容哈希，运行期据此判断要不要重装。
   */
  pluginsSubdir: 'plugins',
  /** 启动入口文件名，落在归档顶层。 */
  entryFile: 'start.mjs',
  readmeFile: 'README.md',
  /** 一次性安装脚本：预检 Node、建数据目录、生成配置。两个平台各一份。 */
  installSh: 'install.sh',
  installCmd: 'install.cmd',
  /**
   * 一次性卸载脚本：把五个插件从 Claude Code 里摘掉（可选连数据目录一起删）。
   *
   * 必须有，而且必须和安装对称：安装会往 `~/.claude` 写五个市场与五个插件注册，
   * 这些都不在产物目录里，"删解压目录即卸载"只对了一半。
   */
  uninstallSh: 'uninstall.sh',
  uninstallCmd: 'uninstall.cmd',
  /** 启动薄壳：只负责把参数转给 start.mjs，配置解析一律在 Node 里做。 */
  startSh: 'start.sh',
  startCmd: 'start.cmd',
  /**
   * 配置模板。**两个平台共用同一份**，是纯 `KEY=VALUE` 文本、由 `start.mjs` 解析。
   * 不写成 `export K=V` 与 `set K=V` 两种——那样同一份配置在两个平台语义不同，
   * 是这类交付物最容易长出来的分歧。
   */
  envExample: 'cosight.env.example',
  /** 上述脚本在源码仓库里的真源目录（相对 `MODULE_ROOT`）。 */
  scriptSourceDir: path.join('scripts', 'artifact'),
};

/**
 * 产物覆盖的平台。
 *
 * 一份通用包同时带两个平台的原生件，而不是按平台出两份包：分发时不会"发错包"，
 * 代价是体积（实测约 +15–20MB，见 `docs/packaging.md`）。
 */
export const ARTIFACT_TARGETS = SUPPORTED_PLATFORMS;

/**
 * 每个平台在依赖树里**必须存在**的原生件。
 *
 * 这两个包都不是直接依赖，而是上游的 `optionalDependencies`——npm/pnpm 默认只装当前平台那一份。
 * 在打包机上"看起来一切正常"，到了别的平台就是启动即崩的 `ERR_MODULE_NOT_FOUND`，
 * 所以这份映射是打包期断言的依据，也是 `docs/packaging.md` 里那张表的真源。
 *
 * 名字的来历（不是随手编的）：
 *  - `@libsql/*`：`libsql/index.js` 用 `@neon-rs/load` 的 `currentTarget()` 拼出 `<平台>-<架构>-<ABI>`
 *    再 `require('@libsql/' + target)`；其实现里 `win32 + x64` 返回的正是 `win32-x64-msvc`。
 *  - `@esbuild/*`：esbuild 按平台取名（tsx 的转译器就是它），Windows 上是 `win32-x64`。
 */
const NATIVE_PACKAGES_BY_TARGET = {
  'linux-x64': ['@libsql/linux-x64-gnu', '@esbuild/linux-x64'],
  'win32-x64': ['@libsql/win32-x64-msvc', '@esbuild/win32-x64'],
};

/** 展开成"依赖树里必须存在的包名"清单（去重，保持稳定顺序）。 */
export function nativePackagesFor(targets = ARTIFACT_TARGETS) {
  const names = new Set();
  for (const target of targets) {
    const packages = NATIVE_PACKAGES_BY_TARGET[target];
    if (packages === undefined) {
      throw new Error(`未知的产物平台 ${target}。可用的有：${Object.keys(NATIVE_PACKAGES_BY_TARGET).join(', ')}`);
    }
    for (const name of packages) {
      names.add(name);
    }
  }
  return [...names];
}

/**
 * 把平台目标翻译成 pnpm 的安装参数。
 *
 * 为什么是 `--os` / `--cpu` 而不是写成配置项：pnpm 11 的这几个旗标会直接改写
 * `supportedArchitectures`（源码 `overrideSupportedArchitecturesWithCLI`），
 * 而写成 `pnpm-workspace.yaml` 里的配置会**连开发态的安装一起改**——
 * 本仓库的 `node_modules` 就要多背两个平台的可选依赖。旗标只作用在这一条命令上。
 *
 * `--os` 可以重复给，就是数组的意思（实测：给了 linux 与 win32，两份原生件都进了树）。
 */
export function deployPlatformArgs(targets = ARTIFACT_TARGETS) {
  const args = [];
  for (const target of targets) {
    const [os, cpu] = target.split('-');
    if (os === undefined || cpu === undefined) {
      throw new Error(`平台目标要写成 <os>-<cpu>，收到 ${target}`);
    }
    args.push(`--os=${os}`, `--cpu=${cpu}`);
  }
  return args;
}

/**
 * 产物内启动入口必须可执行：解压后直接 `./start.mjs` 就能跑，
 * 不需要用户再 chmod——这是"交付物"和"源代码"的区别。
 */
export const ENTRY_FILE_MODE = 0o755;

/**
 * `start.mjs` 及其内部模块的搬运清单：产物内相对路径 →（仓库 `scripts/` 之下的）源码路径。
 *
 * 这份清单**必须与 `start.mjs` 的 import 保持同步**，而这是打包脚本最容易漏的地方：
 * 少搬一个 lib 文件时，**本机什么都不会报**——`start.mjs` 在仓库里跑得好好的，
 * 用户解压后第一句话才是 `ERR_MODULE_NOT_FOUND`。所以它放在这里有三个理由：
 *   1. 是唯一真相：`package.mjs` 的搬运与 `REQUIRED_PATHS` 读回校验都由它派生；
 *   2. `executable` 决定权限位（入口 0755，内部模块 0644）；
 *   3. `tests/entry-imports.test.mjs` 沿着 `start.mjs` 的 import 走一遍，逐一要求
 *      它们在这里出现——靠"记得加一行"，迟早会漏。
 */
export const ENTRY_SCRIPT_SOURCES = [
  { relative: ARTIFACT_LAYOUT.entryFile, source: ARTIFACT_LAYOUT.entryFile, executable: true },
  { relative: 'lib/runtime.mjs', source: 'lib/runtime.mjs' },
  { relative: 'lib/module-probe.mjs', source: 'lib/module-probe.mjs' },
  { relative: 'lib/env-file.mjs', source: 'lib/env-file.mjs' },
  { relative: 'lib/node-version.mjs', source: 'lib/node-version.mjs' },
  { relative: 'lib/text.mjs', source: 'lib/text.mjs' },
  // 装配态模块清单的读取与校验。它只在产物布局下被用到（`modules/` 不存在时
  // 扫描结果为空），但 import 是静态的——少搬这一个文件，产物里的 `start.mjs`
  // 连启动都做不到，本机却毫无征兆。
  { relative: 'lib/artifact-spec.mjs', source: 'lib/artifact-spec.mjs' },
  // 前置检查：骨架 + 每类检查一个文件。同样的道理——全部是静态 import。
  { relative: 'lib/preflight.mjs', source: 'lib/preflight.mjs' },
  { relative: 'lib/checks/platform.mjs', source: 'lib/checks/platform.mjs' },
  { relative: 'lib/checks/node.mjs', source: 'lib/checks/node.mjs' },
  { relative: 'lib/checks/env.mjs', source: 'lib/checks/env.mjs' },
  { relative: 'lib/checks/modules.mjs', source: 'lib/checks/modules.mjs' },
  // Claude Code / Python 3 / 插件载荷：启动前必须先过这几关，任何一个缺失都
  // 意味着插件装不进去，后面的模块启动没有意义。
  { relative: 'lib/cli-exec.mjs', source: 'lib/cli-exec.mjs' },
  { relative: 'lib/claude-cli.mjs', source: 'lib/claude-cli.mjs' },
  { relative: 'lib/checks/claude.mjs', source: 'lib/checks/claude.mjs' },
  { relative: 'lib/plugin-hash.mjs', source: 'lib/plugin-hash.mjs' },
  { relative: 'lib/plugin-index.mjs', source: 'lib/plugin-index.mjs' },
  { relative: 'lib/plugin-install.mjs', source: 'lib/plugin-install.mjs' },
  // 卸载（安装的逆操作）。同样是静态 import：`--uninstall` 在产物里跑不通时，
  // 用户已经删了插件却删不掉市场，只剩手敲十条命令这条路。
  { relative: 'lib/plugin-uninstall.mjs', source: 'lib/plugin-uninstall.mjs' },
  { relative: 'lib/checks/plugins.mjs', source: 'lib/checks/plugins.mjs' },
  // 数值格式化：启动链路（磁盘空间提示）也要用，而 project.mjs 不进产物。
  { relative: 'lib/format.mjs', source: 'lib/format.mjs' },
];

/**
 * 实现移到了 `lib/format.mjs`：产物里的 `start.mjs` 也需要它，
 * 而本文件不进产物。这里保留再导出，打包侧的既有 import 不必改。
 */
export { humanSize } from './format.mjs';

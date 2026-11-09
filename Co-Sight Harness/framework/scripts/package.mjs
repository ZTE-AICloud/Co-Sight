#!/usr/bin/env node
/**
 * Co-Sight Harness 打包（需求 2.5，决策 D29 = A：tar.gz 与 zip 双形态）。
 *
 * ── 运行时装配为什么选"自包含"而不是"首次启动再装"──────────────────────
 *
 * 服务端**没有 JS 产物**：它的 `build` 脚本只是 `tsc --noEmit`，跑起来的是
 * TypeScript 源码，靠 tsx 在运行时转换；`harness-shared` 同理（exports 直接
 * 指向 `src/*.ts`）。这意味着"打包"这一步必须连同**已解析好的依赖树**一起交付，
 * 否则拿到包的人还得先装一遍 pnpm 与依赖——那就不叫分发包了。
 *
 * 所以这里用 `pnpm deploy --filter harness-server --prod` 产出服务端的
 * 生产依赖树（workspace 依赖会被实体化进 node_modules，不依赖源仓库存在），
 * 再把 tsx 补进去（它是 devDependency，但服务端以源码形态运行、运行时离不开它）。
 * 结果是"解压即可 node start.mjs 运行"，代价是产物体积大——见 README 的说明。
 *
 * ── 为什么自己写归档而不是调 tar/zip 命令 ──────────────────────────────
 *
 *  1. 跨平台：Windows 上 `zip` 通常不存在，`tar` 的行为也随实现而异；
 *  2. **可校验**：写完之后在同一个进程里读回来，逐条比对必需路径。
 *     "产出一个看起来正常的坏包"是本任务最坏的失败模式，读回校验是唯一的防线。
 *     系统 tar/unzip 的独立交叉验证放在 smoke-package.mjs 里。
 *
 * ── 已知取舍 ──────────────────────────────────────────────────────────
 *
 *  - 归档条目顺序与 mtime 固定，同一份输入产出同一串字节（可复现）。
 *  - 不实现 ZIP64：产物总量远低于 4 GiB，越界时**报错退出**而不是静默写坏包。
 *
 * ── 一份包同时覆盖 linux-x64 与 win32-x64（决策 D40）─────────────────────
 *
 * 两处改动是这件事的关键，都不是"顺手加的旗标"：
 *
 *  1. `--os/--cpu` 让 deploy 把**两个平台的原生可选依赖**都装进来
 *     （libsql 的原生绑定、esbuild 的二进制）。只装当前平台的话，包里看着完好，
 *     Windows 用户启动即 `ERR_MODULE_NOT_FOUND`。为什么用命令行旗标而不是
 *     写进 `pnpm-workspace.yaml`：旗标只作用于这一条命令，开发态安装不受影响。
 *  2. `node-linker=hoisted` 把依赖树摊成**实体目录**。pnpm 默认的树由 230 个符号链接
 *     编织而成（实测数），而 Windows 自带解压器与 7-Zip 默认都不创建符号链接——
 *     解开就是一堆 0 字节文件，`start.mjs` 解析 tsx 时直接失败。
 *     摊平之后软链为 0，`start.cmd` 的注释里说的问题整类消失。
 *
 * 代价（实测）：比只带 linux-x64 多约 20MB 原生件；见 `docs/packaging.md`。
 */

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

import { withExecutableModes } from './lib/archive/executable-modes.mjs';
import { readTar, writeTarFile } from './lib/archive/tar.mjs';
import { readZip, writeZipFile } from './lib/archive/zip.mjs';
import { prepareModuleBundles } from './lib/artifact-modules.mjs';
import { renderArtifactReadme } from './lib/artifact-readme.mjs';
import { ARTIFACT_SCRIPTS, EXECUTABLE_ENTRIES, loadArtifactScript } from './lib/artifact-scripts.mjs';
import { buildSpawnSpec, resolveExecutable } from './lib/cli-exec.mjs';
import {
  ARTIFACT_LAYOUT,
  ARTIFACT_TARGETS,
  ENTRY_FILE_MODE,
  ENTRY_SCRIPT_SOURCES,
  MODULE_ROOT,
  PACKAGE_DIR,
  REPO_ROOT,
  SERVER_DIR,
  STAGING_DIR,
  WEB_DIST_DIR,
  artifactPaths,
  artifactTimestamp,
  deployPlatformArgs,
  humanSize,
  nativePackagesFor,
  readJson,
  readVersion,
} from './lib/project.mjs';
import { loadHostManifest, readPluginMetadata } from './lib/plugin-index.mjs';
import {
  hashPluginDirectory,
  hashPluginEntries,
  isExcludedPluginPath,
} from './lib/plugin-hash.mjs';
import { collectEntries, findEscapingSymlinks, removeIfExists } from './lib/walk.mjs';

/**
 * 打包时排除的路径。
 *
 * 排除标准：**运行期不可能被读到的东西**。测试、覆盖率报告、开发用的配置文件、
 * 以及 pnpm 的安装簿记文件（里面记着打包机器上的绝对路径——产物是要发给别人的，
 * 不该带着本机目录结构）。任何"可能被运行时读到"的都不排除。
 */
const PRUNE_PATTERNS = [
  /^(tests|coverage|docs)$/,
  /^(vitest|drizzle)\.config\.ts$/,
  // 产物交给别人使用，无需带上本机的 lockfile 与 workspace 定义。
  /^pnpm-(lock\.yaml|workspace\.yaml)$/,
  // pnpm 的安装簿记，内含打包机的绝对路径；运行期不读它。
  /^node_modules\/\.modules\.yaml$/,
  /^node_modules\/\.pnpm-workspace-state-v1\.json$/,
  /^node_modules\/\.pnpm\/lock\.yaml$/,
  // workspace 依赖（harness-shared）被实体化进来时连源码目录一起带了过来，
  // 其中的测试与覆盖率报告同样与运行无关。hoisted 布局下它就在 node_modules 顶层。
  /^node_modules\/harness-shared\/(coverage|docs|tests)(\/|$)/,
  /^node_modules\/harness-shared\/.*\.test\.(ts|js)$/,
  /^node_modules\/harness-shared\/vitest\.config\.ts$/,
];

function shouldPrune(relativePath) {
  return PRUNE_PATTERNS.some((pattern) => pattern.test(relativePath));
}

/**
 * 产物里必须存在的路径（相对产物根目录，调用方会补上顶层目录名）。
 * 缺任何一个都说明装配出了问题，这时**报错退出**，
 * 而不是产出一个"能解压但跑不起来"的包。
 *
 * 这份清单刻意覆盖三类：启动入口、服务端运行必需的源码与迁移、前端静态产物。
 */
const REQUIRED_PATHS = [
  ARTIFACT_LAYOUT.entryFile,
  ARTIFACT_LAYOUT.readmeFile,
  ARTIFACT_LAYOUT.installSh,
  ARTIFACT_LAYOUT.installCmd,
  ARTIFACT_LAYOUT.uninstallSh,
  ARTIFACT_LAYOUT.uninstallCmd,
  ARTIFACT_LAYOUT.startSh,
  ARTIFACT_LAYOUT.startCmd,
  ARTIFACT_LAYOUT.envExample,
  // 入口与它依赖的内部模块：清单来自 lib/project.mjs 的唯一真相，
  // 那里由测试沿着 start.mjs 的 import 逐一核对（见 tests/entry-imports.test.mjs）。
  ...ENTRY_SCRIPT_SOURCES.map((entry) => entry.relative),
  `${ARTIFACT_LAYOUT.serverSubdir}/package.json`,
  `${ARTIFACT_LAYOUT.serverSubdir}/tsconfig.json`,
  // server/tsconfig.json 里 extends 的是 ../tsconfig.base.json；产物内必须自带这份基座，
  // 否则解压后的 extends 指向不存在的路径（当前 tsx 只是忽略它，但那是运气不是保证）。
  `${ARTIFACT_LAYOUT.serverSubdir}/tsconfig.base.json`,
  `${ARTIFACT_LAYOUT.serverSubdir}/src/index.ts`,
  `${ARTIFACT_LAYOUT.serverSubdir}/src/app.ts`,
  `${ARTIFACT_LAYOUT.serverSubdir}/src/config/env.ts`,
  `${ARTIFACT_LAYOUT.serverSubdir}/drizzle/meta/_journal.json`,
  `${ARTIFACT_LAYOUT.webSubdir}/index.html`,
];

/**
 * 必须**以实体文件**存在的依赖入口（不是符号链接，见下面"零软链"那一类断言）。
 *
 * 这几个是运行时的关键依赖入口：tsx（加载 TS 源码，服务端跑的是源码）、
 * harness-shared（契约的真相）、fastify（主框架）、libsql（原生绑定）。
 *
 * 断言实体文件而不是"目录看着在"：解压器丢软链之后目录会变成 0 字节占位文件，
 * 路径照样存在，但 `--import <tsx loader>` 会失败。要点到 package.json 这一层，
 * 才能真正区分"实体目录"与"占位文件"。
 */
const REQUIRED_PACKAGE_FILES = [
  `${ARTIFACT_LAYOUT.serverSubdir}/node_modules/tsx`,
  `${ARTIFACT_LAYOUT.serverSubdir}/node_modules/harness-shared`,
  `${ARTIFACT_LAYOUT.serverSubdir}/node_modules/fastify`,
  `${ARTIFACT_LAYOUT.serverSubdir}/node_modules/@libsql/client`,
].map((relative) => `${relative}/package.json`);

/**
 * 把 pnpm 解析成真实可执行文件路径。
 *
 * 不能把裸名字 `'pnpm'` 交给 spawnSync：Windows 上它实际是 `pnpm.cmd`，
 * 而 Node 22（CVE-2024-27980 修复之后）在 `shell: false` 下既不按名字补
 * `.cmd`（ENOENT），也不允许直接执行 `.cmd`（EINVAL）。先按 PATHEXT 找到
 * 实体文件，再由 `buildSpawnSpec` 拼成 `cmd.exe /d /s /c "…"`——与仓库里
 * 调用 claude / python 走的是同一套规则，不再维护第二份 Windows 分支。
 *
 * @returns {string}
 */
function resolvePnpm() {
  const resolved = resolveExecutable('pnpm');
  if (resolved.path === null) {
    throw new Error('找不到 pnpm。打包需要它来解析生产依赖树（pnpm deploy）。');
  }
  return resolved.path;
}

function run(command, args, options = {}) {
  const spec = buildSpawnSpec(command, args);
  const result = spawnSync(spec.command, spec.args, {
    cwd: options.cwd ?? REPO_ROOT,
    stdio: options.stdio ?? 'inherit',
    encoding: 'utf8',
    windowsVerbatimArguments: spec.windowsVerbatimArguments,
  });
  if (result.error) {
    throw new Error(`执行 ${command} 失败：${result.error.message}`);
  }
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} 退出码 ${result.status}`);
  }
  return result;
}

function requirePnpm() {
  const pnpm = resolvePnpm();
  const spec = buildSpawnSpec(pnpm, ['--version']);
  const probe = spawnSync(spec.command, spec.args, {
    encoding: 'utf8',
    windowsVerbatimArguments: spec.windowsVerbatimArguments,
  });
  if (probe.error || probe.status !== 0) {
    const detail = probe.error?.message ?? (probe.stderr ?? '').trim();
    throw new Error(`找不到 pnpm。打包需要它来解析生产依赖树（pnpm deploy）。${detail}`);
  }
  return probe.stdout.trim();
}

/** 前端静态产物必须先构建好：打包不负责替谁跑构建，但要在缺东西时立刻说清楚。 */
function requireWebDist() {
  const indexHtml = path.join(WEB_DIST_DIR, 'index.html');
  if (!fs.existsSync(indexHtml)) {
    throw new Error(
      `找不到 ${indexHtml}。请先在仓库根目录执行 \`pnpm build\` 构建前端，再打包。`,
    );
  }
}

/**
 * 递归列出目录下的所有符号链接（返回相对路径）。
 *
 * **不跟随链接本身**（`readdirSync` 的 `withFileTypes` 给的是 lstat 语义的结果），
 * 否则遇到 pnpm 那种互相指的链会绕不出来。只用于打包期断言，
 * 正常情况返回空数组。
 */
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

/**
 * deploy 之后立刻验依赖树的两条硬性质。
 *
 * 为什么不等归档写完再验：这两条一旦不成立，症状**只在别人机器上**出现
 * （缺 win32 原生件 → 用户启动即 ERR_MODULE_NOT_FOUND；软链 → Windows 解压成 0 字节文件）。
 * 在打包机上多花两秒走一遍目录，胜过事后拿一份"看起来正常"的包去排查。
 */
function assertStagingLayout() {
  const nodeModules = path.join(STAGING_DIR, 'node_modules');

  const missing = nativePackagesFor().filter(
    (name) => !fs.existsSync(path.join(nodeModules, name, 'package.json')),
  );
  if (missing.length > 0) {
    throw new Error(
      `依赖树里缺这些平台的原生件：${missing.join(', ')}\n` +
        '  它们只在别的平台的机器上被 require，缺了不影响本机打包，但用户装完起不来。\n' +
        `  请确认 deploy 命令带了 ${deployPlatformArgs().join(' ')}。`,
    );
  }

  const symlinks = findSymlinks(STAGING_DIR);
  if (symlinks.length > 0) {
    throw new Error(
      `依赖树里有 ${symlinks.length} 个符号链接，Windows 自带解压器与 7-Zip 不会创建它们：\n` +
        `  - ${symlinks.slice(0, 5).join('\n  - ')}\n` +
        '  请确认 deploy 命令带了 --config.node-linker=hoisted --config.preferSymlinkedExecutables=false。',
    );
  }
}

/**
 * 第一步：把服务端的生产依赖树落成一份自包含的目录。
 * 之后产物里的一切都从这份目录取材，源仓库是否还在都不影响产物内容。
 */
function deployServerRuntime(tsxVersion) {
  removeIfExists(STAGING_DIR);

  /**
   * 两条安装命令共用的安装参数。为什么每一项都在这里：
   *  - `node-linker=hoisted` + `preferSymlinkedExecutables=false`：要实体目录、零软链，
   *    这在 Windows 解压后是"能不能跑"的区别（见文件头的说明）。后者是必须的：
   *    摊平之后 `node_modules/.bin/` 里仍会留下 8 个软链（实测），关掉它才是 0。
   *  - `--os/--cpu`：把两个平台的原生件都装进来。**deploy 的安装步骤会沿用调用方的
   *    安装选项**（pnpm 的 deploy 实现最后就是走一次 install handler），所以这两个旗标
   *    对 deploy 生效；补装 tsx 那条命令是另一次安装，得单独再给一遍。
   *  - `minimumReleaseAge=0` 只给第二条：deploy 出来的 staging 不继承仓库根
   *    `pnpm-workspace.yaml` 里的放行名单，于是 pnpm 11 的供应链策略会以
   *    "fastify 发布不满最小天数"为由拒绝——即使装的就是仓库锁定的那个版本。
   *    这里不引入新的版本选择，因此关掉它不扩大风险面。
   */
  const installFlags = [
    '--config.node-linker=hoisted',
    '--config.preferSymlinkedExecutables=false',
    ...deployPlatformArgs(),
  ];

  process.stdout.write('→ pnpm deploy：解析服务端生产依赖树（含两个平台的原生件）…\n');
  const pnpm = resolvePnpm();
  run(pnpm, ['deploy', '--filter', 'harness-server', '--prod', ...installFlags, STAGING_DIR]);

  // tsx 是 devDependency，但服务端以 TS 源码运行，运行时必须有它。
  // 版本从 harness-server 的 package.json 读，与仓库里跑的那个保持同一个版本——
  // 写死一个版本号会让"仓库里能跑、产物里跑不了"变成一颗定时炸弹。
  process.stdout.write(`→ 补齐运行时加载器 tsx@${tsxVersion}…\n`);
  run(pnpm, [
    'add',
    `tsx@${tsxVersion}`,
    '--dir',
    STAGING_DIR,
    '--config.minimumReleaseAge=0',
    ...installFlags,
  ]);

  // deploy 写下的 workspace 依赖是"源仓库绝对路径"形式的 spec（`harness-shared@file:///home/...`）。
  // 那既不是合法的 npm spec，也把打包机器的目录结构泄漏给了使用者。
  // 实体化后的依赖就在 node_modules/harness-shared，改成相对写法既准确又不带本机信息。
  const manifestPath = path.join(STAGING_DIR, 'package.json');
  const manifest = readJson(manifestPath);
  if (typeof manifest.dependencies?.['harness-shared'] === 'string') {
    manifest.dependencies['harness-shared'] = `file:./node_modules/harness-shared`;
    fs.writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  }

  // 让 server/tsconfig.json 的 `extends: "../tsconfig.base.json"` 在产物内也能解析。
  fs.copyFileSync(path.join(MODULE_ROOT, 'tsconfig.base.json'), path.join(STAGING_DIR, 'tsconfig.base.json'));
}

/**
 * 由脚本自身生成/搬运的条目（不是从依赖树里捡来的）。
 *
 * 入口与它依赖的内部模块、以及用户侧的四个脚本 + 配置模板，都**只有一份真相**：
 * 产物里放的是仓库那份的拷贝，不存在"打包时另写一版"的分叉。
 *
 * 这份拷贝清单必须与 start.mjs 的 import 保持同步——**这是打包脚本最容易漏的地方**：
 * 少搬一个 lib 文件，本机什么都不会报，用户解压后第一句话就是 ERR_MODULE_NOT_FOUND。
 * 所以除了这里列全，`REQUIRED_PATHS` 里还有一份独立清单在读回校验时兜底。
 */
/** 把一个仓库里的真实文件描述成归档条目：大小与内容都**从磁盘现读**，不在这里另写一份。 */
function fromDisk(relative, mode, source) {
  return {
    relative,
    mode,
    size: fs.statSync(source).size,
    read: () => fs.readFileSync(source),
  };
}

function generatedEntries(artifactBase, serverVersion, version) {
  const scriptsDir = path.join(MODULE_ROOT, 'scripts');
  const readme = renderArtifactReadme({
    version,
    serverVersion,
    artifactName: artifactBase,
  });

  const copied = ENTRY_SCRIPT_SOURCES.map((entry) =>
    fromDisk(
      entry.relative,
      entry.executable === true ? ENTRY_FILE_MODE : 0o644,
      path.join(scriptsDir, entry.source),
    ),
  );

  // 用户侧的脚本：行尾与编码在这里规整并校验（见 lib/artifact-scripts.mjs）。
  const scriptsSourceDir = path.join(MODULE_ROOT, ARTIFACT_LAYOUT.scriptSourceDir);
  const artifactScripts = ARTIFACT_SCRIPTS.map((spec) => ({
    relative: spec.name,
    ...loadArtifactScript(spec, scriptsSourceDir),
  }));

  return [
    ...[...copied, ...artifactScripts].map((item) => ({
      path: `${artifactBase}/${item.relative}`,
      kind: 'file',
      mode: item.mode,
      size: item.size,
      read: item.read,
    })),
    {
      path: `${artifactBase}/${ARTIFACT_LAYOUT.readmeFile}`,
      kind: 'file',
      mode: 0o644,
      size: Buffer.byteLength(readme, 'utf8'),
      read: () => Buffer.from(readme, 'utf8'),
    },
  ];
}

/**
 * 插件载荷：五个插件目录 + 生成的 `plugins/index.json`。
 *
 * 为什么版本与哈希在这里算、而不是抄进清单：`plugin.json` 是插件自己的真相，
 * 抄一份到我们的清单里，两边迟早不一致；而哈希必须覆盖**实际进包的那套文件**，
 * 所以它由复制规则现算（`collectPluginFiles` 与 `prune` 共用同一份排除规则）。
 *
 * 交叉校验（目录哈希 vs 归档条目哈希）是防"复制规则与哈希规则分叉"的闸门：
 * 分叉时包看着正常，但运行期每次启动都会判定内容变化、重复安装。
 */
function collectPluginPayload(artifactBase) {
  const manifestPath = path.join(MODULE_ROOT, ARTIFACT_LAYOUT.scriptSourceDir, 'plugins.json');
  const manifest = loadHostManifest(manifestPath);
  if (!manifest.ok) {
    throw new Error(`插件清单不可用：\n  - ${manifest.problems.join('\n  - ')}`);
  }

  const entries = [];
  const indexPlugins = [];
  const requiredPaths = [`${ARTIFACT_LAYOUT.pluginsSubdir}/index.json`];

  for (const item of manifest.plugins) {
    const pluginDir = path.join(REPO_ROOT, item.dir);
    if (!fs.existsSync(pluginDir)) {
      throw new Error(`插件清单里写了 ${item.dir}，但仓库里没有这个目录：${pluginDir}`);
    }

    const metadata = readPluginMetadata(pluginDir);
    if (!metadata.ok) {
      throw new Error(`插件 ${item.dir} 的清单不自洽：\n  - ${metadata.problems.join('\n  - ')}`);
    }
    if (metadata.plugin !== item.plugin || metadata.marketplace !== item.marketplace) {
      throw new Error(
        `插件 ${item.dir} 的坐标与清单不一致：` +
          `plugin.json 是 ${metadata.plugin}@${metadata.marketplace}，` +
          `plugins.json 写的是 ${item.plugin}@${item.marketplace}`,
      );
    }

    const prefix = `${artifactBase}/${ARTIFACT_LAYOUT.pluginsSubdir}/${item.dir}`;
    const pluginEntries = collectEntries(pluginDir, {
      prefix,
      prune: (relative) => isExcludedPluginPath(relative),
    });

    // 复制集必须与哈希集完全一致，否则运行期会永远"发现内容变了"。
    const expected = hashPluginDirectory(pluginDir);
    const packed = hashPluginEntries(pluginEntries, prefix);
    if (packed.sha256 !== expected.sha256 || packed.files !== expected.files) {
      throw new Error(
        `插件 ${item.dir} 的复制集与内容哈希不一致：` +
          `目录 ${expected.files} 个文件 / ${expected.sha256}，` +
          `条目 ${packed.files} 个文件 / ${packed.sha256}`,
      );
    }

    entries.push(...pluginEntries);
    requiredPaths.push(
      `${ARTIFACT_LAYOUT.pluginsSubdir}/${item.dir}/.claude-plugin/plugin.json`,
      `${ARTIFACT_LAYOUT.pluginsSubdir}/${item.dir}/.claude-plugin/marketplace.json`,
    );
    indexPlugins.push({
      id: item.dir,
      dir: item.dir,
      plugin: metadata.plugin,
      marketplace: metadata.marketplace,
      version: metadata.version,
      sha256: expected.sha256,
      files: expected.files,
      requires: item.requires,
    });
  }

  // 刻意保留清单里的顺序：它是安装顺序（drive → agent-genesis → …），
  // 不是展示顺序。JSON 输出本身是确定的，不需要再排一次。
  const text = `${JSON.stringify({ schemaVersion: 1, plugins: indexPlugins }, null, 2)}\n`;
  entries.push({
    path: `${artifactBase}/${ARTIFACT_LAYOUT.pluginsSubdir}/index.json`,
    kind: 'file',
    mode: 0o644,
    size: Buffer.byteLength(text, 'utf8'),
    read: () => Buffer.from(text, 'utf8'),
  });

  return { entries, requiredPaths, plugins: indexPlugins };
}

function assembleEntries(artifactBase, serverVersion, version, moduleEntries, pluginEntries) {
  const serverEntries = collectEntries(STAGING_DIR, {
    prefix: `${artifactBase}/${ARTIFACT_LAYOUT.serverSubdir}`,
    prune: (relative) => shouldPrune(relative),
  });
  const webEntries = collectEntries(WEB_DIST_DIR, {
    prefix: `${artifactBase}/${ARTIFACT_LAYOUT.webSubdir}`,
  });

  const all = [
    ...serverEntries,
    ...webEntries,
    ...moduleEntries,
    ...pluginEntries,
    ...generatedEntries(artifactBase, serverVersion, version),
  ];
  // 统一排序，父目录保证排在子项之前（解压器不必自行补建中间目录）。
  all.sort((left, right) => (left.path < right.path ? -1 : left.path > right.path ? 1 : 0));
  return all;
}

/**
 * 归档写完之后读回来：条目清单必须与源条目清单逐条一致，并且必需路径一个不少。
 * 这两条能抓住绝大多数"包看起来正常但缺东西"的问题。
 */
function verifyArchive(label, entries, requiredPaths, sourcePaths) {
  const archivePaths = new Set(entries.map((entry) => entry.path));

  const missing = requiredPaths.filter((required) => !archivePaths.has(required));
  if (missing.length > 0) {
    throw new Error(`${label} 缺少必需路径：\n  - ${missing.join('\n  - ')}`);
  }

  const missingFromReadback = sourcePaths.filter((item) => !archivePaths.has(item));
  if (missingFromReadback.length > 0) {
    throw new Error(
      `${label} 读回的条目比写入的少了 ${missingFromReadback.length} 条，` +
        `例如：${missingFromReadback.slice(0, 5).join(', ')}`,
    );
  }
}

async function main() {
  const version = readVersion();
  const serverVersion = readJson(path.join(SERVER_DIR, 'package.json')).version;
  const tsxVersion = readJson(path.join(SERVER_DIR, 'package.json')).devDependencies?.tsx;
  if (typeof tsxVersion !== 'string') {
    throw new Error('harness-server 的 devDependencies 里找不到 tsx，无法确定运行时加载器版本。');
  }

  const pnpmVersion = requirePnpm();
  requireWebDist();
  fs.mkdirSync(PACKAGE_DIR, { recursive: true });

  // 时间戳只取一次：归档名、顶层目录名、manifest 与产物 README 必须来自同一个串，
  // 各自调一次 `new Date()` 会在跨秒时得到两个不同的名字。
  const { base, tarball, zip } = artifactPaths(version, artifactTimestamp());

  deployServerRuntime(tsxVersion);
  assertStagingLayout();

  // 模块：判定（有没有 artifact 清单）→ 构建（dist 旧了才重建）→ 断言依赖 → 展开条目。
  // 这一步必须在组装条目之前：构建会改 dist 里的文件。
  process.stdout.write('→ 收集模块（docs/modules/*.artifact.json）…\n');
  const bundles = await prepareModuleBundles({
    modulesDocDir: path.join(MODULE_ROOT, 'docs', 'modules'),
    repoRoot: REPO_ROOT,
    artifactBase: base,
    modulesSubdir: ARTIFACT_LAYOUT.modulesSubdir,
    // 模块构建的中间文件（数据库模板等）只能落在打包脚本自己的临时区，
    // 绝不能写进模块源码树——那是同事维护的 checkout。
    stagingDir: path.join(PACKAGE_DIR, 'module-staging'),
    writeLine: (line) => process.stdout.write(`${line}\n`),
    // 缺件时按清单的 bundle.install 自动补齐。`--no-fix` 关掉它：
    // 离线 / 只读的打包机不该在打包中途突然开始联网装依赖。
    fix: !process.argv.includes('--no-fix'),
  });
  for (const item of bundles.builds) {
    process.stdout.write(`  ${item.id}：${item.detail}\n`);
  }
  for (const item of bundles.platforms) {
    // 一份包同时发 linux-x64 与 win32-x64，而模块可以只声明支持其中之一。
    // 不隐藏这件事：用户在其他平台上会看到模块被跳过，先在这里说清楚。
    if (item.platforms !== null && item.platforms.length < ARTIFACT_TARGETS.length) {
      process.stdout.write(`  ${item.id}：仅支持 ${item.platforms.join(' + ')}（其他平台启动时会跳过）\n`);
    }
  }
  if (bundles.unbundledIds.length > 0) {
    // 有运行时契约却没有装配态清单 = 这个模块不会进包。必须打印出来：
    // "怎么少了一个模块"在这之前只能靠翻文档猜。
    process.stdout.write(`  未打进产物（缺少 <id>.artifact.json）：${bundles.unbundledIds.join(', ')}\n`);
  }

  process.stdout.write('→ 收集插件载荷…\n');
  const payload = collectPluginPayload(base);
  process.stdout.write(
    `  ${payload.plugins.map((item) => `${item.plugin} ${item.version}`).join('、')}\n`,
  );

  process.stdout.write('→ 组装产物条目清单…\n');
  const entries = withExecutableModes(
    assembleEntries(base, serverVersion, version, bundles.entries, payload.entries),
    [...EXECUTABLE_ENTRIES, ...bundles.executablePaths].map((relative) => `${base}/${relative}`),
  );

  // 越界的符号链接必须在打包机上就发现：它在打包机上一切正常，
  // 到了别人机器上才是断链，而那时已经很难定位。
  const escapes = findEscapingSymlinks(entries);
  if (escapes.length > 0) {
    throw new Error(`产物内存在指向外部的符号链接，解压后会断链：\n  - ${escapes.join('\n  - ')}`);
  }

  const entryPaths = entries.map((entry) => entry.path);
  assertNoForbiddenPackages(entryPaths);

  // 清单留档：出问题时不必解压就能看到包里到底有什么。
  const manifestPath = path.join(PACKAGE_DIR, `${base}.manifest.txt`);
  fs.writeFileSync(manifestPath, `${entryPaths.join('\n')}\n`);

  const symlinkCount = entries.filter((entry) => entry.kind === 'symlink').length;
  const rawBytes = entries.reduce((sum, entry) => sum + (entry.kind === 'file' ? entry.size : 0), 0);
  process.stdout.write(
    `→ 条目 ${entries.length} 条（其中符号链接 ${symlinkCount} 条），原始大小 ${humanSize(rawBytes)}\n`,
  );

  process.stdout.write('→ 写 tar.gz…\n');
  const tarballSize = writeTarFile(entries, tarball);

  process.stdout.write('→ 写 zip…\n');
  const zipSize = writeZipFile(entries, zip);

  // 读回校验。tar 必须先 gunzip 再解析；zip 直接按字节解析。
  process.stdout.write('→ 读回校验…\n');
  const requiredPaths = [
    ...REQUIRED_PATHS,
    ...REQUIRED_PACKAGE_FILES,
    ...bundles.requiredPaths,
    ...payload.requiredPaths,
    ...nativePackagesFor().map((name) => `${ARTIFACT_LAYOUT.serverSubdir}/node_modules/${name}/package.json`),
  ].map((relative) => `${base}/${relative}`);

  for (const [label, archiveEntries] of [
    ['tar.gz', readTar(fs.readFileSync(tarball))],
    ['zip', readZip(fs.readFileSync(zip))],
  ]) {
    verifyArchive(label, archiveEntries, requiredPaths, entryPaths);
    assertZeroSymlinks(label, archiveEntries);
    assertExecutableEntries(label, archiveEntries, base, bundles.executablePaths);
  }

  process.stdout.write(
    [
      '',
      '打包完成：',
      `  ${path.relative(REPO_ROOT, tarball)}  ${humanSize(tarballSize)}`,
      `  ${path.relative(REPO_ROOT, zip)}  ${humanSize(zipSize)}`,
      `  条目清单  ${path.relative(REPO_ROOT, manifestPath)}`,
      `  版本      框架 ${version} / 服务端 ${serverVersion} / pnpm ${pnpmVersion}`,
      `  平台      ${ARTIFACT_TARGETS.join(' + ')}（原生件 ${nativePackagesFor().join(', ')}）`,
      `  模块      ${bundles.builds.length === 0 ? '（无）' : bundles.builds.map((item) => item.id).join(', ')}`,
      '',
    ].join('\n'),
  );
}

/**
 * 禁止进入发行物的专有包前缀。
 *
 * Claude Code CLI / Agent SDK 由用户在运行机自行安装并接受 Anthropic 条款；
 * 发行物里出现任何字节都违反开源合规要求。模块清单的 `bundle.exclude` 是第一道，
 * 这里是打包机上的最后一道：漏了 exclude 也直接失败，不产出坏包。
 */
const FORBIDDEN_PACKAGE_PREFIXES = ['node_modules/@anthropic-ai/'];

function assertNoForbiddenPackages(entryPaths) {
  const hits = entryPaths.filter((entry) =>
    FORBIDDEN_PACKAGE_PREFIXES.some((prefix) => entry.includes(prefix)),
  );
  if (hits.length > 0) {
    throw new Error(
      `产物里出现禁止分发的专有包（${hits.length} 条）：\n` +
        `  - ${hits.slice(0, 5).join('\n  - ')}\n` +
        '请在模块 artifact.json 的 bundle.exclude 里排除它们。',
    );
  }
}

/**
 * 归档里**一条符号链接都不该有**。
 *
 * 这是整套跨平台断言里最要紧的一条：符号链接在 Linux 上解压得好好的，
 * 在 Windows 上（自带解压器、7-Zip 的默认设置）会变成 0 字节文件——
 * 包能解开、目录看着也像样，服务端却起不来。宁可在打包机上报错，
 * 也不要让用户拿到一个"看起来正常"的坏包。
 */
function assertZeroSymlinks(label, entries) {
  const symlinks = entries.filter((entry) => entry.kind === 'symlink');
  if (symlinks.length > 0) {
    throw new Error(
      `${label} 里有 ${symlinks.length} 条符号链接（Windows 解压后会是 0 字节文件）：\n` +
        `  - ${symlinks.slice(0, 5).map((entry) => entry.path).join('\n  - ')}`,
    );
  }
}

/** 解压后要能直接运行的脚本必须带着可执行位。 */
function assertExecutableEntries(label, entries, base, extraRelative = []) {
  const byPath = new Map(entries.map((entry) => [entry.path, entry]));
  for (const relative of [...EXECUTABLE_ENTRIES, ...extraRelative]) {
    const entryPath = `${base}/${relative}`;
    const entry = byPath.get(entryPath);
    if (entry === undefined) {
      throw new Error(`${label} 里找不到 ${entryPath}`);
    }
    if ((entry.mode & 0o111) === 0) {
      throw new Error(
        `${label} 里的 ${entryPath} 丢了可执行位（mode=${entry.mode.toString(8)}），解压后无法直接运行。`,
      );
    }
  }
}

main().catch((error) => {
  // 打包失败必须带着一句话退出：这里的错（缺依赖、构建失败、清单写错）
  // 都是"去改某处再重来"，一屏栈没有那句话有用。
  process.stderr.write(`打包失败：${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});

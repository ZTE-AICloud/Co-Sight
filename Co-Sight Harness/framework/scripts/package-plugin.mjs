#!/usr/bin/env node
/**
 * 把 Claude Code 插件目录打成可交付的安装包（tar.gz + zip 双形态）。
 *
 * 为什么单独做一个脚本，而不是让使用方直接 `git clone`：
 *
 *  1. 插件目录里会混着 pipeline 的**运行期过程产物**（`work/`、`output/`、
 *     `.agent-genesis/`）与本机配置（`.claude/`、`.env`）。直接打包整个目录
 *     会把它们一起发出去；这里按"运行期不可能被读到"的口径排除。
 *  2. 归档根目录里需要**额外的装配件**（`install.sh` / `install.cmd` /
 *     `INSTALL.md`）。它们是包的一部分，不该写进插件团队的源码树，
 *     所以由本脚本在内存里生成后直接写进归档。
 *  3. 归档写完必须**读回来校验**：条目一条不少、必需文件齐全、没有符号链接、
 *     安装脚本带着可执行位。"看起来正常但缺东西的包"是这类任务最坏的失败模式。
 *
 * 用法：
 *   node framework/scripts/package-plugin.mjs                 # 默认打包 agent-genesis
 *   node framework/scripts/package-plugin.mjs --plugin drive  # 打别的插件目录
 *   node framework/scripts/package-plugin.mjs --out /tmp/out  # 换产物目录
 *   node framework/scripts/package-plugin.mjs --help
 *
 * 本脚本**不修改插件源码**：根 package.json 里的 `package:plugin` 只是入口，
 * 插件目录（agent-genesis/ 等）由各自的团队维护。
 */

import fs from 'node:fs';
import path from 'node:path';

import { readTar, writeTarFile } from './lib/archive/tar.mjs';
import { readZip, writeZipFile } from './lib/archive/zip.mjs';
import {
  buildCompatibleManifest,
  declaredPluginPaths,
  executablePluginPaths,
  generatedPluginEntries,
  isExcluded,
  manifestCompatAdjustments,
  manifestOverrideEntry,
  pluginArchivePaths,
  readPluginMetadata,
} from './lib/plugin-package.mjs';
import { PACKAGE_DIR, REPO_ROOT, humanSize } from './lib/project.mjs';
import { collectEntries } from './lib/walk.mjs';

const DEFAULT_PLUGIN = 'agent-genesis';

function usage() {
  return [
    '用法：node framework/scripts/package-plugin.mjs [选项]',
    '',
    `  --plugin <目录|名字>  插件目录（相对仓库根）；默认 ${DEFAULT_PLUGIN}`,
    '  --out <目录>          产物目录；默认 .package/',
    '  --compat-manifest     在**包内**修正与当前 Claude Code 发现规则冲突的清单字段',
    '                        （源码不动；改了哪些会在输出与 INSTALL.md 里写明）',
    '  --help                显示本帮助',
    '',
  ].join('\n');
}

function parseArgs(argv) {
  let plugin = DEFAULT_PLUGIN;
  let outDir = PACKAGE_DIR;
  let compatManifest = false;

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--help' || arg === '-h') {
      process.stdout.write(usage());
      process.exit(0);
    } else if (arg === '--compat-manifest') {
      compatManifest = true;
    } else if (arg === '--plugin') {
      plugin = argv[index + 1] ?? '';
      index += 1;
    } else if (arg.startsWith('--plugin=')) {
      plugin = arg.slice('--plugin='.length);
    } else if (arg === '--out') {
      outDir = argv[index + 1] ?? '';
      index += 1;
    } else if (arg.startsWith('--out=')) {
      outDir = arg.slice('--out='.length);
    } else {
      throw new Error(`未知参数：${arg}\n\n${usage()}`);
    }
  }

  if (plugin.trim() === '') {
    throw new Error('--plugin 不能为空');
  }
  if (outDir.trim() === '') {
    throw new Error('--out 不能为空');
  }

  return {
    pluginDir: path.resolve(path.isAbsolute(plugin) ? plugin : path.join(REPO_ROOT, plugin)),
    outDir: path.resolve(outDir),
    compatManifest,
  };
}

/**
 * 归档写完之后读回来，逐条比对。
 *
 * 两类断言都必须过：**条目集合完全相等**（多一条说明排除规则漏了，少一条说明
 * 打包丢了东西），以及必需路径与可执行位齐全。少一条的包解压后才发现，
 * 那时已经离打包现场很远了。
 *
 * @param {string} label `tar.gz` 或 `zip`
 * @param {Array<{path: string, kind: string, mode: number}>} archiveEntries
 * @param {Set<string>} expectedPaths
 * @param {string[]} requiredPaths
 * @param {string[]} executablePaths
 */
function verifyArchive(label, archiveEntries, expectedPaths, requiredPaths, executablePaths) {
  const actual = new Map(archiveEntries.map((entry) => [entry.path, entry]));

  const missing = [...expectedPaths].filter((item) => !actual.has(item));
  if (missing.length > 0) {
    throw new Error(
      `${label} 读回的条目比写入的少了 ${missing.length} 条，例如：\n  - ${missing.slice(0, 5).join('\n  - ')}`,
    );
  }

  const unexpected = [...actual.keys()].filter((item) => !expectedPaths.has(item));
  if (unexpected.length > 0) {
    throw new Error(`${label} 里多出了不该有的条目：\n  - ${unexpected.slice(0, 5).join('\n  - ')}`);
  }

  const missingRequired = requiredPaths.filter((item) => !actual.has(item));
  if (missingRequired.length > 0) {
    throw new Error(`${label} 缺少必需路径：\n  - ${missingRequired.join('\n  - ')}`);
  }

  const symlinks = archiveEntries.filter((entry) => entry.kind === 'symlink');
  if (symlinks.length > 0) {
    throw new Error(
      `${label} 里有 ${symlinks.length} 条符号链接（Windows 解压后会是 0 字节文件）：\n` +
        `  - ${symlinks.slice(0, 5).map((entry) => entry.path).join('\n  - ')}`,
    );
  }

  for (const item of executablePaths) {
    const entry = actual.get(item);
    if ((entry.mode & 0o111) === 0) {
      throw new Error(`${label} 里的 ${item} 丢了可执行位（mode=${entry.mode.toString(8)}）`);
    }
  }
}

function main() {
  const { pluginDir, outDir, compatManifest } = parseArgs(process.argv.slice(2));
  if (!fs.existsSync(pluginDir)) {
    throw new Error(`插件目录不存在：${pluginDir}`);
  }

  const metadata = readPluginMetadata(pluginDir);
  const { base, tarball, zip, manifest } = pluginArchivePaths(outDir, metadata.name, metadata.version);

  // 清单与当前 CLI 的发现规则冲突时：默认忠实打包但**必须**说出来，
  // 否则交付出去的是一个"装得上、但组件少了一大半"的包。
  const detected = manifestCompatAdjustments(metadata.manifest);
  const adjustments = compatManifest ? detected : [];
  if (detected.length > 0 && !compatManifest) {
    process.stdout.write('⚠ 插件清单与当前 Claude Code 的发现规则有冲突：\n');
    for (const item of detected) {
      process.stdout.write(`  - ${item.field}：${item.reason}\n`);
    }
    process.stdout.write('  默认忠实于源码打包；要恢复这些组件，请加 --compat-manifest。\n');
  } else if (adjustments.length > 0) {
    process.stdout.write('→ 包内清单兼容调整（源码不变）：\n');
    for (const item of adjustments) {
      process.stdout.write(`  - 去掉 ${item.field}：${item.reason}\n`);
    }
  }

  // 声明了就必须在：缺文件时这里就报错，而不是等归档读回时才说"少了一条"。
  const declared = declaredPluginPaths(metadata);
  const missingDeclared = declared.filter((item) => !fs.existsSync(path.join(pluginDir, item)));
  if (missingDeclared.length > 0) {
    throw new Error(
      `插件清单声明了这些文件，但目录里没有：\n  - ${missingDeclared.join('\n  - ')}`,
    );
  }

  process.stdout.write(`→ 收集 ${metadata.name} v${metadata.version}（${pluginDir}）…\n`);
  let sourceEntries = collectEntries(pluginDir, { prefix: base, prune: isExcluded });

  // 兼容模式下，用包内生成的那份清单顶掉源码里的 plugin.json。
  // 其余条目（含 agents/、commands/ 目录本身）原样保留，所以组件仍能被默认目录发现。
  if (adjustments.length > 0) {
    const manifestPath = `${base}/.claude-plugin/plugin.json`;
    sourceEntries = sourceEntries.filter((entry) => entry.path !== manifestPath);
    sourceEntries.push(manifestOverrideEntry(base, buildCompatibleManifest(metadata.manifest, adjustments)));
  }

  const entries = [...sourceEntries, ...generatedPluginEntries(base, metadata, adjustments)];
  // 父目录排在子项之前，解压器不必自行补建中间目录；顺序固定也让产物字节可复现。
  entries.sort((left, right) => (left.path < right.path ? -1 : left.path > right.path ? 1 : 0));

  const sourceSymlinks = sourceEntries.filter((entry) => entry.kind === 'symlink');
  if (sourceSymlinks.length > 0) {
    throw new Error(
      `插件目录里有符号链接，安装包不支持（Windows 解压会变成 0 字节文件）：\n` +
        `  - ${sourceSymlinks.map((entry) => entry.path).join('\n  - ')}`,
    );
  }

  const entryPaths = entries.map((entry) => entry.path);
  const expectedPaths = new Set(entryPaths);
  const requiredPaths = [
    `${base}/.claude-plugin/plugin.json`,
    `${base}/.claude-plugin/marketplace.json`,
    ...declared.map((item) => `${base}/${item}`),
    ...['install.sh', 'install.cmd', 'INSTALL.md'].map((item) => `${base}/${item}`),
  ];
  const executablePaths = executablePluginPaths(base);

  fs.mkdirSync(outDir, { recursive: true });

  // 清单留档：出问题时不必解压就能看到包里到底有什么。
  fs.writeFileSync(manifest, `${entryPaths.join('\n')}\n`);

  const rawBytes = entries.reduce((sum, entry) => sum + (entry.kind === 'file' ? entry.size : 0), 0);
  process.stdout.write(`→ 条目 ${entries.length} 条，原始大小 ${humanSize(rawBytes)}\n`);

  process.stdout.write('→ 写 tar.gz…\n');
  const tarballSize = writeTarFile(entries, tarball);

  process.stdout.write('→ 写 zip…\n');
  const zipSize = writeZipFile(entries, zip);

  process.stdout.write('→ 读回校验…\n');
  verifyArchive('tar.gz', readTar(fs.readFileSync(tarball)), expectedPaths, requiredPaths, executablePaths);
  verifyArchive('zip', readZip(fs.readFileSync(zip)), expectedPaths, requiredPaths, executablePaths);

  process.stdout.write(
    [
      '',
      '插件安装包已生成：',
      `  ${path.relative(REPO_ROOT, tarball)}  ${humanSize(tarballSize)}`,
      `  ${path.relative(REPO_ROOT, zip)}  ${humanSize(zipSize)}`,
      `  条目清单  ${path.relative(REPO_ROOT, manifest)}`,
      `  插件      ${metadata.name} v${metadata.version}（${metadata.marketplaceName}）`,
      '',
    ].join('\n'),
  );
}

try {
  main();
} catch (error) {
  // 失败时带一句话退出：这里的错都是"去改某处再重来"，一屏栈没有那句话有用。
  process.stderr.write(`打包失败：${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
}

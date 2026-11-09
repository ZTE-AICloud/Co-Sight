#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
/**
 * @file Co-Sight Viewer 卸载清理脚本
 *
 * 由 npm 在 preuninstall / postuninstall 钩子调用,清理安装时产生的副作用:
 *  1. 停止运行中的 daemon
 *  2. 清理两个 mode (claude/cosight) 的 settings.json 中由本工具注入的 hook 条目
 *  3. 删除 PID 文件
 *  4. 删除日志目录(可通过 UNINSTALL_KEEP_LOGS=1 保留)
 *
 * 数据目录(项目文件、轨迹、任务数据) **永不**自动清理 —— 卸载即丢数据风险太大,
 * 如需清理请手动 rm -rf ~/.cosight/ ~/.claude/ 或子目录。
 *
 * 行为:
 *   node scripts/uninstall.js
 *   UNINSTALL_KEEP_LOGS=1 node scripts/uninstall.js   # 保留日志
 *   UNINSTALL_DRY_RUN=1  node scripts/uninstall.js    # 仅打印,不做任何修改
 *
 * 错误处理原则:每个清理步骤 try/catch 隔离,任一步失败不影响后续步骤 —— 卸载要"尽力而为",
 * 否则残留半残状态比部分缺失更难收场。
 */
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");

// ─── 定位自身路径 ───
// npm uninstall 全局包时会先标记目录为"待删除",cwd 进入不稳定状态,
// 相对路径 require 会失败。必须用绝对路径或 npm 提供的环境变量回溯。
//
// npm 在执行生命周期脚本时设置的环境变量:
//   npm_package_json — 当前包 package.json 的绝对路径
//   INIT_CWD         — 调用 npm 时用户的原始 cwd
//
// __dirname 在卸载时仍指向"已被 npm 标记删除但文件还在"的目录,
// 直接用 __dirname 即可拿到 self 路径,只有相对 require 会失败。
const SCRIPT_DIR = __dirname;

// 用绝对路径 require helper 模块,避免依赖 cwd
const vp = require(path.join(SCRIPT_DIR, "lib", "viewer-process.cjs"));
const {
  getAllSourceHomes,
  getViewerDataDir,
} = require(path.join(SCRIPT_DIR, "..", "server", "lib", "claude-home"));

const HOOK_HANDLER_NAME = "cosight-viewer-hook-handler.js";
const KEEP_LOGS = process.env.UNINSTALL_KEEP_LOGS === "1";
const DRY_RUN = process.env.UNINSTALL_DRY_RUN === "1";

function log(msg) {
  console.log(`[uninstall] ${msg}`);
}
function warn(msg) {
  console.warn(`[uninstall] ⚠️  ${msg}`);
}

// ─── Step 1: 停止 daemon ───
function stopDaemon() {
  if (DRY_RUN) {
    log("[dry-run] 跳过 daemon 停止");
    return;
  }
  log("停止运行中的 daemon...");
  try {
    const port = process.env.CO_SIGHT_PORT || "4830";
    const pids = [
      ...vp.findViewerPids(),
      ...(vp.readPidFromFile() !== null ? [vp.readPidFromFile()] : []),
      ...vp.findPidsByPort(port),
    ].filter((p, i, arr) => Number.isFinite(p) && arr.indexOf(p) === i);

    if (pids.length === 0) {
      log("  无运行中的实例");
    } else {
      log(`  发现 PID: ${pids.join(", ")}`);
      vp.killPids(pids);
      const alive = pids.filter((p) => vp.isAlive(p));
      if (alive.length === 0) log("  ✅ 已停止");
      else warn(`  仍有残留 PID: ${alive.join(", ")}`);
    }
    vp.removePidFile();
  } catch (err) {
    warn(`停止 daemon 失败(非致命): ${err.message}`);
  }
}

// ─── Step 2: 清理 settings.json 中的 hook 条目 ───
/**
 * 判断 hook 条目是否由本工具注入
 */
function isOurHookEntry(entry) {
  if (entry.command && entry.command.includes(HOOK_HANDLER_NAME)) return true;
  if (Array.isArray(entry.hooks)) {
    return entry.hooks.some((h) => h.command && h.command.includes(HOOK_HANDLER_NAME));
  }
  return false;
}

/**
 * 从指定 settings.json 中移除本工具的 hook 条目
 * @param {string} settingsPath
 * @returns {{removed: number, kept: number, missing: boolean}}
 */
function cleanSettingsHooks(settingsPath) {
  if (!fs.existsSync(settingsPath)) {
    return { removed: 0, kept: 0, missing: true };
  }

  let settings;
  try {
    settings = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
  } catch (err) {
    warn(`解析 ${settingsPath} 失败,跳过: ${err.message}`);
    return { removed: 0, kept: 0, missing: false };
  }

  if (!settings.hooks || typeof settings.hooks !== "object") {
    return { removed: 0, kept: 0, missing: false };
  }

  let removed = 0;
  let kept = 0;
  for (const hookType of Object.keys(settings.hooks)) {
    const entries = settings.hooks[hookType];
    if (!Array.isArray(entries)) continue;
    const filtered = entries.filter((e) => {
      const ours = isOurHookEntry(e);
      if (ours) removed++;
      else kept++;
      return !ours;
    });
    settings.hooks[hookType] = filtered;
  }

  // 清理空数组(可选,这里保留以避免误删用户手动配置的空列表)
  if (!DRY_RUN) {
    fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2) + "\n", "utf8");
  }
  return { removed, kept, missing: false };
}

function cleanAllHooks() {
  log("清理 settings.json 中的 hook 条目...");
  for (const source of getAllSourceHomes()) {
    const result = cleanSettingsHooks(source.settingsPath);
    if (result.missing) {
      log(`  ${source.id}: settings.json 不存在,跳过`);
    } else if (DRY_RUN) {
      log(`  ${source.id}: [dry-run] 将移除 ${result.removed} 条,保留 ${result.kept} 条`);
    } else {
      log(`  ${source.id}: 移除 ${result.removed} 条,保留 ${result.kept} 条`);
    }
  }
}

// ─── Step 3: 删除 PID 文件 ───
// 注:PID 文件位于 os.tmpdir()/co-sight-viewer.pid (由 viewer-process.cjs 管理),
// stopDaemon() 已调用 vp.removePidFile() 清理。此处保留函数以备扩展
// (例如未来按 mode 隔离 PID 文件),但目前只需调用一次 vp.removePidFile()。
function cleanPidFiles() {
  log("清理 PID 文件...");
  if (DRY_RUN) {
    log("  [dry-run] 跳过");
    return;
  }
  try {
    vp.removePidFile();
    log(`  已删除 ${require("node:os").tmpdir()}/co-sight-viewer.pid`);
  } catch (err) {
    warn(`删除 PID 文件失败(非致命): ${err.message}`);
  }
}

// ─── Step 4: 清理日志(可选) ───
function cleanLogs() {
  if (KEEP_LOGS) {
    log("保留日志(UNINSTALL_KEEP_LOGS=1)");
    return;
  }
  log("清理日志...");
  if (DRY_RUN) {
    log("  [dry-run] 跳过");
    return;
  }
  const logDirs = [
    // 当前统一位置
    path.join(getViewerDataDir(), "logs", "cosight-viewer"),
    // 历史位置（旧版本按 CLI home 存放），一并清理
    ...getAllSourceHomes().map((source) =>
      path.join(source.home, "logs", "cosight-viewer")
    ),
  ];
  for (const logDir of logDirs) {
    try {
      if (fs.existsSync(logDir)) {
        fs.rmSync(logDir, { recursive: true, force: true });
        log(`  已删除 ${logDir}`);
      }
    } catch (err) {
      warn(`  删除日志失败(${logDir}): ${err.message}`);
    }
  }
}

// ─── Step 5: 卸载 npm 全局包(文件层面的删除) ───
/**
 * 查找 npm-cli.js 的绝对路径,跨平台兼容多种 Node 安装布局:
 *
 * | 布局                              | 命中路径                                              |
 * |-----------------------------------|-------------------------------------------------------|
 * | Windows 系统 / nvm-windows        | `<node_dir>/node_modules/npm/bin/npm-cli.js`          |
 * | Linux/macOS nvm / 系统 Node       | `<node_dir>/../lib/node_modules/npm/bin/npm-cli.js`   |
 * | fnm / volta / asdf                | `<node_dir>/../node_modules/npm/bin/npm-cli.js`       |
 *
 * 都找不到时返回 null,调用方应回退到 shell 解析 PATH 中的 "npm"。
 *
 * @returns {string|null}
 */
function findNpmCliPath() {
  const nodeDir = path.dirname(process.execPath);
  const candidates = [
    // Windows 系统安装 / nvm-windows:node.exe 与 node_modules 同级
    path.join(nodeDir, "node_modules", "npm", "bin", "npm-cli.js"),
    // nvm (Linux/macOS) / 系统 Node:bin 目录在 <prefix>/bin, npm 在 <prefix>/lib/node_modules
    path.join(nodeDir, "..", "lib", "node_modules", "npm", "bin", "npm-cli.js"),
    // fnm / volta / 部分 asdf 布局:node_modules 在 <prefix>/node_modules
    path.join(nodeDir, "..", "node_modules", "npm", "bin", "npm-cli.js"),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return path.resolve(candidate);
    }
  }
  return null;
}

/**
 * 调用 `npm uninstall -g co-sight-viewer` 删除包目录与 bin 链接。
 *
 * 注意: 调用本函数时 cli.js 还在内存中运行,npm 删除磁盘上的 cli.js 不会中断
 * 当前进程(已通过实验验证)。本函数返回后,调用方应立即 process.exit()。
 *
 * 跨平台策略:
 *   1. 优先通过 `findNpmCliPath()` 找到 npm-cli.js,直接用 `node <npm-cli.js>` 调用
 *      —— 不需要 shell,跨平台一致,避免 Windows 上 cmd.exe 的转义差异。
 *   2. 找不到 npm-cli.js 时,回退到 `npm` 字符串 + `shell: true`,让系统 PATH 解析
 *      —— Windows 上 cmd.exe 会找到 npm.cmd,Linux/macOS 上 /bin/sh 会找到 npm shell 脚本。
 *
 * @param {object} [options]
 * @param {boolean} [options.dryRun] 仅打印,不实际执行
 * @param {typeof console.log} [options.logger] 日志函数,默认 console.log
 * @returns {{ok: boolean, code: number|null, error?: string}}
 */
function runNpmUninstall({ dryRun = false, logger = console.log } = {}) {
  if (dryRun) {
    logger("[dry-run] 跳过 npm uninstall -g co-sight-viewer");
    return { ok: true, code: 0 };
  }

  logger("执行 npm uninstall -g co-sight-viewer ...");
  try {
    const { spawnSync } = require("node:child_process");
    const npmCliPath = findNpmCliPath();

    let result;
    if (npmCliPath) {
      // 直接通过 Node 调用 npm-cli.js —— 跨平台一致,无需 shell
      logger(`  (使用 Node 直接调用: ${npmCliPath})`);
      result = spawnSync(process.execPath, [npmCliPath, "uninstall", "-g", "co-sight-viewer"], {
        stdio: "inherit",
        windowsHide: true,
      });
    } else {
      // 回退:通过 shell 解析 PATH 中的 "npm"
      logger("  (npm-cli.js 未找到,回退到 shell 解析 PATH 中的 npm)");
      result = spawnSync("npm", ["uninstall", "-g", "co-sight-viewer"], {
        stdio: "inherit",
        shell: true,
        windowsHide: true,
      });
    }

    if (result.error) {
      warn(`npm uninstall 调用失败: ${result.error.message}`);
      return { ok: false, code: null, error: result.error.message };
    }
    if (result.status !== 0) {
      warn(`npm uninstall 以非 0 状态退出: ${result.status}`);
      return { ok: false, code: result.status };
    }
    logger("  ✅ 包已从全局卸载");
    return { ok: true, code: 0 };
  } catch (err) {
    warn(`npm uninstall 过程中发生未捕获错误: ${err.message}`);
    return { ok: false, code: null, error: err.message };
  }
}

// ─── 主流程 ───
/**
 * 执行卸载清理(停止 daemon、清理 hook、PID、日志)。
 * 由 main() 和 cli.js 的 uninstall 子命令共同调用。
 */
function runCleanup() {
  stopDaemon();
  cleanAllHooks();
  cleanPidFiles();
  cleanLogs();
}

function main() {
  console.log("");
  console.log("=== Co-Sight Viewer 卸载清理 ===");
  if (DRY_RUN) console.log("(DRY-RUN 模式:仅打印,不做修改)");
  console.log("");

  runCleanup();

  console.log("");
  log("✅ 卸载清理完成");
  console.log("");
}

/**
 * 完整卸载流程: 先做清理,再调用 npm uninstall -g 删除包目录。
 * 由 scripts/cli.js 的 uninstall 子命令调用。
 *
 * 行为通过模块级常量 DRY_RUN / KEEP_LOGS 控制 —— 调用方(cli.js)在 require 本模块之前
 * 设置环境变量 UNINSTALL_DRY_RUN=1 / UNINSTALL_KEEP_LOGS=1 即可覆盖默认值。
 *
 * @returns {{ok: boolean, code: number|null, error?: string}}
 */
function runFullUninstall() {
  console.log("");
  console.log("=== Co-Sight Viewer 完整卸载 ===");
  if (DRY_RUN) console.log("(DRY-RUN 模式:仅打印,不做修改)");
  console.log("");

  runCleanup();
  const npmResult = runNpmUninstall({ dryRun: DRY_RUN });

  console.log("");
  if (npmResult.ok) {
    log("✅ 完整卸载完成");
  } else {
    warn("卸载清理已完成,但 npm uninstall 失败 — 包文件可能残留");
    warn("可手动执行: npm uninstall -g co-sight-viewer");
  }
  console.log("");

  return npmResult;
}

if (require.main === module) {
  try {
    main();
  } catch (err) {
    warn(`卸载过程中发生未捕获错误: ${err.message}`);
    process.exit(1);
  }
}

module.exports = {
  isOurHookEntry,
  cleanSettingsHooks,
  stopDaemon,
  cleanAllHooks,
  cleanPidFiles,
  cleanLogs,
  runCleanup,
  runFullUninstall,
  runNpmUninstall,
  findNpmCliPath,
  HOOK_HANDLER_NAME,
};

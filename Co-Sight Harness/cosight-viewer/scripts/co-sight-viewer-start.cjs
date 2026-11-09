#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
/**
 * Co-Sight Viewer 统一启动脚本(方式 A / 方式 B 共用,Linux + Windows)
 *
 * 行为:先杀已有实例 → detached 后台起新进程 → 写 PID → 探活 /api/health
 *
 * 启动命令:
 *   node scripts/co-sight-viewer-start.cjs
 *   或:node packages/cosight-viewer/scripts/co-sight-viewer-start.cjs (方式 B 主包)
 *
 * 环境变量(均可覆盖):
 *   CO_SIGHT_MODE=claude|cosight   (默认 claude)
 *   CO_SIGHT_PORT=<port>           (默认 4830)
 *
 * 标识方案(位置参数单标识):
 *   启动命令:node server/index.js co-sight-viewer
 *   查找方式:pgrep -f / PowerShell CommandLine 匹配
 */
"use strict";

const { spawn } = require("child_process");
const { existsSync } = require("fs");

// 导入共享模块
const vp = require("./lib/viewer-process.cjs");

function log(msg) {
  console.log(`[co-sight-viewer] ${msg}`);
}
function logError(msg) {
  console.error(`[co-sight-viewer] ${msg}`);
}

// ─── 解析运行参数 ───
// 双源观测：不再有模式选择，启动后同时监控 Claude 与 Cosight。
const { getViewerDataDir, getSourceHomes } = require("../server/lib/claude-home");
const { getApiBasePath } = require("../server/lib/hook-config");
const PORT = process.env.CO_SIGHT_PORT || "4830";
const API_BASE = getApiBasePath();

// viewer 自有数据目录：DASHBOARD_DATA_DIR 显式覆盖优先，
// 否则 <COSIGHT_HOME ?? ~/.cosight-harness>/cosight-viewer。
const COSIGHT_VIEWER_DATA_DIR = getViewerDataDir();

// ─── 前置检查 ───
if (!existsSync(vp.SERVER_JS)) {
  logError(`Error: ${vp.SERVER_JS} 不存在`);
  process.exit(1);
}

// ─── 决策2:先杀已有实例 ───
// 先用命令行参数匹配查找(标准启动的实例),再用端口查找兜底(手动启动或其他方式启动的实例)
const existingPids = vp.findViewerPids();
const portPids = vp.findPidsByPort(PORT).filter((p) => !existingPids.includes(p));
const allPids = [...existingPids, ...portPids];
if (allPids.length > 0) {
  log(`检测到已有实例(PID: ${allPids.join(", ")}),先停止...`);
  vp.killPids(allPids);
}

// ─── 等待端口真正释放(最多 ~5s) ───
// killPids 后进程可能仍在关闭;直接 spawn 会撞上 EADDRINUSE 导致启动失败。
// 若超时仍被占,按端口强制清理(可捕获无位置参数的孤儿进程)。
let releaseTries = 0;
while (vp.findPidsByPort(PORT).length > 0 && releaseTries < 10) {
  vp.syncSleep();
  releaseTries++;
}
const stillOnPort = vp.findPidsByPort(PORT);
if (stillOnPort.length > 0) {
  log(`端口 ${PORT} 仍被占用(PID: ${stillOnPort.join(", ")}),强制清理...`);
  vp.killPids(stillOnPort);
  vp.syncSleep();
}

// ─── detached 后台启动 ───
// Build clean env — strip npm lifecycle vars to prevent interference
// (npm_lifecycle_event, npm_package_json, etc. can cause issues in detached processes)
const cleanEnv = { ...process.env };
for (const key of Object.keys(cleanEnv)) {
  if (key.startsWith("npm_")) delete cleanEnv[key];
}

// viewer 数据目录只用 DASHBOARD_DATA_DIR 表达；CLI 源目录由 claude-home.js
// 从 CLAUDE_CONFIG_DIR / COSIGHT_CONFIG_DIR（或默认目录）自动发现。
const childEnv = {
  ...cleanEnv,
  DASHBOARD_DATA_DIR: COSIGHT_VIEWER_DATA_DIR,
  NODE_ENV: process.env.NODE_ENV || "production",
  PORT: PORT, // server/index.js reads process.env.PORT
  DASHBOARD_PORT: PORT, // dev.js / server-info.js reads DASHBOARD_PORT
};

// 旧版的模式变量不再参与任何决策；清掉，避免误导排查。
delete childEnv.CO_SIGHT_MODE;

const sources = getSourceHomes().map((source) => source.id).join(", ") || "(none)";
log(`启动中(sources=${sources}, data=${COSIGHT_VIEWER_DATA_DIR}, port=${PORT})...`);

const child = spawn(process.execPath, [vp.SERVER_JS, vp.INSTANCE_ARG], {
  env: childEnv,
  cwd: vp.PKG_ROOT,
  detached: true, // 关键:脱离父进程,后台存活
  stdio: ["ignore", "ignore", "ignore"], // 日志统一由 pino 写入文件，不再重定向 stdout/stderr
  windowsHide: true, // Windows: 避免弹出控制台窗口
});
child.unref(); // 父进程不等待子进程

vp.writePidFile(child.pid);
log(`进程已起(PID=${child.pid}),日志:${vp.LOG_FILE}`);

// Track early crashes — if the daemon exits within the probe window,
// surface the exit code immediately instead of waiting for probe timeout.
let childExited = false;
let childExitCode = null;
child.on("exit", (code, signal) => {
  childExited = true;
  childExitCode = code;
  if (code !== 0 && code !== null) {
    logError(`❌ 子进程异常退出: code=${code}, signal=${signal}`);
    logError(`   请查看日志: ${vp.LOG_FILE}`);
  }
});

// ─── 探活 /api/health(最多 30s)───
log("等待服务就绪...");
vp.probe(PORT, 60).then((ok) => {
  if (ok) {
    log(`✅ 启动成功 → http://localhost:${PORT}${API_BASE}/`);
    process.exit(0);
  } else if (childExited) {
    // Daemon exited before probe succeeded — surface the exit code
    logError(`❌ 进程已退出(exit code=${childExitCode})，服务未能启动`);
    logError(`   请查看日志: ${vp.LOG_FILE}`);
    logError(`   常见原因: 端口 ${PORT} 被占用 / Node 版本不兼容 / 依赖缺失`);
    logError(`   手动排查: node "${vp.SERVER_JS}" co-sight-viewer`);
    process.exit(1);
  } else if (!vp.isAlive(child.pid)) {
    logError(`Error: 进程启动后退出,请查看日志 ${vp.LOG_FILE}`);
    process.exit(1);
  } else {
    log(`⚠️  服务仍在初始化(后台进行中),稍后访问 http://localhost:${PORT}${API_BASE}/`);
    log(`    日志:${vp.LOG_FILE}`);
    process.exit(0);
  }
});

#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
/**
 * Co-Sight Viewer 统一停止脚本(方式 A / 方式 B 共用,Linux + Windows)
 *
 * 行为:按位置参数 CommandLine 查找实例(Linux pgrep -f / Win PowerShell)+ PID 文件兜底 → 全杀
 *
 * 停止命令:
 *   node scripts/co-sight-viewer-stop.cjs
 *   或:node packages/cosight-viewer/scripts/co-sight-viewer-stop.cjs (方式 B 主包)
 */
"use strict";

const vp = require("./lib/viewer-process.cjs");

function log(msg) { console.log(`[co-sight-viewer] ${msg}`); }

// ─── 收集目标 PID:位置参数匹配(主)+ PID 文件(兜底) + 端口匹配(兜底) ───
// 端口兜底可捕获无位置参数启动的孤儿进程（如 `node server/index.js`），
// 它们不会被字符串匹配找到，但会持续占用端口导致后续启动失败。
let pids = vp.findViewerPids();
const filed = vp.readPidFromFile();
if (filed !== null && !pids.includes(filed)) {
  pids.push(filed);
}
const PORT = process.env.CO_SIGHT_PORT || "4830";
const portPids = vp.findPidsByPort(PORT).filter(p => !pids.includes(p));
pids = [...new Set([...pids, ...portPids])].filter(Number.isFinite);

if (pids.length === 0) {
  log("未发现运行中的 viewer 进程");
  vp.removePidFile();
  process.exit(0);
}

log(`停止进程(PID: ${pids.join(", ")})...`);
vp.killPids(pids);

// ─── 复查 ───
const remaining = pids.filter(p => vp.isAlive(p));
if (remaining.length > 0) {
  log(`⚠️  仍有残留(PID: ${remaining.join(", ")}),已强制处理`);
} else {
  log("✅ 已停止");
}

vp.removePidFile();

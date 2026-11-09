#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
/**
 * Postinstall script — rebuilds client if needed, then starts the server
 * as a background daemon. Both Claude and Cosight are monitored together;
 * there is no mode to choose.
 *
 * The "|| true" in package.json ensures failure here never blocks install.
 *
 * Environment variables supported:
 *   CO_SIGHT_NO_AUTO_START=1       (skip auto-start)
 */

const { execSync } = require("node:child_process");
const { existsSync, writeFileSync } = require("node:fs");
const { join } = require("node:path");
const os = require("node:os");
const vp = require("./lib/viewer-process.cjs");

const ROOT = join(__dirname, "..");
const CLIENT = join(ROOT, "client");
const DIST = join(CLIENT, "dist");

function log(msg) {
  console.log(`[postinstall] ${msg}`);
}

function step(n, total, msg) {
  log(`[${n}/${total}] ${msg}`);
}

const PORT = process.env.CO_SIGHT_PORT || "4830";

const TOTAL_STEPS = 4;

// ─── Step 1: Check client dist ───
step(1, TOTAL_STEPS, `检查前端构建产物 (port=${PORT})...`);
if (!existsSync(join(DIST, "index.html"))) {
  log("client/dist not found — rebuilding...");
  if (existsSync(join(CLIENT, "package.json"))) {
    try {
      execSync("npm install", { cwd: CLIENT, stdio: "inherit", windowsHide: true });
    } catch {
      log("Failed to install client deps — skipping build (non-fatal)");
    }
    try {
      execSync("npx vite build", { cwd: CLIENT, stdio: "inherit", windowsHide: true });
    } catch {
      log("Failed to build client — starting without frontend (non-fatal)");
    }
  } else {
    log("client/package.json not found — skipping client rebuild (normal for global install)");
  }
} else {
  log("✅ client/dist 已存在，跳过构建");
}

// ─── Step 2: Validate Node version ───
step(2, TOTAL_STEPS, "验证 Node.js 版本...");
const nodeVersion = process.version;
const major = parseInt(nodeVersion.slice(1).split(".")[0], 10);
if (major < 22 || (major === 22 && parseInt(process.version.slice(1).split(".")[1], 10) < 5)) {
  log(`⚠️  Node ${nodeVersion} < 22.5 — node:sqlite 不可用，服务可能无法启动`);
} else {
  log(`✅ Node ${nodeVersion} (node:sqlite 可用)`);
}

// ─── Step 3: Stop existing instance ───
step(3, TOTAL_STEPS, "停止已有实例（如有）...");
try {
  const stopScript = join(__dirname, "co-sight-viewer-stop.cjs");
  execSync(`node "${stopScript}"`, { stdio: "pipe", windowsHide: true });
  log("已有实例已停止（或无运行实例）");
} catch {
  log("无已有实例");
}

// ─── Step 4: Start service ───
step(4, TOTAL_STEPS, "启动服务...");
log(`  port=${PORT}`);

// Allow users to skip auto-start (e.g. for debugging or manual control)
if (process.env.CO_SIGHT_NO_AUTO_START === "1") {
  log("⏭️  CO_SIGHT_NO_AUTO_START=1 — 跳过自动启动");
  log("  手动启动: npx co-sight-viewer start");
} else {
  // Build clean env for daemon — strip npm lifecycle vars that can interfere
  // with the child process (e.g. npm_lifecycle_event, npm_package_json, etc.)
  const daemonEnv = { ...process.env };
  for (const key of Object.keys(daemonEnv)) {
    if (key.startsWith("npm_")) delete daemonEnv[key];
  }
  daemonEnv.CO_SIGHT_PORT = PORT;

  try {
    const startScript = join(__dirname, "co-sight-viewer-start.cjs");
    execSync(`node "${startScript}"`, {
      stdio: "inherit",
      windowsHide: true,
      env: daemonEnv,
    });
    log("✅ 安装完成，服务已启动");
  } catch (err) {
    const errMsg = err.message || "unknown error";
    log(`⚠️  服务启动异常: ${errMsg}`);
    log("  可手动启动: npx co-sight-viewer start");
    // Write error details to a temp file for debugging
    try {
      const errorFile = join(os.tmpdir(), "co-sight-viewer-install-error.log");
      writeFileSync(
        errorFile,
        `[${new Date().toISOString()}] postinstall start failed\n${err.stack || errMsg}\n`,
        "utf8"
      );
      log(`  错误详情已写入: ${errorFile}`);
    } catch {}
  }

  // ─── 验证服务状态 ───
  // 等待 2 秒，让慢启动的 server 完成初始化后再检测
  execSync(process.platform === "win32" ? "ping -n 2 127.0.0.1 >nul" : "sleep 2", {
    stdio: "ignore",
    windowsHide: true,
  });

  let serviceOk = false;
  try {
    // 方式 1: pgrep / PowerShell 按 CommandLine 查找
    const pids = vp.findViewerPids();
    if (pids.length > 0 && pids.some((pid) => vp.isAlive(pid))) {
      serviceOk = true;
    }
    // 方式 2: PID 文件兜底
    if (!serviceOk) {
      const filedPid = vp.readPidFromFile();
      if (filedPid !== null && vp.isAlive(filedPid)) {
        serviceOk = true;
      }
    }
  } catch {}

  if (serviceOk) {
    log(`✅ 服务运行中 → http://localhost:${PORT}/api/cosight-viewer/v1/`);
  } else {
    log("⚠️  服务未能正常运行！");
    log("  可能原因:");
    log("    - Node.js 版本低于 22.5 (node:sqlite 不可用)");
    log("    - 端口 4830 被其他程序占用");
    log("    - 文件权限不足");
    log("  手动启动命令:");
    log(`    npx co-sight-viewer start`);
  }
}

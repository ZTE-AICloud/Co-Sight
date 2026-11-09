#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
/**
 * CLI entry point for co-sight-viewer.
 *
 * Usage:
 *   npx co-sight-viewer              — start dashboard (default mode, background)
 *   npx co-sight-viewer start        — start in Claude mode (background)
 *   npx co-sight-viewer stop         — stop running daemon
 *   npx co-sight-viewer --mode cosight — start in Cosight mode (background)
 *   npx co-sight-viewer --help        — show help
 *
 * After global install:
 *   npm install -g co-sight-viewer
 *   co-sight-viewer --mode claude
 *
 * Note: start/stop now delegates to co-sight-viewer-start.cjs / co-sight-viewer-stop.cjs
 *       for unified cross-platform daemon management (Linux + Windows).
 */

const { spawn } = require("node:child_process");
const path = require("node:path");
const os = require("node:os");
const { getApiBasePath } = require("../server/lib/hook-config");

const HOME = os.homedir();
const API_BASE = getApiBasePath();

// ─── Parse CLI args ───
const args = process.argv.slice(2);

// Subcommand: stop → delegate to unified stop script
if (args[0] === "stop") {
  const stopScript = path.join(__dirname, "co-sight-viewer-stop.cjs");
  const child = spawn(process.execPath, [stopScript], {
    stdio: "inherit",
    windowsHide: true,
  });
  child.on("exit", (code) => {
    process.exit(code || 0);
  });
  // Exit early — stop flow handled by stop script
  return;
}

// Subcommand: uninstall → cleanup + npm uninstall -g
// 由于 npm 10+ 不再执行 preuninstall/postuninstall 生命周期钩子,
// 必须通过显式子命令完成清理(停止 daemon、移除 settings.json 中的 hook、
// 删除 PID/日志),然后调用 `npm uninstall -g co-sight-viewer` 删除包目录。
if (args[0] === "uninstall") {
  // 在 require 之前设置 env,让 uninstall.js 的模块级常量读到正确值
  if (args.includes("--dry-run")) process.env.UNINSTALL_DRY_RUN = "1";
  if (args.includes("--keep-logs")) process.env.UNINSTALL_KEEP_LOGS = "1";
  const { runFullUninstall } = require("./uninstall");
  const result = runFullUninstall();
  process.exit(result.ok ? 0 : 1);
  return;
}

// Subcommand: status → query current daemon status
if (args[0] === "status") {
  const http = require("http");
  const PORT = process.env.CO_SIGHT_PORT || "4830";

  const vp = require("./lib/viewer-process.cjs");
  const pids = vp.findViewerPids();
  const portPids = vp.findPidsByPort(PORT).filter((p) => !pids.includes(p));
  const allPids = [...pids, ...portPids];

  if (allPids.length === 0) {
    console.log(`[co-sight-viewer] ⚠️  服务未运行`);
    process.exit(1);
  }

  console.log(`[co-sight-viewer] ✅ 服务运行中 (PID: ${allPids.join(", ")})`);
  console.log(`[co-sight-viewer]    端口: ${PORT}`);

  // Query API for details

  function apiGet(urlPath) {
    return new Promise((resolve) => {
      const req = http.get(`http://127.0.0.1:${PORT}${urlPath}`, (res) => {
        let body = "";
        res.on("data", (c) => (body += c));
        res.on("end", () => {
          try {
            resolve(JSON.parse(body));
          } catch {
            resolve(null);
          }
        });
      });
      req.on("error", () => resolve(null));
      req.setTimeout(3000, () => {
        req.destroy();
        resolve(null);
      });
    });
  }

  (async () => {
    const [info, modeStatus] = await Promise.all([
      apiGet(`${API_BASE}/settings/info`),
      apiGet(`${API_BASE}/settings/mode-status`),
    ]);

    if (modeStatus && modeStatus.currentMode) {
      console.log(`[co-sight-viewer]    模式: ${modeStatus.currentMode}`);
      console.log(`[co-sight-viewer]    服务激活: ${modeStatus.serviceActive ? "是" : "否"}`);
    }
    if (info && info.db) {
      console.log(`[co-sight-viewer]    数据库: ${info.db.path}`);
      console.log(`[co-sight-viewer]    会话数: ${info.db.counts?.sessions || 0}`);
    }
    if (modeStatus) {
      const installed = [];
      if (modeStatus.claude?.installed)
        installed.push(`Claude Code (${modeStatus.claude.commandPath})`);
      if (modeStatus.cosight?.installed)
        installed.push(`Cosight Code (${modeStatus.cosight.commandPath})`);
      if (installed.length > 0) {
        console.log(`[co-sight-viewer]    检测到: ${installed.join(", ")}`);
      }
      if (modeStatus.recommendedMode) {
        console.log(`[co-sight-viewer]    推荐模式: ${modeStatus.recommendedMode}`);
      }
    }
  })().finally(() => process.exit(0));
  return;
}
// Subcommand: selfcheck → run environment diagnostics (hooks / processes / data)
if (args[0] === "selfcheck") {
  const { runSelfCheckCli } = require("./selfcheck");
  runSelfCheckCli(args.slice(1));
  return;
}

// Unknown subcommand → show error and help
if (args[0] && !args[0].startsWith("-") && args[0] !== "start") {
  console.error(`Error: unknown subcommand "${args[0]}". See "co-sight-viewer --help".`);
  process.exit(1);
}
if (args[0] === "start") {
  args.shift(); // remove 'start', parse rest as options
}

const opts = { mode: null, watch: true, port: null, help: false };

for (let i = 0; i < args.length; i++) {
  switch (args[i]) {
    case "--help":
    case "-h":
      opts.help = true;
      break;
    case "--mode":
      opts.mode = args[++i] || null;
      break;
    case "--watch":
    case "-w":
      opts.watch = true;
      break;
    case "--no-watch":
      opts.watch = false;
      break;
    case "--port":
    case "-p":
      opts.port = args[++i];
      break;
    case "--decision-mode":
      opts.decisionMode = args[++i];
      break;
  }
}

if (opts.help) {
  console.log(
    `
co-sight-viewer — Real-time dashboard for Claude Code / Cosight Code

Usage:
  co-sight-viewer [start] [options]
  co-sight-viewer stop
  co-sight-viewer status
  co-sight-viewer selfcheck [--json] [--fix] [--verbose]
  co-sight-viewer uninstall [--dry-run] [--keep-logs]

Options:
  --mode <claude|cosight|auto>   Deprecated / ignored: both CLIs are monitored together
  --port, -p <port>              Override default port (default: 4830)
  --decision-mode <mode>         Task decision mode: llm | feature | feature-only
  --help, -h                     Show this help

Subcommands:
  stop                           Stop running daemon
  status                         Show running daemon status (mode, port, DB, PID)
  selfcheck                      Diagnose environment: hook config, duplicate/abnormal
                                 processes, PID/discovery files, health, data integrity
                                 (--json machine-readable, --fix safe file cleanups,
                                  --verbose show PASS/INFO details)
  uninstall                      Full uninstall: cleanup hooks/daemon/logs, then remove package

Uninstall options:
  --dry-run                      Preview cleanup without modifying anything
  --keep-logs                    Preserve log directory

Examples:
  co-sight-viewer                        # Monitor Claude and Cosight together
  co-sight-viewer stop                   # Stop running daemon
  co-sight-viewer selfcheck              # Diagnose hooks / processes / data
  co-sight-viewer selfcheck --fix        # Selfcheck + safe file cleanups
  co-sight-viewer uninstall              # Full uninstall (recommended)
  co-sight-viewer uninstall --dry-run    # Preview what uninstall would do
`.trim()
  );
  process.exit(0);
}

// --mode 已废弃：Claude 与 Cosight 会同时监控，不再需要选择模式。
if (opts.mode) {
  console.warn(
    `[co-sight-viewer] --mode ${opts.mode} 已废弃并被忽略：Claude 与 Cosight 会同时监控`
  );
}

const { getViewerDataDir } = require("../server/lib/claude-home");
console.log(`[co-sight-viewer] Data: ${getViewerDataDir()}`);
console.log(
  `[co-sight-viewer] Dashboard → http://localhost:${opts.port || 4830}${API_BASE}/`
);

// ─── Delegate to unified start script (background daemon with health probe) ───
const startScript = path.join(__dirname, "co-sight-viewer-start.cjs");

// Build clean env — strip npm lifecycle vars that can interfere with detached daemon
const cliEnv = { ...process.env };
for (const key of Object.keys(cliEnv)) {
  if (key.startsWith("npm_")) delete cliEnv[key];
}
// 旧模式变量不再透传；viewer 数据目录统一由 claude-home.js 解析。
delete cliEnv.CO_SIGHT_MODE;
cliEnv.CO_SIGHT_PORT = opts.port || "4830";
cliEnv.DASHBOARD_DATA_DIR = getViewerDataDir();
cliEnv.NODE_ENV = "production";
cliEnv.TASK_DECISION_MODE = opts.decisionMode || process.env.TASK_DECISION_MODE || "";

const child = spawn(process.execPath, [startScript], {
  stdio: "inherit",
  windowsHide: true,
  env: cliEnv,
});

child.on("exit", (code) => {
  process.exit(code || 0);
});

for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => child.kill(sig));
}

/**
 * @deprecated stopDaemon logic has been moved to co-sight-viewer-stop.cjs
 *             for unified cross-platform process management (Linux + Windows).
 *             The CLI stop subcommand now spawns the stop script directly.
 */
// stopDaemon() removed — see co-sight-viewer-stop.cjs

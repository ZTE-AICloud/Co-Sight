#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
/**
 * Co-Sight Viewer 进程管理共享模块
 *
 * 提供跨平台(Linux + Windows)的进程查找、杀进程、探活等能力,
 * 供 co-sight-viewer-start.cjs 和 co-sight-viewer-stop.cjs 复用。
 *
 * 标识方案(位置参数单标识):
 *   启动: node server/index.js co-sight-viewer
 *   查找: Linux pgrep -f / Windows PowerShell CommandLine 匹配
 */
"use strict";

const { spawn, execSync } = require("child_process");
const { join } = require("path");
const { existsSync, readFileSync, writeFileSync, openSync } = require("fs");
const os = require("os");
const net = require("net");

// ─── 常量 ───
const IS_WIN = process.platform === "win32";
const TMP = os.tmpdir();
const PID_FILE = join(TMP, "co-sight-viewer.pid");

// 统一日志目录：COSIGHT_LOG_DIR > <viewerDataDir>/logs/cosight-viewer
function resolveLogDir() {
  if (process.env.COSIGHT_LOG_DIR) return process.env.COSIGHT_LOG_DIR;
  const { getViewerDataDir } = require("../../server/lib/claude-home");
  return join(getViewerDataDir(), "logs", "cosight-viewer");
}

const LOG_FILE = join(resolveLogDir(), "cosight-viewer.log");
const INSTANCE_ARG = "co-sight-viewer";   // 位置参数标识
const PKG_ROOT = join(__dirname, "..", "..");
const SERVER_JS = join(PKG_ROOT, "server", "index.js");

// ─── 进程查找 ───

/**
 * 查找占用指定端口的所有进程 PID(跨平台）
 * 通过 netstat 解析,比命令行参数匹配更可靠(无论进程如何启动都能找到)
 * @param {number|string} port
 * @returns {number[]} PID 数组
 */
function findPidsByPort(port) {
  try {
    const targetPort = parseInt(port, 10);
    if (!Number.isFinite(targetPort)) return [];
    if (IS_WIN) {
      // Windows: netstat -ano 输出格式 "  TCP    0.0.0.0:4830    0.0.0.0:0    LISTENING    4992"
      const out = execSync(`netstat -ano`, { encoding: "utf8", windowsHide: true, maxBuffer: 1024 * 1024 });
      const pids = new Set();
      for (const line of out.split(/\r?\n/)) {
        const parts = line.trim().split(/\s+/);
        if (parts.length < 5) continue;
        // 匹配 LISTENING 状态的端口行,提取 PID
        if (parts[3] === "LISTENING" && parts[1].endsWith(`:${targetPort}`)) {
          const pid = parseInt(parts[4], 10);
          if (Number.isFinite(pid)) pids.add(pid);
        }
      }
      return [...pids];
    } else {
      // Linux/macOS: lsof -ti:{port} 返回 PID 列表
      const out = execSync(`lsof -ti:${targetPort} -sTCP:LISTEN 2>/dev/null || true`, { encoding: "utf8", windowsHide: true });
      return out.split(/\s+/).map(s => parseInt(s, 10)).filter(Number.isFinite);
    }
  } catch {
    return [];
  }
}

/**
 * 查找所有 viewer 进程的 PID(跨平台)
 * 通过位置参数 CommandLine 匹配,排除 dev 进程(node --watch)和别的服务。
 * @returns {number[]} PID 数组
 */
function findViewerPids() {
  try {
    if (IS_WIN) {
      // Windows:PowerShell 按 CommandLine 含位置参数匹配,且限定 node.exe 可执行文件
      // （否则 bash 包装 / wmic 自身等命令行含该字符串的进程会误匹配到自己）
      // 使用 *index.js* 而不是 *server/index.js* 避免 Windows 反斜杠/正斜杠不匹配
      const out = execSync(
        `powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'node.exe' -and $_.CommandLine -like '*index.js ${INSTANCE_ARG}*' } | Select-Object -ExpandProperty ProcessId"`,
        { encoding: "utf8", windowsHide: true }
      );
      return out.split(/\s+/).map(s => parseInt(s, 10)).filter(Number.isFinite);
    } else {
      // Linux/macOS:pgrep -f 按 CommandLine 含位置参数匹配,再按 /proc/comm 限定为 node 进程
      // （排除 bash 包装进程的误匹配）
      const out = execSync(`pgrep -f "server/index\\\\.js ${INSTANCE_ARG}"`, { encoding: "utf8", windowsHide: true });
      return out
        .split(/\s+/)
        .map(s => parseInt(s, 10))
        .filter(Number.isFinite)
        .filter((pid) => {
          try {
            const comm = readFileSync(`/proc/${pid}/comm`, "utf8").trim();
            return comm === "node" || comm === "nodejs";
          } catch {
            return false;
          }
        });
    }
  } catch {
    // pgrep/powershell 无匹配返回非零,视作无实例
    return [];
  }
}

/**
 * 从 PID 文件读取记录的 PID(兜底)
 * @returns {number|null} PID 或 null
 */
function readPidFromFile() {
  try {
    if (existsSync(PID_FILE)) {
      const pid = parseInt(readFileSync(PID_FILE, "utf8").trim(), 10);
      return Number.isFinite(pid) ? pid : null;
    }
  } catch {}
  return null;
}

/**
 * 写 PID 文件
 * @param {number} pid
 */
function writePidFile(pid) {
  writeFileSync(PID_FILE, String(pid));
}

/**
 * 删除 PID 文件
 */
function removePidFile() {
  try {
    if (existsSync(PID_FILE)) {
      const { unlinkSync } = require("fs");
      unlinkSync(PID_FILE);
    }
  } catch {}
}

// ─── 进程控制 ───

/**
 * 检查进程是否存活
 * @param {number} pid
 * @returns {boolean}
 */
function isAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

/**
 * 杀掉一组进程(优雅 → 等待 → 强杀)
 * @param {number[]} pids
 */
function killPids(pids) {
  // 第一轮:SIGTERM / taskkill
  for (const pid of pids) {
    try {
      if (IS_WIN) {
        execSync(`taskkill /F /PID ${pid}`, { stdio: "ignore", windowsHide: true });
      } else {
        process.kill(pid, "SIGTERM");
      }
    } catch {}
  }

  // 等待优雅退出(最多 5s)
  for (let i = 0; i < 10; i++) {
    const still = pids.filter(p => isAlive(p));
    if (still.length === 0) break;
    syncSleep(500);
  }

  // 仍存活则强杀
  for (const pid of pids.filter(p => isAlive(p))) {
    try {
      if (IS_WIN) {
        execSync(`taskkill /F /PID ${pid}`, { stdio: "ignore", windowsHide: true });
      } else {
        process.kill(pid, "SIGKILL");
      }
    } catch {}
  }
}

// ─── 辅助工具 ───

/**
 * 同步睡眠(跨平台)
 * @param {number} ms 毫秒
 */
function syncSleep(ms) {
  try {
    if (IS_WIN) {
      // Windows:用 ping 实现短暂延迟
      execSync(`ping -n 1 127.0.0.1 >nul`, { stdio: "ignore", windowsHide: true });
    } else {
      execSync(`sleep 0.5`, { stdio: "ignore", windowsHide: true });
    }
  } catch {}
}

/**
 * TCP 探活(等待端口可连接)
 * @param {number|string} port 端口
 * @param {number} tries 最大尝试次数(每次 500ms 间隔)
 * @returns {Promise<boolean>}
 */
function probe(port, tries) {
  return new Promise((resolve) => {
    let n = 0;
    const tryOnce = () => {
      const sock = net.createConnection({ port: parseInt(port, 10) }, () => {
        sock.destroy();
        resolve(true);
      });
      sock.once("error", () => {
        if (++n >= tries) resolve(false);
        else setTimeout(tryOnce, 500);
      });
      sock.setTimeout(500, () => {
        sock.destroy();
        if (++n >= tries) resolve(false);
        else setTimeout(tryOnce, 500);
      });
    };
    tryOnce();
  });
}

// ─── 导出 ───
module.exports = {
  IS_WIN,
  TMP,
  PID_FILE,
  LOG_FILE,
  INSTANCE_ARG,
  PKG_ROOT,
  SERVER_JS,
  findPidsByPort,
  findViewerPids,
  readPidFromFile,
  writePidFile,
  removePidFile,
  isAlive,
  killPids,
  syncSleep,
  probe,
};

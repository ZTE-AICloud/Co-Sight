// SPDX-License-Identifier: Apache-2.0
/**
 * @fileoverview Unified structured logger for the entire co-sight-viewer project.
 *
 * Uses pino (NDJSON) with pino-roll for automatic file rotation.
 *
 * Output: {logDir}/cosight-viewer.log
 *   - claude 模式  → ~/.claude/logs/
 *   - cosight 模式 → ~/.cosight/logs/
 *   - 环境变量 COSIGHT_LOG_DIR 最高优先级覆盖
 *
 * Environment variables:
 *   LOG_LEVEL          — debug | info | warn | error (default: info)
 *   LOG_SKIP_HIGH_FREQ — true to skip logs marked with highFreq (default: false)
 *   LOG_MAX_SIZE_MB    — max size per log file in MB (default: 10)
 *   LOG_MAX_FILES      — max number of rotated files to keep (default: 10)
 *   COSIGHT_LOG_DIR    — absolute log directory path (highest priority)
 *
 * Log cleanup:
 *   - Startup: Synchronously prunes old files exceeding LOG_MAX_FILES
 *   - Runtime: Periodically (hourly) prunes old files to prevent accumulation
 *   - This ensures cleanup works even when pino-roll's async cleanup is
 *     interrupted by process restarts (SIGTERM/SIGKILL).
 *
 * Usage:
 *   const { getLogger, createChildLogger } = require("./lib/unified-logger");
 *
 *   // Root logger
 *   const root = getLogger();
 *   root.info("server started");
 *
 *   // Child logger with prefix
 *   const log = createChildLogger("watch/daemon");
 *   log.info({ taskId: "abc" }, "task created");
 *   log.debug({ highFreq: true }, "event loop p50=2ms p99=15ms");
 */

const { join, dirname, basename } = require("node:path");
const { readdirSync, unlinkSync } = require("node:fs");
const os = require("node:os");
const pino = require("pino");
const { getViewerDataDir } = require("./claude-home");

// ─── Path resolution ────────────────────────────────────────────────

/**
 * Resolve the log directory.
 * Priority: COSIGHT_LOG_DIR > <viewerDataDir>/logs/cosight-viewer
 */
function getLogDir() {
  if (process.env.COSIGHT_LOG_DIR) {
    return process.env.COSIGHT_LOG_DIR;
  }
  return join(getViewerDataDir(), "logs", "cosight-viewer");
}

/**
 * Get the active log file path.
 * @returns {string}
 */
function getLogFile() {
  return join(getLogDir(), "cosight-viewer.log");
}

// ─── Synchronous log cleanup ────────────────────────────────────────

/**
 * Synchronously remove old log files exceeding maxFiles count.
 * Runs at startup and periodically to ensure log directory stays clean
 * even when pino-roll's async cleanup is interrupted by process restarts.
 *
 * @param {string} logFile - Active log file path (e.g., ~/.cosight/logs/cosight-viewer/cosight-viewer.log)
 * @param {number} maxFiles - Maximum number of rotated files to keep
 */
function pruneOldLogsSync(logFile, maxFiles) {
  const dir = dirname(logFile);
  const base = basename(logFile, ".log"); // "cosight-viewer"
  const ext = ".log";

  try {
    const files = readdirSync(dir)
      .filter((f) => f.startsWith(base + ".") && f.endsWith(ext) && f !== basename(logFile))
      .map((f) => {
        const match = f.match(/\.(\d+)\.log$/);
        return { name: f, num: match ? parseInt(match[1], 10) : 0 };
      })
      .filter((f) => f.num > 0)
      .sort((a, b) => a.num - b.num);

    if (files.length > maxFiles) {
      const toRemove = files.slice(0, files.length - maxFiles);
      for (const f of toRemove) {
        try {
          unlinkSync(join(dir, f.name));
        } catch {
          /* ignore */
        }
      }
    }
  } catch {
    /* ignore — directory may not exist yet */
  }
}

// ─── Environment configuration ──────────────────────────────────────

function getConfig() {
  return {
    level: process.env.LOG_LEVEL || "info",
    skipHighFreq: process.env.LOG_SKIP_HIGH_FREQ === "true",
    maxSizeMB: parseInt(process.env.LOG_MAX_SIZE_MB || "10", 10),
    maxFiles: parseInt(process.env.LOG_MAX_FILES || "10", 10),
  };
}

// ─── Beijing time formatting ────────────────────────────────────────

function toBeijingISOString(date = new Date()) {
  const bjMs = date.getTime() + 8 * 60 * 60 * 1000;
  const bj = new Date(bjMs);
  return bj.toISOString().replace("Z", "+08:00");
}

// ─── Root logger singleton ──────────────────────────────────────────

let _rootLogger = null;
let _transport = null;

/**
 * Get or create the singleton root pino logger.
 * @returns {import("pino").Logger}
 */
function getLogger() {
  if (_rootLogger) return _rootLogger;

  const config = getConfig();
  const logFile = getLogFile();

  // 启动时立即同步清理多余旧文件（防止 daemon 长期运行累积）
  pruneOldLogsSync(logFile, config.maxFiles);

  // pino-roll transport for automatic file rotation
  _transport = pino.transport({
    target: "pino-roll",
    options: {
      file: logFile,
      size: config.maxSizeMB, // MB
      limit: {
        count: config.maxFiles,
        removeOtherLogFiles: true, // 删除所有匹配模式的旧文件，不只是当前进程创建的
      },
      mkdir: true,
      dateFormat: "yyyy-MM-dd",
      extension: ".log",
    },
  });

  _rootLogger = pino(
    {
      level: config.level,
      base: { pid: process.pid, hostname: os.hostname() },
      timestamp: () => `,"time":"${toBeijingISOString()}"`,
      formatters: {
        // 将数字级别改为名称输出（如 "info" 而非 30）
        level(label, _number) {
          return { level: label };
        },
      },
    },
    _transport
  );

  // 运行中定期清理（每 1 小时），防止长期运行不重启时文件累积
  const cleanupInterval = setInterval(
    () => {
      pruneOldLogsSync(logFile, config.maxFiles);
    },
    60 * 60 * 1000
  ); // 1 小时
  cleanupInterval.unref(); // 不阻止进程退出

  // Flush on process exit
  for (const signal of ["beforeExit", "SIGTERM", "SIGINT"]) {
    process.on(signal, () => {
      try {
        _rootLogger.flush();
      } catch {
        /* ignore */
      }
    });
  }

  return _rootLogger;
}

/**
 * Create a child logger with a fixed prefix.
 * All log calls on the child will include { prefix: "..." } in the JSON output.
 *
 * The returned logger has the same API as pino, plus automatic high-freq filtering:
 *   log.debug({ highFreq: true }, "msg") — skipped when LOG_SKIP_HIGH_FREQ=true
 *
 * @param {string} prefix — module/component identifier (e.g. "watch/daemon", "hooks")
 * @returns {import("pino").Logger}
 */
function createChildLogger(prefix) {
  const child = getLogger().child({ prefix });
  const skipHighFreq = process.env.LOG_SKIP_HIGH_FREQ === "true";

  if (!skipHighFreq) {
    // No filtering needed — return child directly
    return child;
  }

  // Wrap each level method to filter high-frequency logs
  const levels = ["trace", "debug", "info", "warn", "error", "fatal"];
  const wrapped = Object.create(child);

  for (const level of levels) {
    const original = child[level].bind(child);
    wrapped[level] = function (first, ...rest) {
      // pino signature: logger(mergeObj, msg, ...args) or logger(msg, ...args)
      if (first && typeof first === "object" && first.highFreq === true) {
        return; // Skip high-frequency log
      }
      return original(first, ...rest);
    };
  }

  // Preserve child() for further nesting
  wrapped.child = (bindings) => createChildLogger(`${prefix}/${bindings.prefix || "unknown"}`);

  return wrapped;
}

/**
 * Flush the root logger (synchronous, for graceful shutdown).
 */
function flush() {
  if (_rootLogger) {
    try {
      _rootLogger.flush();
    } catch {
      /* ignore */
    }
  }
}

// ─── Exports ────────────────────────────────────────────────────────

module.exports = {
  getLogDir,
  getLogFile,
  getLogger,
  createChildLogger,
  flush,
  pruneOldLogsSync,
};

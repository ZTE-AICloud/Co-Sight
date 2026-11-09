// SPDX-License-Identifier: Apache-2.0
/**
 * @file perf-trace.js
 * @description 性能诊断工具 — 事件循环延迟监控、代码段耗时测量。
 *
 * 日志输出统一到 unified-logger（prefix: "perf"）。
 * 高频日志（事件循环每秒采样）标记 highFreq: true，可通过 LOG_SKIP_HIGH_FREQ=true 跳过。
 * 超阈值告警（[EL_BLOCKED]、[EL_BEAT]）使用 warn 级别，始终可见。
 *
 * 三个证据维度:
 *   - mark()/measure()        — 同步代码段耗时
 *   - 全局请求中间件           — 请求排队时长
 *   - startEventLoopMonitor() — 事件循环每轮延迟（黄金指标）
 */

const { monitorEventLoopDelay } = require("node:perf_hooks");
const { createChildLogger } = require("./unified-logger");

const perfLog = createChildLogger("perf");

const EL_DELAY_THRESHOLD_MS = Number(process.env.PERF_EL_THRESHOLD_MS) || 50;
// monitorEventLoopDelay() 直方图返回值单位是纳秒,统一在此转为毫秒后再比较/输出
const NS_PER_MS = 1e6;
// 内存心跳间隔 —— 默认 60s,可通过 PERF_MEM_MS 覆盖
const MEM_HEARTBEAT_MS = Number(process.env.PERF_MEM_MS) || 60000;

/**
 * 写入诊断日志到统一 logger。
 * 低频调用（请求摘要、daemon 段耗时）— info 级别。
 * 保持向后兼容的 API（被 server/index.js 等调用）。
 *
 * @param {string} message
 */
function writeDiag(message) {
  try {
    perfLog.info(message);
  } catch {
    /* ignore — diagnostics must never throw */
  }
}

/**
 * 纳秒级时间戳。
 */
function nowNs() {
  return process.hrtime.bigint();
}

/**
 * 计算两个纳秒时间戳的毫秒差（保留 2 位小数）。
 */
function msBetween(startNs, endNs) {
  return Number(endNs - startNs) / 1e6;
}

/* ────────────────────────────────────────────────────────────
 * 事件循环延迟监控 —— 黄金指标
 * 每轮事件循环迭代若超过阈值，说明这段时间有同步代码霸占了循环。
 * histogram 每 PERF_EL_SAMPLE_MS 毫秒 flush 一次，打出这段时间内的
 *   p50 / p99 / max 延迟；超过阈值的会单独用 warn 级别告警。
 * ──────────────────────────────────────────────────────────── */
let elMonitorStarted = false;
function startEventLoopMonitor() {
  if (elMonitorStarted) return;
  elMonitorStarted = tryStartEventLoopMonitor();
}

function tryStartEventLoopMonitor() {
  try {
    const histogram = monitorEventLoopDelay();
    histogram.enable();

    const intervalMs = Number(process.env.PERF_EL_SAMPLE_MS) || 1000;
    const timer = setInterval(() => {
      try {
        // 单位 bug 修复:直方图值为纳秒,此前被当作毫秒与阈值比较
        // (max 恒 > 50),导致 [EL_BLOCKED] 每秒误报。现先转为毫秒再比较/输出。
        const p50 = histogram.mean / NS_PER_MS;
        const p99 = histogram.percentile(99) / NS_PER_MS;
        const max = histogram.max / NS_PER_MS;
        const blocked = max > EL_DELAY_THRESHOLD_MS;

        const msg = `p50=${msFmt(p50)} p99=${msFmt(p99)} max=${msFmt(max)}`;

        if (blocked) {
          // 超阈值告警 — warn 级别，始终可见
          perfLog.warn(`${msg}  *** [EL_BLOCKED] threshold=${EL_DELAY_THRESHOLD_MS}ms ***`);
        } else {
          // 常规采样 — debug + highFreq，可通过 LOG_SKIP_HIGH_FREQ 跳过
          perfLog.debug({ highFreq: true }, `[EL] ${msg}`);
        }
        histogram.reset();
      } catch {
        /* ignore */
      }
    }, intervalMs);
    if (timer.unref) timer.unref();

    // 心跳探测：每 intervalMs 投递一个 setTimeout，测量它实际延迟多少
    const beat = () => {
      const posted = Date.now();
      const beatTimer = setTimeout(() => {
        const lag = Date.now() - posted - intervalMs;
        if (lag > EL_DELAY_THRESHOLD_MS) {
          perfLog.warn(`[EL_BEAT] setTimeout lag=${lag}ms — 事件循环此期间被阻塞`);
        }
        beat();
      }, intervalMs);
      if (beatTimer.unref) beatTimer.unref();
    };
    beat();

    perfLog.info(`[EL] monitor started, sample=${intervalMs}ms, threshold=${EL_DELAY_THRESHOLD_MS}ms`);
    return true;
  } catch (e) {
    perfLog.error(`[EL] monitor FAILED to start: ${e.message}`);
    return false;
  }
}

/* ────────────────────────────────────────────────────────────
 * 内存心跳 —— 观测长期运行的内存增长趋势
 * 每 PERF_MEM_MS(默认 60s)记录一次 process.memoryUsage()。
 * 作用:
 *   1. 日志中能看到 heapUsed/rss 是否随时间单调上涨(内存泄漏方向);
 *   2. 若发生"跑一段时间就僵死",重启前的最后一条 [MEM] 即冻结时的堆大小。
 * 低频(60s)使用 info 级别,始终可见。
 * ──────────────────────────────────────────────────────────── */
let memHeartbeatStarted = false;
function startMemoryHeartbeat() {
  if (memHeartbeatStarted) return;
  memHeartbeatStarted = tryStartMemoryHeartbeat();
}

function tryStartMemoryHeartbeat() {
  try {
    const timer = setInterval(() => {
      try {
        const m = process.memoryUsage();
        const heapUsedMB = m.heapUsed / 1e6;
        const rssMB = m.rss / 1e6;
        perfLog.info(
          `[MEM] heapUsed=${heapUsedMB.toFixed(1)}MB heapTotal=${(m.heapTotal / 1e6).toFixed(1)}MB rss=${rssMB.toFixed(1)}MB external=${(m.external / 1e6).toFixed(1)}MB`
        );
      } catch {
        /* ignore — diagnostics must never throw */
      }
    }, MEM_HEARTBEAT_MS);
    if (timer.unref) timer.unref();

    perfLog.info(`[MEM] heartbeat started, interval=${MEM_HEARTBEAT_MS}ms`);
    return true;
  } catch (e) {
    perfLog.error(`[MEM] heartbeat FAILED to start: ${e.message}`);
    return false;
  }
}

function msFmt(ms) {
  if (!Number.isFinite(ms)) return "n/a";
  return `${ms.toFixed(2)}ms`;
}

// DIAG_FILE kept as empty string for backward compatibility (some code references it)
const DIAG_FILE = "";

module.exports = {
  writeDiag,
  nowNs,
  msBetween,
  msFmt,
  startEventLoopMonitor,
  startMemoryHeartbeat,
  DIAG_FILE,
};

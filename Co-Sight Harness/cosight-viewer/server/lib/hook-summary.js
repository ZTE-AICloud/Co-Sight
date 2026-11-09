// SPDX-License-Identifier: Apache-2.0
/**
 * @file hook-summary.js
 * 低频 hook 接收汇总 —— 每 N 分钟输出一条"最近收到多少 hook"的 info 日志。
 *
 * 用途: 从日志判断 hook 链路是否中断。进程活着、/api/health 正常,但该计数
 * 长期为 0,说明 Claude 的 hook 没进到本服务 —— 链路在"进"这一端断了。
 *
 * 独立成模块以便隔离测试(不加载 hooks router / db / websocket)。
 * 窗口默认 5 分钟,可用环境变量 HOOK_SUMMARY_MS 覆盖(毫秒)。
 */

const DEFAULT_SUMMARY_MS = 5 * 60 * 1000;

/** 解析汇总窗口;非法输入回退默认值。 */
function resolveSummaryMs(envValue) {
  const raw = parseInt(envValue, 10);
  return Number.isFinite(raw) && raw > 0 ? raw : DEFAULT_SUMMARY_MS;
}

/**
 * 创建 hook 汇总计数器。
 * @param {(msg: string) => void} logFn - 统一 logger 的 info 封装(可抛异常,内部已 try/catch)
 * @param {number} [intervalMs] - 汇总窗口,默认 resolveSummaryMs(process.env.HOOK_SUMMARY_MS)
 * @returns {{
 *   increment(): void,
 *   reset(): void,
 *   getCount(): number,
 *   getIntervalMs(): number,
 *   start(): NodeJS.Timeout,
 *   stop(): void,
 * }}
 */
function createHookSummary(logFn, intervalMs) {
  let count = 0;
  let timer = null;
  const windowMs = intervalMs || resolveSummaryMs(process.env.HOOK_SUMMARY_MS);

  function increment() {
    count++;
  }

  function reset() {
    count = 0;
  }

  function getCount() {
    return count;
  }

  function start() {
    if (timer) return timer;
    timer = setInterval(() => {
      const n = count;
      count = 0;
      try {
        logFn(`[HOOK_SUMMARY] received ${n} hooks in last ${Math.round(windowMs / 60000)}min`);
      } catch {
        /* 日志失败绝不影响 hook 处理链路 */
      }
    }, windowMs);
    if (timer.unref) timer.unref();
    return timer;
  }

  function stop() {
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
  }

  return { increment, reset, getCount, getIntervalMs: () => windowMs, start, stop };
}

module.exports = { createHookSummary, resolveSummaryMs, DEFAULT_SUMMARY_MS };

// SPDX-License-Identifier: Apache-2.0
/**
 * @file state-store.js
 * @description viewer 运行时状态的读写入口（与用户配置分开）。
 *
 * 配置放 `settings.json`（用户可编辑）；这里放由程序自己写的运行结果，
 * 例如自动清理的上次执行记录：
 *
 *   {
 *     "version": 1,
 *     "autoCleanup": {
 *       "lastRun": {
 *         "time": "2026-11-07T01:00:00.000Z",
 *         "type": "auto",
 *         "purged_sessions": 3,
 *         "purged_events": 120,
 *         "purged_agents": 5,
 *         "purged_runs": 0
 *       }
 *     }
 *   }
 *
 * 结构与 settings.json 同构（按功能段组织），未知的顶层段原样保留；
 * 写入走 tmp + rename，避免写一半被读到。
 */

const fs = require("node:fs");
const path = require("node:path");

const { getViewerDataDir } = require("./claude-home");

const STATE_VERSION = 1;

const DEFAULT_STATE = Object.freeze({
  version: STATE_VERSION,
  autoCleanup: Object.freeze({ lastRun: null }),
});

function getStatePath() {
  return path.join(getViewerDataDir(), "state.json");
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/**
 * 归一化状态：已知字段做类型兜底，未知的顶层段原样保留。
 *
 * @param {unknown} raw
 * @returns {{version: number, autoCleanup: {lastRun: object|null}}}
 */
function normalizeState(raw) {
  const source = isPlainObject(raw) ? raw : {};
  const auto = isPlainObject(source.autoCleanup) ? source.autoCleanup : {};

  return {
    ...source,
    version: typeof source.version === "number" ? source.version : STATE_VERSION,
    autoCleanup: {
      lastRun: isPlainObject(auto.lastRun) ? auto.lastRun : null,
    },
  };
}

function writeState(state) {
  const filePath = getStatePath();
  fs.mkdirSync(path.dirname(filePath), { recursive: true });

  // 临时文件名带进程/时间戳，避免并发写共用同一个 tmp
  const tmpPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(tmpPath, JSON.stringify(state, null, 2), "utf-8");
  fs.renameSync(tmpPath, filePath);
}

/** 读取归一化后的状态（含默认值）。 */
function readState() {
  const filePath = getStatePath();
  let raw = null;

  if (fs.existsSync(filePath)) {
    try {
      raw = JSON.parse(fs.readFileSync(filePath, "utf-8"));
    } catch (err) {
      console.warn(`[state] 解析 ${filePath} 失败，使用默认状态：${err.message}`);
      raw = null;
    }
  }

  return normalizeState(raw);
}

/**
 * 更新状态：按顶层段浅合并，段内浅合并。
 *
 * @param {object} patch 例如 `{ autoCleanup: { lastRun: {...} } }`
 * @returns {object} 更新后的完整状态
 */
function updateState(patch) {
  const current = readState();
  const nextPatch = isPlainObject(patch) ? patch : {};

  const merged = { ...current };
  for (const [section, value] of Object.entries(nextPatch)) {
    if (isPlainObject(value) && isPlainObject(current[section])) {
      merged[section] = { ...current[section], ...value };
    } else {
      merged[section] = value;
    }
  }

  const next = normalizeState(merged);
  writeState(next);
  return next;
}

/** 只更新 autoCleanup 段。 */
function updateAutoCleanupState(patch) {
  return updateState({ autoCleanup: patch }).autoCleanup;
}

module.exports = {
  STATE_VERSION,
  DEFAULT_STATE,
  getStatePath,
  readState,
  updateState,
  updateAutoCleanupState,
};

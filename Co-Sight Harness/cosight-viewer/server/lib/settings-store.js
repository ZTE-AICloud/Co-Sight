// SPDX-License-Identifier: Apache-2.0
/**
 * @file settings-store.js
 * @description viewer 自有配置的读写入口。
 *
 * 配置文件统一放在 viewer 数据目录下的 `settings.json`，按「功能段」组织，
 * 便于后续增加新参数而不串味：
 *
 *   {
 *     "version": 1,
 *     "autoCleanup": {
 *       "enabled": true,
 *       "abandonHours": 24,
 *       "purgeDays": 90
 *     }
 *   }
 *
 * 这里**只放用户配置**；程序自己写的运行结果（如上次清理记录）放
 * `server/lib/state-store.js` 管理的 `state.json`。
 *
 * - 已知字段会被归一化（类型/取值范围），未知的顶层段原样保留；
 * - 文件不存在时返回默认值，不主动落盘；
 * - 写入走 tmp + rename，避免写一半被读到。
 */

const fs = require("node:fs");
const path = require("node:path");

const { getViewerDataDir } = require("./claude-home");

const SETTINGS_VERSION = 1;

/** 默认配置：自动清理默认开启，保留 90 天。 */
const DEFAULT_SETTINGS = Object.freeze({
  version: SETTINGS_VERSION,
  autoCleanup: Object.freeze({
    enabled: true,
    abandonHours: 24,
    purgeDays: 90,
  }),
});

function getSettingsPath() {
  return path.join(getViewerDataDir(), "settings.json");
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function positiveNumber(value, fallback) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : fallback;
}

/**
 * 归一化配置：已知字段补默认值与类型，未知顶层段原样保留。
 *
 * @param {unknown} raw
 * @returns {{version: number, autoCleanup: {enabled: boolean, abandonHours: number, purgeDays: number}}}
 */
function normalizeSettings(raw) {
  const source = isPlainObject(raw) ? raw : {};
  const auto = isPlainObject(source.autoCleanup) ? source.autoCleanup : {};
  const fallback = DEFAULT_SETTINGS.autoCleanup;

  return {
    ...source,
    version: typeof source.version === "number" ? source.version : SETTINGS_VERSION,
    autoCleanup: {
      enabled: typeof auto.enabled === "boolean" ? auto.enabled : fallback.enabled,
      abandonHours: positiveNumber(auto.abandonHours, fallback.abandonHours),
      purgeDays: positiveNumber(auto.purgeDays, fallback.purgeDays),
    },
  };
}

function writeSettings(settings) {
  const filePath = getSettingsPath();
  fs.mkdirSync(path.dirname(filePath), { recursive: true });

  // 临时文件名带进程/时间戳，避免并发写共用同一个 tmp
  const tmpPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(tmpPath, JSON.stringify(settings, null, 2), "utf-8");
  fs.renameSync(tmpPath, filePath);
}

/**
 * 读取配置。
 *
 * @returns {{settings: object, hasAutoCleanup: boolean}} hasAutoCleanup 表示文件里
 *   **显式**存在 autoCleanup 段。调用方需要区分「默认值」与「用户显式配置」时用它，
 *   例如废弃阈值只在显式配置时才覆盖环境变量。
 */
function readSettingsState() {
  const filePath = getSettingsPath();
  let raw = null;

  if (fs.existsSync(filePath)) {
    try {
      raw = JSON.parse(fs.readFileSync(filePath, "utf-8"));
    } catch (err) {
      console.warn(`[settings] 解析 ${filePath} 失败，使用默认配置：${err.message}`);
      raw = null;
    }
  }

  return {
    settings: normalizeSettings(raw),
    hasAutoCleanup: isPlainObject(raw) && isPlainObject(raw.autoCleanup),
  };
}

/** 读取归一化后的配置（含默认值）。 */
function readSettings() {
  return readSettingsState().settings;
}

/**
 * 更新配置：按顶层段浅合并，段内浅合并。
 *
 * @param {object} patch 例如 `{ autoCleanup: { enabled: false } }`
 * @returns {object} 更新后的完整配置
 */
function updateSettings(patch) {
  const current = readSettings();
  const nextPatch = isPlainObject(patch) ? patch : {};

  const merged = { ...current };
  for (const [section, value] of Object.entries(nextPatch)) {
    if (isPlainObject(value) && isPlainObject(current[section])) {
      merged[section] = { ...current[section], ...value };
    } else {
      merged[section] = value;
    }
  }

  const next = normalizeSettings(merged);
  writeSettings(next);
  return next;
}

/** 只更新 autoCleanup 段。 */
function updateAutoCleanup(patch) {
  return updateSettings({ autoCleanup: patch }).autoCleanup;
}

module.exports = {
  SETTINGS_VERSION,
  DEFAULT_SETTINGS,
  getSettingsPath,
  readSettings,
  readSettingsState,
  updateSettings,
  updateAutoCleanup,
};

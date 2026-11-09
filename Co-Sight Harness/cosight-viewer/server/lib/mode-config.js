// SPDX-License-Identifier: Apache-2.0
/**
 * @file mode-config.js
 * @description Centralized configuration for mode detection, priority, and path mapping.
 * Provides a single source of truth for mode-related constants and utility functions.
 */

const path = require("path");
const os = require("os");

// ─── Mode Constants ───
const MODES = {
  CLAUDE: "claude",
  COSIGHT: "cosight",
  AUTO: "auto",
};

// ─── Default mode when no --mode flag is given and auto-detect finds nothing ───
const DEFAULT_MODE = MODES.CLAUDE;

// ─── Directory Names ───
const DIR_NAMES = {
  [MODES.CLAUDE]: ".claude",
  [MODES.COSIGHT]: ".cosight",
};

// ─── Priority Order (first match wins) ───
const PRIORITY = [MODES.CLAUDE, MODES.COSIGHT];

// ─── Environment Variable Names ───
const ENV_VARS = {
  MODE: "CO_SIGHT_MODE",
  COSIGHT_HOME: "COSIGHT_HOME",
  CLAUDE_HOME: "CLAUDE_HOME",
  CLAUDE_CONFIG_DIR: "CLAUDE_CONFIG_DIR", // Claude CLI native config directory
  DASHBOARD_DATA_DIR: "DASHBOARD_DATA_DIR",
};

/**
 * Get the data directory path for a given mode.
 * @param {string} mode - The mode (claude or cosight)
 * @returns {string|null} The data directory path, or null if mode is falsy
 */
function getDataDir(mode) {
  if (!mode) return null;
  const dirName = DIR_NAMES[mode];
  if (!dirName) {
    throw new Error(`Unknown mode: ${mode}. Valid modes: ${Object.keys(DIR_NAMES).join(", ")}`);
  }
  return path.join(os.homedir(), dirName);
}

/**
 * Get the directory name for a given mode.
 * @param {string} mode - The mode (claude or cosight)
 * @returns {string} The directory name (e.g., ".claude")
 */
function getDirName(mode) {
  const dirName = DIR_NAMES[mode];
  if (!dirName) {
    throw new Error(`Unknown mode: ${mode}. Valid modes: ${Object.keys(DIR_NAMES).join(", ")}`);
  }
  return dirName;
}

/**
 * Get all valid mode values.
 * @returns {string[]} Array of valid mode strings
 */
function getValidModes() {
  return Object.values(MODES).filter((m) => typeof m === "string");
}

/**
 * Check if a mode string is valid.
 * @param {string} mode - The mode to check
 * @returns {boolean} True if valid
 */
function isValidMode(mode) {
  return getValidModes().includes(mode);
}

/**
 * Get the environment variables object for a given mode.
 * Useful for spawning child processes with correct mode configuration.
 * Sets CLAUDE_CONFIG_DIR (Claude CLI native) for proper directory resolution.
 * @param {string} mode - The mode (claude or cosight)
 * @param {object} baseEnv - Base environment variables to extend
 * @returns {object} Environment variables object
 */
function getEnvForMode(mode, baseEnv = {}) {
  const dataDir = getDataDir(mode);
  // 使用新数据目录:~/.cosight-harness/cosight-viewer/
  // 保持与 co-sight-viewer-start.cjs 和 cli.js 一致
  const dashboardDataDir = path.join(os.homedir(), ".cosight-harness", "cosight-viewer");
  return {
    ...baseEnv,
    [ENV_VARS.MODE]: mode,
    [ENV_VARS.COSIGHT_HOME]: dataDir,
    [ENV_VARS.CLAUDE_HOME]: dataDir,
    [ENV_VARS.CLAUDE_CONFIG_DIR]: dataDir, // Claude CLI native env var
    [ENV_VARS.DASHBOARD_DATA_DIR]: dashboardDataDir,
  };
}

module.exports = {
  // Constants
  MODES,
  DIR_NAMES,
  PRIORITY,
  ENV_VARS,
  DEFAULT_MODE,

  // Utility functions
  getDataDir,
  getDirName,
  getValidModes,
  isValidMode,
  getEnvForMode,
};

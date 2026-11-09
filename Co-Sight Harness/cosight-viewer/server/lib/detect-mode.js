// SPDX-License-Identifier: Apache-2.0
/**
 * @file detect-mode.js
 * @description Detects whether Claude Code and/or Cosight Code are installed
 * on the current system. Checks for the CLI command (via which/where) and the
 * data directory (~/.claude or ~/.cosight). Supports Linux, macOS, and Windows.
 */

const { execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { MODES, PRIORITY, DIR_NAMES } = require("./mode-config");

/**
 * Detect whether a single tool (claude or cosight) is installed.
 * Checks both the CLI command and the data directory.
 */
function detectTool(toolName, isWindows) {
  const homeDir = os.homedir();
  const dirName = DIR_NAMES[toolName];
  if (!dirName) {
    throw new Error(`Unknown tool: ${toolName}. Valid tools: ${Object.keys(DIR_NAMES).join(", ")}`);
  }
  const dataDir = path.join(homeDir, dirName);

  // Check CLI command
  let commandPath = null;
  let installed = false;

  try {
    const cmd = isWindows ? "where" : "which";
    const result = execFileSync(cmd, [toolName], {
      encoding: "utf-8",
      stdio: ["pipe", "pipe", "ignore"],
      windowsHide: true,
    }).trim();

    if (result) {
      // Windows `where` may return multiple lines; take the first
      commandPath = isWindows ? result.split("\n")[0].trim() : result;
      installed = true;
    }
  } catch {
    installed = false;
  }

  // Check data directory
  let dataDirExists = false;
  try {
    dataDirExists = fs.existsSync(dataDir) && fs.statSync(dataDir).isDirectory();
  } catch {
    dataDirExists = false;
  }

  return { installed, commandPath, dataDir, dataDirExists };
}

/**
 * Determine the current runtime mode from environment variables.
 * Priority:
 * 1. COSIGHT_HOME - If contains ".cosight" → cosight mode, otherwise claude mode
 * 2. CLAUDE_CONFIG_DIR - Claude CLI native config directory (claude mode)
 * 3. Default: claude mode
 */
function detectCurrentMode() {
  // Priority 1: COSIGHT_HOME is set (framework container)
  const cosightHome = process.env.COSIGHT_HOME;
  if (cosightHome) {
    if (cosightHome.includes(".cosight")) {
      return "cosight";
    }
    return "claude";
  }

  // Priority 2: CLAUDE_CONFIG_DIR is set - always claude mode (Claude CLI native)
  if (process.env.CLAUDE_CONFIG_DIR) {
    return "claude";
  }

  // Priority 3: Default to claude mode
  return "claude";
}

/**
 * Detect installation status of Claude Code and Cosight Code.
 * Returns a ModeStatus object with per-tool details, current mode,
 * recommended mode, and whether any tool is installed.
 */
function detectClaudeCosight() {
  const isWindows = process.platform === "win32";

  const claude = detectTool(MODES.CLAUDE, isWindows);
  const cosight = detectTool(MODES.COSIGHT, isWindows);
  const currentMode = detectCurrentMode();

  // Use PRIORITY array to determine recommended mode
  let recommendedMode = null;
  for (const mode of PRIORITY) {
    const tool = mode === MODES.CLAUDE ? claude : cosight;
    if (tool.installed) {
      recommendedMode = mode;
      break;
    }
  }

  const anyInstalled = claude.installed || cosight.installed;

  return { claude, cosight, currentMode, recommendedMode, anyInstalled };
}

/**
 * CLI使用的简化版本：根据安装情况决定应该使用的模式
 * 使用 PRIORITY 数组确定优先级顺序
 * @returns {"claude"|"cosight"|null}
 */
function getRecommendedMode() {
  const isWindows = process.platform === "win32";

  for (const mode of PRIORITY) {
    const tool = detectTool(mode, isWindows);
    if (tool.installed) return mode;
  }

  return MODES.NEUTRAL;
}

module.exports = {
  detectClaudeCosight,
  detectCurrentMode,
  getRecommendedMode,
};

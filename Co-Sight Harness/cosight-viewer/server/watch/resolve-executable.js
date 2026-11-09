// SPDX-License-Identifier: Apache-2.0
/**
 * @fileoverview Resolve the claude executable path.
 * Environment variable CC_EXECUTABLE > which claude > fallback 'claude'.
 */

const { execFileSync } = require("child_process");

let _cachedExecutable = null;

/**
 * @returns {string}
 */
function resolveClaudeExecutable() {
  if (_cachedExecutable) return _cachedExecutable;
  if (process.env.CC_EXECUTABLE) {
    _cachedExecutable = process.env.CC_EXECUTABLE;
    return _cachedExecutable;
  }
  try {
    // Use 'which' on Unix, 'where' on Windows to resolve PATH
    const cmd = process.platform === "win32" ? "where" : "which";
    const result = execFileSync(cmd, ["claude"], {
      encoding: "utf8",
      windowsHide: true,
    }).trim();
    // Validate: should be an absolute path, not an alias
    if (result && !result.startsWith("alias") && !result.includes("=")) {
      _cachedExecutable = result;
      return _cachedExecutable;
    }
  } catch {
    // which/where failed
  }
  // Fallback: let spawn resolve 'claude' from PATH
  _cachedExecutable = "claude";
  return _cachedExecutable;
}

module.exports = { resolveClaudeExecutable };

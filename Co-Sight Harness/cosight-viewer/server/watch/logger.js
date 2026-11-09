// SPDX-License-Identifier: Apache-2.0
/**
 * @fileoverview Backward-compatible logger wrapper.
 *
 * Delegates to the unified structured logger (server/lib/unified-logger.js).
 * Maintains the legacy log(prefix, message) / logError(prefix, message) API
 * so all 22+ existing call sites work without changes.
 *
 * Old output: plain text log files
 * New output: {modeHome}/logs/cosight-viewer.log (NDJSON via pino)
 */

const { createChildLogger, getLogFile: unifiedGetLogFile } = require("../lib/unified-logger");

/**
 * Legacy log function — maps to unified logger child with the given prefix.
 * @param {string} prefix — module/component name (e.g. "watch", "hooks", "startup")
 * @param {string} message — log message text
 */
function log(prefix, message) {
  try {
    const child = createChildLogger(prefix);
    child.info(message);
  } catch {
    // Non-fatal — logging should never crash the daemon
  }
}

/**
 * Debug level log function — maps to unified logger debug level.
 * Only outputs when log level is set to debug.
 * @param {string} prefix — module/component name (e.g. "watch", "hooks", "startup")
 * @param {string} message — log message text
 */
function logDebug(prefix, message) {
  try {
    const child = createChildLogger(prefix);
    child.debug(message);
  } catch {
    // Non-fatal — logging should never crash the daemon
  }
}

/**
 * Legacy error log function — maps to unified logger error level.
 * @param {string} prefix — module/component name
 * @param {string} message — error message text
 */
function logError(prefix, message) {
  try {
    const child = createChildLogger(prefix);
    child.error(message);
  } catch {
    // Non-fatal
  }
}

/**
 * Returns the current log file path.
 * @returns {string}
 */
function getLogFile() {
  return unifiedGetLogFile();
}

module.exports = { log, logDebug, logError, getLogFile };

// SPDX-License-Identifier: Apache-2.0
/**
 * @file Hook 配置管理
 *
 * Hook 脚本路径管理
 */
const path = require("path");
const { createChildLogger } = require("./unified-logger");

const log = createChildLogger("hook-config");

// ==================== API 基础路径 ====================

/**
 * 获取 API 基础路径
 * @returns {string}
 */
function getApiBasePath() {
  if (process.env.API_BASE_PATH !== undefined && process.env.API_BASE_PATH !== "") {
    let p = process.env.API_BASE_PATH;
    if (!p.startsWith("/")) p = "/" + p;
    p = p.replace(/\/+$/, "");
    return p;
  }
  return "";
}

// ==================== 路径管理 ====================

/**
 * 获取 Hook 脚本的路径
 * @returns {string}
 */
function getHookHandlerPath() {
  return path.resolve(__dirname, "..", "..", "scripts", "cosight-viewer-hook-handler.js");
}

module.exports = {
  getApiBasePath,
  getHookHandlerPath,
};

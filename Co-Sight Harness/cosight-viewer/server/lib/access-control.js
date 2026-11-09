// SPDX-License-Identifier: Apache-2.0
/**
 * @file access-control.js
 * @description 文件浏览/读取接口的跨机访问策略。
 *
 * 默认**不限制来源**：服务本身默认监听 0.0.0.0，局域网打开页面后，
 * 正文里的文件链接、附件预览都需要能读到文件。
 *
 * 如需收紧，设置环境变量：
 *   VIEWER_FS_LOCAL_ONLY=1
 * 只允许回环地址（127.0.0.1 / ::1）访问 `/fs/*` 与 `/session-files/*`。
 *
 * 注意：默认放开意味着同网段机器可以读到本机绝对路径下的文本文件
 * （上限 2 MiB）以及原始字节流。只在可信网络使用；共享网络建议打开开关。
 */

const LOOPBACK_ADDRESSES = new Set(["127.0.0.1", "::1", "::ffff:127.0.0.1"]);

/** 是否是回环地址。 */
function isLoopbackAddress(address) {
  return LOOPBACK_ADDRESSES.has(String(address || ""));
}

/** 请求是否来自本机回环。只信任 socket 对端地址，不解析代理头。 */
function isLoopback(req) {
  return isLoopbackAddress(req && req.socket && req.socket.remoteAddress);
}

/** 是否配置了“只允许本机”。默认 false（不做限制）。 */
function isLocalOnlyEnabled() {
  const raw = process.env.VIEWER_FS_LOCAL_ONLY;
  if (raw === undefined || raw === "") return false;
  const value = String(raw).trim().toLowerCase();
  return value === "1" || value === "true" || value === "yes" || value === "on";
}

/** 当前请求是否允许访问文件接口。 */
function allowRequest(req) {
  return !isLocalOnlyEnabled() || isLoopback(req);
}

module.exports = {
  isLoopbackAddress,
  isLoopback,
  isLocalOnlyEnabled,
  allowRequest,
};

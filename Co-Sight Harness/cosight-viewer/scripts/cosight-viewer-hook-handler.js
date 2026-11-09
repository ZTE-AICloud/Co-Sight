#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0

/**
 * Claude Code hook handler.
 * Receives hook event JSON on stdin and forwards it to cosight-viewer.
 *
 * 运行场景：单机模式，请求 127.0.0.1:4830
 *
 * Designed to fail silently so it never blocks Claude Code.
 * Delivery is fire-and-forget: we exit as soon as the request body is on the
 * wire, WITHOUT waiting for the dashboard's HTTP response.
 *
 */

const http = require("http");

const hookType = process.argv[2] || "unknown";

// 来源标记：安装 hook 时按目标 CLI 写入 `--source claude|cosight`。
// 两个 CLI 调用同一个 handler，这个参数让 server 不必靠路径去猜。
const sourceIndex = process.argv.indexOf("--source");
const viewerSource =
  sourceIndex >= 0 && process.argv[sourceIndex + 1] ? process.argv[sourceIndex + 1] : null;

// ==================== 目标地址配置 ====================

// API 基础路径：与 server/lib/hook-config.js getApiBasePath() 保持一致
// - 优先读取环境变量 API_BASE_PATH（用户显式配置）
// - 默认：""（空字符串，API 在根路径）
function getApiBasePath() {
  if (process.env.API_BASE_PATH !== undefined && process.env.API_BASE_PATH !== "") {
    let p = process.env.API_BASE_PATH;
    if (!p.startsWith("/")) p = "/" + p;
    p = p.replace(/\/+$/, "");
    return p;
  }
  return "";
}

/**
 * 解析目标服务器地址
 * 单机模式：使用默认地址 127.0.0.1:4830
 */
function resolveTargets() {
  return [{ ip: "127.0.0.1", port: 4830 }];
}

const targets = resolveTargets();

// ==================== 主流程 ====================

let input = "";

process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => (input += chunk));
process.stdin.on("end", () => {
  let parsedData;
  try {
    parsedData = JSON.parse(input);
  } catch {
    parsedData = { raw: input };
  }

  const payload = JSON.stringify({
    hook_type: hookType,
    viewer_source: viewerSource,
    data: parsedData,
  });
  const contentLength = Buffer.byteLength(payload);

  // Fan out one POST per target. Each per-target promise resolves the
  // moment the request body has been flushed — NOT when the dashboard replies
  // — so a busy, slow, or wedged dashboard can't stall the hook.
  const sends = targets.map(
    ({ ip, port }) =>
      new Promise((resolve) => {
        let settled = false;
        const done = () => {
          if (settled) return;
          settled = true;
          resolve();
        };

        const req = http.request(
          {
            hostname: ip,
            port,
            path: `${getApiBasePath()}/hooks/event`,
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "Content-Length": contentLength,
            },
            timeout: 2000,
          },
          (res) => res.resume()
        );

        req.on("error", done);
        req.on("timeout", () => {
          req.destroy();
          done();
        });
        req.write(payload);
        req.end(done);
      })
  );

  Promise.all(sends).finally(() => setImmediate(() => process.exit(0)));
});

// Safety net — guarantees the hook never blocks Claude Code.
setTimeout(() => process.exit(0), 2500);

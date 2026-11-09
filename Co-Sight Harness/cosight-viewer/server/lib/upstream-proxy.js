// SPDX-License-Identifier: Apache-2.0
/**
 * @file upstream-proxy.js
 * @description 同源反代：把浏览器对 viewer 的相对请求转发到本机上游服务。
 *
 * 模块（viewer）在宿主里以 iframe 挂载，自己的源是 `:4830`。它调框架 `:4300`
 * 与 smart-factory `:4100` 时，若直接写死回环地址，局域网/远程浏览器会打在
 * 客户端自己身上，并且跨源还会被框架 CORS 拦掉。
 *
 * 由 viewer 服务端代理后：
 *   - 浏览器只访问 `http://<当前主机>:4830/...`，不存在跨源；
 *   - 上游固定走 `127.0.0.1`，不依赖用户配置；
 *   - 前端也不再硬编码 `127.0.0.1` / `localhost`。
 *
 * 只代理 REST；WebSocket 由 `ws-proxy.js` 在 HTTP upgrade 阶段单独接管。
 */

const http = require("node:http");
const { URL } = require("node:url");

/**
 * 创建一个 Express 中间件。
 *
 * @param {object} options
 * @param {string} options.target 上游源，例如 `http://127.0.0.1:4300`
 * @param {(path: string) => string} [options.rewritePath] 路径重写（含查询串）
 * @param {number} [options.timeoutMs] 上游超时
 */
function createProxy({ target, rewritePath = (p) => p, timeoutMs = 30_000 }) {
  const targetUrl = new URL(target);
  const port = targetUrl.port ? Number(targetUrl.port) : targetUrl.protocol === "https:" ? 443 : 80;

  return function proxy(req, res) {
    const originalPath = req.originalUrl || req.url || "/";
    let path;
    try {
      path = rewritePath(originalPath);
    } catch {
      path = originalPath;
    }
    if (!path.startsWith("/")) path = `/${path}`;

    const headers = { ...req.headers, host: targetUrl.host };
    // 同源反代到本机上游：不把浏览器的 Origin/Referer 传下去，避免上游做来源判断。
    delete headers.origin;
    delete headers.referer;
    // 让 Node 自己决定连接头，转发浏览器原始值可能造成 keep-alive 语义混乱。
    delete headers.connection;

    const proxyReq = http.request(
      {
        protocol: targetUrl.protocol,
        hostname: targetUrl.hostname,
        port,
        method: req.method,
        path,
        headers,
        timeout: timeoutMs,
      },
      (proxyRes) => {
        res.writeHead(proxyRes.statusCode || 502, proxyRes.headers);
        proxyRes.pipe(res);
      },
    );

    proxyReq.on("timeout", () => {
      proxyReq.destroy(new Error(`上游响应超时（${timeoutMs}ms）`));
    });

    proxyReq.on("error", (err) => {
      if (res.headersSent) {
        res.destroy();
        return;
      }
      const body = JSON.stringify({
        error: { code: "BAD_GATEWAY", message: `上游服务不可达：${err.message}` },
      });
      res.writeHead(502, {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Length": Buffer.byteLength(body),
      });
      res.end(body);
    });

    req.on("aborted", () => proxyReq.destroy(new Error("客户端已断开")));
    req.pipe(proxyReq);
  };
}

module.exports = { createProxy };

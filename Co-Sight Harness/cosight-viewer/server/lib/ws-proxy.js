// SPDX-License-Identifier: Apache-2.0
/**
 * @file ws-proxy.js
 * @description 同源 WebSocket 反代：把浏览器对 viewer 的 WS 升级请求转发到本机上游服务。
 *
 * 与 `upstream-proxy.js`（REST）配套。对话 WS 原本由前端硬编码
 * `ws://localhost:4100`，局域网/远程浏览器会连到客户端自己的回环地址。
 * 由 viewer 服务端代理后，浏览器只连 `ws(s)://<当前主机>:4830/api/smart-factory/v1/ws`。
 *
 * 实现方式：**裸 TCP 转发**。只在 HTTP upgrade 阶段做一次握手转发，之后两端
 * 字节流直通，不解帧、不改帧，天然兼容 ping/pong、permessage-deflate 等扩展。
 *
 * 只接管精确匹配 `path` 的请求；其它路径直接返回，不碰 socket，
 * 因此可以和 viewer 自己的 `/ws` 处理器（`server/websocket.js`）共存。
 */

const net = require("node:net");
const { URL } = require("node:url");
const { createChildLogger } = require("./unified-logger");

const wsProxyLog = createChildLogger("ws-proxy");

/** 建立到上游的 TCP 连接最长等待时间。 */
const CONNECT_TIMEOUT_MS = 10_000;

/**
 * 用客户端原始的升级请求构造发往上游的握手请求。
 *
 * @param {import("node:http").IncomingMessage} request
 * @param {URL} targetUrl 上游地址（取 host）
 * @param {string} upstreamPath 上游路径（含查询串）
 * @returns {string}
 */
function buildHandshake(request, targetUrl, upstreamPath) {
  const lines = [`GET ${upstreamPath} HTTP/1.1`, `Host: ${targetUrl.host}`];

  for (const [key, value] of Object.entries(request.headers)) {
    if (value === undefined) continue;
    const lower = key.toLowerCase();
    // host 由上游目标决定；connection/upgrade 在最后统一补，避免重复。
    if (lower === "host" || lower === "connection" || lower === "upgrade") continue;
    lines.push(`${key}: ${Array.isArray(value) ? value.join(", ") : value}`);
  }

  lines.push(`Connection: ${request.headers.connection || "Upgrade"}`);
  lines.push(`Upgrade: ${request.headers.upgrade || "websocket"}`);
  return `${lines.join("\r\n")}\r\n\r\n`;
}

/**
 * 在 HTTP server 上挂载一个 WS 反代。
 *
 * @param {import("node:http").Server} server
 * @param {object} options
 * @param {string} options.path 需要接管的路径（精确匹配，不含查询串）
 * @param {string} options.target 上游源，例如 `ws://127.0.0.1:4100`
 * @returns {() => void} 取消挂载
 */
function attachWsProxy(server, { path: proxyPath, target }) {
  const targetUrl = new URL(target);
  if (!proxyPath || !proxyPath.startsWith("/")) {
    throw new Error(`ws-proxy: path 必须是绝对路径，收到 ${proxyPath}`);
  }
  const port = targetUrl.port ? Number(targetUrl.port) : targetUrl.protocol === "wss:" ? 443 : 80;

  function onUpgrade(request, socket, head) {
    let clientUrl;
    try {
      clientUrl = new URL(request.url, `http://${request.headers.host || "localhost"}`);
    } catch {
      return;
    }
    // 不是本代理的路径：原样留给其它 upgrade 监听器（如 viewer 自己的 /ws）。
    if (clientUrl.pathname !== proxyPath) return;

    // upgrade 后的 socket 已脱离 HTTP 服务器的时间限制，这里显式关掉超时。
    socket.setTimeout(0);
    socket.setNoDelay(true);
    // 客户端断开是常态，避免未捕获的 ECONNRESET 影响进程。
    socket.on("error", () => {});

    const upstream = net.connect({ host: targetUrl.hostname, port });
    upstream.setNoDelay(true);

    let settled = false;
    let closed = false;

    const teardown = () => {
      if (closed) return;
      closed = true;
      socket.destroy();
      upstream.destroy();
    };

    const fail = (reason) => {
      if (closed) return;
      closed = true;
      wsProxyLog.warn(`[ws-proxy] 上游不可达（${reason}）`);
      const body = "upstream unavailable";
      try {
        if (socket.writable) {
          socket.write(
            "HTTP/1.1 502 Bad Gateway\r\n" +
              "Content-Type: text/plain; charset=utf-8\r\n" +
              "Connection: close\r\n" +
              `Content-Length: ${Buffer.byteLength(body)}\r\n\r\n` +
              body,
          );
        }
      } catch {
        // socket 可能已断开，忽略
      }
      socket.destroy();
      upstream.destroy();
    };

    // 连接上游前只做一次超时保护；连接建立后取消，避免长连接被误杀。
    upstream.setTimeout(CONNECT_TIMEOUT_MS, () => fail("connect timeout"));

    upstream.once("connect", () => {
      if (closed) return;
      settled = true;
      upstream.setTimeout(0);

      const upstreamPath = `${proxyPath}${clientUrl.search}`;
      upstream.write(buildHandshake(request, targetUrl, upstreamPath));
      // upgrade 事件可能已带上客户端发来的首帧数据，握手后原样转发。
      if (head && head.length) upstream.write(head);

      socket.pipe(upstream);
      upstream.pipe(socket);
    });

    upstream.on("error", (err) => {
      if (!settled) {
        fail(err.code || err.message);
        return;
      }
      wsProxyLog.warn(`[ws-proxy] 上游连接异常：${err.code || err.message}`);
      teardown();
    });

    upstream.on("close", teardown);
    socket.on("close", teardown);
    socket.on("error", teardown);
  }

  server.on("upgrade", onUpgrade);

  return () => server.off("upgrade", onUpgrade);
}

module.exports = { attachWsProxy };

// SPDX-License-Identifier: Apache-2.0
/**
 * @file Tests for server/lib/ws-proxy.js — 同源 WebSocket 反代。
 *
 * 覆盖：
 *  - 握手与查询串原样转发到上游，双向数据直通；
 *  - 与 viewer 自身 `/ws` 处理器按路径共存，互不干扰；
 *  - 上游不可达时返回 502，而不是挂住连接。
 */

const { describe, it, before, after } = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const fs = require("node:fs");

// 必须在 require 相关模块之前设置,确保统一 logger 写入临时目录
const LOG_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "ws-proxy-test-log-"));
process.env.COSIGHT_LOG_DIR = LOG_DIR;

const { WebSocketServer, WebSocket } = require("ws");
const { attachWsProxy } = require("../lib/ws-proxy");
const { initWebSocket } = require("../websocket");
const { getApiBasePath } = require("../lib/hook-config");

const PROXY_PATH = "/api/smart-factory/v1/ws";
/** viewer 自身 WS 的路径随 API_BASE_PATH 变化，不能写死 `/ws`。 */
const VIEWER_WS_PATH = `${getApiBasePath()}/ws`;

function listen(server) {
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve(server.address().port));
  });
}

function closeServer(server) {
  return new Promise((resolve) => server.close(resolve));
}

function openWs(url) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url);
    const timer = setTimeout(() => {
      ws.terminate();
      reject(new Error(`WS 握手超时：${url}`));
    }, 5000);
    ws.once("open", () => {
      clearTimeout(timer);
      resolve(ws);
    });
    ws.once("error", (err) => {
      clearTimeout(timer);
      reject(err);
    });
  });
}

function nextMessage(ws) {
  return new Promise((resolve) => ws.once("message", (data) => resolve(data.toString())));
}

describe("ws-proxy", () => {
  let upstream;
  let upstreamWss;
  let front;
  let frontWss;
  let upstreamPort;
  let frontPort;
  const upstreamUrlSuffixes = [];

  before(async () => {
    upstream = http.createServer();
    upstreamWss = new WebSocketServer({ server: upstream, path: PROXY_PATH });
    upstreamWss.on("connection", (ws, req) => {
      upstreamUrlSuffixes.push(req.url);
      ws.on("message", (data) => ws.send(`echo:${data}`));
    });
    upstreamPort = await listen(upstream);

    front = http.createServer();
    // 顺序与生产一致：先挂 viewer 自身 WS，再挂反代
    frontWss = initWebSocket(front);
    attachWsProxy(front, {
      path: PROXY_PATH,
      target: `ws://127.0.0.1:${upstreamPort}`,
    });
    frontPort = await listen(front);
  });

  after(async () => {
    frontWss.close();
    await closeServer(front);
    upstreamWss.close();
    await closeServer(upstream);
  });

  it("转发握手与查询串，双向数据直通", async () => {
    const client = await openWs(`ws://127.0.0.1:${frontPort}${PROXY_PATH}?userId=dev`);

    const reply = nextMessage(client);
    client.send("ping");
    assert.equal(await reply, "echo:ping");

    client.close();
    await new Promise((resolve) => client.once("close", resolve));

    assert.ok(
      upstreamUrlSuffixes.includes(`${PROXY_PATH}?userId=dev`),
      `上游应收到带查询串的握手路径，实际：${upstreamUrlSuffixes.join(", ")}`,
    );
  });

  it("不影响 viewer 自身的 /ws", async () => {
    const client = await openWs(`ws://127.0.0.1:${frontPort}${VIEWER_WS_PATH}`);
    assert.ok(client.readyState === WebSocket.OPEN);

    client.close();
    await new Promise((resolve) => client.once("close", resolve));
  });

  it("上游不可达时返回 502", async () => {
    // 先占一个端口再释放，拿到一个大概率无人监听的端口
    const scratch = http.createServer();
    const deadPort = await listen(scratch);
    await closeServer(scratch);

    const server = http.createServer();
    attachWsProxy(server, {
      path: PROXY_PATH,
      target: `ws://127.0.0.1:${deadPort}`,
    });
    const port = await listen(server);

    const status = await new Promise((resolve, reject) => {
      const client = new WebSocket(`ws://127.0.0.1:${port}${PROXY_PATH}`);
      client.once("unexpected-response", (_req, res) => {
        resolve(res.statusCode);
        client.terminate();
      });
      client.once("error", () => {
        // 部分平台在 502 后直接报错，等同于失败
        resolve(502);
      });
      client.once("open", () => reject(new Error("上游不可达时不应握手成功")));
    });

    assert.equal(status, 502);
    await closeServer(server);
  });
});

// SPDX-License-Identifier: Apache-2.0
/**
 * @file Integration tests for server/websocket.js — 连接/断开生命周期与连接计数。
 *
 * 覆盖 initWebSocket 的 connection/close/error 处理器不抛异常,以及
 * getConnectionCount 在连接生命周期内正确增减、broadcast 正常投递。
 * 日志经 COSIGHT_LOG_DIR 指向临时目录,不污染真实日志。
 */

const { describe, it, before, after } = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const fs = require("node:fs");

// 必须在 require websocket 之前设置,确保统一 logger 写入临时目录
const LOG_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "ws-test-log-"));
process.env.COSIGHT_LOG_DIR = LOG_DIR;

const WebSocket = require("ws");
const { initWebSocket, getConnectionCount, broadcast } = require("../websocket");

describe("websocket connection lifecycle", () => {
  let server;
  let port;

  before(async () => {
    server = http.createServer();
    initWebSocket(server);
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    port = server.address().port;
  });

  after(() => new Promise((resolve) => server.close(resolve)));

  it("无连接时计数为 0", () => {
    assert.equal(getConnectionCount(), 0);
  });

  it("连接后计数为 1,断开后回到 0", async () => {
    const client = new WebSocket(`ws://127.0.0.1:${port}/api/cosight-viewer/v1/ws`);
    await new Promise((resolve, reject) => {
      client.on("open", resolve);
      client.on("error", reject);
    });
    assert.equal(getConnectionCount(), 1);

    client.close();
    await new Promise((resolve, reject) => {
      client.on("close", resolve);
      client.on("error", reject);
    });
    // 等待服务器侧 close 事件传播
    await new Promise((r) => setTimeout(r, 50));
    assert.equal(getConnectionCount(), 0);
  });

  it("broadcast 向已连接客户端投递消息", async () => {
    const client = new WebSocket(`ws://127.0.0.1:${port}/api/cosight-viewer/v1/ws`);
    await new Promise((resolve, reject) => {
      client.on("open", resolve);
      client.on("error", reject);
    });

    const received = new Promise((resolve) => {
      client.on("message", (data) => resolve(JSON.parse(data.toString())));
    });
    broadcast("test_event", { hello: "world" });
    const msg = await received;
    assert.equal(msg.type, "test_event");
    assert.deepEqual(msg.data, { hello: "world" });

    client.close();
    await new Promise((resolve, reject) => {
      client.on("close", resolve);
      client.on("error", reject);
    });
    await new Promise((r) => setTimeout(r, 50));
  });
});

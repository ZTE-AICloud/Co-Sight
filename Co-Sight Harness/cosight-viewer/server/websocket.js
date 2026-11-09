// SPDX-License-Identifier: Apache-2.0
/**
 * @file WebSocket functionalities for real-time communication with clients, including connection management, heartbeat for detecting dead connections, and broadcasting messages to all connected clients.
 */

const { WebSocketServer } = require("ws");
const { createChildLogger } = require("./lib/unified-logger");
const { getApiBasePath } = require("./lib/hook-config");

const wsLog = createChildLogger("ws");

let wss = null;

function initWebSocket(server) {
  const WS_PATH = `${getApiBasePath()}/ws`;
  // 使用 noServer: true 手动处理 upgrade，避免 ws 库关闭不匹配路径的连接
  wss = new WebSocketServer({ noServer: true, maxPayload: 64 * 1024 });

  // 手动处理 upgrade 事件
  server.on("upgrade", (request, socket, head) => {
    const pathname = new URL(request.url, `http://${request.headers.host}`).pathname;

    if (pathname === WS_PATH) {
      wss.handleUpgrade(request, socket, head, (ws) => {
        wss.emit("connection", ws, request);
      });
    }
    // 不匹配的路径不做处理，让其他处理器（如 agent-runtime 代理）处理
  });

  wss.on("connection", (ws) => {
    ws.isAlive = true;
    ws.on("pong", () => {
      ws.isAlive = true;
    });
    ws.on("error", (err) => {
      // Log but don't crash — client disconnects are normal
      if (err.code !== "ECONNRESET") {
        wsLog.warn(`[WS] client error: ${err.code || err.message}`);
      }
    });
    ws.on("close", () => {
      wsLog.info(`[WS] client disconnected, connections=${getConnectionCount()}`);
    });
    wsLog.info(`[WS] client connected, connections=${getConnectionCount()}`);
  });

  // Heartbeat every 30s to detect dead connections
  const interval = setInterval(() => {
    if (!wss) {
      clearInterval(interval);
      return;
    }
    wss.clients.forEach((ws) => {
      if (!ws.isAlive) {
        ws.terminate();
        return;
      }
      ws.isAlive = false;
      ws.ping();
    });
  }, 30000);
  interval.unref();

  wss.on("close", () => {
    clearInterval(interval);
  });

  return wss;
}

function broadcast(type, data) {
  if (!wss) return;
  const message = JSON.stringify({ type, data, timestamp: new Date().toISOString() });
  wss.clients.forEach((client) => {
    if (client.readyState === 1) {
      try {
        client.send(message);
      } catch {
        // Client closed between readyState check and send — safe to ignore
      }
    }
  });
}

function getConnectionCount() {
  if (!wss) return 0;
  let count = 0;
  wss.clients.forEach((client) => {
    if (client.readyState === 1) count++;
  });
  return count;
}

module.exports = { initWebSocket, broadcast, getConnectionCount };

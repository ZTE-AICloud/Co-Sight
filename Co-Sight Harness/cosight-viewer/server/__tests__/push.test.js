// SPDX-License-Identifier: Apache-2.0
/**
 * @file Tests for push notification API endpoints, covering subscription management and sending notifications. It verifies that the server correctly handles subscription creation, deletion, and sending push messages, ensuring proper validation and response formats.
 */

const { describe, it, before, after } = require("node:test");
const assert = require("node:assert/strict");
const path = require("path");
const os = require("os");
const http = require("http");

// Isolate test database
const TEST_DB = path.join(os.tmpdir(), `push-test-${Date.now()}-${process.pid}.db`);
process.env.DASHBOARD_DB_PATH = TEST_DB;

const { createApp, startServer } = require("../index");

let server;
let BASE;
const BASE_PATH = "/api/cosight-viewer/v1";

function request(urlPath, options = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(BASE_PATH + urlPath.replace(/^\/api/, ""), BASE);
    const bodyString = options.body ? JSON.stringify(options.body) : null;
    const opts = {
      hostname: url.hostname,
      port: url.port,
      path: url.pathname + url.search,
      method: options.method || "GET",
      headers: {
        "Content-Type": "application/json",
        ...(bodyString ? { "Content-Length": Buffer.byteLength(bodyString) } : {}),
        ...options.headers,
      },
    };
    const req = http.request(opts, (res) => {
      let body = "";
      res.on("data", (chunk) => (body += chunk));
      res.on("end", () => {
        let parsed;
        try {
          parsed = JSON.parse(body);
        } catch {
          parsed = body;
        }
        resolve({ status: res.statusCode, body: parsed });
      });
    });
    req.on("error", reject);
    if (bodyString) req.write(bodyString);
    req.end();
  });
}

function post(urlPath, body) {
  return request(urlPath, { method: "POST", body });
}

function del(urlPath, body) {
  return request(urlPath, { method: "DELETE", body });
}

before(async () => {
  const app = createApp();
  server = await startServer(app, 0);
  const addr = server.address();
  BASE = `http://127.0.0.1:${addr.port}`;
});

after(async () => {
  await new Promise((resolve) => server.close(resolve));
  const fs = require("fs");
  try {
    fs.unlinkSync(TEST_DB);
  } catch {}
});

describe("GET /api/push/vapid-public-key", () => {
  it("returns a non-empty public key string", async () => {
    const res = await request("/api/push/vapid-public-key");
    assert.equal(res.status, 200);
    assert.ok(typeof res.body.publicKey === "string");
    assert.ok(res.body.publicKey.length > 0);
  });
});

describe("POST /api/push/subscribe", () => {
  it("stores a subscription and returns ok", async () => {
    const res = await post("/api/push/subscribe", {
      endpoint: "https://example.com/push/abc123",
      keys: { p256dh: "dGVzdA==", auth: "dGVzdA==" },
    });
    assert.equal(res.status, 200);
    assert.equal(res.body.ok, true);
  });

  it("returns 400 when endpoint is missing", async () => {
    const res = await post("/api/push/subscribe", {
      keys: { p256dh: "dGVzdA==", auth: "dGVzdA==" },
    });
    assert.equal(res.status, 400);
  });

  it("returns 400 when keys are missing", async () => {
    const res = await post("/api/push/subscribe", {
      endpoint: "https://example.com/push/abc123",
    });
    assert.equal(res.status, 400);
  });
});

describe("DELETE /api/push/subscribe", () => {
  it("removes a subscription and returns ok", async () => {
    const endpoint = "https://example.com/push/to-delete";
    await post("/api/push/subscribe", {
      endpoint,
      keys: { p256dh: "dGVzdA==", auth: "dGVzdA==" },
    });
    const res = await del("/api/push/subscribe", { endpoint });
    assert.equal(res.status, 200);
    assert.equal(res.body.ok, true);
  });

  it("returns 400 when endpoint is missing", async () => {
    const res = await del("/api/push/subscribe", {});
    assert.equal(res.status, 400);
  });
});

describe("POST /api/push/send", () => {
  it("returns ok when there are no subscriptions", async () => {
    const res = await post("/api/push/send", {
      title: "Test",
      body: "Hello",
    });
    assert.equal(res.status, 200);
    assert.equal(res.body.ok, true);
  });

  it("returns 400 when title is missing", async () => {
    const res = await post("/api/push/send", { body: "Hello" });
    assert.equal(res.status, 400);
  });
});

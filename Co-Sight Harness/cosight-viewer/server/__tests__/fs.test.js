// SPDX-License-Identifier: Apache-2.0
/**
 * @file Tests for the viewer-owned local file browser endpoints.
 *
 * Covers the one-level listing contract, absolute-path validation, error codes
 * and the capabilities flag the client uses to pick an attachment provider.
 */

const { describe, it, before, after } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const express = require("express");

const fsRouter = require("../routes/fs");

let server;
let base;
let dir;

before(async () => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "viewer-fs-"));
  fs.mkdirSync(path.join(dir, "sub"));
  fs.writeFileSync(path.join(dir, "a.txt"), "hello");
  fs.writeFileSync(path.join(dir, ".hidden"), "x");

  const app = express();
  app.use("/fs", fsRouter);
  server = http.createServer(app);
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${server.address().port}/fs`;
});

after(() => {
  if (server) server.close();
  fs.rmSync(dir, { recursive: true, force: true });
});

function get(pathname) {
  return fetch(`${base}${pathname}`);
}

describe("fs list", () => {
  it("lists one level with directories first and the real path", async () => {
    const response = await get(`/list?path=${encodeURIComponent(dir)}`);
    assert.equal(response.status, 200);

    const body = await response.json();
    // Windows 上 realpathSync 可能给出 8.3 短路径，异步 realpath 给出长路径；
    // 只断言「是同一个目录」与「parent 是它的上一级」，不比较字符串形态。
    assert.equal(path.basename(body.path), path.basename(dir));
    assert.equal(body.truncated, false);

    const names = body.items.map((item) => item.name);
    assert.ok(names.includes("a.txt"));
    assert.ok(names.includes(".hidden"));

    const first = body.items[0];
    assert.equal(first.name, "sub");
    assert.equal(first.type, "dir");
    assert.equal(body.parent, path.dirname(body.path));
  });

  it("rejects relative paths", async () => {
    const response = await get("/list?path=a.txt");
    assert.equal(response.status, 400);

    const body = await response.json();
    assert.equal(body.error.code, "BAD_REQUEST");
  });

  it("returns 404 for a missing directory", async () => {
    const response = await get(`/list?path=${encodeURIComponent(path.join(dir, "nope"))}`);
    assert.equal(response.status, 404);
  });

  it("rejects a file path", async () => {
    const response = await get(`/list?path=${encodeURIComponent(path.join(dir, "a.txt"))}`);
    assert.equal(response.status, 400);
  });
});

describe("fs roots and capabilities", () => {
  it("returns browsable roots including the home directory", async () => {
    const response = await get("/roots");
    assert.equal(response.status, 200);

    const body = await response.json();
    assert.ok(Array.isArray(body.items));
    assert.ok(body.items.some((item) => item.path === os.homedir()));
  });

  it("reports local-path attachment mode", async () => {
    const response = await get("/capabilities");
    assert.equal(response.status, 200);

    const body = await response.json();
    assert.equal(body.attachmentMode, "local-path");
  });
});

describe("fs list with workspace root", () => {
  it("省略 path 时以 root 作为起点", async () => {
    const root = path.join(dir, "sub");
    const response = await get(`/list?root=${encodeURIComponent(root)}`);
    assert.equal(response.status, 200);
    const body = await response.json();
    // Windows 上 realpath 可能给出 8.3 短路径，形态不同但是同一个目录
    assert.equal(path.basename(body.path), "sub");
  });

  it("root 内的路径正常列出", async () => {
    const root = path.join(dir, "sub");
    fs.writeFileSync(path.join(root, "inner.md"), "# inner\n");
    const response = await get(
      `/list?root=${encodeURIComponent(root)}&path=${encodeURIComponent(root)}`
    );
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.ok(body.items.some((item) => item.name === "inner.md"));
  });

  it("超出 root 的路径一律 403（含父目录）", async () => {
    const root = path.join(dir, "sub");
    const response = await get(
      `/list?root=${encodeURIComponent(root)}&path=${encodeURIComponent(dir)}`
    );
    assert.equal(response.status, 403);
    const body = await response.json();
    assert.equal(body.error.code, "FORBIDDEN");
  });

  it("root 必须是绝对路径；不存在时 404", async () => {
    assert.equal((await get("/list?root=relative")).status, 400);
    assert.equal(
      (await get(`/list?root=${encodeURIComponent(path.join(dir, "missing"))}`)).status,
      404
    );
  });
});

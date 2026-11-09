// SPDX-License-Identifier: Apache-2.0
/**
 * @file Tests for the viewer-owned session file endpoints.
 *
 * Covers the read/raw contract, Windows-style drive paths, and the error codes
 * the client maps to UI states (404 / 413 / 415).
 */

const { describe, it, before, after } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const express = require("express");

const sessionFilesRouter = require("../routes/session-files");

let server;
let base;
let dir;
let textFile;
let htmlFile;
let pdfFile;
let spacedFile;
let binaryFile;
let largeFile;
let utf16leFile;
let utf16beFile;
let utf16NoBomFile;

const UTF16_TEXT = "[main]\n名字=测试\n";

before(async () => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "session-files-"));
  textFile = path.join(dir, "note.md");
  fs.writeFileSync(textFile, "# hello\n");
  htmlFile = path.join(dir, "page.html");
  fs.writeFileSync(htmlFile, "<p>hi</p>");
  spacedFile = path.join(dir, "my report v2.md");
  fs.writeFileSync(spacedFile, "# spaced\n");
  pdfFile = path.join(dir, "report.pdf");
  fs.writeFileSync(pdfFile, "%PDF-1.4\n");
  binaryFile = path.join(dir, "blob.bin");
  fs.writeFileSync(binaryFile, Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x00, 0x01]));
  largeFile = path.join(dir, "large.txt");
  fs.writeFileSync(largeFile, Buffer.alloc(sessionFilesRouter.MAX_TEXT_BYTES + 1, 0x61));

  // Windows（PowerShell / 记事本）常见的 UTF-16 文本：BOM + 每个 ASCII 字符带一个 0 字节
  utf16leFile = path.join(dir, "settings-le.ini");
  fs.writeFileSync(
    utf16leFile,
    Buffer.concat([Buffer.from([0xff, 0xfe]), Buffer.from(UTF16_TEXT, "utf16le")])
  );
  utf16beFile = path.join(dir, "settings-be.ini");
  fs.writeFileSync(
    utf16beFile,
    Buffer.concat([
      Buffer.from([0xfe, 0xff]),
      Buffer.from(UTF16_TEXT, "utf16le").swap16(),
    ])
  );
  // 无 BOM 的 ASCII 型 UTF-16LE：靠"高字节大量为 0"的启发式认出来
  utf16NoBomFile = path.join(dir, "settings-nobom.ini");
  fs.writeFileSync(utf16NoBomFile, Buffer.from("[main]\nname=test\n", "utf16le"));

  const app = express();
  app.use(express.json());
  app.use("/session-files", sessionFilesRouter);
  server = http.createServer(app);
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${server.address().port}/session-files`;
});

after(() => {
  if (server) server.close();
  fs.rmSync(dir, { recursive: true, force: true });
});

function read(pathValue) {
  return fetch(`${base}/read?path=${encodeURIComponent(pathValue)}`);
}

function rawUrl(pathValue) {
  const normalized = pathValue.replace(/\\/g, "/");
  const segments = normalized.split("/").map(encodeURIComponent).join("/");
  return `${base}/raw${segments.startsWith("/") ? "" : "/"}${segments}`;
}

describe("session-files read", () => {
  it("returns text content and real path", async () => {
    const response = await read(textFile);
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.content, "# hello\n");
    assert.equal(body.path, fs.realpathSync(textFile));
    assert.equal(body.name, "note.md");
  });

  it("rejects relative paths", async () => {
    const response = await read("note.md");
    assert.equal(response.status, 400);
    const body = await response.json();
    assert.equal(body.error.code, "BAD_REQUEST");
  });

  it("decodes UTF-16LE text with BOM (Windows-produced .ini)", async () => {
    const response = await read(utf16leFile);
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.content, UTF16_TEXT);
  });

  it("decodes UTF-16BE text with BOM", async () => {
    const response = await read(utf16beFile);
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.content, UTF16_TEXT);
  });

  it("decodes BOM-less UTF-16LE when the zero-byte pattern is unmistakable", async () => {
    const response = await read(utf16NoBomFile);
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.content, "[main]\nname=test\n");
  });

  it("returns 404 for missing files", async () => {
    const response = await read(path.join(dir, "missing.md"));
    assert.equal(response.status, 404);
  });

  it("returns 400 for directories", async () => {
    const response = await read(dir);
    assert.equal(response.status, 400);
  });

  it("returns 415 for binary files", async () => {
    const response = await read(binaryFile);
    assert.equal(response.status, 415);
  });

  it("returns 413 for files over the text limit", async () => {
    const response = await read(largeFile);
    assert.equal(response.status, 413);
  });

  it("accepts forward-slash Windows drive paths", async () => {
    if (process.platform !== "win32") return;
    const response = await read(textFile.replace(/\\/g, "/"));
    assert.equal(response.status, 200);
    assert.equal((await response.json()).content, "# hello\n");
  });
});

describe("session-files raw", () => {
  it("streams raw bytes with no-store", async () => {
    const response = await fetch(rawUrl(textFile));
    assert.equal(response.status, 200);
    assert.equal(await response.text(), "# hello\n");
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  });

  it("streams binary files", async () => {
    const response = await fetch(rawUrl(binaryFile));
    assert.equal(response.status, 200);
    const bytes = Buffer.from(await response.arrayBuffer());
    assert.deepEqual([...bytes], [0x89, 0x50, 0x4e, 0x47, 0x00, 0x01]);
  });

  it("handles paths containing spaces (POSIX and Windows)", async () => {
    const response = await fetch(rawUrl(spacedFile));
    assert.equal(response.status, 200);
    assert.equal(await response.text(), "# spaced\n");
    assert.equal((await read(spacedFile)).status, 200);
  });

  it("sandboxes HTML responses", async () => {
    const response = await fetch(rawUrl(htmlFile));
    assert.equal(response.status, 200);
    assert.match(response.headers.get("content-security-policy") ?? "", /sandbox/);
  });

  it("serves PDFs without CSP sandbox so the browser viewer can render them", async () => {
    const response = await fetch(rawUrl(pdfFile));
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("content-type"), "application/pdf");
    assert.equal(response.headers.get("content-security-policy"), null);
    assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  });

  it("returns 404 for a missing raw path", async () => {
    const response = await fetch(rawUrl(path.join(dir, "missing.png")));
    assert.equal(response.status, 404);
  });

  it("accepts forward-slash Windows drive paths", async () => {
    if (process.platform !== "win32") return;
    const response = await fetch(rawUrl(textFile.replace(/\\/g, "/")));
    assert.equal(response.status, 200);
    assert.equal(await response.text(), "# hello\n");
  });
});

describe("session-files resolve", () => {
  function resolveItems(items) {
    return fetch(`${base}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    });
  }

  it("按候选根顺序解析，取第一个真实存在的文件", async () => {
    // 相对路径同时存在于两个根下：`first/` 优先
    const first = path.join(dir, "first");
    const second = path.join(dir, "second");
    fs.mkdirSync(first, { recursive: true });
    fs.mkdirSync(second, { recursive: true });
    const expected = path.join(first, "pics", "a.png");
    fs.mkdirSync(path.join(first, "pics"), { recursive: true });
    fs.mkdirSync(path.join(second, "pics"), { recursive: true });
    fs.writeFileSync(expected, "one");
    fs.writeFileSync(path.join(second, "pics", "a.png"), "two");

    const response = await resolveItems([
      { path: "pics/a.png", roots: [first, second] },
    ]);
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.items[0].resolved, fs.realpathSync(expected));
  });

  it("候选根里都没有时返回 null（不制造死链）", async () => {
    const response = await resolveItems([
      { path: "pics/missing.png", roots: [dir] },
    ]);
    const body = await response.json();
    assert.equal(body.items[0].resolved, null);
  });

  it("绝对路径直接用，不拼候选根", async () => {
    const response = await resolveItems([
      { path: textFile, roots: [path.join(dir, "nope")] },
    ]);
    const body = await response.json();
    assert.equal(body.items[0].resolved, fs.realpathSync(textFile));
  });

  it("相对路径里的 .. 逃出候选根不认", async () => {
    const outside = path.join(os.tmpdir(), `outside-${Date.now()}.png`);
    fs.writeFileSync(outside, "x");
    try {
      const response = await resolveItems([
        { path: `../${path.basename(outside)}`, roots: [dir] },
      ]);
      const body = await response.json();
      assert.equal(body.items[0].resolved, null);
    } finally {
      fs.rmSync(outside, { force: true });
    }
  });

  it("畸形入参：items 为空 / 不是数组都是 400", async () => {
    assert.equal((await resolveItems([])).status, 400);
    const response = await fetch(`${base}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: "nope" }),
    });
    assert.equal(response.status, 400);
  });
});

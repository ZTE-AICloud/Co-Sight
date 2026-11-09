// SPDX-License-Identifier: Apache-2.0
/**
 * @file Regression tests for per-message TPS in the transcript endpoint across
 * pagination boundaries. Previously the first message of every batch lost its
 * TPS because computeTpsFromTimestamps started at index 1 and had no in-window
 * predecessor for the batch head. Each pagination mode (after / before /
 * around_uuid / offset / default) now seeds the batch head's predecessor
 * timestamp so the head can still compute TPS.
 *
 * Transcript fixture (5 JSONL lines):
 *   L1 user      00:00:00
 *   L2 assistant 00:00:02   output 200 → 100 tok/s
 *   L3 user      00:00:04
 *   L4 assistant 00:00:06   output 100 →  50 tok/s
 *   L5 user      00:00:08
 */

const { describe, it, before, after } = require("node:test");
const assert = require("node:assert/strict");
const path = require("path");
const fs = require("fs");
const os = require("os");
const http = require("http");

// Point every path the transcript endpoint resolves against at temp dirs,
// BEFORE requiring any server modules.
const TEST_ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "tps-pagination-"));
const TEST_DB = path.join(TEST_ROOT, "tps-test.db");
const TEST_DATA_DIR = path.join(TEST_ROOT, "data");
const TEST_HOME = path.join(TEST_ROOT, "home");
fs.mkdirSync(TEST_DATA_DIR, { recursive: true });
fs.mkdirSync(TEST_HOME, { recursive: true });
process.env.DASHBOARD_DB_PATH = TEST_DB;
process.env.DASHBOARD_DATA_DIR = TEST_DATA_DIR;
process.env.COSIGHT_HOME = TEST_HOME;
process.env.CO_SIGHT_MODE = "claude";

const { createApp, startServer } = require("../index");
const { db, stmts } = require("../db");

const SESSION_ID = "tps-pagination-test-session";
const L1 = {
  type: "user",
  message: { role: "user", content: "hello" },
  timestamp: "2026-01-01T00:00:00Z",
  uuid: "u1",
};
const L2 = {
  type: "assistant",
  message: {
    role: "assistant",
    model: "claude-sonnet-4",
    content: [{ type: "text", text: "hi" }],
    usage: { input_tokens: 10, output_tokens: 200 },
  },
  timestamp: "2026-01-01T00:00:02Z",
  uuid: "u2",
};
const L3 = {
  type: "user",
  message: { role: "user", content: "next" },
  timestamp: "2026-01-01T00:00:04Z",
  uuid: "u3",
};
const L4 = {
  type: "assistant",
  message: {
    role: "assistant",
    model: "claude-sonnet-4",
    content: [{ type: "text", text: "again" }],
    usage: { input_tokens: 10, output_tokens: 100 },
  },
  timestamp: "2026-01-01T00:00:06Z",
  uuid: "u4",
};
const L5 = {
  type: "user",
  message: { role: "user", content: "end" },
  timestamp: "2026-01-01T00:00:08Z",
  uuid: "u5",
};
const LINES = [L1, L2, L3, L4, L5];

let server;
let BASE;
const BASE_PATH = "/api/cosight-viewer/v1";

function fetch(urlPath, options = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(BASE_PATH + urlPath.replace(/^\/api/, ""), BASE);
    const opts = {
      hostname: url.hostname,
      port: url.port,
      path: url.pathname + url.search,
      method: options.method || "GET",
      headers: { "Content-Type": "application/json", ...options.headers },
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
        resolve({ status: res.statusCode, body: parsed, headers: res.headers });
      });
    });

    req.on("error", reject);
    if (options.body) req.write(JSON.stringify(options.body));
    req.end();
  });
}

before(async () => {
  // Seed a session with a null cwd so the endpoint falls back to the snapshot
  // transcript under DASHBOARD_DATA_DIR/transcripts.
  stmts.insertSession.run(SESSION_ID, "TPS Pagination", "active", null, null, null);

  // Write the transcript to the durable snapshot location (transcripts/<id>.jsonl).
  const snapshotDir = path.join(TEST_DATA_DIR, "transcripts");
  fs.mkdirSync(snapshotDir, { recursive: true });
  fs.writeFileSync(
    path.join(snapshotDir, `${SESSION_ID}.jsonl`),
    LINES.map((l) => JSON.stringify(l)).join("\n") + "\n"
  );

  const app = createApp();
  server = await startServer(app, 0); // port 0 = random available port
  const addr = server.address();
  BASE = `http://127.0.0.1:${addr.port}`;
});

after(() => {
  if (server) server.close();
  if (db) db.close();
  try {
    fs.rmSync(TEST_ROOT, { recursive: true, force: true });
  } catch {
    // ignore cleanup errors
  }
});

describe("GET /api/sessions/:id/transcript — TPS across pagination boundaries", () => {
  it("default (latest-N) mode seeds the batch head with the shifted-out predecessor", async () => {
    // limit=2 keeps [L4, L5]; L3 (the predecessor) was shifted out and must seed L4.
    const res = await fetch(`/api/sessions/${SESSION_ID}/transcript?limit=2`);
    assert.equal(res.status, 200);
    assert.equal(res.body.messages.length, 2);
    const head = res.body.messages[0];
    assert.equal(head.type, "assistant");
    assert.equal(head.tps, 50, "L4: 100 output / 2s = 50 tok/s");
    assert.equal(head.durationMs, 2000);
  });

  it("after (incremental) mode seeds the first message of the batch", async () => {
    // after=3 means the client already has L1–L3; the next batch starts at L4,
    // whose predecessor L3 is outside the batch and must seed it.
    const res = await fetch(`/api/sessions/${SESSION_ID}/transcript?after=3&limit=50`);
    assert.equal(res.status, 200);
    assert.equal(res.body.messages.length, 2);
    const head = res.body.messages[0];
    assert.equal(head.type, "assistant");
    assert.equal(head.tps, 50, "L4: 100 output / 2s = 50 tok/s");
    assert.equal(head.durationMs, 2000);
  });

  it("before (history) mode seeds the batch head after window overflow", async () => {
    // before=5&limit=1 keeps [L4]; L3 was shifted out and must seed L4.
    const res = await fetch(`/api/sessions/${SESSION_ID}/transcript?before=5&limit=1`);
    assert.equal(res.status, 200);
    assert.equal(res.body.messages.length, 1);
    const head = res.body.messages[0];
    assert.equal(head.type, "assistant");
    assert.equal(head.tps, 50, "L4: 100 output / 2s = 50 tok/s");
    assert.equal(head.durationMs, 2000);
  });

  it("around_uuid mode seeds the buffered context head", async () => {
    // Anchor at L4 with limit=2 buffers [L2, L3]; L1 was shifted out and must seed L2.
    const res = await fetch(`/api/sessions/${SESSION_ID}/transcript?around_uuid=u4&limit=2`);
    assert.equal(res.status, 200);
    assert.ok(res.body.messages.length >= 2);
    const head = res.body.messages[0];
    assert.equal(head.type, "assistant");
    assert.equal(head.tps, 100, "L2: 200 output / 2s = 100 tok/s");
    assert.equal(head.durationMs, 2000);
  });

  it("offset mode seeds the batch head with the last skipped message", async () => {
    // offset=1 skips L1, then collects [L2, L3]; L1 must seed L2.
    const res = await fetch(`/api/sessions/${SESSION_ID}/transcript?offset=1&limit=2`);
    assert.equal(res.status, 200);
    assert.equal(res.body.messages.length, 2);
    const head = res.body.messages[0];
    assert.equal(head.type, "assistant");
    assert.equal(head.tps, 100, "L2: 200 output / 2s = 100 tok/s");
    assert.equal(head.durationMs, 2000);
  });

  it("still yields no tps when the batch head genuinely has no predecessor", async () => {
    // after=0 starts from the very first file line — L2 (index 1) computes against
    // L1 in-window, and no batch-head seed exists, so nothing may be fabricated.
    const res = await fetch(`/api/sessions/${SESSION_ID}/transcript?after=0&limit=50`);
    assert.equal(res.status, 200);
    assert.equal(res.body.messages.length, 5);
    // L2 computes normally against L1 in-window.
    assert.equal(res.body.messages[1].tps, 100, "L2: 200 output / 2s = 100 tok/s");
    // No fabricated tps on the very first assistant batch head is possible here
    // because L2 is index 1; L1 is a user message with no tps field.
    assert.equal(res.body.messages[0].tps, undefined);
  });

  // ── thinking-inclusive TPS (Claude mode thinking/response split) ──
  // Fixture: real user 00:00:00 → thinking-only 00:00:03 → text 00:00:05 (out 200).
  const SPLIT_ID = "tps-pagination-thinking-session";
  const SP1 = {
    type: "user",
    message: { role: "user", content: "task" },
    timestamp: "2026-01-01T00:00:00Z",
    uuid: "sp1",
  };
  const SP2 = {
    type: "assistant",
    message: {
      role: "assistant",
      model: "claude-sonnet-4",
      content: [{ type: "thinking", thinking: "plan..." }],
      usage: { input_tokens: 10, output_tokens: 0 },
    },
    timestamp: "2026-01-01T00:00:03Z",
    uuid: "sp2",
  };
  const SP3 = {
    type: "assistant",
    message: {
      role: "assistant",
      model: "claude-sonnet-4",
      content: [{ type: "text", text: "done" }],
      usage: { input_tokens: 10, output_tokens: 200 },
    },
    timestamp: "2026-01-01T00:00:05Z",
    uuid: "sp3",
  };

  function writeSplitTranscript(lines) {
    try {
      stmts.insertSession.run(SPLIT_ID, "TPS Split", "active", null, null, null);
    } catch {
      // Session already seeded by a sibling test — reuse it (idempotent fixture).
    }
    const dir = path.join(TEST_DATA_DIR, "transcripts");
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(
      path.join(dir, `${SPLIT_ID}.jsonl`),
      lines.map((l) => JSON.stringify(l)).join("\n") + "\n"
    );
  }

  it("in-window thinking/response split: thinking has no tps, text measures from the real user", async () => {
    writeSplitTranscript([SP1, SP2, SP3]);
    // limit=2 keeps [thinking, text] in the window — the split is resolved by
    // the in-window running flag, no boundary seed needed.
    const res = await fetch(`/api/sessions/${SPLIT_ID}/transcript?limit=2`);
    assert.equal(res.status, 200);
    assert.equal(res.body.messages.length, 2);
    const [thinking, text] = res.body.messages;
    assert.equal(thinking.type, "assistant");
    assert.equal(thinking.tps, undefined, "thinking-only bubble never carries a tps");
    assert.equal(text.tps, 40, "text: 200 output / 5s from real user = 40 tok/s");
    assert.equal(text.durationMs, 5000);
  });

  it("thinking-split across the pagination boundary seeds seedBlockBoundaryTs", async () => {
    writeSplitTranscript([SP1, SP2, SP3]);
    // limit=1 keeps only [text]; the thinking entry is shifted out and must be
    // carried across the boundary as seedPrevIsAssistantCall=true + seedBlockBoundaryTs so the
    // text batch head still measures from the real user prompt.
    const res = await fetch(`/api/sessions/${SPLIT_ID}/transcript?limit=1`);
    assert.equal(res.status, 200);
    assert.equal(res.body.messages.length, 1);
    const head = res.body.messages[0];
    assert.equal(head.type, "assistant");
    assert.equal(head.tps, 40, "200 output / 5s from real user (seedUserTs) = 40 tok/s");
    assert.equal(head.durationMs, 5000);
  });

  it("deepseek-style split (thinking carries output_tokens>0): no tps on thinking, text measures from the real user", async () => {
    // deepseek-v4-flash writes the SAME usage on the thinking and text entries,
    // so the thinking entry's output_tokens>0 must not break thinking detection.
    const DEEPSEEK_ID = "tps-pagination-deepseek-session";
    try {
      stmts.insertSession.run(DEEPSEEK_ID, "TPS Deepseek Split", "active", null, null, null);
    } catch {
      // Session already seeded by a sibling test — reuse it (idempotent fixture).
    }
    const dir = path.join(TEST_DATA_DIR, "transcripts");
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(
      path.join(dir, `${DEEPSEEK_ID}.jsonl`),
      [
        {
          type: "user",
          message: { role: "user", content: "明天的日期是多少" },
          timestamp: "2026-01-01T00:00:00Z",
          uuid: "d1",
        },
        {
          type: "assistant",
          message: {
            role: "assistant",
            model: "deepseek-v4-flash",
            content: [{ type: "thinking", thinking: "The user asks what tomorrow's date is..." }],
            usage: { input_tokens: 55, output_tokens: 49 },
          },
          timestamp: "2026-01-01T00:00:03Z",
          uuid: "d2",
        },
        {
          type: "assistant",
          message: {
            role: "assistant",
            model: "deepseek-v4-flash",
            content: [{ type: "text", text: "明天是 2026年1月2日(周五)。" }],
            usage: { input_tokens: 55, output_tokens: 49 },
          },
          timestamp: "2026-01-01T00:00:05Z",
          uuid: "d3",
        },
      ]
        .map((l) => JSON.stringify(l))
        .join("\n") + "\n"
    );

    const res = await fetch(`/api/sessions/${DEEPSEEK_ID}/transcript?limit=3`);
    assert.equal(res.status, 200);
    assert.equal(res.body.messages.length, 3);
    const [thinking, text] = res.body.messages.slice(1);
    assert.equal(thinking.type, "assistant");
    assert.equal(
      thinking.tps,
      undefined,
      "thinking-only bubble never carries a tps even with out>0"
    );
    assert.equal(text.tps, 9.8, "49 output / 5s from real user = 9.8 tok/s");
    assert.equal(text.durationMs, 5000);
  });

  it("tool_use-only continuation (out=0) keeps the thinking-inclusive baseline", async () => {
    // deepseek-v4-pro split: user → thinking(out=0) → tool_use(out=0) →
    // tool_use(out=280). The out=0 tool_use is part of the SAME turn and must
    // NOT clear the thinking-inclusive flag, so the token-carrying tool_use
    // still measures from the real user prompt (thinking time counts).
    const TOOLUSE_ID = "tps-pagination-tooluse-session";
    try {
      stmts.insertSession.run(TOOLUSE_ID, "TPS ToolUse Continuation", "active", null, null, null);
    } catch {
      // Session already seeded by a sibling test — reuse it (idempotent fixture).
    }
    const dir = path.join(TEST_DATA_DIR, "transcripts");
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(
      path.join(dir, `${TOOLUSE_ID}.jsonl`),
      [
        {
          type: "user",
          message: { role: "user", content: "analyze cpu" },
          timestamp: "2026-01-01T00:00:01Z",
          uuid: "tu1",
        },
        {
          type: "assistant",
          message: {
            role: "assistant",
            model: "deepseek-v4-pro",
            content: [{ type: "thinking", thinking: "plan" }],
            usage: { input_tokens: 10, output_tokens: 0 },
          },
          timestamp: "2026-01-01T00:00:02Z",
          uuid: "tu2",
        },
        {
          type: "assistant",
          message: {
            role: "assistant",
            model: "deepseek-v4-pro",
            content: [{ type: "tool_use", id: "t1", name: "Bash", input: {} }],
            usage: { input_tokens: 10, output_tokens: 0 },
          },
          timestamp: "2026-01-01T00:00:03Z",
          uuid: "tu3",
        },
        {
          type: "assistant",
          message: {
            role: "assistant",
            model: "deepseek-v4-pro",
            content: [{ type: "tool_use", id: "t2", name: "Bash", input: {} }],
            usage: { input_tokens: 10, output_tokens: 280 },
          },
          timestamp: "2026-01-01T00:00:05Z",
          uuid: "tu4",
        },
      ]
        .map((l) => JSON.stringify(l))
        .join("\n") + "\n"
    );

    const res = await fetch(`/api/sessions/${TOOLUSE_ID}/transcript?limit=10`);
    assert.equal(res.status, 200);
    assert.equal(res.body.messages.length, 4);
    const [user, thinking, toolUseOut0, toolUseCarry] = res.body.messages;
    assert.equal(user.type, "user");
    // thinking-only bubble: no tps.
    assert.equal(thinking.type, "assistant");
    assert.equal(thinking.tps, undefined, "thinking-only bubble never carries a tps");
    // out=0 tool_use continuation: no tps, but the thinking-inclusive baseline
    // persists — its duration is measured from the real user prompt.
    assert.equal(toolUseOut0.type, "assistant");
    assert.equal(toolUseOut0.tps, undefined, "out=0 tool_use never carries a tps");
    assert.equal(toolUseOut0.durationMs, 2000, "baseline still from the real user (flag kept)");
    // token-carrying tool_use: 280 output over the full 4s from the real user.
    assert.equal(toolUseCarry.type, "assistant");
    assert.equal(toolUseCarry.tps, 70, "280 output / 4s (thinking incl.) = 70 tok/s");
    assert.equal(toolUseCarry.durationMs, 4000);
  });

  it("cosight single-assistant mode is unchanged (tool_result, no thinking split)", async () => {
    // Cosight: real user 00:00:00 → tool_result 00:00:04 → single assistant
    // 00:00:06 (out 100). The assistant measures from the tool_result (immediate
    // predecessor), NOT the real user — tool time is excluded as before.
    const COSIGHT_ID = "tps-pagination-cosight-session";
    stmts.insertSession.run(COSIGHT_ID, "TPS Cosight", "active", null, null, null);
    const dir = path.join(TEST_DATA_DIR, "transcripts");
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(
      path.join(dir, `${COSIGHT_ID}.jsonl`),
      [
        {
          type: "user",
          message: { role: "user", content: "task" },
          timestamp: "2026-01-01T00:00:00Z",
          uuid: "c1",
        },
        {
          type: "user",
          message: {
            role: "user",
            content: [{ type: "tool_result", tool_use_id: "t1", content: "ok" }],
          },
          timestamp: "2026-01-01T00:00:04Z",
          uuid: "c2",
        },
        {
          type: "assistant",
          message: {
            role: "assistant",
            model: "qwen3",
            content: [{ type: "text", text: "done" }],
            usage: { input_tokens: 10, output_tokens: 100 },
          },
          timestamp: "2026-01-01T00:00:06Z",
          uuid: "c3",
        },
      ]
        .map((l) => JSON.stringify(l))
        .join("\n") + "\n"
    );

    // limit=1 keeps only [assistant]; the tool_result (00:00:04) is the shifted
    // immediate predecessor, so it must seed the TPS baseline.
    const res = await fetch(`/api/sessions/${COSIGHT_ID}/transcript?limit=1`);
    assert.equal(res.status, 200);
    assert.equal(res.body.messages.length, 1);
    const head = res.body.messages[0];
    assert.equal(head.tps, 50, "100 output / 2s from tool_result = 50 tok/s");
    assert.equal(head.durationMs, 2000);
  });
});

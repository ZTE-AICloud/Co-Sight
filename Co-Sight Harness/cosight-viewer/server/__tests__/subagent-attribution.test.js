// SPDX-License-Identifier: Apache-2.0
/**
 * @file Tests for subagent tool-event attribution.
 *
 * Subagent tool calls (Read, Bash, Edit, etc.) never fire hooks on the
 * parent session — they only show up in the subagent's own JSONL file.
 * Without dedicated extraction, every subagent ends up with at most a
 * single spawn event, leaving 561/561 historical subagents with 0–5
 * events instead of the dozens-to-hundreds they actually performed.
 *
 * This suite verifies that:
 *   1. parseSubagentFile pairs tool_use blocks with their tool_result
 *      counterparts and surfaces them as `toolEvents`.
 *   2. importSubagentFromJsonl emits PreToolUse + PostToolUse events
 *      under the subagent's own `agent_id`, so the UI attributes them
 *      to the subagent rather than the main agent.
 *   3. Re-running the import is idempotent — no duplicate event rows.
 *   4. When a live subagent (created via PreToolUse "Agent" hook) matches
 *      the JSONL by type + start time, events attach to the live row
 *      instead of creating a duplicate JSONL-keyed row.
 *
 */

const { describe, it, before, after } = require("node:test");
const assert = require("node:assert/strict");
const path = require("path");
const fs = require("fs");
const os = require("os");

const TEST_DB = path.join(os.tmpdir(), `dashboard-subagent-test-${Date.now()}-${process.pid}.db`);
process.env.DASHBOARD_DB_PATH = TEST_DB;

const dbModule = require("../db");
const { db, stmts } = dbModule;
const importHistory = require("../../scripts/import-history");

after(() => {
  if (db) db.close();
  for (const suffix of ["", "-wal", "-shm"]) {
    try {
      fs.unlinkSync(TEST_DB + suffix);
    } catch {
      /* ignore */
    }
  }
});

// ── Fixture helpers ──────────────────────────────────────────────────

function writeSubagentJsonl(filePath, lines) {
  fs.writeFileSync(filePath, lines.map((o) => JSON.stringify(o)).join("\n"));
}

/**
 * Builds a minimal subagent JSONL with two tool calls — one Read with a
 * paired tool_result, and one Bash with a paired error tool_result.
 */
function buildSubagentLines(agentType = "coder") {
  return [
    {
      type: "user",
      timestamp: "2026-04-28T10:00:00.000Z",
      message: { content: [{ type: "text", text: "Investigate the bug" }] },
    },
    {
      type: "assistant",
      timestamp: "2026-04-28T10:00:01.000Z",
      message: {
        model: "claude-opus-4-7",
        content: [
          {
            type: "tool_use",
            id: "toolu_read_001",
            name: "Read",
            input: { file_path: "/tmp/foo.py" },
          },
        ],
        usage: {
          input_tokens: 50,
          output_tokens: 20,
          cache_read_input_tokens: 0,
          cache_creation_input_tokens: 0,
        },
      },
    },
    {
      type: "user",
      timestamp: "2026-04-28T10:00:02.000Z",
      message: {
        content: [
          {
            type: "tool_result",
            tool_use_id: "toolu_read_001",
            content: "def main():\n    pass\n",
          },
        ],
      },
    },
    {
      type: "assistant",
      timestamp: "2026-04-28T10:00:03.000Z",
      message: {
        model: "claude-opus-4-7",
        content: [
          {
            type: "tool_use",
            id: "toolu_bash_002",
            name: "Bash",
            input: { command: "ls /tmp" },
          },
        ],
      },
    },
    {
      type: "user",
      timestamp: "2026-04-28T10:00:04.000Z",
      message: {
        content: [
          {
            type: "tool_result",
            tool_use_id: "toolu_bash_002",
            content: "ls: cannot access /tmp: not allowed",
            is_error: true,
          },
        ],
      },
    },
    {
      // Meta: keeps file timestamps coherent
      type: "user",
      timestamp: "2026-04-28T10:00:05.000Z",
      message: { content: [{ type: "text", text: "done" }] },
    },
  ].map((line, i) => {
    // Inject agentType into one entry as a hint, mirroring real CC output
    if (i === 0) line.agentType = agentType;
    return line;
  });
}

function writeMetaJson(filePath, agentType) {
  fs.writeFileSync(filePath, JSON.stringify({ agentType }));
}

// ── Tests ────────────────────────────────────────────────────────────

describe("parseSubagentFile — tool event extraction", () => {
  it("pairs tool_use with tool_result and returns ordered toolEvents", async () => {
    const tmpFile = path.join(os.tmpdir(), `agent-${Date.now()}-${process.pid}.jsonl`);
    writeSubagentJsonl(tmpFile, buildSubagentLines("coder"));
    writeMetaJson(tmpFile.replace(/\.jsonl$/, ".meta.json"), "coder");

    try {
      const data = await importHistory.parseSubagentFile(tmpFile);
      assert.ok(data, "subagent data should parse");
      assert.equal(data.agentType, "coder");
      assert.ok(Array.isArray(data.toolEvents));
      assert.equal(data.toolEvents.length, 2);

      const [readEv, bashEv] = data.toolEvents;
      assert.equal(readEv.tool_use_id, "toolu_read_001");
      assert.equal(readEv.tool_name, "Read");
      assert.deepEqual(readEv.tool_input, { file_path: "/tmp/foo.py" });
      assert.equal(readEv.is_error, false);
      assert.equal(typeof readEv.pre_timestamp, "string");
      assert.equal(typeof readEv.post_timestamp, "string");
      assert.ok(readEv.tool_response);

      assert.equal(bashEv.tool_use_id, "toolu_bash_002");
      assert.equal(bashEv.is_error, true);
    } finally {
      fs.unlinkSync(tmpFile);
      try {
        fs.unlinkSync(tmpFile.replace(/\.jsonl$/, ".meta.json"));
      } catch {
        /* ignore */
      }
    }
  });

  it("emits a tool_use even when no matching tool_result exists yet (live tail)", async () => {
    const tmpFile = path.join(os.tmpdir(), `agent-tail-${Date.now()}-${process.pid}.jsonl`);
    writeSubagentJsonl(tmpFile, [
      {
        type: "assistant",
        timestamp: "2026-04-28T10:00:01.000Z",
        message: {
          model: "claude-opus-4-7",
          content: [{ type: "tool_use", id: "toolu_pending", name: "Read", input: {} }],
        },
      },
    ]);

    try {
      const data = await importHistory.parseSubagentFile(tmpFile);
      assert.equal(data.toolEvents.length, 1);
      const ev = data.toolEvents[0];
      assert.equal(ev.tool_use_id, "toolu_pending");
      assert.equal(ev.post_timestamp, null);
      assert.equal(ev.tool_response, null);
    } finally {
      fs.unlinkSync(tmpFile);
    }
  });
});

describe("importSubagentFromJsonl — event attribution", () => {
  const sessionId = "test-sess-attribution";
  const mainAgentId = `${sessionId}-main`;

  before(() => {
    // Seed session + main agent so importSubagentFromJsonl has parents to point at.
    stmts.insertSession.run(sessionId, "Test Session", "active", "/tmp", null, null);
    stmts.insertAgent.run(
      mainAgentId,
      sessionId,
      "Main Agent",
      "main",
      null,
      "waiting",
      null,
      null,
      null
    );
  });

  it("creates one subagent row and per-call PreToolUse + PostToolUse events", async () => {
    const tmpFile = path.join(os.tmpdir(), `agent-attr-${Date.now()}-${process.pid}.jsonl`);
    writeSubagentJsonl(tmpFile, buildSubagentLines("coder"));
    writeMetaJson(tmpFile.replace(/\.jsonl$/, ".meta.json"), "coder");

    try {
      const data = await importHistory.parseSubagentFile(tmpFile);
      const created = importHistory.importSubagentFromJsonl(dbModule, sessionId, mainAgentId, data);
      assert.ok(created > 0, "should create at least the agent + spawn + 4 events");

      const subId = `${sessionId}-jsonl-${data.agentId}`;
      const subAgent = stmts.getAgent.get(subId);
      assert.ok(subAgent, "JSONL-keyed subagent row should exist");
      assert.equal(subAgent.parent_agent_id, mainAgentId);

      const toolEvents = db
        .prepare(
          "SELECT event_type, tool_name FROM events WHERE agent_id = ? AND event_type IN ('PreToolUse', 'PostToolUse') ORDER BY id ASC"
        )
        .all(subId);
      assert.equal(toolEvents.length, 4, "expected 2 Pre + 2 Post events under subagent's id");
      assert.deepEqual(
        toolEvents.map((e) => `${e.event_type}:${e.tool_name}`),
        ["PreToolUse:Read", "PostToolUse:Read", "PreToolUse:Bash", "PostToolUse:Bash"]
      );

      // Spawn marker lives under the main agent so the parent chain shows
      // "Subagent spawned: coder" alongside main's other actions.
      const spawnEvents = db
        .prepare(
          "SELECT 1 FROM events WHERE agent_id = ? AND event_type = 'PreToolUse' AND tool_name = 'Agent'"
        )
        .all(mainAgentId);
      assert.equal(spawnEvents.length, 1);
    } finally {
      fs.unlinkSync(tmpFile);
      try {
        fs.unlinkSync(tmpFile.replace(/\.jsonl$/, ".meta.json"));
      } catch {
        /* ignore */
      }
    }
  });

  it("is idempotent — re-running does not duplicate events", async () => {
    const tmpFile = path.join(os.tmpdir(), `agent-idem-${Date.now()}-${process.pid}.jsonl`);
    writeSubagentJsonl(tmpFile, buildSubagentLines("reviewer"));
    writeMetaJson(tmpFile.replace(/\.jsonl$/, ".meta.json"), "reviewer");

    try {
      const data = await importHistory.parseSubagentFile(tmpFile);
      importHistory.importSubagentFromJsonl(dbModule, sessionId, mainAgentId, data);
      const subId = `${sessionId}-jsonl-${data.agentId}`;
      const before = db.prepare("SELECT COUNT(*) AS c FROM events WHERE agent_id = ?").get(subId).c;

      // Second run — should be a no-op.
      importHistory.importSubagentFromJsonl(dbModule, sessionId, mainAgentId, data);
      const after = db.prepare("SELECT COUNT(*) AS c FROM events WHERE agent_id = ?").get(subId).c;

      assert.equal(after, before, "idempotent re-import — no new rows");
    } finally {
      fs.unlinkSync(tmpFile);
      try {
        fs.unlinkSync(tmpFile.replace(/\.jsonl$/, ".meta.json"));
      } catch {
        /* ignore */
      }
    }
  });

  it("merges into a live subagent when one matches — no JSONL-keyed duplicate row", async () => {
    // Simulate a live PreToolUse Agent hook having pre-created a subagent row.
    const liveSubId = "live-uuid-xyz";
    const startedAt = "2026-04-28T10:00:00.000Z";
    stmts.insertAgent.run(
      liveSubId,
      sessionId,
      "Live Coder",
      "subagent",
      "live-coder",
      "completed",
      "task",
      mainAgentId,
      null
    );
    db.prepare("UPDATE agents SET started_at = ?, ended_at = ?, updated_at = ? WHERE id = ?").run(
      startedAt,
      startedAt,
      startedAt,
      liveSubId
    );

    const tmpFile = path.join(os.tmpdir(), `agent-live-${Date.now()}-${process.pid}.jsonl`);
    const lines = buildSubagentLines("live-coder");
    writeSubagentJsonl(tmpFile, lines);
    writeMetaJson(tmpFile.replace(/\.jsonl$/, ".meta.json"), "live-coder");

    try {
      const data = await importHistory.parseSubagentFile(tmpFile);
      importHistory.importSubagentFromJsonl(dbModule, sessionId, mainAgentId, data);

      const jsonlSubId = `${sessionId}-jsonl-${data.agentId}`;
      assert.equal(
        stmts.getAgent.get(jsonlSubId),
        undefined,
        "no JSONL-keyed row when a live subagent absorbed the events"
      );

      const eventsUnderLive = db
        .prepare(
          "SELECT 1 FROM events WHERE agent_id = ? AND event_type IN ('PreToolUse', 'PostToolUse')"
        )
        .all(liveSubId);
      assert.ok(eventsUnderLive.length >= 4, "events should attach to the live subagent's id");
    } finally {
      fs.unlinkSync(tmpFile);
      try {
        fs.unlinkSync(tmpFile.replace(/\.jsonl$/, ".meta.json"));
      } catch {
        /* ignore */
      }
    }
  });
});

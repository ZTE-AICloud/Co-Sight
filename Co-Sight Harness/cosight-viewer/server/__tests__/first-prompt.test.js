// SPDX-License-Identifier: Apache-2.0
/**
 * @file Merged tests for first_prompt write channels:
 *   - DB migration (column + one-write semantics)
 *   - Import channel (JSONL extraction)
 *   - Hook channel (UserPromptSubmit)
 */

const { describe, it, before, after } = require("node:test");
const assert = require("node:assert/strict");
const path = require("path");
const fs = require("fs");
const os = require("os");

// =====================================================================
// sessions.first_prompt migration
// =====================================================================

let MIGRATION_DB;

before(() => {
  MIGRATION_DB = path.join(os.tmpdir(), `dashboard-fp-migration-${Date.now()}-${process.pid}.db`);
  process.env.DASHBOARD_DB_PATH = MIGRATION_DB;
});

after(() => {
  try {
    fs.unlinkSync(MIGRATION_DB);
  } catch {}
  try {
    fs.unlinkSync(MIGRATION_DB + "-wal");
  } catch {}
  try {
    fs.unlinkSync(MIGRATION_DB + "-shm");
  } catch {}
});

describe("sessions.first_prompt migration", () => {
  it("adds first_prompt column on first load", () => {
    delete require.cache[require.resolve("../db")];
    const { db } = require("../db");
    const cols = db.prepare("PRAGMA table_info(sessions)").all();
    const names = cols.map((c) => c.name);
    assert.ok(names.includes("first_prompt"), `expected first_prompt; got: ${names.join(",")}`);
  });

  it("is idempotent — loading db.js a second time does not throw", () => {
    delete require.cache[require.resolve("../db")];
    assert.doesNotThrow(() => require("../db"));
  });

  it("first_prompt is NULL by default and setSessionFirstPrompt writes once", () => {
    delete require.cache[require.resolve("../db")];
    const { db, stmts } = require("../db");
    stmts.insertSession.run("s-fp-1", "name", "active", "/tmp/proj", "claude", null);

    const row = db.prepare("SELECT first_prompt FROM sessions WHERE id = ?").get("s-fp-1");
    assert.equal(row.first_prompt, null);

    const now = new Date().toISOString();
    stmts.setSessionFirstPrompt.run("hello world", now, "s-fp-1");
    const updated = db.prepare("SELECT first_prompt FROM sessions WHERE id = ?").get("s-fp-1");
    assert.equal(updated.first_prompt, "hello world");
  });

  it("does not overwrite existing first_prompt (one-write semantics)", () => {
    const { stmts } = require("../db");
    const now = new Date().toISOString();
    stmts.setSessionFirstPrompt.run("second value", now, "s-fp-1");
    const row = stmts.getSession.get("s-fp-1");
    assert.equal(row.first_prompt, "hello world", "should remain first write");
  });
});

// =====================================================================
// import channel: writes first_prompt from JSONL
// =====================================================================

function writeJsonl(lines) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "fp-import-test-"));
  const file = path.join(dir, "test.jsonl");
  fs.writeFileSync(file, lines.map((l) => JSON.stringify(l)).join("\n"));
  return file;
}

describe("import channel: writes first_prompt from JSONL", () => {
  it("extracts and writes first_prompt for a newly imported session", () => {
    delete require.cache[require.resolve("../db")];
    const { stmts } = require("../db");
    const {
      extractFirstPromptFromTranscript,
      formatPromptForTitle,
    } = require("../lib/extract-prompt");

    const jsonlPath = writeJsonl([
      { type: "system", subtype: "init", timestamp: "2026-01-01T00:00:00Z" },
      {
        type: "user",
        message: { content: "imported prompt" },
        timestamp: "2026-01-01T00:01:00Z",
      },
    ]);

    stmts.insertSession.run("s-import-1", "name", "completed", "/tmp/proj", "claude", null);

    const first = extractFirstPromptFromTranscript(jsonlPath);
    if (first && first.content) {
      const formatted = formatPromptForTitle(first.content);
      if (formatted) {
        stmts.setSessionFirstPrompt.run(formatted, new Date().toISOString(), "s-import-1");
      }
    }

    const row = stmts.getSession.get("s-import-1");
    assert.equal(row.first_prompt, "imported prompt");
  });

  it("skips write when JSONL has no user message", () => {
    const { stmts } = require("../db");
    const {
      extractFirstPromptFromTranscript,
      formatPromptForTitle,
    } = require("../lib/extract-prompt");

    const jsonlPath = writeJsonl([{ type: "system", subtype: "init" }]);
    stmts.insertSession.run("s-import-2", "name", "completed", "/tmp/proj", "claude", null);

    const first = extractFirstPromptFromTranscript(jsonlPath);
    let written = false;
    if (first && first.content) {
      const formatted = formatPromptForTitle(first.content);
      if (formatted) written = true;
    }
    assert.equal(written, false);

    const row = stmts.getSession.get("s-import-2");
    assert.equal(row.first_prompt, null);
  });

  it("skips write when JSONL file is missing", () => {
    const { stmts } = require("../db");
    const {
      extractFirstPromptFromTranscript,
      formatPromptForTitle,
    } = require("../lib/extract-prompt");

    stmts.insertSession.run("s-import-3", "name", "completed", "/tmp/proj", "claude", null);

    const first = extractFirstPromptFromTranscript("/nonexistent/file.jsonl");
    let written = false;
    if (first && first.content) {
      const formatted = formatPromptForTitle(first.content);
      if (formatted) written = true;
    }
    assert.equal(written, false);

    const row = stmts.getSession.get("s-import-3");
    assert.equal(row.first_prompt, null);
  });
});

// =====================================================================
// hook channel: UserPromptSubmit writes first_prompt
// =====================================================================

describe("hook channel: UserPromptSubmit writes first_prompt", () => {
  it("writes formatted first_prompt on first UserPromptSubmit", () => {
    delete require.cache[require.resolve("../db")];
    const { stmts } = require("../db");
    const { formatPromptForTitle } = require("../lib/extract-prompt");

    stmts.insertSession.run("s-hook-1", "name", "active", "/tmp/proj", "claude", null);

    const data = { prompt: "first user prompt" };
    if (typeof data.prompt === "string" && data.prompt.trim()) {
      const formatted = formatPromptForTitle(data.prompt);
      if (formatted) {
        stmts.setSessionFirstPrompt.run(formatted, new Date().toISOString(), "s-hook-1");
      }
    }

    const row = stmts.getSession.get("s-hook-1");
    assert.equal(row.first_prompt, "first user prompt");
  });

  it("does not overwrite on subsequent UserPromptSubmit", () => {
    const { stmts } = require("../db");
    const { formatPromptForTitle } = require("../lib/extract-prompt");

    const data = { prompt: "second user prompt" };
    const formatted = formatPromptForTitle(data.prompt);
    stmts.setSessionFirstPrompt.run(formatted, new Date().toISOString(), "s-hook-1");

    const row = stmts.getSession.get("s-hook-1");
    assert.equal(row.first_prompt, "first user prompt", "should remain first");
  });

  it("skips write when data.prompt is empty", () => {
    const { stmts } = require("../db");
    const { formatPromptForTitle } = require("../lib/extract-prompt");

    stmts.insertSession.run("s-hook-2", "name", "active", "/tmp/proj", "claude", null);

    const data = { prompt: "" };
    let written = false;
    if (typeof data.prompt === "string" && data.prompt.trim()) {
      const formatted = formatPromptForTitle(data.prompt);
      if (formatted) written = true;
    }
    assert.equal(written, false);

    const row = stmts.getSession.get("s-hook-2");
    assert.equal(row.first_prompt, null);
  });

  it("beautifies slash command from hook payload", () => {
    const { stmts } = require("../db");
    const { formatPromptForTitle } = require("../lib/extract-prompt");

    stmts.insertSession.run("s-hook-3", "name", "active", "/tmp/proj", "claude", null);

    const data = {
      prompt:
        "<command-name>/brainstorming</command-name><command-args>\nsome args\n</command-args>",
    };
    const formatted = formatPromptForTitle(data.prompt);
    stmts.setSessionFirstPrompt.run(formatted, new Date().toISOString(), "s-hook-3");

    const row = stmts.getSession.get("s-hook-3");
    assert.ok(
      row.first_prompt.startsWith("/brainstorming"),
      `expected /brainstorming, got: ${row.first_prompt}`
    );
    assert.ok(row.first_prompt.includes("some args"), "expected args included");
  });
});

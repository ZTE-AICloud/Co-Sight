// SPDX-License-Identifier: Apache-2.0
/**
 * @file Tests for resolveReadableTranscriptPath() and the
 * sessions.transcript_path write-back it drives.
 *
 * Hook payloads report transcript_path as the *Claude process* sees it, and in a
 * container that path can be unreadable from the viewer process (the agent
 * runtime's HOME differs from COSIGHT_HOME). When it is, every transcript-derived
 * write in routes/hooks.js (model, tokens, title, first prompt, compaction,
 * errors, turn durations) silently stays empty — and the bogus path gets frozen
 * into sessions.transcript_path, which the periodic sweep then trusts.
 *
 * All file writes go to throwaway temp dirs; the developer's real ~/.cosight and
 * dashboard.db are never touched.
 */

const { describe, it, before, beforeEach, after } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const crypto = require("crypto");
const path = require("path");

// Redirect the DB before ../db is first required.
const TEST_DB = path.join(os.tmpdir(), `transcript-path-test-${Date.now()}-${process.pid}.db`);
process.env.DASHBOARD_DB_PATH = TEST_DB;

const {
  resolveReadableTranscriptPath,
  encodeCwd,
  getProjectsDirs,
} = require("../lib/claude-home");
const { stmts } = require("../db");

let roots = [];

/** A throwaway runtime root standing in for the container's COSIGHT_HOME. */
function makeRuntime() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tpr-"));
  roots.push(dir);
  return dir;
}

/** Point the CLI sources at `root` (container-style layout). */
function useRuntime(root) {
  process.env.VIEWER_SOURCES = "claude,cosight";
  process.env.CLAUDE_CONFIG_DIR = path.join(root, ".claude");
  process.env.COSIGHT_CONFIG_DIR = path.join(root, ".cosight");
  delete process.env.TASK_MANAGEMENT_ROOT;
}

/** Create the file (and its parents) and return its path. */
function touch(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, '{"type":"system"}\n', "utf8");
  return filePath;
}

/** Where THIS process would look for the session, mirroring getTranscriptPath(). */
function computedPath(sessionId, cwd) {
  // getProjectsDirs() returns [claude, cosight]; use the cosight source here.
  return path.join(getProjectsDirs()[1], encodeCwd(cwd), `${sessionId}.jsonl`);
}

before(() => {
  for (const key of [
    "COSIGHT_HOME",
    "CLAUDE_HOME",
    "CO_SIGHT_MODE",
    "CLAUDE_CONFIG_DIR",
    "COSIGHT_CONFIG_DIR",
    "VIEWER_SOURCES",
    "TASK_MANAGEMENT_ROOT",
    "DASHBOARD_DATA_DIR",
  ]) {
    delete process.env[key];
  }
});

beforeEach(() => {
  roots = [];
});

after(() => {
  for (const dir of roots) {
    try {
      fs.rmSync(dir, { recursive: true, force: true });
    } catch {
      /* best effort */
    }
  }
  try {
    fs.rmSync(TEST_DB, { force: true });
  } catch {
    /* best effort */
  }
});

// ─────────────────────────────────────────────────────────────────────────────
describe("resolveReadableTranscriptPath()", () => {
  const CWD = "/home/oes/agent-runtime-data/runtime/agent_2c4c4fe3/ver_28e0c5ec";

  it("keeps the reported path when this process can read it", () => {
    // Arrange
    const runtime = makeRuntime();
    useRuntime(runtime);
    const sessionId = crypto.randomUUID();
    const reported = touch(path.join(runtime, "somewhere", `${sessionId}.jsonl`));

    // Act
    const resolved = resolveReadableTranscriptPath(sessionId, { cwd: CWD, reportedPath: reported });

    // Assert
    assert.deepEqual(resolved, { path: reported, corrected: false });
  });

  it("falls back to the path this process computes when the reported one is unreadable", () => {
    // Arrange — the container case: the payload points at the agent runtime's
    // HOME, while the very same session file sits under this process's projects dir.
    const runtime = makeRuntime();
    useRuntime(runtime);
    const sessionId = crypto.randomUUID();
    const reported = `/home/oes/.cosight/projects/${encodeCwd(CWD)}/${sessionId}.jsonl`;
    const expected = touch(computedPath(sessionId, CWD));
    assert.ok(!fs.existsSync(reported), "reported path must genuinely be unreadable");

    // Act
    const resolved = resolveReadableTranscriptPath(sessionId, { cwd: CWD, reportedPath: reported });

    // Assert
    assert.equal(resolved.path, expected);
    assert.equal(resolved.corrected, true);
  });

  it("scans the projects dirs when the payload carries no cwd", () => {
    // Arrange — no cwd to encode, so only the directory scan can find it.
    const runtime = makeRuntime();
    useRuntime(runtime);
    const sessionId = crypto.randomUUID();
    const elsewhere = touch(
      path.join(getProjectsDirs()[1], "-some-other-project", `${sessionId}.jsonl`)
    );

    // Act
    const resolved = resolveReadableTranscriptPath(sessionId, {
      cwd: null,
      reportedPath: "/nope/whatever.jsonl",
    });

    // Assert
    assert.equal(resolved.path, elsewhere);
    assert.equal(resolved.corrected, true);
  });

  it("returns the reported path unchanged when nothing is readable", () => {
    // Arrange — must not regress: callers then behave exactly as before.
    const runtime = makeRuntime();
    useRuntime(runtime);
    const sessionId = crypto.randomUUID();
    const reported = `/home/oes/.cosight/projects/${encodeCwd(CWD)}/${sessionId}.jsonl`;

    // Act
    const resolved = resolveReadableTranscriptPath(sessionId, { cwd: CWD, reportedPath: reported });

    // Assert
    assert.deepEqual(resolved, { path: reported, corrected: false });
  });

  it("handles a payload with no transcript_path at all", () => {
    // Arrange
    const runtime = makeRuntime();
    useRuntime(runtime);
    const sessionId = crypto.randomUUID();
    const expected = touch(computedPath(sessionId, CWD));

    // Act
    const resolved = resolveReadableTranscriptPath(sessionId, { cwd: CWD, reportedPath: null });

    // Assert
    assert.equal(resolved.path, expected);
    assert.equal(resolved.corrected, true);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe("sessions.transcript_path write-back", () => {
  it("overwrites a stored path that turned out to be unreadable", () => {
    // Arrange — the row as the first hook event leaves it: the bogus path, frozen
    // in by setSessionTranscriptPath's NULL/'' guard.
    const sessionId = crypto.randomUUID();
    const bogus = `/home/oes/.cosight/projects/x/${sessionId}.jsonl`;
    const readable = `/agent/runtime/.cosight/projects/x/${sessionId}.jsonl`;
    stmts.insertSession.run(sessionId, "t", "active", "/tmp", null, null);
    stmts.setSessionTranscriptPath.run(bogus, sessionId);
    assert.equal(stmts.getSession.get(sessionId).transcript_path, bogus);

    // Act
    const first = stmts.overwriteSessionTranscriptPath.run(readable, sessionId, readable);

    // Assert
    assert.equal(first.changes, 1, "the write-back must actually replace the stored value");
    assert.equal(stmts.getSession.get(sessionId).transcript_path, readable);

    // …and it stays quiet on every later hook event for the same session.
    const second = stmts.overwriteSessionTranscriptPath.run(readable, sessionId, readable);
    assert.equal(second.changes, 0);
  });
});

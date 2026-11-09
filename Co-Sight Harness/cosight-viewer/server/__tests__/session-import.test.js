// SPDX-License-Identifier: Apache-2.0
/**
 * @file Tests for the single-session ZIP import path (export/import 会话) and
 * the shared task-management root resolution it depends on.
 *
 * This covers two regressions that shipped unnoticed because nothing tested
 * `server/lib/session-import.js` at all:
 *
 *   1. `getBaseDataDir is not defined` — the module called a helper it never
 *      imported. Invisible in containers (TASK_MANAGEMENT_ROOT short-circuits
 *      the expression) and only reproducible standalone.
 *   2. Split destination — the session JSONL and its task JSON were resolved
 *      through two different rules, so an import in claude mode scattered
 *      files across ~/.claude and ~/.cosight.
 *
 * All file writes are redirected into throwaway temp dirs; the developer's real
 * ~/.claude, ~/.cosight and dashboard.db are never touched.
 */

const { describe, it, before, after, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const path = require("path");
const fs = require("fs");
const os = require("os");
const crypto = require("crypto");

// Redirect the DB before ../db is first required (same precedent as import.test.js).
const TEST_DB = path.join(os.tmpdir(), `session-import-test-${Date.now()}-${process.pid}.db`);
process.env.DASHBOARD_DB_PATH = TEST_DB;

const {
  getTaskManagementRoot,
  getImportedSessionsDir,
} = require("../lib/claude-home");
const { importSessionFromZip } = require("../lib/session-import");
const { extractSessionMetadata } = require("../lib/session-metadata");
const { extractTitlesFromTranscript } = require("../lib/extract-prompt");
const { stmts } = require("../db");

const MANAGED_VARS = [
  "COSIGHT_HOME",
  "CLAUDE_HOME",
  "CO_SIGHT_MODE",
  "CLAUDE_CONFIG_DIR",
  "COSIGHT_CONFIG_DIR",
  "TASK_MANAGEMENT_ROOT",
  "DASHBOARD_DATA_DIR",
];

let tempRoots = [];

/** A throwaway directory that stands in for the user's home / runtime root. */
function makeTempRoot(label) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), `ccam-${label}-`));
  tempRoots.push(dir);
  return dir;
}

/** Point os.homedir() at a temp dir so standalone resolution stays isolated. */
function useFakeHome(dir) {
  process.env.USERPROFILE = dir;
  process.env.HOME = dir;
}

function clearManagedEnv() {
  for (const key of MANAGED_VARS) delete process.env[key];
}

/**
 * Build a ZIP in the layout the exporter produces:
 *   <topDir>/session/<id>.jsonl
 *   <topDir>/tasks/*.json
 */
function buildSessionZip(root, sessionId, { withTasks = true } = {}) {
  const AdmZip = require("adm-zip");
  const topDir = `session-${sessionId.slice(0, 12)}-test`;
  const lines = [
    JSON.stringify({
      type: "system",
      sessionId,
      timestamp: "2026-10-12T00:00:00.000Z",
      cwd: "/agent/app",
      model: "claude-sonnet-5-5",
    }),
    JSON.stringify({
      type: "user",
      message: { role: "user", content: "hello" },
      timestamp: "2026-10-12T00:00:01.000Z",
    }),
  ];

  const zip = new AdmZip();
  zip.addFile(`${topDir}/session/${sessionId}.jsonl`, Buffer.from(lines.join("\n") + "\n", "utf8"));
  if (withTasks) {
    zip.addFile(`${topDir}/tasks/task_t1.json`, Buffer.from('{"id":"t1"}', "utf8"));
  }

  const zipPath = path.join(root, `export-${sessionId}.zip`);
  zip.writeZip(zipPath);
  return zipPath;
}

/**
 * Transcript in the newer shape: two control records that carry only a
 * sessionId, with cwd/timestamp appearing from line 3 and the model nested on
 * an assistant entry rather than at the top level.
 */
function newFormatTranscript(sessionId, { cwd, model, title, prompt, timestamp }) {
  const entries = [
    { type: "mode", mode: "normal", sessionId },
    { type: "permission-mode", permissionMode: "default", sessionId },
    {
      type: "system",
      subtype: "informational",
      sessionId,
      cwd,
      timestamp,
      content: "hook warning",
    },
    {
      type: "assistant",
      sessionId,
      timestamp,
      message: { role: "assistant", model, content: [{ type: "text", text: "ok" }] },
    },
  ];
  if (title) entries.push({ type: "ai-title", sessionId, aiTitle: title });
  entries.push({ type: "user", sessionId, timestamp, message: { role: "user", content: prompt } });
  return entries.map((entry) => JSON.stringify(entry)).join("\n") + "\n";
}

/** Transcript in the legacy shape: the first line carries everything. */
function legacyTranscript(sessionId, { cwd, model, prompt, timestamp }) {
  return (
    [
      { type: "system", subtype: "init", sessionId, cwd, timestamp, model },
      { type: "user", sessionId, timestamp, message: { role: "user", content: prompt } },
    ]
      .map((entry) => JSON.stringify(entry))
      .join("\n") + "\n"
  );
}

/** Write a bare transcript file (no ZIP) for extractor-level tests. */
function writeTranscript(dir, sessionId, body) {
  const filePath = path.join(dir, `${sessionId}.jsonl`);
  fs.writeFileSync(filePath, body, "utf8");
  return filePath;
}

/**
 * Wrap a raw transcript body in the exporter's ZIP layout. The top-level folder
 * suffix is settable so a test can prove the importer does not trust it.
 */
function writeSessionZip(root, sessionId, body, { topDirSuffix = "test" } = {}) {
  const AdmZip = require("adm-zip");
  const zip = new AdmZip();
  const topDir = `session-${sessionId.slice(0, 12)}-${topDirSuffix}`;
  zip.addFile(`${topDir}/session/${sessionId}.jsonl`, Buffer.from(body, "utf8"));
  const zipPath = path.join(root, `export-${sessionId}.zip`);
  zip.writeZip(zipPath);
  return zipPath;
}

/** Every file under `dir`, relative and POSIX-normalised. */
function listFiles(dir) {
  const out = [];
  (function walk(current) {
    if (!fs.existsSync(current)) return;
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === "tmp") continue; // transient extraction scratch
        walk(full);
      } else if (!/\.(db|zip|db-wal|db-shm)$/.test(entry.name)) {
        out.push(path.relative(dir, full).split(path.sep).join("/"));
      }
    }
  })(dir);
  return out.sort();
}

before(() => clearManagedEnv());

afterEach(() => {
  clearManagedEnv();
  for (const dir of tempRoots) {
    try {
      fs.rmSync(dir, { recursive: true, force: true });
    } catch {
      /* best effort */
    }
  }
  tempRoots = [];
});

after(() => {
  try {
    fs.rmSync(TEST_DB, { force: true });
  } catch {
    /* best effort */
  }
  for (const dir of tempRoots) {
    try {
      fs.rmSync(dir, { recursive: true, force: true });
    } catch {}
  }
});

// ─────────────────────────────────────────────────────────────────────────────
describe("getTaskManagementRoot()", () => {
  it("returns TASK_MANAGEMENT_ROOT verbatim when it is set", () => {
    // Arrange
    const runtime = makeTempRoot("container");
    clearManagedEnv();
    process.env.TASK_MANAGEMENT_ROOT = path.join(runtime, "task-management");

    // Act
    const resolved = getTaskManagementRoot();

    // Assert
    assert.equal(resolved, path.join(runtime, "task-management"));
  });

  it("expands a leading ~ in TASK_MANAGEMENT_ROOT", () => {
    // Arrange
    clearManagedEnv();
    process.env.TASK_MANAGEMENT_ROOT = "~/task-management";

    // Act
    const resolved = getTaskManagementRoot();

    // Assert — compared via path.resolve because expansion splices the home dir
    // in verbatim (matching the historical behaviour of the watch/task consumers,
    // which can yield mixed separators on Windows). What matters is that the
    // result is absolute, resolves to the home dir, and keeps no literal "~".
    assert.ok(!resolved.includes("~"), `must not leave a literal ~ in ${resolved}`);
    assert.equal(path.resolve(resolved), path.resolve(os.homedir(), "task-management"));
  });

  it("falls back to <COSIGHT_HOME>/cosight-viewer/task-management in a container", () => {
    // Arrange — viewer-owned data lives under the framework container root,
    // never inside the CLI homes.
    const runtime = makeTempRoot("container");
    clearManagedEnv();
    process.env.COSIGHT_HOME = runtime;

    // Act
    const resolved = getTaskManagementRoot();

    // Assert
    assert.equal(
      resolved,
      path.join(runtime, "cosight-viewer", "task-management")
    );
  });

  it("lets DASHBOARD_DATA_DIR override the viewer data root", () => {
    const dataDir = makeTempRoot("viewer-data");
    clearManagedEnv();
    process.env.COSIGHT_HOME = makeTempRoot("container");
    process.env.DASHBOARD_DATA_DIR = dataDir;

    assert.equal(getTaskManagementRoot(), path.join(dataDir, "task-management"));
  });

  it("never resolves through a CLI home", () => {
    // Arrange — viewer-owned task data must not scatter into ~/.claude or ~/.cosight.
    const home = makeTempRoot("home");
    clearManagedEnv();
    useFakeHome(home);

    // Act
    const resolved = getTaskManagementRoot();

    // Assert
    assert.equal(
      resolved,
      path.join(home, ".cosight-harness", "cosight-viewer", "task-management")
    );
    assert.ok(!resolved.includes(`${path.sep}.claude${path.sep}`));
    assert.ok(!resolved.includes(`${path.sep}.cosight${path.sep}task-management`));
  });

  it("keeps every consumer on TASK_MANAGEMENT_ROOT when the container sets it", () => {
    // Arrange
    const runtime = makeTempRoot("container");
    clearManagedEnv();
    process.env.COSIGHT_HOME = runtime;
    process.env.CLAUDE_HOME = runtime;
    process.env.CO_SIGHT_MODE = "claude";
    process.env.TASK_MANAGEMENT_ROOT = path.join(runtime, "task-management");

    // Act + Assert — the task APIs and the importer must agree.
    assert.equal(getTaskManagementRoot(), process.env.TASK_MANAGEMENT_ROOT);
    assert.equal(
      getImportedSessionsDir(),
      path.join(process.env.TASK_MANAGEMENT_ROOT, "imported-sessions")
    );
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe("importSessionFromZip()", () => {
  it("imports without throwing when TASK_MANAGEMENT_ROOT is unset", async () => {
    // Arrange — this is the exact condition that produced
    // "ReferenceError: getBaseDataDir is not defined".
    const runtime = makeTempRoot("container");
    clearManagedEnv();
    process.env.COSIGHT_HOME = runtime;
    process.env.CLAUDE_HOME = runtime;
    process.env.CO_SIGHT_MODE = "claude";
    const sessionId = crypto.randomUUID();
    const zipPath = buildSessionZip(runtime, sessionId);

    // Act
    const result = await importSessionFromZip(zipPath);

    // Assert
    assert.equal(result.success, true);
    assert.equal(result.session.id, sessionId);
    assert.equal(result.files.jsonl, 1);
    assert.equal(result.files.tasks, 1);
  });

  it("writes the session and its task JSON under one root in standalone claude mode", async () => {
    // Arrange — no COSIGHT_HOME/CLAUDE_HOME/TASK_MANAGEMENT_ROOT: the standalone
    // shape where the destinations used to diverge across ~/.claude and ~/.cosight.
    const home = makeTempRoot("home");
    clearManagedEnv();
    useFakeHome(home);
    process.env.CO_SIGHT_MODE = "claude";

    // Guard: if this Node ever caches os.homedir(), writing here would land in the
    // developer's real home. Skip loudly rather than pollute it.
    if (os.homedir() !== home) {
      assert.fail(
        `os.homedir() did not follow USERPROFILE/HOME (got ${os.homedir()}); ` +
          "skipping to avoid writing outside the temp dir"
      );
    }

    const sessionId = crypto.randomUUID();
    const zipPath = buildSessionZip(home, sessionId);

    // Act
    const result = await importSessionFromZip(zipPath);

    // Assert
    assert.equal(result.success, true);
    const root = path.join(
      home,
      ".cosight-harness",
      "cosight-viewer",
      "task-management"
    );
    const files = listFiles(root);
    const sessionFile = files.find((f) => f.endsWith(`${sessionId}.jsonl`));
    const taskFile = files.find((f) => f.endsWith(`_task_t1.json`));
    assert.ok(sessionFile, `session JSONL should land under ${root}, got ${files.join(", ")}`);
    assert.ok(taskFile, `task JSON should land under ${root}, got ${files.join(", ")}`);
    assert.equal(listFiles(path.join(home, ".claude", "task-management")).length, 0);
    assert.equal(listFiles(path.join(home, ".cosight", "task-management")).length, 0);
  });

  it("places everything under TASK_MANAGEMENT_ROOT in a container", async () => {
    // Arrange — the confirmed container environment.
    const runtime = makeTempRoot("container");
    clearManagedEnv();
    process.env.COSIGHT_HOME = runtime;
    process.env.CLAUDE_HOME = runtime;
    process.env.CO_SIGHT_MODE = "claude";
    process.env.TASK_MANAGEMENT_ROOT = path.join(runtime, "task-management");
    const sessionId = crypto.randomUUID();
    const zipPath = buildSessionZip(runtime, sessionId);

    // Act
    const result = await importSessionFromZip(zipPath);

    // Assert
    assert.equal(result.success, true);
    const files = listFiles(process.env.TASK_MANAGEMENT_ROOT);
    assert.ok(files.some((f) => f.endsWith(`${sessionId}.jsonl`)));
    assert.ok(files.some((f) => f.endsWith(`_task_t1.json`)));
    assert.equal(listFiles(path.join(runtime, ".claude", "task-management")).length, 0);
    assert.equal(listFiles(path.join(runtime, ".cosight", "task-management")).length, 0);
  });

  it("rejects a session that was already imported", async () => {
    // Arrange
    const runtime = makeTempRoot("container");
    clearManagedEnv();
    process.env.COSIGHT_HOME = runtime;
    process.env.CLAUDE_HOME = runtime;
    process.env.CO_SIGHT_MODE = "claude";
    const sessionId = crypto.randomUUID();
    const zipPath = buildSessionZip(runtime, sessionId);
    await importSessionFromZip(zipPath);

    // Act + Assert — imports are idempotent by refusal, not by silent overwrite.
    await assert.rejects(() => importSessionFromZip(zipPath), /已存在/);
  });

  it("imports a new-format session into its real cwd instead of unknown/", async () => {
    // Arrange — a transcript whose first lines are control records, packed under
    // a deliberately useless folder suffix so the importer cannot cheat off it.
    const runtime = makeTempRoot("container");
    clearManagedEnv();
    process.env.COSIGHT_HOME = runtime;
    process.env.CLAUDE_HOME = runtime;
    process.env.CO_SIGHT_MODE = "claude";
    const sessionId = crypto.randomUUID();
    const startedAt = "2026-09-15T03:00:37.031Z";
    const body = newFormatTranscript(sessionId, {
      cwd: "/agent/app",
      model: "qwen3.7-plus",
      title: "WSL命令无法识别",
      prompt: "其实我要装docker",
      timestamp: startedAt,
    });
    const zipPath = writeSessionZip(runtime, sessionId, body, { topDirSuffix: "unknown" });

    // Act
    const result = await importSessionFromZip(zipPath);

    // Assert
    assert.equal(result.success, true);
    const taskRoot = path.join(runtime, "cosight-viewer", "task-management");
    const files = listFiles(taskRoot);
    assert.ok(
      files.includes(`imported-sessions/-agent-app/${sessionId}.jsonl`),
      `expected the transcript under imported-sessions/-agent-app/, got: ${files.join(", ")}`
    );
    assert.equal(listFiles(path.join(taskRoot, "imported-sessions", "unknown")).length, 0);

    const row = stmts.getSession.get(sessionId);
    assert.equal(row.cwd, "/agent/app");
    assert.equal(row.model, "qwen3.7-plus");
    assert.equal(row.name, "WSL命令无法识别");
    // The transcript's own start time, not the moment the import ran.
    assert.equal(row.started_at, startedAt);
    assert.ok(
      new Date(row.started_at) < new Date(Date.now() - 24 * 60 * 60 * 1000),
      "started_at must be the session's time, not the import time"
    );
  });

  it("imports a legacy transcript unchanged", async () => {
    // Arrange
    const runtime = makeTempRoot("container");
    clearManagedEnv();
    process.env.COSIGHT_HOME = runtime;
    process.env.CLAUDE_HOME = runtime;
    process.env.CO_SIGHT_MODE = "claude";
    const sessionId = crypto.randomUUID();
    const startedAt = "2026-08-01T10:20:30.000Z";
    const body = legacyTranscript(sessionId, {
      cwd: "/home/dev/project",
      model: "claude-sonnet-5-5",
      prompt: "legacy first prompt",
      timestamp: startedAt,
    });
    const zipPath = writeSessionZip(runtime, sessionId, body);

    // Act
    const result = await importSessionFromZip(zipPath);

    // Assert
    assert.equal(result.success, true);
    const taskRoot = path.join(runtime, "cosight-viewer", "task-management");
    assert.ok(
      listFiles(taskRoot).includes(`imported-sessions/-home-dev-project/${sessionId}.jsonl`)
    );
    const row = stmts.getSession.get(sessionId);
    assert.equal(row.cwd, "/home/dev/project");
    assert.equal(row.model, "claude-sonnet-5-5");
    assert.equal(row.started_at, startedAt);
    // No title record in a legacy transcript, so the placeholder name stands.
    assert.equal(row.name, `Session ${sessionId.slice(0, 8)}`);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe("extractSessionMetadata()", () => {
  it("reads cwd, start time, model and title past the control-record header", async () => {
    // Arrange
    const dir = makeTempRoot("meta");
    const sessionId = crypto.randomUUID();
    const startedAt = "2026-09-15T03:00:37.031Z";
    const filePath = writeTranscript(
      dir,
      sessionId,
      newFormatTranscript(sessionId, {
        cwd: "/agent/app",
        model: "qwen3.7-plus",
        title: "WSL命令无法识别",
        prompt: "其实我要装docker",
        timestamp: startedAt,
      })
    );

    // Act
    const meta = await extractSessionMetadata(filePath, { sessionId });

    // Assert
    assert.equal(meta.cwd, "/agent/app");
    assert.equal(meta.model, "qwen3.7-plus");
    assert.equal(meta.started_at, startedAt);
    assert.equal(meta.name, "WSL命令无法识别");
    assert.equal(meta.first_prompt, "其实我要装docker");
  });

  it("still resolves a legacy transcript that carries everything on line 1", async () => {
    // Arrange
    const dir = makeTempRoot("meta");
    const sessionId = crypto.randomUUID();
    const startedAt = "2026-08-01T10:20:30.000Z";
    const filePath = writeTranscript(
      dir,
      sessionId,
      legacyTranscript(sessionId, {
        cwd: "/home/dev/project",
        model: "claude-sonnet-5-5",
        prompt: "legacy first prompt",
        timestamp: startedAt,
      })
    );

    // Act
    const meta = await extractSessionMetadata(filePath, { sessionId });

    // Assert
    assert.equal(meta.cwd, "/home/dev/project");
    assert.equal(meta.model, "claude-sonnet-5-5");
    assert.equal(meta.started_at, startedAt);
    assert.equal(meta.first_prompt, "legacy first prompt");
    assert.equal(meta.name, `Session ${sessionId.slice(0, 8)}`);
  });

  it("falls back to the file mtime — never to now — when no timestamp exists", async () => {
    // Arrange — a transcript with no timestamp at all, back-dated on disk.
    const dir = makeTempRoot("meta");
    const sessionId = crypto.randomUUID();
    const filePath = writeTranscript(
      dir,
      sessionId,
      JSON.stringify({ type: "mode", mode: "normal", sessionId }) + "\n"
    );
    const past = new Date("2026-01-02T03:04:05.000Z");
    fs.utimesSync(filePath, past, past);

    // Act
    const meta = await extractSessionMetadata(filePath, { sessionId });

    // Assert — "now" would have been the old bug's signature.
    assert.equal(meta.started_at, past.toISOString());
  });

  it("uses attachment.snapshot.workingDirectory when no entry carries cwd", async () => {
    // Arrange
    const dir = makeTempRoot("meta");
    const sessionId = crypto.randomUUID();
    const body =
      [
        { type: "mode", mode: "normal", sessionId },
        {
          type: "attachment",
          sessionId,
          timestamp: "2026-09-15T03:00:37.031Z",
          attachment: {
            type: "environment",
            snapshot: { workingDirectory: "/agent/from-attachment" },
          },
        },
        {
          type: "user",
          sessionId,
          timestamp: "2026-09-15T03:00:38.000Z",
          message: { role: "user", content: "hi" },
        },
      ]
        .map((entry) => JSON.stringify(entry))
        .join("\n") + "\n";
    const filePath = writeTranscript(dir, sessionId, body);

    // Act
    const meta = await extractSessionMetadata(filePath, { sessionId });

    // Assert
    assert.equal(meta.cwd, "/agent/from-attachment");
  });

  it("takes the last ai-title, matching extract-prompt.js", async () => {
    // Arrange — two titles; both extractors must settle on the newest.
    const dir = makeTempRoot("meta");
    const sessionId = crypto.randomUUID();
    const body =
      [
        { type: "mode", mode: "normal", sessionId },
        { type: "system", sessionId, cwd: "/agent/app", timestamp: "2026-09-15T03:00:37.031Z" },
        { type: "ai-title", sessionId, aiTitle: "第一个标题" },
        {
          type: "user",
          sessionId,
          timestamp: "2026-09-15T03:00:38.000Z",
          message: { role: "user", content: "hi" },
        },
        { type: "ai-title", sessionId, aiTitle: "后来重新生成的标题" },
      ]
        .map((entry) => JSON.stringify(entry))
        .join("\n") + "\n";
    const filePath = writeTranscript(dir, sessionId, body);

    // Act
    const meta = await extractSessionMetadata(filePath, { sessionId });

    // Assert
    assert.equal(meta.name, "后来重新生成的标题");
    assert.equal(extractTitlesFromTranscript(filePath).aiTitle, "后来重新生成的标题");
  });
});

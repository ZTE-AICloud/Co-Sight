// SPDX-License-Identifier: Apache-2.0
/**
 * @file Tests for dual-source path resolution.
 *
 * Two independent concepts must not be mixed:
 * - CLI source homes: CLAUDE_CONFIG_DIR/~/.claude and COSIGHT_CONFIG_DIR/~/.cosight
 * - viewer-owned data: DASHBOARD_DATA_DIR or <COSIGHT_HOME>/cosight-viewer
 *
 * The old implementation used COSIGHT_HOME to derive the CLI home, which
 * produced ~/.claude/.claude and made every transcript lookup silently empty.
 */

const { describe, it, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");

const {
  getViewerDataDir,
  getSourceHomes,
  getProjectsDirs,
  getClaudeHome,
  getTranscriptPath,
  inferSourceFromPath,
  resolveSessionSource,
} = require("../lib/claude-home");

const ENV_KEYS = [
  "COSIGHT_HOME",
  "CLAUDE_CONFIG_DIR",
  "COSIGHT_CONFIG_DIR",
  "DASHBOARD_DATA_DIR",
  "TASK_MANAGEMENT_ROOT",
  "VIEWER_SOURCES",
];
let saved;
const scratchDirs = [];

beforeEach(() => {
  saved = {};
  for (const key of ENV_KEYS) {
    saved[key] = process.env[key];
    delete process.env[key];
  }
});

afterEach(() => {
  for (const key of ENV_KEYS) {
    if (saved[key] === undefined) delete process.env[key];
    else process.env[key] = saved[key];
  }
  for (const dir of scratchDirs.splice(0)) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

function scratch() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "viewer-home-"));
  scratchDirs.push(dir);
  return dir;
}

describe("getViewerDataDir()", () => {
  it("defaults to <home>/.cosight-harness/cosight-viewer", () => {
    assert.equal(
      getViewerDataDir(),
      path.join(os.homedir(), ".cosight-harness", "cosight-viewer")
    );
  });

  it("follows COSIGHT_HOME", () => {
    process.env.COSIGHT_HOME = "/data/cosight-home";
    assert.equal(
      getViewerDataDir(),
      path.join(path.resolve("/data/cosight-home"), "cosight-viewer")
    );
  });

  it("lets DASHBOARD_DATA_DIR override everything", () => {
    process.env.COSIGHT_HOME = "/data/cosight-home";
    process.env.DASHBOARD_DATA_DIR = "/tmp/viewer-data";
    assert.equal(getViewerDataDir(), "/tmp/viewer-data");
  });
});

describe("getSourceHomes() / VIEWER_SOURCES", () => {
  it("defaults to claude only", () => {
    const sources = getSourceHomes();
    assert.deepEqual(
      sources.map((s) => s.id),
      ["claude"]
    );
    assert.equal(sources[0].home, path.join(os.homedir(), ".claude"));
  });

  it("enables cosight only when listed in VIEWER_SOURCES", () => {
    process.env.VIEWER_SOURCES = "claude,cosight";
    const sources = getSourceHomes();
    assert.deepEqual(
      sources.map((s) => s.id),
      ["claude", "cosight"]
    );
    assert.equal(sources[1].home, path.join(os.homedir(), ".cosight"));
  });

  it("honours the native config dir variables", () => {
    process.env.VIEWER_SOURCES = "claude,cosight";
    process.env.CLAUDE_CONFIG_DIR = "/custom/claude";
    process.env.COSIGHT_CONFIG_DIR = "/custom/cosight";
    const sources = getSourceHomes();
    assert.equal(sources[0].home, path.resolve("/custom/claude"));
    assert.equal(sources[1].home, path.resolve("/custom/cosight"));
  });

  it("deduplicates two ids pointing at the same home", () => {
    process.env.VIEWER_SOURCES = "claude,cosight";
    process.env.CLAUDE_CONFIG_DIR = "/same/home";
    process.env.COSIGHT_CONFIG_DIR = "/same/home";
    assert.equal(getSourceHomes().length, 1);
  });

  it("ignores unknown and unimplemented sources", () => {
    process.env.VIEWER_SOURCES = "claude,unknown,codex";
    assert.deepEqual(
      getSourceHomes().map((s) => s.id),
      ["claude"]
    );
  });

  it("falls back to claude when nothing valid is enabled", () => {
    process.env.VIEWER_SOURCES = "unknown,codex";
    assert.deepEqual(
      getSourceHomes().map((s) => s.id),
      ["claude"]
    );
  });

  it("does not let COSIGHT_HOME change the CLI home", () => {
    process.env.COSIGHT_HOME = "/data/cosight-home";
    assert.equal(getClaudeHome(), path.join(os.homedir(), ".claude"));
  });
});

describe("source inference", () => {
  it("infers from the transcript path", () => {
    assert.equal(inferSourceFromPath("/home/u/.cosight/projects/a/b.jsonl"), "cosight");
    assert.equal(inferSourceFromPath("C:\\Users\\u\\.claude\\projects\\a\\b.jsonl"), "claude");
    assert.equal(inferSourceFromPath("/tmp/b.jsonl"), null);
  });

  it("falls back to claude when the session has no source and no usable path", () => {
    assert.equal(resolveSessionSource({ source: "cosight" }), "cosight");
    assert.equal(
      resolveSessionSource({ transcript_path: "/home/u/.cosight/projects/a/b.jsonl" }),
      "cosight"
    );
    assert.equal(resolveSessionSource({}), "claude");
  });
});

describe("getTranscriptPath() searches every source", () => {
  it("finds a cosight transcript by cwd encoding when enabled", () => {
    const cosightHome = scratch();
    process.env.VIEWER_SOURCES = "claude,cosight";
    process.env.COSIGHT_CONFIG_DIR = cosightHome;

    const cwd = "F:\\code\\demo";
    const encoded = cwd.replace(/[^a-zA-Z0-9]/g, "-");
    const dir = path.join(cosightHome, "projects", encoded);
    fs.mkdirSync(dir, { recursive: true });
    const file = path.join(dir, "sess-1.jsonl");
    fs.writeFileSync(file, "{}\n");

    assert.equal(getTranscriptPath("sess-1", cwd), file);
    assert.equal(getProjectsDirs().length, 2);
  });

  it("finds a claude transcript the same way", () => {
    const claudeHome = scratch();
    process.env.CLAUDE_CONFIG_DIR = claudeHome;

    const cwd = "/home/u/ws";
    const encoded = cwd.replace(/[^a-zA-Z0-9]/g, "-");
    const dir = path.join(claudeHome, "projects", encoded);
    fs.mkdirSync(dir, { recursive: true });
    const file = path.join(dir, "sess-2.jsonl");
    fs.writeFileSync(file, "{}\n");

    assert.equal(getTranscriptPath("sess-2", cwd), file);
  });
});

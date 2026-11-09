// SPDX-License-Identifier: Apache-2.0
/**
 * @file Tests that TranscriptCache caps the size of each per-entry array
 * (turnDurations / errors / compaction.entries) so a long
 * session cannot grow a single cache entry without bound.
 */

const { describe, it, before, after } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const os = require("os");

const TranscriptCache = require("../lib/transcript-cache");

let tmpDir;
before(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "tc-bounded-"));
});
after(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

function writeJsonl(name, lines) {
  const p = path.join(tmpDir, name);
  fs.writeFileSync(p, lines.map((l) => JSON.stringify(l)).join("\n") + "\n");
  return p;
}

describe("TranscriptCache._trimArray", () => {
  it("exists and trims arrays to the given max length, keeping the tail", () => {
    const cache = new TranscriptCache();
    assert.equal(typeof cache._trimArray, "function");
    const arr = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
    cache._trimArray(arr, 3);
    assert.deepEqual(arr, [8, 9, 10]);
  });

  it("is a no-op when array is within the cap", () => {
    const cache = new TranscriptCache();
    const arr = [1, 2, 3];
    cache._trimArray(arr, 5);
    assert.deepEqual(arr, [1, 2, 3]);
  });

  it("handles null/undefined safely", () => {
    const cache = new TranscriptCache();
    assert.doesNotThrow(() => cache._trimArray(null, 5));
    assert.doesNotThrow(() => cache._trimArray(undefined, 5));
  });
});

describe("TranscriptCache.extract — array caps", () => {
  it("caps turnDurations at MAX_ARRAY_LEN on full read, keeping the tail", () => {
    // 1500 turn_duration entries, ascending timestamps
    const lines = [];
    for (let i = 0; i < 1500; i++) {
      lines.push({
        type: "system",
        subtype: "turn_duration",
        durationMs: i + 1,
        timestamp: new Date(2026, 0, 1, 0, 0, i).toISOString(),
      });
    }
    const p = writeJsonl("turns.jsonl", lines);

    process.env.TRANSCRIPT_CACHE_MAX_ARRAY_LEN = "100";
    // Re-require fresh to pick up the env override
    delete require.cache[require.resolve("../lib/transcript-cache")];
    const Fresh = require("../lib/transcript-cache");
    const cache = new Fresh();

    const result = cache.extract(p);
    assert.ok(result, "expected non-null result");
    assert.equal(result.turnDurations.length, 100);
    // Tail-kept: durationMs should be 1401..1500
    assert.equal(result.turnDurations[0].durationMs, 1401);
    assert.equal(result.turnDurations[99].durationMs, 1500);

    delete process.env.TRANSCRIPT_CACHE_MAX_ARRAY_LEN;
    delete require.cache[require.resolve("../lib/transcript-cache")];
  });

  it("caps errors and compaction.entries on full read", () => {
    const lines = [];
    for (let i = 0; i < 300; i++) {
      lines.push({
        isApiErrorMessage: true,
        error: "rate_limit",
        message: { content: [{ text: `err-${i}` }] },
        timestamp: new Date(2026, 0, 1, 0, 0, i).toISOString(),
      });
      lines.push({
        isCompactSummary: true,
        uuid: `c-${i}`,
        timestamp: new Date(2026, 0, 1, 0, 0, i).toISOString(),
      });
    }
    const p = writeJsonl("err-compact.jsonl", lines);

    process.env.TRANSCRIPT_CACHE_MAX_ARRAY_LEN = "50";
    delete require.cache[require.resolve("../lib/transcript-cache")];
    const Fresh = require("../lib/transcript-cache");
    const cache = new Fresh();
    const result = cache.extract(p);

    assert.equal(result.errors.length, 50);
    assert.equal(result.compaction.entries.length, 50);
    assert.equal(
      result.compaction.count,
      300,
      "count must reflect ALL parsed entries, not just retained"
    );

    delete process.env.TRANSCRIPT_CACHE_MAX_ARRAY_LEN;
    delete require.cache[require.resolve("../lib/transcript-cache")];
  });

  it("incremental merge respects cap (append to existing capped entry)", () => {
    process.env.TRANSCRIPT_CACHE_MAX_ARRAY_LEN = "100";
    delete require.cache[require.resolve("../lib/transcript-cache")];
    const Fresh = require("../lib/transcript-cache");
    const cache = new Fresh();

    // First batch: 80 turns
    const linesA = [];
    for (let i = 0; i < 80; i++) {
      linesA.push({
        type: "system",
        subtype: "turn_duration",
        durationMs: i + 1,
        timestamp: new Date(2026, 0, 1, 0, 0, i).toISOString(),
      });
    }
    const p = writeJsonl("incr.jsonl", linesA);
    let result = cache.extract(p);
    assert.equal(result.turnDurations.length, 80);

    // Append 50 more — total 130, cache should retain only last 100
    const fd = fs.openSync(p, "a");
    for (let i = 80; i < 130; i++) {
      const line =
        JSON.stringify({
          type: "system",
          subtype: "turn_duration",
          durationMs: i + 1,
          timestamp: new Date(2026, 0, 1, 0, 0, i).toISOString(),
        }) + "\n";
      fs.writeSync(fd, line);
    }
    fs.closeSync(fd);

    result = cache.extract(p);
    assert.equal(result.turnDurations.length, 100);
    // Tail check: last entry should be durationMs=130
    assert.equal(result.turnDurations[99].durationMs, 130);
    // Head should be durationMs=31 (130 - 100 + 1)
    assert.equal(result.turnDurations[0].durationMs, 31);

    delete process.env.TRANSCRIPT_CACHE_MAX_ARRAY_LEN;
    delete require.cache[require.resolve("../lib/transcript-cache")];
  });
});

describe("TranscriptCache._set — single storage", () => {
  it("cache entry contains ONLY {mtimeMs, size, bytesRead, result}", () => {
    const p = writeJsonl("single.jsonl", [
      {
        type: "system",
        subtype: "turn_duration",
        durationMs: 100,
        timestamp: "2026-01-01T00:00:00Z",
      },
    ]);
    const cache = new TranscriptCache();
    cache.extract(p);
    const entry = cache._cache.get(p);
    assert.ok(entry, "entry should be cached");
    const keys = Object.keys(entry).sort();
    assert.deepEqual(keys, ["bytesRead", "mtimeMs", "result", "size"]);
  });

  it("does not store duplicate top-level errors/turnDurations/compaction", () => {
    const p = writeJsonl("dup.jsonl", [
      {
        type: "system",
        subtype: "turn_duration",
        durationMs: 1,
        timestamp: "2026-01-01T00:00:00Z",
      },
      {
        isApiErrorMessage: true,
        error: "x",
        message: { content: [{ text: "y" }] },
        timestamp: "2026-01-01T00:00:01Z",
      },
      { isCompactSummary: true, uuid: "u1", timestamp: "2026-01-01T00:00:02Z" },
    ]);
    const cache = new TranscriptCache();
    cache.extract(p);
    const entry = cache._cache.get(p);
    assert.equal(entry.errors, undefined);
    assert.equal(entry.turnDurations, undefined);
    assert.equal(entry.compaction, undefined);
    assert.equal(entry.tokensByModel, undefined);
    assert.equal(entry.latestModel, undefined);
  });
});

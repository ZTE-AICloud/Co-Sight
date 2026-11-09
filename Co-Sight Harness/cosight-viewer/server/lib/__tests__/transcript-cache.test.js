// SPDX-License-Identifier: Apache-2.0
/**
 * @file Unit tests for the TranscriptCache class, which extracts token usage from Claude transcript JSONL files and caches results for performance. Tests cover cache hits/misses, compaction detection, multiple models, and edge cases like malformed files and eviction behavior.
 */

const { describe, it, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const os = require("os");

let tmpDir;
let TranscriptCache;

function writeJsonl(filePath, entries) {
  fs.writeFileSync(filePath, entries.map((e) => JSON.stringify(e)).join("\n") + "\n");
}

describe("TranscriptCache", () => {
  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "tc-test-"));
    delete require.cache[require.resolve("../../lib/transcript-cache")];
    TranscriptCache = require("../../lib/transcript-cache");
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it("should extract tokens on first read (cache miss)", () => {
    const file = path.join(tmpDir, "session.jsonl");
    writeJsonl(file, [
      {
        message: {
          model: "claude-sonnet-4-20250514",
          usage: { input_tokens: 100, output_tokens: 50 },
        },
      },
      {
        message: {
          model: "claude-sonnet-4-20250514",
          usage: { input_tokens: 200, output_tokens: 75 },
        },
      },
    ]);

    const cache = new TranscriptCache();
    const result = cache.extract(file);

    assert.deepStrictEqual(result.tokensByModel, {
      "claude-sonnet-4-20250514": { input: 300, output: 125, cacheRead: 0, cacheWrite: 0 },
    });
    assert.strictEqual(result.compaction, null);
  });

  it("should return cached result when file is unchanged", () => {
    const file = path.join(tmpDir, "session.jsonl");
    writeJsonl(file, [
      {
        message: {
          model: "claude-sonnet-4-20250514",
          usage: { input_tokens: 100, output_tokens: 50 },
        },
      },
    ]);

    const cache = new TranscriptCache();
    const r1 = cache.extract(file);
    const r2 = cache.extract(file);

    assert.deepStrictEqual(r1, r2);
    // Same object reference proves cache hit (no re-parse)
    assert.strictEqual(r1, r2);
  });

  it("should detect new data when file grows", () => {
    const file = path.join(tmpDir, "session.jsonl");
    writeJsonl(file, [
      {
        message: {
          model: "claude-sonnet-4-20250514",
          usage: { input_tokens: 100, output_tokens: 50 },
        },
      },
    ]);

    const cache = new TranscriptCache();
    const r1 = cache.extract(file);
    assert.strictEqual(r1.tokensByModel["claude-sonnet-4-20250514"].input, 100);

    // Append more data (simulates Claude writing to transcript)
    fs.appendFileSync(
      file,
      JSON.stringify({
        message: {
          model: "claude-sonnet-4-20250514",
          usage: { input_tokens: 200, output_tokens: 75 },
        },
      }) + "\n"
    );

    const r2 = cache.extract(file);
    assert.strictEqual(r2.tokensByModel["claude-sonnet-4-20250514"].input, 300);
    assert.strictEqual(r2.tokensByModel["claude-sonnet-4-20250514"].output, 125);
  });

  it("should do full re-read when file shrinks (compaction rewrite)", () => {
    const file = path.join(tmpDir, "session.jsonl");
    writeJsonl(file, [
      {
        message: {
          model: "claude-sonnet-4-20250514",
          usage: { input_tokens: 500, output_tokens: 200 },
        },
      },
      {
        message: {
          model: "claude-sonnet-4-20250514",
          usage: { input_tokens: 300, output_tokens: 100 },
        },
      },
    ]);

    const cache = new TranscriptCache();
    cache.extract(file);

    // Simulate compaction — file is rewritten with fewer entries + summary
    writeJsonl(file, [
      { isCompactSummary: true, uuid: "abc-123", timestamp: "2026-03-20T10:00:00Z" },
      {
        message: {
          model: "claude-sonnet-4-20250514",
          usage: { input_tokens: 50, output_tokens: 20 },
        },
      },
    ]);

    const r2 = cache.extract(file);
    assert.strictEqual(r2.tokensByModel["claude-sonnet-4-20250514"].input, 50);
    assert.strictEqual(r2.compaction.count, 1);
    assert.strictEqual(r2.compaction.entries[0].uuid, "abc-123");
  });

  it("should return null for non-existent file", () => {
    const cache = new TranscriptCache();
    assert.strictEqual(cache.extract("/nonexistent/file.jsonl"), null);
    assert.strictEqual(cache.extract(null), null);
    assert.strictEqual(cache.extract(""), null);
  });

  it("should expose compaction entries via extractCompactions()", () => {
    const file = path.join(tmpDir, "session.jsonl");
    writeJsonl(file, [
      {
        message: {
          model: "claude-sonnet-4-20250514",
          usage: { input_tokens: 100, output_tokens: 50 },
        },
      },
      { isCompactSummary: true, uuid: "c1", timestamp: "2026-03-20T09:00:00Z" },
      {
        message: {
          model: "claude-sonnet-4-20250514",
          usage: { input_tokens: 50, output_tokens: 20 },
        },
      },
      { isCompactSummary: true, uuid: "c2", timestamp: "2026-03-20T10:00:00Z" },
    ]);

    const cache = new TranscriptCache();
    const compactions = cache.extractCompactions(file);

    assert.strictEqual(compactions.length, 2);
    assert.strictEqual(compactions[0].uuid, "c1");
    assert.strictEqual(compactions[1].uuid, "c2");
  });

  it("should handle multiple models in same file", () => {
    const file = path.join(tmpDir, "session.jsonl");
    writeJsonl(file, [
      {
        message: {
          model: "claude-sonnet-4-20250514",
          usage: { input_tokens: 100, output_tokens: 50 },
        },
      },
      {
        message: {
          model: "claude-opus-4-20250514",
          usage: { input_tokens: 500, output_tokens: 200 },
        },
      },
    ]);

    const cache = new TranscriptCache();
    const result = cache.extract(file);

    assert.strictEqual(result.tokensByModel["claude-sonnet-4-20250514"].input, 100);
    assert.strictEqual(result.tokensByModel["claude-opus-4-20250514"].input, 500);
  });

  it("should skip <synthetic> model entries", () => {
    const file = path.join(tmpDir, "session.jsonl");
    writeJsonl(file, [
      { message: { model: "<synthetic>", usage: { input_tokens: 999, output_tokens: 999 } } },
      {
        message: {
          model: "claude-sonnet-4-20250514",
          usage: { input_tokens: 100, output_tokens: 50 },
        },
      },
    ]);

    const cache = new TranscriptCache();
    const result = cache.extract(file);

    assert.strictEqual(Object.keys(result.tokensByModel).length, 1);
    assert.strictEqual(result.tokensByModel["claude-sonnet-4-20250514"].input, 100);
  });

  it("should handle cache_read and cache_write tokens", () => {
    const file = path.join(tmpDir, "session.jsonl");
    writeJsonl(file, [
      {
        message: {
          model: "claude-sonnet-4-20250514",
          usage: {
            input_tokens: 100,
            output_tokens: 50,
            cache_read_input_tokens: 30,
            cache_creation_input_tokens: 15,
          },
        },
      },
    ]);

    const cache = new TranscriptCache();
    const result = cache.extract(file);

    assert.strictEqual(result.tokensByModel["claude-sonnet-4-20250514"].cacheRead, 30);
    assert.strictEqual(result.tokensByModel["claude-sonnet-4-20250514"].cacheWrite, 15);
  });

  it("should remove entry on invalidate()", () => {
    const file = path.join(tmpDir, "session.jsonl");
    writeJsonl(file, [
      { message: { model: "m1", usage: { input_tokens: 100, output_tokens: 50 } } },
    ]);

    const cache = new TranscriptCache();
    cache.extract(file);
    assert.strictEqual(cache.size, 1);

    cache.invalidate(file);
    assert.strictEqual(cache.size, 0);
  });

  it("should clear all entries", () => {
    const file1 = path.join(tmpDir, "s1.jsonl");
    const file2 = path.join(tmpDir, "s2.jsonl");
    writeJsonl(file1, [
      { message: { model: "m1", usage: { input_tokens: 10, output_tokens: 5 } } },
    ]);
    writeJsonl(file2, [
      { message: { model: "m1", usage: { input_tokens: 20, output_tokens: 10 } } },
    ]);

    const cache = new TranscriptCache();
    cache.extract(file1);
    cache.extract(file2);
    assert.strictEqual(cache.size, 2);

    cache.clear();
    assert.strictEqual(cache.size, 0);
  });

  it("should return correct stats()", () => {
    const file = path.join(tmpDir, "session.jsonl");
    writeJsonl(file, [{ message: { model: "m1", usage: { input_tokens: 10, output_tokens: 5 } } }]);

    const cache = new TranscriptCache();
    cache.extract(file);

    const stats = cache.stats();
    assert.strictEqual(stats.entries, 1);
    assert.strictEqual(stats.paths.length, 1);
    assert.strictEqual(stats.paths[0], file);
  });

  it("should only read new bytes on incremental update", () => {
    const file = path.join(tmpDir, "session.jsonl");
    const line1 =
      JSON.stringify({
        message: { model: "m1", usage: { input_tokens: 100, output_tokens: 50 } },
      }) + "\n";
    fs.writeFileSync(file, line1);

    const cache = new TranscriptCache();
    cache.extract(file);

    // Append a second line
    const line2 =
      JSON.stringify({
        message: { model: "m1", usage: { input_tokens: 200, output_tokens: 75 } },
      }) + "\n";
    fs.appendFileSync(file, line2);

    const r2 = cache.extract(file);
    assert.strictEqual(r2.tokensByModel["m1"].input, 300);

    // Verify bytesRead advanced to full file size
    const entry = cache._cache.get(file);
    assert.strictEqual(entry.bytesRead, Buffer.byteLength(line1 + line2, "utf8"));
  });

  it("should handle incremental read adding new compaction entries", () => {
    const file = path.join(tmpDir, "session.jsonl");
    writeJsonl(file, [
      { message: { model: "m1", usage: { input_tokens: 100, output_tokens: 50 } } },
    ]);

    const cache = new TranscriptCache();
    const r1 = cache.extract(file);
    assert.strictEqual(r1.compaction, null);

    // Append a compaction entry
    fs.appendFileSync(
      file,
      JSON.stringify({ isCompactSummary: true, uuid: "new-c", timestamp: "2026-03-20T12:00:00Z" }) +
        "\n"
    );

    const r2 = cache.extract(file);
    assert.strictEqual(r2.compaction.count, 1);
    assert.strictEqual(r2.compaction.entries[0].uuid, "new-c");
  });

  it("should return null for empty file", () => {
    const file = path.join(tmpDir, "empty.jsonl");
    fs.writeFileSync(file, "");

    const cache = new TranscriptCache();
    assert.strictEqual(cache.extract(file), null);
  });

  it("should skip malformed JSON lines gracefully", () => {
    const file = path.join(tmpDir, "session.jsonl");
    fs.writeFileSync(
      file,
      [
        "not valid json",
        JSON.stringify({
          message: { model: "m1", usage: { input_tokens: 100, output_tokens: 50 } },
        }),
        "{broken",
      ].join("\n") + "\n"
    );

    const cache = new TranscriptCache();
    const result = cache.extract(file);
    assert.strictEqual(result.tokensByModel["m1"].input, 100);
  });

  it("should evict oldest entries when exceeding maxEntries", () => {
    const cache = new TranscriptCache(3); // max 3 entries
    const files = [];
    for (let i = 0; i < 5; i++) {
      const file = path.join(tmpDir, `s${i}.jsonl`);
      writeJsonl(file, [
        { message: { model: "m1", usage: { input_tokens: i * 10, output_tokens: i * 5 } } },
      ]);
      files.push(file);
    }

    // Fill cache with 5 entries, but max is 3
    for (const f of files) cache.extract(f);

    assert.strictEqual(cache.size, 3);
    // Oldest two (s0, s1) should be evicted; newest three (s2, s3, s4) remain
    const stats = cache.stats();
    assert.ok(!stats.paths.includes(files[0]), "oldest entry s0 should be evicted");
    assert.ok(!stats.paths.includes(files[1]), "second-oldest entry s1 should be evicted");
    assert.ok(stats.paths.includes(files[2]), "s2 should remain");
    assert.ok(stats.paths.includes(files[3]), "s3 should remain");
    assert.ok(stats.paths.includes(files[4]), "s4 should remain");
  });

  it("should refresh LRU order on access", () => {
    const cache = new TranscriptCache(3);
    const files = [];
    for (let i = 0; i < 3; i++) {
      const file = path.join(tmpDir, `lru${i}.jsonl`);
      writeJsonl(file, [
        { message: { model: "m1", usage: { input_tokens: 10, output_tokens: 5 } } },
      ]);
      files.push(file);
      cache.extract(file);
    }

    // Access file[0] again (moves it to most-recently-used)
    fs.appendFileSync(
      files[0],
      JSON.stringify({ message: { model: "m1", usage: { input_tokens: 5, output_tokens: 2 } } }) +
        "\n"
    );
    cache.extract(files[0]);

    // Add a new file — should evict file[1] (now the oldest), not file[0]
    const newFile = path.join(tmpDir, "lru_new.jsonl");
    writeJsonl(newFile, [
      { message: { model: "m1", usage: { input_tokens: 1, output_tokens: 1 } } },
    ]);
    cache.extract(newFile);

    assert.strictEqual(cache.size, 3);
    const stats = cache.stats();
    assert.ok(stats.paths.includes(files[0]), "recently accessed file should remain");
    assert.ok(!stats.paths.includes(files[1]), "oldest untouched file should be evicted");
    assert.ok(stats.paths.includes(files[2]), "file[2] should remain");
    assert.ok(stats.paths.includes(newFile), "new file should be present");
  });

  it("should return defensive copy from extractCompactions", () => {
    const file = path.join(tmpDir, "session.jsonl");
    writeJsonl(file, [
      { isCompactSummary: true, uuid: "c1", timestamp: "2026-03-20T09:00:00Z" },
      { message: { model: "m1", usage: { input_tokens: 10, output_tokens: 5 } } },
    ]);

    const cache = new TranscriptCache();
    const compactions = cache.extractCompactions(file);
    assert.strictEqual(compactions.length, 1);

    // Mutate returned array — should NOT affect cache
    compactions.push({ uuid: "fake", timestamp: null });
    compactions[0].uuid = "mutated";

    const compactions2 = cache.extractCompactions(file);
    assert.strictEqual(compactions2.length, 1);
    assert.strictEqual(compactions2[0].uuid, "c1");
  });

  it("should return empty array from extractCompactions for file with no compactions", () => {
    const file = path.join(tmpDir, "session.jsonl");
    writeJsonl(file, [{ message: { model: "m1", usage: { input_tokens: 10, output_tokens: 5 } } }]);

    const cache = new TranscriptCache();
    const compactions = cache.extractCompactions(file);
    assert.deepStrictEqual(compactions, []);
  });

  it("should return empty array from extractCompactions for non-existent file", () => {
    const cache = new TranscriptCache();
    const compactions = cache.extractCompactions("/nonexistent.jsonl");
    assert.deepStrictEqual(compactions, []);
  });
});

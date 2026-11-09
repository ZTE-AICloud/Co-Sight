// SPDX-License-Identifier: Apache-2.0
const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

/**
 * Parse the timestamp from a JSONL line. Returns epoch ms or null.
 * (Inline reference implementation for testing — actual code lives in replay-feed.ts)
 */
function parseTimestamp(jsonLine) {
  try {
    const obj = JSON.parse(jsonLine);
    const ts = obj.timestamp;
    if (!ts) return null;
    const epoch = Date.parse(ts);
    return Number.isNaN(epoch) ? null : epoch;
  } catch {
    return null;
  }
}

/**
 * Assign synthetic timestamps to lines that lack a real timestamp.
 * Each no-ts line inherits the preceding line's effective timestamp.
 * Lines before the first ts use the first ts value.
 */
function assignSyntheticTimestamps(lines) {
  let firstTsIndex = -1;
  const timestamps = [];

  for (let i = 0; i < lines.length; i++) {
    const ts = parseTimestamp(lines[i]);
    timestamps.push(ts);
    if (firstTsIndex === -1 && ts !== null) {
      firstTsIndex = i;
    }
  }

  const result = [];
  for (let i = 0; i < lines.length; i++) {
    const ts = timestamps[i];
    if (ts !== null) {
      result.push(ts);
    } else if (i > 0 && result.length > 0) {
      result.push(result[i - 1]);
    } else {
      result.push(timestamps[firstTsIndex] ?? 0);
    }
  }

  return result;
}

describe("parseTimestamp", () => {
  it("parses a valid ISO 8601 timestamp", () => {
    const ts = parseTimestamp('{"timestamp":"2026-05-19T07:35:42.869Z","type":"assistant"}');
    assert.equal(ts, Date.parse("2026-05-19T07:35:42.869Z"));
  });

  it("returns null when timestamp field is missing", () => {
    const ts = parseTimestamp('{"type":"file-history-snapshot"}');
    assert.equal(ts, null);
  });

  it("returns null when timestamp is empty string", () => {
    const ts = parseTimestamp('{"timestamp":"","type":"assistant"}');
    assert.equal(ts, null);
  });

  it("returns null for invalid JSON", () => {
    const ts = parseTimestamp("not json");
    assert.equal(ts, null);
  });
});

describe("assignSyntheticTimestamps", () => {
  it("passes through lines that all have timestamps", () => {
    const lines = [
      '{"timestamp":"2026-05-19T07:00:00.000Z"}',
      '{"timestamp":"2026-05-19T07:00:01.000Z"}',
    ];
    const result = assignSyntheticTimestamps(lines);
    assert.equal(result[0], Date.parse("2026-05-19T07:00:00.000Z"));
    assert.equal(result[1], Date.parse("2026-05-19T07:00:01.000Z"));
  });

  it("inherits preceding timestamp for no-ts lines", () => {
    const lines = [
      '{"timestamp":"2026-05-19T07:00:00.000Z"}',
      '{"type":"file-history-snapshot"}',
      '{"timestamp":"2026-05-19T07:00:02.000Z"}',
    ];
    const result = assignSyntheticTimestamps(lines);
    assert.equal(result[1], result[0], "no-ts line inherits preceding ts");
  });

  it("uses first timestamp for lines before any ts", () => {
    const lines = [
      '{"type":"file-history-snapshot"}',
      '{"type":"file-history-snapshot"}',
      '{"timestamp":"2026-05-19T07:00:00.000Z"}',
    ];
    const result = assignSyntheticTimestamps(lines);
    const expectedTs = Date.parse("2026-05-19T07:00:00.000Z");
    assert.equal(result[0], expectedTs);
    assert.equal(result[1], expectedTs);
  });

  it("consecutive no-ts lines get same ts (stable sort preserves order)", () => {
    const lines = [
      '{"timestamp":"2026-05-19T07:00:00.000Z"}',
      '{"type":"no-ts-1"}',
      '{"type":"no-ts-2"}',
      '{"type":"no-ts-3"}',
      '{"timestamp":"2026-05-19T07:00:05.000Z"}',
    ];
    const result = assignSyntheticTimestamps(lines);
    assert.equal(result[1], result[0]);
    assert.equal(result[2], result[0]);
    assert.equal(result[3], result[0]);
  });
});

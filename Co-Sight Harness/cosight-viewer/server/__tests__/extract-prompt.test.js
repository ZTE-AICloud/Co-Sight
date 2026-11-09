// SPDX-License-Identifier: Apache-2.0
/**
 * @file Pure-function tests for server/lib/extract-prompt.js.
 */

const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");

const {
  formatPromptForTitle,
  extractFirstPromptFromTranscript,
  MAX_FIRST_PROMPT_LENGTH,
} = require("../lib/extract-prompt");

describe("formatPromptForTitle", () => {
  it("returns plain text unchanged", () => {
    assert.equal(formatPromptForTitle("帮我加个标题列"), "帮我加个标题列");
  });

  it("beautifies slash command with args", () => {
    const input =
      "<command-name>/brainstorming</command-name><command-args>\n加标题列\n</command-args>";
    const result = formatPromptForTitle(input);
    assert.ok(result.startsWith("/brainstorming"), `expected /brainstorming prefix, got: ${result}`);
    assert.ok(result.includes("加标题列"), `expected args included, got: ${result}`);
    assert.ok(!result.includes("<command-name>"), "should not contain XML tags");
    assert.ok(!result.includes("<command-args>"), "should not contain XML tags");
  });

  it("handles slash command without args", () => {
    const result = formatPromptForTitle("<command-name>/clear</command-name>");
    assert.equal(result, "/clear");
  });

  it("handles slash command with empty args block", () => {
    const result = formatPromptForTitle(
      "<command-name>/init</command-name><command-args>   </command-args>"
    );
    assert.equal(result, "/init");
  });

  it("truncates to MAX_FIRST_PROMPT_LENGTH", () => {
    const long = "x".repeat(3000);
    const result = formatPromptForTitle(long);
    assert.equal(result.length, MAX_FIRST_PROMPT_LENGTH);
  });

  it("returns null for blank input", () => {
    assert.equal(formatPromptForTitle(""), null);
    assert.equal(formatPromptForTitle("   "), null);
  });

  it("returns null for non-string input", () => {
    assert.equal(formatPromptForTitle(null), null);
    assert.equal(formatPromptForTitle(undefined), null);
    assert.equal(formatPromptForTitle(42), null);
  });

  it("collapses multi-line whitespace to single line", () => {
    const result = formatPromptForTitle("line1\n  line2\t  line3");
    assert.equal(result, "line1 line2 line3");
  });
});

describe("extractFirstPromptFromTranscript", () => {
  function writeJsonl(lines) {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "fp-test-"));
    const file = path.join(dir, "test.jsonl");
    fs.writeFileSync(file, lines.map((l) => JSON.stringify(l)).join("\n"));
    return file;
  }

  it("returns the first user message with string content", () => {
    const file = writeJsonl([
      { type: "system", subtype: "init", timestamp: "2026-01-01T00:00:00Z" },
      {
        type: "user",
        message: { content: "first prompt" },
        timestamp: "2026-01-01T00:01:00Z",
      },
    ]);
    const result = extractFirstPromptFromTranscript(file);
    assert.deepEqual(result, {
      content: "first prompt",
      timestamp: "2026-01-01T00:01:00Z",
    });
  });

  it("skips isCompactSummary entries", () => {
    const file = writeJsonl([
      {
        type: "user",
        message: { content: "compact summary" },
        isCompactSummary: true,
        timestamp: "2026-01-01T00:00:00Z",
      },
      {
        type: "user",
        message: { content: "real prompt" },
        timestamp: "2026-01-01T00:01:00Z",
      },
    ]);
    const result = extractFirstPromptFromTranscript(file);
    assert.deepEqual(result, {
      content: "real prompt",
      timestamp: "2026-01-01T00:01:00Z",
    });
  });

  it("skips blank-string content", () => {
    const file = writeJsonl([
      { type: "user", message: { content: "   " }, timestamp: "2026-01-01T00:00:00Z" },
      {
        type: "user",
        message: { content: "actual prompt" },
        timestamp: "2026-01-01T00:01:00Z",
      },
    ]);
    const result = extractFirstPromptFromTranscript(file);
    assert.equal(result.content, "actual prompt");
  });

  it("skips user messages with array content (tool results)", () => {
    const file = writeJsonl([
      {
        type: "user",
        message: { content: [{ type: "tool_result", content: "ok" }] },
        timestamp: "2026-01-01T00:00:00Z",
      },
      {
        type: "user",
        message: { content: "real prompt" },
        timestamp: "2026-01-01T00:01:00Z",
      },
    ]);
    const result = extractFirstPromptFromTranscript(file);
    assert.equal(result.content, "real prompt");
  });

  it("returns null for non-existent file", () => {
    const result = extractFirstPromptFromTranscript("/nonexistent/file.jsonl");
    assert.equal(result, null);
  });

  it("returns null when no user message found", () => {
    const file = writeJsonl([{ type: "system", subtype: "init" }]);
    const result = extractFirstPromptFromTranscript(file);
    assert.equal(result, null);
  });

  it("returns null for null/undefined path", () => {
    assert.equal(extractFirstPromptFromTranscript(null), null);
    assert.equal(extractFirstPromptFromTranscript(undefined), null);
  });
});

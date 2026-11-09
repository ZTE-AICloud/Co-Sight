// SPDX-License-Identifier: Apache-2.0
/**
 * @file Regression tests for TPS on the live transcript_update path.
 * TranscriptMessage objects broadcast by the file watcher must carry the same
 * per-message tps/durationMs as the transcript endpoint. Previously
 * parseJsonlEntry produced messages without tps, so any assistant message that
 * reached the UI via the WebSocket file-watcher path displayed tokens but no
 * tokens-per-second — even though the same message queried from the transcript
 * endpoint had a tps.
 *
 * Also covers watch-start seeding: the watcher begins at the file's current line
 * count so the first broadcast only carries lines appended after watching began
 * (instead of replaying the whole file, which duplicated already-displayed
 * messages and delivered no-tps copies of them).
 */

const { describe, it, before, after } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const os = require("os");

const fileWatcher = require("../lib/file-watcher");

let tmpDir;
let filePath;

function userEntry(content, timestamp) {
  return { type: "user", message: { role: "user", content }, timestamp };
}

function assistantEntry(text, timestamp, usage) {
  // Under the block rule, TPS is only computed when input_tokens > 0.
  // Auto-inject input_tokens when usage is provided without it, so existing
  // tests that only specify output_tokens still exercise the TPS path.
  let effectiveUsage = usage;
  if (usage && !("input_tokens" in usage)) {
    effectiveUsage = { input_tokens: 100, ...usage };
  }
  return {
    type: "assistant",
    message: {
      role: "assistant",
      content: [{ type: "text", text }],
      ...(effectiveUsage ? { usage: effectiveUsage } : {}),
    },
    timestamp,
  };
}

function thinkingEntry(thinking, timestamp, usage = { input_tokens: 100, output_tokens: 0 }) {
  return {
    type: "assistant",
    message: {
      role: "assistant",
      content: [{ type: "thinking", thinking }],
      usage,
    },
    timestamp,
  };
}

function toolUseEntry(name, timestamp, usage) {
  return {
    type: "assistant",
    message: {
      role: "assistant",
      content: [{ type: "tool_use", id: "t1", name, input: {} }],
      ...(usage ? { usage } : {}),
    },
    timestamp,
  };
}

function toolResultEntry(content, timestamp) {
  return {
    type: "user",
    message: {
      role: "user",
      content: [{ type: "tool_result", tool_use_id: "t1", content }],
    },
    timestamp,
  };
}

function writeJsonl(lines) {
  fs.writeFileSync(filePath, lines.map((l) => JSON.stringify(l)).join("\n") + "\n");
}

function appendJsonl(lines) {
  fs.appendFileSync(filePath, lines.map((l) => JSON.stringify(l)).join("\n") + "\n");
}

before(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "fw-tps-"));
  filePath = path.join(tmpDir, "session.jsonl");
});

after(() => {
  fileWatcher.shutdown();
  try {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  } catch {
    // ignore cleanup errors
  }
});

describe("FileWatcher TPS on the transcript_update path", () => {
  it("seeds watch position and computes TPS for the first new assistant (batch head)", async () => {
    // Watch starts on an existing transcript: user 00:00:01 → assistant 00:00:03
    // (out 100) → user 00:00:05.
    writeJsonl([
      userEntry("a", "2026-01-01T00:00:01Z"),
      assistantEntry("b", "2026-01-01T00:00:03Z", { output_tokens: 100 }),
      userEntry("c", "2026-01-01T00:00:05Z"),
    ]);

    const started = fileWatcher.addClient("s1", filePath, "c1");
    assert.equal(started, true);
    try {
      const state = fileWatcher.watchers.get("s1");
      assert.equal(state.lastLine, 3, "watch position seeds to the current line count");
      assert.equal(
        state.prevTs,
        "2026-01-01T00:00:05Z",
        "prevTs seeds to the last user/assistant timestamp"
      );

      // Append the next exchange; the assistant is the batch head — its in-file
      // predecessor (user 00:00:05) is outside this batch and must seed it.
      appendJsonl([
        assistantEntry("d", "2026-01-01T00:00:07Z", { output_tokens: 200 }),
        userEntry("e", "2026-01-01T00:00:09Z"),
      ]);

      const { messages, lastLine, prevTs } = await fileWatcher._readNewLines(
        filePath,
        state.lastLine,
        state.prevTs
      );

      assert.equal(lastLine, 5, "only the 2 new lines are counted, not the whole file");
      assert.equal(prevTs, "2026-01-01T00:00:09Z");
      assert.equal(messages.length, 2, "only lines appended after watch start are returned");

      const head = messages[0];
      assert.equal(head.type, "assistant");
      assert.equal(head.tps, 100, "200 output / 2s = 100 tok/s against the seeded predecessor");
      assert.equal(head.durationMs, 2000);
      assert.equal(head.usage.output_tokens, 200);
    } finally {
      fileWatcher.stopWatching("s1");
    }
  });

  it("_scanSeed counts lines and prevTs like the reader does", () => {
    // 3 complete lines + trailing newline; the trailing '' segment is dropped.
    // The final user entry (00:00:05) breaks the block that the assistant started.
    // blockBoundaryTs stays at the user where the block began (00:00:01).
    writeJsonl([
      userEntry("a", "2026-01-01T00:00:01Z"),
      assistantEntry("b", "2026-01-01T00:00:03Z", { output_tokens: 100 }),
      userEntry("c", "2026-01-01T00:00:05Z"),
    ]);

    const seed = fileWatcher._scanSeed(filePath);
    assert.deepEqual(seed, {
      lastLine: 3,
      prevTs: "2026-01-01T00:00:05Z",
      blockBoundaryTs: "2026-01-01T00:00:01Z",
      prevIsAssistantCall: false,
    });
  });

  it("_scanSeed tracks thinking-only assistant and last real user prompt", () => {
    // user 00:00:01 → thinking-only assistant 00:00:03 → tool_result user 00:00:04.
    // The thinking-only assistant sets prevIsAssistantCall; the tool_result user
    // does NOT displace blockBoundaryTs (stays at 00:00:01).
    writeJsonl([
      userEntry("a", "2026-01-01T00:00:01Z"),
      {
        type: "assistant",
        message: {
          role: "assistant",
          content: [{ type: "thinking", thinking: "planning..." }],
          usage: { input_tokens: 100, output_tokens: 0 },
        },
        timestamp: "2026-01-01T00:00:03Z",
      },
      {
        type: "user",
        message: {
          role: "user",
          content: [{ type: "tool_result", tool_use_id: "t1", content: "ok" }],
        },
        timestamp: "2026-01-01T00:00:04Z",
      },
    ]);

    const seed = fileWatcher._scanSeed(filePath);
    assert.equal(seed.lastLine, 3);
    assert.equal(seed.prevTs, "2026-01-01T00:00:04Z", "immediate predecessor is the tool_result user");
    assert.equal(seed.blockBoundaryTs, "2026-01-01T00:00:01Z", "block started at the user before thinking");
    assert.equal(seed.prevIsAssistantCall, false, "tool_result broke the block");
  });

  it("does not return already-seen lines when the file is unchanged", async () => {
    // Self-contained fixture: two lines already present, lastLine seeded to 2.
    writeJsonl([
      userEntry("a", "2026-01-01T00:00:01Z"),
      assistantEntry("b", "2026-01-01T00:00:03Z", { output_tokens: 100 }),
    ]);

    fileWatcher.addClient("s2", filePath, "c2");
    try {
      const state = fileWatcher.watchers.get("s2");
      assert.equal(state.lastLine, 2);

      // No new lines → nothing returned. This is the guard against replaying
      // the whole file (which previously duplicated every already-displayed
      // message with a no-tps copy).
      const { messages } = await fileWatcher._readNewLines(filePath, state.lastLine, state.prevTs);
      assert.equal(messages.length, 0, "no new lines → nothing to broadcast");
    } finally {
      fileWatcher.stopWatching("s2");
    }
  });

  it("leaves tps undefined for assistant messages without usage or predecessor", async () => {
    // File: user 00:00:01 → assistant (no usage) 00:00:03 → assistant 00:00:05 (out 50).
    writeJsonl([
      userEntry("a", "2026-01-01T00:00:01Z"),
      assistantEntry("b", "2026-01-01T00:00:03Z"), // no usage
    ]);
    appendJsonl([assistantEntry("c", "2026-01-01T00:00:05Z", { output_tokens: 50 })]);

    // Read from line 1 with no seed: the no-usage assistant gets no tps, the
    // usage assistant measures against its predecessor (00:00:03).
    const { messages } = await fileWatcher._readNewLines(filePath, 0, null);
    assert.equal(messages.length, 3);
    assert.equal(messages[0].type, "user");
    assert.equal(messages[1].tps, undefined, "no usage → no tps");
    assert.equal(messages[2].tps, 25, "50 output / 2s = 25 tok/s");
    assert.equal(messages[2].durationMs, 2000);
  });

  it("includes thinking time when the previous assistant was thinking-only", async () => {
    // Watch starts after: real user 00:00:01 → thinking-only 00:00:03 →
    // real user 00:00:05. Then a thinking/response split is appended:
    //   thinking-only 00:00:07 → text response 00:00:10 (out 300).
    // The text response must measure from the real user prompt (00:00:05),
    // NOT the thinking-only entry (00:00:07), so thinking time counts.
    writeJsonl([
      userEntry("a", "2026-01-01T00:00:01Z"),
      thinkingEntry("plan A", "2026-01-01T00:00:03Z"),
      userEntry("b", "2026-01-01T00:00:05Z"),
    ]);

    fileWatcher.addClient("s3", filePath, "c3");
    try {
      const state = fileWatcher.watchers.get("s3");
      assert.equal(state.lastLine, 3);
      assert.equal(state.blockBoundaryTs, "2026-01-01T00:00:01Z", "block started at user before thinking");
      // User "b" (line 3) broke the block, so prevIsAssistantCall is false.
      assert.equal(state.prevIsAssistantCall, false);

      appendJsonl([
        thinkingEntry("plan B", "2026-01-01T00:00:07Z"),
        assistantEntry("reply", "2026-01-01T00:00:10Z", { output_tokens: 300 }),
      ]);

      const { messages, lastLine, blockBoundaryTs, prevIsAssistantCall } =
        await fileWatcher._readNewLines(
          filePath,
          state.lastLine,
          state.prevTs,
          state.blockBoundaryTs,
          state.prevIsAssistantCall
        );

      assert.equal(lastLine, 5);
      assert.equal(messages.length, 2);
      // Thinking-only bubble: no tps, but sets the flag for the next assistant.
      // Renders as the canonical {type:"thinking", text} shape (same as the
      // transcript endpoint), so MessageList's Thinking bubble shows on live.
      assert.equal(messages[0].type, "assistant");
      assert.equal(messages[0].content[0].type, "thinking");
      assert.equal(messages[0].content[0].text, "plan B");
      assert.equal(messages[0].tps, undefined, "thinking-only → no tps");
      // Text response: 300 tokens over the full 5s from the real user prompt.
      assert.equal(messages[1].type, "assistant");
      assert.equal(messages[1].tps, 60, "300 output / 5s (thinking incl.) = 60 tok/s");
      assert.equal(messages[1].durationMs, 5000);
      // State advanced: last real user unchanged; last assistant was the text
      // response (not thinking-only), so the flag clears.
      assert.equal(blockBoundaryTs, "2026-01-01T00:00:05Z", "block started at user b");
      assert.equal(prevIsAssistantCall, true, "text response continues the block");
    } finally {
      fileWatcher.stopWatching("s3");
    }
  });

  it("deepseek-style split: thinking entry with output_tokens>0 still yields no tps and text measures from the real user", async () => {
    // deepseek-v4-flash writes the SAME usage on the thinking and text entries,
    // so the thinking entry's output_tokens>0 must not break thinking detection.
    // user 00:00:01 → thinking(out 49) 00:00:03 → text(out 49) 00:00:05.
    writeJsonl([
      userEntry("a", "2026-01-01T00:00:01Z"),
      thinkingEntry("plan", "2026-01-01T00:00:03Z", { input_tokens: 55, output_tokens: 49 }),
      assistantEntry("reply", "2026-01-01T00:00:05Z", { input_tokens: 55, output_tokens: 49 }),
    ]);

    const { messages, prevIsAssistantCall } = await fileWatcher._readNewLines(
      filePath, 0, null, null, false
    );

    assert.equal(messages.length, 3);
    // Thinking-only bubble: no tps even though output_tokens>0, and its usage
    // is not double-counted into a TPS figure.
    assert.equal(messages[1].type, "assistant");
    assert.equal(messages[1].content[0].type, "thinking");
    assert.equal(messages[1].tps, undefined, "thinking-only → no tps despite out>0");
    // Text response: 49 output over the full 4s from the real user prompt.
    assert.equal(messages[2].type, "assistant");
    assert.equal(messages[2].tps, 12.25, "49 output / 4s (thinking incl.) = 12.25 tok/s");
    assert.equal(messages[2].durationMs, 4000);
    // State advanced: the last assistant seen was the text response (with
    // input_tokens, so in the block).
    assert.equal(prevIsAssistantCall, true);
  });

  it("tool_use-only continuation (out=0) keeps the thinking-inclusive baseline", async () => {
    // deepseek-v4-pro split: user → thinking(out=0) → tool_use(out=0) →
    // tool_use(out=280). The out=0 tool_use is part of the SAME turn and must
    // NOT clear the thinking-inclusive flag, so the token-carrying tool_use
    // still measures from the real user prompt (thinking time counts).
    writeJsonl([
      userEntry("a", "2026-01-01T00:00:01Z"),
      thinkingEntry("plan", "2026-01-01T00:00:03Z"),
      toolUseEntry("Bash", "2026-01-01T00:00:04Z", { input_tokens: 10, output_tokens: 0 }),
      toolUseEntry("Bash", "2026-01-01T00:00:05Z", { input_tokens: 10, output_tokens: 280 }),
    ]);

    const { messages, prevIsAssistantCall } = await fileWatcher._readNewLines(
      filePath, 0, null, null, false
    );

    assert.equal(messages.length, 4);
    // thinking-only: no tps, sets the flag.
    assert.equal(messages[1].type, "assistant");
    assert.equal(messages[1].tps, undefined, "thinking-only → no tps");
    // out=0 tool_use: no tps (out=0), but keeps the flag — its duration is
    // still measured from the real user, showing the baseline persists.
    assert.equal(messages[2].type, "assistant");
    assert.equal(messages[2].tps, undefined, "out=0 tool_use → no tps");
    assert.equal(messages[2].durationMs, 3000, "out=0 tool_use measured from the real user (flag kept)");
    // token-carrying tool_use: 280 output over the full 4s from the real user.
    assert.equal(messages[3].type, "assistant");
    assert.equal(messages[3].tps, 70, "280 output / 4s (thinking incl.) = 70 tok/s");
    assert.equal(messages[3].durationMs, 4000);
    // Block still active after the token-carrying entry.
    assert.equal(prevIsAssistantCall, true);
  });

  it("_scanSeed keeps prevIsAssistantCall true when the file ends mid-turn (tool_use out=0)", () => {
    // File ends after an out=0 tool_use continuation of a thinking split — the
    // next appended token-carrying entry must still measure from the real user.
    writeJsonl([
      userEntry("a", "2026-01-01T00:00:01Z"),
      thinkingEntry("plan", "2026-01-01T00:00:03Z"),
      toolUseEntry("Bash", "2026-01-01T00:00:04Z", { input_tokens: 10, output_tokens: 0 }),
    ]);

    const seed = fileWatcher._scanSeed(filePath);
    assert.equal(seed.lastLine, 3);
    assert.equal(
      seed.prevIsAssistantCall,
      true,
      "out=0 tool_use continuation keeps the block alive for the next batch head"
    );
    assert.equal(seed.blockBoundaryTs, "2026-01-01T00:00:01Z");
    assert.equal(seed.prevTs, "2026-01-01T00:00:04Z");
  });

  it("cosight single-assistant mode is unchanged (no thinking split)", async () => {
    // Cosight writes ONE assistant per turn with real output tokens — no
    // thinking-only entry, so TPS keeps measuring against the immediate
    // predecessor. A tool_result feed between turns advances the immediate
    // predecessor (prevTs) but must NOT shift the thinking-inclusive baseline.
    writeJsonl([
      userEntry("a", "2026-01-01T00:00:01Z"),
      toolResultEntry("out", "2026-01-01T00:00:04Z"),
      assistantEntry("b", "2026-01-01T00:00:06Z", { input_tokens: 10, output_tokens: 100 }),
    ]);

    // Read the whole file with no seed.
    const { messages, blockBoundaryTs } = await fileWatcher._readNewLines(
      filePath, 0, null, null, false
    );
    // tool_result-only user entries are not displayable → skipped as messages,
    // but they still advance the running predecessor.
    assert.equal(messages.length, 2);
    assert.equal(messages[0].type, "user");
    assert.equal(messages[1].type, "assistant");
    assert.equal(messages[1].tps, 50, "100 output / 2s (from tool_result 00:00:04) = 50 tok/s");
    assert.equal(messages[1].durationMs, 2000);
    assert.equal(
      blockBoundaryTs,
      "2026-01-01T00:00:04Z",
      "tool_result is the block boundary for the next assistant"
    );
  });
});

// SPDX-License-Identifier: Apache-2.0
/**
 * @file Verifies the sweep queries used in server/index.js don't read
 * transcript_path via json_extract(events.data,...). The compaction-agent
 * sweep that previously read active sessions' transcript_path was removed
 * (compaction no longer generates agents), so only the negative check remains.
 */

const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(__dirname, "..", "index.js"), "utf8");

describe("server/index.js sweep queries", () => {
  it("does NOT contain json_extract on events.data for transcript_path", () => {
    const matches = SRC.match(/json_extract\([^)]*events?\.data[^)]*transcript_path/gi) || [];
    assert.equal(
      matches.length,
      0,
      `expected zero events.data json_extract for transcript_path; found:\n${matches.join("\n")}`
    );
  });
});

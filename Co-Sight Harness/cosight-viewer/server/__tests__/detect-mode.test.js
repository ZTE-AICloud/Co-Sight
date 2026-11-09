// SPDX-License-Identifier: Apache-2.0
/**
 * @file Pure-function tests for server/lib/detect-mode.js.
 */

const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const os = require("os");
const path = require("path");

const { detectClaudeCosight } = require("../lib/detect-mode");

describe("detectClaudeCosight", () => {
  it("returns correct top-level structure", () => {
    const result = detectClaudeCosight();

    assert.ok(typeof result === "object" && result !== null);
    assert.ok("claude" in result, "missing claude field");
    assert.ok("cosight" in result, "missing cosight field");
    assert.ok("currentMode" in result, "missing currentMode field");
    assert.ok("recommendedMode" in result, "missing recommendedMode field");
    assert.ok("anyInstalled" in result, "missing anyInstalled field");
  });

  it("returns correct ToolStatus structure for each tool", () => {
    const result = detectClaudeCosight();

    for (const tool of [result.claude, result.cosight]) {
      assert.equal(typeof tool.installed, "boolean");
      assert.ok(
        tool.commandPath === null || typeof tool.commandPath === "string",
        "commandPath must be string or null"
      );
      assert.equal(typeof tool.dataDir, "string");
      assert.equal(typeof tool.dataDirExists, "boolean");
    }
  });

  it("claude dataDir points to ~/.claude", () => {
    const result = detectClaudeCosight();
    const expected = path.join(os.homedir(), ".claude");
    assert.equal(result.claude.dataDir, expected);
  });

  it("cosight dataDir points to ~/.cosight", () => {
    const result = detectClaudeCosight();
    const expected = path.join(os.homedir(), ".cosight");
    assert.equal(result.cosight.dataDir, expected);
  });

  it("currentMode is 'claude' or 'cosight'", () => {
    const result = detectClaudeCosight();
    assert.ok(
      result.currentMode === "claude" || result.currentMode === "cosight",
      `unexpected currentMode: ${result.currentMode}`
    );
  });

  it("recommendedMode follows priority: claude > cosight", () => {
    const result = detectClaudeCosight();
    // 开源版 PRIORITY 是 [claude, cosight]：两者都装时推荐 claude
    if (result.claude.installed) {
      assert.equal(result.recommendedMode, "claude");
    } else if (result.cosight.installed) {
      assert.equal(result.recommendedMode, "cosight");
    } else {
      assert.equal(result.recommendedMode, null);
    }
  });

  it("anyInstalled is true when at least one tool is installed", () => {
    const result = detectClaudeCosight();
    const expected = result.claude.installed || result.cosight.installed;
    assert.equal(result.anyInstalled, expected);
  });

  it("detects currentMode as 'cosight' when COSIGHT_HOME contains .cosight", () => {
    const original = process.env.COSIGHT_HOME;
    try {
      process.env.COSIGHT_HOME = "/home/test/.cosight";
      const result = detectClaudeCosight();
      assert.equal(result.currentMode, "cosight");
    } finally {
      if (original !== undefined) {
        process.env.COSIGHT_HOME = original;
      } else {
        delete process.env.COSIGHT_HOME;
      }
    }
  });

  it("detects currentMode as 'claude' when COSIGHT_HOME does not contain .cosight", () => {
    const original = process.env.COSIGHT_HOME;
    try {
      process.env.COSIGHT_HOME = "/home/test/.claude";
      const result = detectClaudeCosight();
      assert.equal(result.currentMode, "claude");
    } finally {
      if (original !== undefined) {
        process.env.COSIGHT_HOME = original;
      } else {
        delete process.env.COSIGHT_HOME;
      }
    }
  });
});

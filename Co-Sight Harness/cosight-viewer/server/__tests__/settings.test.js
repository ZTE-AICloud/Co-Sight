// SPDX-License-Identifier: Apache-2.0
/**
 * @file Tests for the auto-cleanup settings endpoint and the settings store.
 *
 * 重点锁定：
 *  - 没有配置文件时「启用自动清理」默认为开；
 *  - 用户显式保存 `enabled: false` 之后以文件为准；
 *  - 存储格式是分段的 settings.json（便于后续扩展），未知段不被覆盖；
 *  - 配置（settings.json）与上次执行记录（state.json）分开存放。
 */

const { describe, it, before, after, beforeEach } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const express = require("express");

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "viewer-settings-"));
process.env.DASHBOARD_DATA_DIR = dir;

const settingsRouter = require("../routes/settings");

const SETTINGS_PATH = path.join(dir, "settings.json");
const STATE_PATH = path.join(dir, "state.json");

let server;
let base;

before(async () => {
  const app = express();
  app.use(express.json());
  app.use("/settings", settingsRouter);
  server = http.createServer(app);
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${server.address().port}/settings`;
});

after(() => {
  if (server) server.close();
  fs.rmSync(dir, { recursive: true, force: true });
});

beforeEach(() => {
  fs.rmSync(SETTINGS_PATH, { force: true });
  fs.rmSync(STATE_PATH, { force: true });
});

function readSettingsFile() {
  return JSON.parse(fs.readFileSync(SETTINGS_PATH, "utf-8"));
}

describe("auto-cleanup settings", () => {
  it("没有配置文件时默认启用", async () => {
    const response = await fetch(`${base}/auto-cleanup`);
    assert.equal(response.status, 200);

    const body = await response.json();
    assert.equal(body.enabled, true);
    assert.equal(body.abandon_hours, 24);
    assert.equal(body.purge_days, 90);
  });

  it("用户显式关闭后保持关闭", async () => {
    fs.writeFileSync(
      SETTINGS_PATH,
      JSON.stringify({
        version: 1,
        autoCleanup: { enabled: false, abandonHours: 12, purgeDays: 30 },
      }),
    );

    const response = await fetch(`${base}/auto-cleanup`);
    const body = await response.json();
    assert.equal(body.enabled, false);
    assert.equal(body.abandon_hours, 12);
    assert.equal(body.purge_days, 30);
  });

  it("保存后写入分段的 settings.json，并保留未知配置段", async () => {
    fs.writeFileSync(
      SETTINGS_PATH,
      JSON.stringify({ version: 1, futureFeature: { foo: "bar" } }),
    );

    const response = await fetch(`${base}/auto-cleanup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: false, abandon_hours: 48, purge_days: 7 }),
    });
    assert.equal(response.status, 200);

    const saved = readSettingsFile();
    assert.deepEqual(saved.futureFeature, { foo: "bar" });
    assert.equal(saved.autoCleanup.enabled, false);
    assert.equal(saved.autoCleanup.abandonHours, 48);
    assert.equal(saved.autoCleanup.purgeDays, 7);
  });

  it("上次清理记录放在 state.json，保存配置不会写回 settings.json", async () => {
    fs.writeFileSync(
      STATE_PATH,
      JSON.stringify({
        version: 1,
        autoCleanup: {
          lastRun: {
            time: "2026-11-07T01:00:00.000Z",
            type: "auto",
            purged_sessions: 3,
            purged_events: 120,
            purged_agents: 5,
            purged_runs: 0,
          },
        },
      }),
    );

    const getResponse = await fetch(`${base}/auto-cleanup`);
    const readBody = await getResponse.json();
    assert.equal(readBody.last_run.time, "2026-11-07T01:00:00.000Z");
    assert.equal(readBody.last_run.purged_sessions, 3);

    const postResponse = await fetch(`${base}/auto-cleanup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: true, abandon_hours: 24, purge_days: 90 }),
    });
    const savedBody = await postResponse.json();
    assert.equal(savedBody.last_run.purged_sessions, 3);

    const saved = readSettingsFile();
    assert.equal(saved.autoCleanup.lastRun, undefined);
  });
});

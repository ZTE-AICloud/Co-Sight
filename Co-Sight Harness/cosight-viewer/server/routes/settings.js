// SPDX-License-Identifier: Apache-2.0
/**
 * @file Express router for settings endpoints — auto-cleanup configuration.
 *
 * 配置存 `<viewerDataDir>/settings.json`（settings-store），上次执行记录存
 * `<viewerDataDir>/state.json`（state-store）。对外仍保持扁平字段，前端无需感知。
 */

const { Router } = require("express");

const router = Router();

const { readSettings, updateAutoCleanup } = require("../lib/settings-store");
const { readState } = require("../lib/state-store");

/** 把存储格式映射成对外 API 的扁平字段（last_run 来自运行状态）。 */
function toApiResponse(config, lastRun) {
  return {
    enabled: config.enabled,
    abandon_hours: config.abandonHours,
    purge_days: config.purgeDays,
    last_run: lastRun,
  };
}

/** 上次清理记录（没有执行过则为 null）。 */
function readLastRun() {
  return readState().autoCleanup.lastRun;
}

/**
 * GET /auto-cleanup
 * Read auto-cleanup configuration.
 * Returns defaults if config file doesn't exist.
 *
 * 默认启用：首次使用（没有配置文件）时，自动清理按 90 天保留策略运行。
 * 用户显式保存过 `enabled: false` 后，以文件里的值为准。
 */
router.get("/auto-cleanup", (req, res) => {
  try {
    const { autoCleanup } = readSettings();
    res.json({ ok: true, ...toApiResponse(autoCleanup, readLastRun()) });
  } catch (err) {
    console.error("[settings] Failed to read auto-cleanup config:", err.message);
    res.status(500).json({
      ok: false,
      error: "Failed to read configuration",
    });
  }
});

/**
 * POST /auto-cleanup
 * Save auto-cleanup configuration.
 * Body: { enabled: boolean, abandon_hours: number, purge_days: number }
 * last_run 属于运行状态，不在这里覆盖。
 */
router.post("/auto-cleanup", (req, res) => {
  try {
    const { enabled, abandon_hours, purge_days } = req.body;

    // Validate input
    if (typeof enabled !== "boolean") {
      return res.status(400).json({
        ok: false,
        error: "enabled must be a boolean",
      });
    }
    if (typeof abandon_hours !== "number" || abandon_hours <= 0) {
      return res.status(400).json({
        ok: false,
        error: "abandon_hours must be a positive number",
      });
    }
    if (typeof purge_days !== "number" || purge_days <= 0) {
      return res.status(400).json({
        ok: false,
        error: "purge_days must be a positive number",
      });
    }

    const saved = updateAutoCleanup({
      enabled,
      abandonHours: abandon_hours,
      purgeDays: purge_days,
    });

    res.json({ ok: true, ...toApiResponse(saved, readLastRun()) });
  } catch (err) {
    console.error("[settings] Failed to save auto-cleanup config:", err.message);
    res.status(500).json({
      ok: false,
      error: "Failed to save configuration",
    });
  }
});

module.exports = router;

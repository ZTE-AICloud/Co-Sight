// SPDX-License-Identifier: Apache-2.0
/**
 * @file HTTP routes for dashboard upstream-update detection. The dashboard never
 * restarts itself — users copy the printed command and run it in their terminal.
 */

const { Router } = require("express");
const { getUpdatesStatus } = require("../lib/update-check");

const router = Router();

router.get("/status", async (_req, res) => {
  try {
    const status = await getUpdatesStatus();
    res.json(status);
  } catch (err) {
    res.status(500).json({
      error: { code: "UPDATE_STATUS_FAILED", message: err.message || String(err) },
    });
  }
});

router.post("/check", async (_req, res) => {
  try {
    const status = await getUpdatesStatus();
    try {
      const { broadcast } = require("../websocket");
      broadcast("update_status", status);
    } catch {
      // WS not initialized (e.g. in isolated tests) — safe to ignore.
    }
    res.json(status);
  } catch (err) {
    res.status(500).json({
      error: { code: "UPDATE_CHECK_FAILED", message: err.message || String(err) },
    });
  }
});

module.exports = router;

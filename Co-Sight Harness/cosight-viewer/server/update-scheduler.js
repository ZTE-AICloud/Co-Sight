// SPDX-License-Identifier: Apache-2.0
/**
 * @file Periodic git upstream check and WebSocket broadcast when update availability changes.
 */

const { getUpdatesStatus } = require("./lib/update-check");

function isUpdateCheckDisabled() {
  const v = process.env.DASHBOARD_UPDATE_CHECK;
  return v === "0" || v === "false" || v === "off";
}

function intervalMs() {
  const n = Number.parseInt(process.env.DASHBOARD_UPDATE_CHECK_INTERVAL_MS || "", 10);
  if (Number.isFinite(n) && n >= 60_000) return n;
  return 5 * 60 * 1000;
}

function startUpdateScheduler({ broadcast }) {
  if (isUpdateCheckDisabled()) return { stop: () => {} };

  let lastFingerprint = "";
  let lastHadUpdate = false;
  let stopped = false;
  let initialTimer = null;
  let intervalTimer = null;

  async function tick() {
    if (stopped) return;
    try {
      const status = await getUpdatesStatus();
      // Fingerprint must change whenever anything user-visible changes,
      // including the *shape* of manual_command (e.g. user switches branch
      // or adds an upstream remote — same remote_sha / commits_behind, but
      // different command). Including manual_command here covers situation
      // transitions automatically.
      const fp = JSON.stringify({
        a: Boolean(status.update_available),
        r: status.remote_sha || null,
        b: status.commits_behind || 0,
        e: status.fetch_error || null,
        c: status.manual_command || null,
      });
      const changed = fp !== lastFingerprint;
      lastFingerprint = fp;
      if (changed) {
        broadcast("update_status", status);
      }
      const becameAvailable = status.update_available && !lastHadUpdate;
      lastHadUpdate = Boolean(status.update_available);
      if (becameAvailable) {
        const line = "━".repeat(52);
        console.log(`\n${line}`);
        console.log("  Co-Sight Viewer: upstream update available");
        console.log(`  ${status.message || ""}`);
        if (status.situation_note) {
          console.log(`  ${status.situation_note}`);
        }
        if (status.manual_command) {
          console.log(`  Run: ${status.manual_command}`);
          // Only suggest restart when the command actually rewrites the
          // working tree. fetch-only situations (feature_branch /
          // detached_head) don't need a restart.
          const updatesWorkingTree =
            status.situation === "tracking_canonical" ||
            status.situation === "fork_or_diverged_tracking";
          if (updatesWorkingTree) {
            console.log("  Then restart the dashboard the same way you started it.");
          }
        }
        console.log(`${line}\n`);
      }
    } catch {
      // Non-fatal — never block the server on update checks
    }
  }

  initialTimer = setTimeout(() => {
    tick();
  }, 8_000);
  if (typeof initialTimer.unref === "function") initialTimer.unref();

  intervalTimer = setInterval(tick, intervalMs());
  if (typeof intervalTimer.unref === "function") intervalTimer.unref();

  return {
    stop: () => {
      stopped = true;
      if (initialTimer) clearTimeout(initialTimer);
      if (intervalTimer) clearInterval(intervalTimer);
    },
  };
}

module.exports = { startUpdateScheduler };

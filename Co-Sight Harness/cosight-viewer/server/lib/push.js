// SPDX-License-Identifier: Apache-2.0
/**
 * @file Handles web push notifications using the `web-push` library, including generating/loading VAPID keys, sending notifications to all subscribed clients, and cleaning up invalid subscriptions. It provides a function to retrieve the public VAPID key for client registration and a function to broadcast notifications to all subscribers stored in the database.
 */

const webpush = require("web-push");
const path = require("path");
const fs = require("fs");

const { getViewerDataDir } = require("./claude-home");

// VAPID keys live in the viewer-owned data directory.
const KEYS_PATH = path.join(getViewerDataDir(), "vapid-keys.json");

function loadOrCreateVapidKeys() {
  if (fs.existsSync(KEYS_PATH)) {
    return JSON.parse(fs.readFileSync(KEYS_PATH, "utf8"));
  }
  const keys = webpush.generateVAPIDKeys();
  fs.mkdirSync(path.dirname(KEYS_PATH), { recursive: true });
  fs.writeFileSync(KEYS_PATH, JSON.stringify(keys, null, 2));
  return keys;
}

const vapidKeys = loadOrCreateVapidKeys();

webpush.setVapidDetails(
  "https://cosight-viewer.local",
  vapidKeys.publicKey,
  vapidKeys.privateKey
);

function getPublicKey() {
  return vapidKeys.publicKey;
}

/**
 * Try to show a native OS notification if running in an Electron environment.
 * Returns true when a notification was actually shown.
 *
 * @param {string} title
 * @param {string} body
 * @returns {boolean}
 */
function showNativeNotificationIfElectron(title, body) {
  if (!process.versions || !process.versions.electron) return false;
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { Notification: ElectronNotification } = require("electron");
    if (!ElectronNotification) return false;
    if (
      typeof ElectronNotification.isSupported === "function" &&
      !ElectronNotification.isSupported()
    ) {
      return false;
    }
    new ElectronNotification({ title, body, silent: false }).show();
    return true;
  } catch {
    return false;
  }
}

/**
 * Dispatch notifications via all available channels:
 *   - Native OS notification if running in Electron.
 *   - Web Push to all subscribed browser endpoints.
 *
 * Returns `{ native, pushed, failed }` so the caller can report delivery status.
 */
async function sendPushToAll(db, title, body) {
  const native = showNativeNotificationIfElectron(title, body);

  const subscriptions = db.prepare("SELECT * FROM push_subscriptions").all();
  if (subscriptions.length === 0) {
    return { native, pushed: 0, failed: 0 };
  }

  const payload = JSON.stringify({
    title,
    body,
    icon: "/favicon.ico",
    badge: "/favicon.ico",
    silent: false,
    sound: "default",
  });
  const results = await Promise.allSettled(
    subscriptions.map((sub) =>
      webpush.sendNotification(
        { endpoint: sub.endpoint, keys: { p256dh: sub.p256dh, auth: sub.auth } },
        payload
      )
    )
  );

  // Remove subscriptions that are gone (HTTP 410); count what landed.
  let pushed = 0;
  let failed = 0;
  for (let index = 0; index < results.length; index++) {
    const result = results[index];
    if (result.status === "fulfilled") {
      pushed++;
    } else {
      failed++;
      if (result.reason?.statusCode === 410) {
        db.prepare("DELETE FROM push_subscriptions WHERE endpoint = ?").run(
          subscriptions[index].endpoint
        );
      }
    }
  }

  return { native, pushed, failed };
}

module.exports = { getPublicKey, sendPushToAll };

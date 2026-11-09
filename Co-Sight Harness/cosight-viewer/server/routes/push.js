// SPDX-License-Identifier: Apache-2.0
/**
 * @file Express router for managing push notifications, providing endpoints to retrieve the VAPID public key, subscribe/unsubscribe to push notifications, and send push notifications to all subscribers. It interacts with the database to store subscription details and uses a push library to send notifications.
 */

const { Router } = require("express");
const { getPublicKey, sendPushToAll } = require("../lib/push");
const { db } = require("../db");

const router = Router();

router.get("/vapid-public-key", (_req, res) => {
  res.json({ publicKey: getPublicKey() });
});

router.post("/subscribe", (req, res) => {
  const { endpoint, keys } = req.body;
  if (!endpoint || !keys?.p256dh || !keys?.auth) {
    return res.status(400).json({ error: { message: "Missing required fields" } });
  }
  db.prepare(
    "INSERT OR REPLACE INTO push_subscriptions (endpoint, p256dh, auth) VALUES (?, ?, ?)"
  ).run(endpoint, keys.p256dh, keys.auth);
  res.json({ ok: true });
});

router.delete("/subscribe", (req, res) => {
  const { endpoint } = req.body;
  if (!endpoint) {
    return res.status(400).json({ error: { message: "Missing endpoint" } });
  }
  db.prepare("DELETE FROM push_subscriptions WHERE endpoint = ?").run(endpoint);
  res.json({ ok: true });
});

router.post("/send", async (req, res) => {
  const { title, body } = req.body;
  if (!title || !body) {
    return res.status(400).json({ error: { message: "Missing title or body" } });
  }
  try {
    // `result` tells the caller which surfaces actually fired:
    //   { native: true|false, pushed: <count>, failed: <count> }
    // so a silent "no subscribers, no Electron host" no-op stops looking like
    // success on the client side.
    const result = await sendPushToAll(db, title, body);
    res.json({ ok: true, ...result });
  } catch (err) {
    res.status(500).json({ error: { message: err.message } });
  }
});

module.exports = router;

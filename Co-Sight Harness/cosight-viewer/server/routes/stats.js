// SPDX-License-Identifier: Apache-2.0
/**
 * @file Express router for stats endpoints, providing aggregated statistics about agents, sessions, events, and WebSocket connections. It queries the database for various counts and statuses, and returns a comprehensive overview in JSON format for frontend display on the dashboard.
 */

const { Router } = require("express");
const { stmts } = require("../db");
const { getConnectionCount } = require("../websocket");

const router = Router();

router.get("/", (req, res) => {
  // Client sends tz_offset (minutes from getTimezoneOffset(), e.g. 420 for PDT)
  const rawOffset = parseInt(req.query.tz_offset, 10);
  const offsetMin = Number.isFinite(rawOffset) ? rawOffset : 0;
  const toLocal = `${-offsetMin} minutes`; // shift UTC → local
  const toUTC = `${offsetMin} minutes`; // shift local → UTC

  const overview = stmts.stats.get();
  const agentsByStatus = stmts.agentStatusCounts.all();
  const sessionsByStatus = stmts.sessionStatusCounts.all();

  const eventsToday = stmts.countEventsToday.get(toLocal, toUTC);

  res.json({
    ...overview,
    events_today: eventsToday?.count ?? 0,
    ws_connections: getConnectionCount(),
    agents_by_status: Object.fromEntries(agentsByStatus.map((r) => [r.status, r.count])),
    sessions_by_status: Object.fromEntries(sessionsByStatus.map((r) => [r.status, r.count])),
  });
});

module.exports = router;

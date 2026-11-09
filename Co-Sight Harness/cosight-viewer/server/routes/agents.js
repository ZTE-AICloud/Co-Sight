// SPDX-License-Identifier: Apache-2.0
/**
 * @file Express router for managing agents, providing endpoints to list, retrieve, create, and update agents. It interacts with the database using prepared statements and broadcasts changes to connected WebSocket clients for real-time updates.
 */

const { Router } = require("express");
const { stmts } = require("../db");
const { broadcast } = require("../websocket");

const router = Router();

router.get("/", (req, res) => {
  const rawLimit = parseInt(req.query.limit);
  const limit = rawLimit > 0 ? rawLimit : 10000;
  const offset = parseInt(req.query.offset) || 0;
  const status = req.query.status;
  const session_id = req.query.session_id;

  let rows;
  if (session_id) {
    rows = stmts.listAgentsBySession.all(session_id);
  } else if (status) {
    rows = stmts.listAgentsByStatus.all(status, limit, offset);
  } else {
    rows = stmts.listAgents.all(limit, offset);
  }

  res.json({ agents: rows, limit, offset });
});

router.get("/:id", (req, res) => {
  const agent = stmts.getAgent.get(req.params.id);
  if (!agent) {
    return res.status(404).json({ error: { code: "NOT_FOUND", message: "Agent not found" } });
  }
  res.json({ agent });
});

router.post("/", (req, res) => {
  const { id, session_id, name, type, subagent_type, status, task, parent_agent_id, metadata } =
    req.body;
  if (!id || !session_id || !name) {
    return res.status(400).json({
      error: { code: "INVALID_INPUT", message: "id, session_id, and name are required" },
    });
  }

  const existing = stmts.getAgent.get(id);
  if (existing) {
    return res.json({ agent: existing, created: false });
  }

  stmts.insertAgent.run(
    id,
    session_id,
    name,
    type || "main",
    subagent_type || null,
    status || "waiting",
    task || null,
    parent_agent_id || null,
    metadata ? JSON.stringify(metadata) : null
  );

  const agent = stmts.getAgent.get(id);
  broadcast("agent_created", agent);
  res.status(201).json({ agent, created: true });
});

router.patch("/:id", (req, res) => {
  const { name, status, task, current_tool, ended_at, metadata } = req.body;
  const existing = stmts.getAgent.get(req.params.id);
  if (!existing) {
    return res.status(404).json({ error: { code: "NOT_FOUND", message: "Agent not found" } });
  }

  stmts.updateAgent.run(
    name || null,
    status || null,
    task || null,
    current_tool !== undefined ? current_tool : existing.current_tool,
    ended_at || null,
    metadata ? JSON.stringify(metadata) : null,
    req.params.id
  );

  const agent = stmts.getAgent.get(req.params.id);
  broadcast("agent_updated", agent);
  res.json({ agent });
});

module.exports = router;

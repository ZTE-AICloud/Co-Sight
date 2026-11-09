// SPDX-License-Identifier: Apache-2.0
/**
 * @file Express router for session endpoints, allowing creation, retrieval, and updating of sessions with optional pagination and filtering by status. It also computes costs for sessions based on token usage and pricing rules, and broadcasts session changes to connected WebSocket clients for real-time updates.
 */

const { Router } = require("express");
const fs = require("fs");
const os = require("os");
const path = require("path");
const readline = require("readline");
const { stmts, db } = require("../db");
const { broadcast } = require("../websocket");
const { calculateCost } = require("./pricing");
const fileWatcher = require("../lib/file-watcher");
const { DIR_NAMES } = require("../lib/mode-config");
const { createChildLogger } = require("../lib/unified-logger");
const sessionsLog = createChildLogger("sessions");
const {
  getClaudeHome,
  getProjectsDirs,
  getImportedSessionsDir,
  getTaskManagementRoot,
  getTranscriptPath,
  getSubagentTranscriptPath,
  getSnapshotTranscriptPath,
  getSnapshotSubagentTranscriptPath,
  getTranscriptSnapshotDir,
  findTranscriptPath,
  findSubagentTranscriptPath,
  encodeCwd,
} = require("../lib/claude-home");
const { importSessionFromZip } = require("../lib/session-import");
const { transcriptCache } = require("./hooks");
const http = require("http");

// ───── [PERF-DIAG] handler 计时(可选) ─────
let __perf;
try {
  __perf = require("../lib/perf-trace");
} catch {}
const __hStart = () => (__perf ? __perf.nowNs() : 0n);
const __hEnd = (req, t0, label) => {
  if (!__perf) return;
  const ms = __perf.msBetween(t0, __perf.nowNs());
  req.__perfHandlerMs = ms;
  if (ms > 500) __perf.writeDiag(`[SESSIONS_HANDLER] ${label} ${ms.toFixed(1)}ms`);
};
// ───── [PERF-DIAG] end ─────

const router = Router();

// No mode set: return empty data (service not yet activated)
/**
 * SQL condition: session cwd equals the workspace dir or is nested under it.
 * Accepts both separators — Windows session cwds use "\" while POSIX uses "/",
 * and a "/"-only prefix silently hides every subdirectory session on Windows.
 * Takes the directory three times (exact match, "/"-prefix, "\"-prefix).
 */
const CWD_WITHIN_CONDITION =
  "(s.cwd = ? OR s.cwd LIKE ? || '/%' OR s.cwd LIKE ? || '\\%')";

/**
 * Read only the first non-empty line from a JSONL file using streaming.
 * Avoids loading the entire file into memory.
 */
/**
 * Read only the first line of a JSONL file by reading a small buffer.
 * Much faster than readline streaming — only reads first 2KB instead of
 * creating a full ReadStream that may buffer the entire file.
 */
async function readFirstLine(filePath) {
  let fh;
  try {
    fh = await fs.promises.open(filePath, "r");
    const buf = Buffer.alloc(2048);
    const { bytesRead } = await fh.read(buf, 0, 2048, 0);
    const text = buf.toString("utf8", 0, bytesRead);
    const nlIdx = text.indexOf("\n");
    const line = nlIdx >= 0 ? text.slice(0, nlIdx) : text;
    return line.trim() || null;
  } catch {
    return null;
  } finally {
    if (fh)
      try {
        await fh.close();
      } catch {}
  }
}

router.get("/", (req, res) => {
  const limit = Math.min(parseInt(req.query.limit) || 50, 10000);
  const offset = parseInt(req.query.offset) || 0;
  const status = req.query.status;
  const q = typeof req.query.q === "string" ? req.query.q.trim() : "";
  const cwd = req.query.cwd;
  const cwds = req.query.cwds; // comma-separated list of directories
  const sortBy = req.query.sort_by || "time"; // "time", "duration", "price"
  const sortDesc = req.query.sort_desc !== "false";

  let where = [];
  let params = [];

  if (q) {
    const like = `%${q}%`;
    where.push("(s.id LIKE ? OR s.name LIKE ? OR s.cwd LIKE ?)");
    params.push(like, like, like);
  }
  if (status) {
    where.push("s.status = ?");
    params.push(status);
  }
  if (cwd) {
    where.push(CWD_WITHIN_CONDITION);
    params.push(cwd, cwd, cwd);
  } else if (cwds) {
    // Multi-directory filter: cwds=/path1,/path2,/path3
    // Prefix match: workspace dir is contained in session cwd
    const cwdList = cwds.split(",").filter(Boolean);
    if (cwdList.length > 0) {
      const conditions = cwdList.map(() => CWD_WITHIN_CONDITION);
      where.push(`(${conditions.join(" OR ")})`);
      for (const d of cwdList) {
        params.push(d, d, d);
      }
    }
  }

  const whereSql = where.length > 0 ? `WHERE ${where.join(" AND ")}` : "";
  const total = db.prepare(`SELECT COUNT(*) as c FROM sessions s ${whereSql}`).get(...params).c;

  let rows = [];

  if (sortBy === "price") {
    const allRows = db
      .prepare(
        // Exclude compaction agents from the count — they're metadata events, not real agents.
        `SELECT s.*, COUNT(CASE WHEN COALESCE(a.subagent_type, '') != 'compaction' THEN a.id END) as agent_count, s.updated_at as last_activity
         FROM sessions s LEFT JOIN agents a ON a.session_id = s.id
         ${whereSql}
         GROUP BY s.id`
      )
      .all(...params);

    if (allRows.length > 0) {
      const rules = stmts.listPricing.all();

      for (let i = 0; i < allRows.length; i += 900) {
        const chunk = allRows.slice(i, i + 900);
        const ids = chunk.map((r) => r.id);
        const placeholders = ids.map(() => "?").join(",");
        const chunkTokens = db
          .prepare(
            `SELECT session_id, model,
              input_tokens + baseline_input as input_tokens,
              output_tokens + baseline_output as output_tokens,
              cache_read_tokens + baseline_cache_read as cache_read_tokens,
              cache_write_tokens + baseline_cache_write as cache_write_tokens
            FROM token_usage WHERE session_id IN (${placeholders})`
          )
          .all(...ids);

        const tokensBySession = {};
        for (const t of chunkTokens) {
          if (!tokensBySession[t.session_id]) tokensBySession[t.session_id] = [];
          tokensBySession[t.session_id].push(t);
        }

        for (const row of chunk) {
          const sessionTokens = tokensBySession[row.id];
          row.cost = sessionTokens ? calculateCost(sessionTokens, rules).total_cost : 0;
        }
      }

      allRows.sort((a, b) => {
        return sortDesc ? b.cost - a.cost : a.cost - b.cost;
      });
      rows = allRows.slice(offset, offset + limit);
    }
  } else {
    let orderSql = "s.updated_at DESC";
    if (sortBy === "time") {
      orderSql = `s.updated_at ${sortDesc ? "DESC" : "ASC"}`;
    } else if (sortBy === "duration") {
      orderSql = `(julianday(COALESCE(s.ended_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))) - julianday(s.started_at)) ${sortDesc ? "DESC" : "ASC"}`;
    }

    rows = db
      .prepare(
        // Exclude compaction agents from the count — they're metadata events, not real agents.
        `SELECT s.*, COUNT(CASE WHEN COALESCE(a.subagent_type, '') != 'compaction' THEN a.id END) as agent_count, s.updated_at as last_activity
         FROM sessions s LEFT JOIN agents a ON a.session_id = s.id
         ${whereSql}
         GROUP BY s.id ORDER BY ${orderSql} LIMIT ? OFFSET ?`
      )
      .all(...params, limit, offset);

    if (rows.length > 0) {
      const ids = rows.map((r) => r.id);
      const placeholders = ids.map(() => "?").join(",");
      const allTokens = db
        .prepare(
          `SELECT session_id, model,
            input_tokens + baseline_input as input_tokens,
            output_tokens + baseline_output as output_tokens,
            cache_read_tokens + baseline_cache_read as cache_read_tokens,
            cache_write_tokens + baseline_cache_write as cache_write_tokens
          FROM token_usage WHERE session_id IN (${placeholders})`
        )
        .all(...ids);

      const rules = stmts.listPricing.all();
      const tokensBySession = {};
      for (const t of allTokens) {
        if (!tokensBySession[t.session_id]) tokensBySession[t.session_id] = [];
        tokensBySession[t.session_id].push(t);
      }

      for (const row of rows) {
        const sessionTokens = tokensBySession[row.id];
        row.cost = sessionTokens ? calculateCost(sessionTokens, rules).total_cost : 0;
      }
    }
  }

  res.json({ sessions: rows, limit, offset, total });
});

// ─────────────────────────────────────────────────────────────────────────────
// Framework workspace API integration
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Fetch workspaces from smart-factory directories/list API
 * GET /api/smart-factory/v1/workspaces/directories/list
 * Returns: array of directory paths (extracted from workspace items)
 *
 * smart-factory 自身的接口无鉴权（无 auth 中间件），直接请求即可。
 * 注意区分：框架的模块面接口（/api/framework/v1/*）才需要 .module-token，
 * 那是 smart-factory 作为调用方去请求框架时用的，与 cosight-viewer 无关。
 */
async function fetchWorkspaceDirectories() {
  const smartFactoryBase =
    process.env.SMART_FACTORY_BASE_URL || "http://127.0.0.1:4100";
  const apiUrl = `${smartFactoryBase}/api/smart-factory/v1/workspaces/directories/list`;

  try {
    const response = await fetch(apiUrl);

    if (!response.ok) {
      sessionsLog.warn(`[facets] smart-factory API returned ${response.status}: ${response.statusText}`);
      return [];
    }

    const body = await response.json();
    // Tolerate both `{ items }` and `{ success, data: { items } }` shapes.
    const data = body && body.data ? body.data : body;
    if (!data || !Array.isArray(data.items)) {
      sessionsLog.warn("[facets] smart-factory API response format unexpected");
      return [];
    }

    // Extract directory paths, filter out null/undefined
    const directories = data.items
      .map((item) => item.directory)
      .filter((dir) => dir != null && dir !== "");

    return directories;
  } catch (err) {
    sessionsLog.warn(`[facets] Failed to fetch workspaces from smart-factory: ${err.message}`);
    return [];
  }
}

router.get("/facets", async (req, res) => {
  try {
    const cwds = await fetchWorkspaceDirectories();
    res.json({ cwds });
  } catch (err) {
    sessionsLog.error(`[facets] Error: ${err.message}`);
    // 降级返回空列表
    res.json({ cwds: [] });
  }
});

// ─────────────────────────────────────────────────────────────────────────────

router.get("/:id", (req, res) => {
  const __t0 = __hStart();
  let session = stmts.getSession.get(req.params.id);

  // Fallback: If session not in SQLite, try to find it via task JSON files
  if (!session) {
    const taskInfo = findSessionFromTasks(req.params.id);
    if (taskInfo && taskInfo.jsonlPath && fs.existsSync(taskInfo.jsonlPath)) {
      session = {
        id: req.params.id,
        name: null,
        status: "active",
        cwd: taskInfo.cwd,
        model: null,
        metadata: null,
        started_at: null,
        updated_at: null,
        ended_at: null,
      };
    }
  }

  if (!session) {
    __hEnd(req, __t0, `GET /:id NOT_FOUND`);
    return res.status(404).json({ error: { code: "NOT_FOUND", message: "Session not found" } });
  }
  // Use UI-facing agent list that excludes compaction entries.
  // Compaction agents are metadata events, not real subagents with transcript
  // files — including them inflates the count and causes "transcript not found"
  // errors when users click them. Internal endpoints (transcripts, tasks) still
  // use listAgentsBySession to get the full list.
  const agents = stmts.listAgentsBySessionForUI.all(req.params.id);

  // ── Events loading: default OFF to avoid 1-2s stall on sessions with 100k+ events.
  //    Callers that actually need events should pass ?include_events=true
  //    (or use the paginated ?limit=N endpoint). ChatPanel and SessionDetail both
  //    load events via api.events.list() pagination, so they never need this.
  const includeEvents = req.query.include_events === "true";
  let events = null;
  let total = 0;
  let offset = 0;

  if (includeEvents) {
    const limit = parseInt(req.query.limit);
    offset = parseInt(req.query.offset) || 0;
    if (Number.isFinite(limit) && limit > 0) {
      const pagedStmt = db.prepare(
        "SELECT * FROM events WHERE session_id = ? ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
      );
      events = pagedStmt.all(req.params.id, limit, offset);
      const countRow = db
        .prepare("SELECT COUNT(*) AS cnt FROM events WHERE session_id = ?")
        .get(req.params.id);
      total = countRow.cnt;
    } else {
      events = stmts.listEventsBySession.all(req.params.id);
      total = events?.length || 0;
    }
  }

  __hEnd(
    req,
    __t0,
    `GET /:id events=${includeEvents ? events?.length || 0 : "skipped"}/${total} agents=${agents?.length || 0}${includeEvents ? "" : " (include_events=false)"}`
  );
  res.json({
    session,
    agents,
    events,
    total,
    has_more:
      includeEvents &&
      Number.isFinite(parseInt(req.query.limit)) &&
      offset + (events?.length || 0) < total,
  });
});

/**
 * GET /:id/stats — Aggregated counts for the SessionOverview panel.
 *
 * Returns at-a-glance metrics used by the Agents tab on the Session detail page.
 * All aggregation runs in SQL so we don't ship 14k+ event rows to the client.
 */
router.get("/:id/stats", (req, res) => {
  const sessionId = req.params.id;
  const session = stmts.getSession.get(sessionId);
  if (!session) {
    return res.status(404).json({ error: { code: "NOT_FOUND", message: "Session not found" } });
  }

  const totalEvents = stmts.sessionEventCount.get(sessionId)?.count ?? 0;
  const eventsByType = stmts.sessionEventTypeCounts.all(sessionId);
  const tools = stmts.sessionToolUsageCounts.all(sessionId);
  const errors = stmts.sessionErrorCount.get(sessionId)?.count ?? 0;
  const timeRange = stmts.sessionEventTimeRange.get(sessionId) || {};
  const subagentTypes = stmts.sessionAgentTypeCounts.all(sessionId);
  const agentStatusRows = stmts.sessionAgentStatusCounts.all(sessionId);

  // Read tokens from DB (persisted by per-event extract on every hook event).
  // sessionTokenTotals folds baseline columns so effective_total = current + baseline.
  const tokens = stmts.sessionTokenTotals.get(sessionId) || {
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    cache_write_tokens: 0,
  };

  // Compaction count from agents table (persisted by per-event extract).
  const compactionRow = subagentTypes.find((r) => r.subagent_type === "compaction");
  const compaction_count = compactionRow?.count ?? 0;

  // Aggregate agent counts by category. Compaction is an inline metadata event,
  // not a real subagent — exclude it from total/main/subagent so the numbers
  // match the Agent panel (listAgentsBySessionForUI). It is still surfaced
  // separately via `compaction_count` (from JSONL) and `agents.compaction`.
  const agentCounts = {
    total: 0,
    main: 0,
    subagent: 0,
    compaction: 0,
    by_status: {},
  };
  for (const row of agentStatusRows) {
    agentCounts.by_status[row.status] = row.count;
  }
  // Compactions: already computed above from subagentTypes
  agentCounts.compaction = compactionRow?.count ?? 0;
  // Main vs sub: count by type in SQL (avoids loading all agents). Excludes
  // compaction so totals stay consistent with the Agent panel.
  const typeCounts = db
    .prepare(
      `SELECT type, COUNT(*) as count FROM agents WHERE session_id = ? AND COALESCE(subagent_type, '') != 'compaction' GROUP BY type`
    )
    .all(sessionId);
  for (const row of typeCounts) {
    if (row.type === "main") agentCounts.main = row.count;
    else if (row.type === "subagent") agentCounts.subagent = row.count;
    agentCounts.total += row.count;
  }

  res.json({
    session_id: sessionId,
    total_events: totalEvents,
    events_by_type: eventsByType,
    tools_used: tools,
    error_count: errors,
    first_event_at: timeRange.first_at ?? null,
    last_event_at: timeRange.last_at ?? null,
    agents: agentCounts,
    subagent_types: subagentTypes.filter((r) => r.subagent_type !== "compaction"),
    tokens,
    compaction_count,
  });
});

router.post("/", (req, res) => {
  const { id, name, cwd, model, metadata } = req.body;
  if (!id) {
    return res.status(400).json({ error: { code: "INVALID_INPUT", message: "id is required" } });
  }

  const existing = stmts.getSession.get(id);
  if (existing) {
    return res.json({ session: existing, created: false });
  }

  stmts.insertSession.run(
    id,
    name || null,
    "active",
    cwd || null,
    model || null,
    metadata ? JSON.stringify(metadata) : null
  );
  const session = stmts.getSession.get(id);
  broadcast("session_created", session);
  res.status(201).json({ session, created: true });
});

router.patch("/:id", (req, res) => {
  const { name, status, ended_at, metadata } = req.body;
  const existing = stmts.getSession.get(req.params.id);
  if (!existing) {
    return res.status(404).json({ error: { code: "NOT_FOUND", message: "Session not found" } });
  }

  stmts.updateSession.run(
    name || null,
    status || null,
    ended_at || null,
    metadata ? JSON.stringify(metadata) : null,
    req.params.id
  );

  const session = stmts.getSession.get(req.params.id);
  broadcast("session_updated", session);
  res.json({ session });
});

// GET /:id/transcripts — List available transcript files for a session (main + sub-agents)
router.get("/:id/transcripts", async (req, res) => {
  const __t0 = __hStart();
  let session = stmts.getSession.get(req.params.id);

  // Fallback: If session not in SQLite, try to find it via task JSON files
  let fallbackJsonlPath = null;
  if (!session) {
    const taskInfo = findSessionFromTasks(req.params.id);
    if (taskInfo && taskInfo.jsonlPath && fs.existsSync(taskInfo.jsonlPath)) {
      session = { id: req.params.id, cwd: taskInfo.cwd };
      fallbackJsonlPath = taskInfo.jsonlPath;
    }
  }

  if (!session) {
    __hEnd(req, __t0, `GET /:id/transcripts NOT_FOUND`);
    return res.status(404).json({ error: { code: "NOT_FOUND", message: "Session not found" } });
  }

  // ── [PERF-DIAG] transcripts 分阶段耗时埋点 ──
  // 仅当总耗时超过阈值时才输出完整分阶段耗时；正常请求静默，
  // 避免每 15s 轮询 + agent 事件触发导致的日志刷屏。
  const __TRANSCRIPTS_SLOW_MS = 200;
  const __steps = [];
  const __mark = (label) => {
    try {
      __steps.push(`${label}=${(__perf?.msBetween(__t0, __perf.nowNs()) ?? 0).toFixed(1)}ms`);
    } catch {}
  };
  __mark("session_query");

  const result = [];

  // Query database agent list for db_agent_id association
  const dbAgents = stmts.listAgentsBySession.all(req.params.id) || [];
  __mark("db_agents");

  // Main session transcript. Prefer the path the hook recorded on the session row:
  // it is the only value that survives a mis-resolved Claude home (e.g. the
  // server resolving ~/.claude/.claude while the CLI writes to ~/.claude).
  // Recomputing from cwd/session only works when both processes agree on the home.
  // Order: recorded path → cwd-derived → full scan → durable import snapshot.
  // Every candidate is existence-checked, so a stale recorded path falls through.
  const mainCandidates = [
    session.transcript_path,
    getTranscriptPath(req.params.id, session.cwd),
    findTranscriptPath(req.params.id),
    fallbackJsonlPath,
    getSnapshotTranscriptPath(req.params.id),
  ];
  __mark("main_path_find");
  let resolvedMainPath = null;
  for (const candidate of mainCandidates) {
    if (!candidate) continue;
    try {
      await fs.promises.access(candidate);
      resolvedMainPath = candidate;
      break;
    } catch {}
  }
  __mark("main_path_access");
  if (resolvedMainPath) {
    // Main agent database ID format: <sessionId>-main
    const mainDbAgent = dbAgents.find((a) => a.type === "main");
    result.push({
      id: "main",
      name: "Main Agent",
      type: "main",
      has_transcript: true,
      db_agent_id: mainDbAgent ? mainDbAgent.id : null,
    });
  }

  // Sub-agent transcript files
  const encoded = session.cwd ? session.cwd.replace(/[^a-zA-Z0-9]/g, "-") : null;
  const subagentDirs = [];

  // Check both native and imported sessions directories
  const searchDirs = [...getProjectsDirs(), getImportedSessionsDir()];

  // Direct path (check both directories)
  if (encoded) {
    for (const baseDir of searchDirs) {
      const directDir = path.join(baseDir, encoded, req.params.id, "subagents");
      try {
        await fs.promises.access(directDir);
        subagentDirs.push(directDir);
      } catch {}
    }
  }

  // Also derive the subagent directory from wherever the main transcript
  // actually is. When the recorded transcript_path comes from a different home
  // than getProjectsDir(), the loops above scan the wrong tree and would miss
  // every subagent even though the main transcript was found.
  if (resolvedMainPath && resolvedMainPath.endsWith(".jsonl")) {
    const sibling = path.join(
      path.dirname(resolvedMainPath),
      req.params.id,
      "subagents"
    );
    if (!subagentDirs.includes(sibling)) {
      try {
        await fs.promises.access(sibling);
        subagentDirs.push(sibling);
      } catch {}
    }
  }

  // Fallback: scan all project directories when direct path doesn't exist
  if (subagentDirs.length === 0) {
    for (const baseDir of searchDirs) {
      try {
        await fs.promises.access(baseDir);
        const entries = await fs.promises.readdir(baseDir, { withFileTypes: true });
        // ── Parallel access check: run all candidate checks concurrently
        const dirChecks = entries
          .filter((d) => d.isDirectory())
          .map((d) => {
            const candidate = path.join(baseDir, d.name, req.params.id, "subagents");
            return fs.promises
              .access(candidate)
              .then(() => candidate)
              .catch(() => null);
          });
        const results = await Promise.all(dirChecks);
        for (const r of results) {
          if (r) subagentDirs.push(r);
        }
      } catch {
        /* ignore */
      }
    }
  }

  for (const dir of subagentDirs) {
    try {
      const files = await fs.promises.readdir(dir);
      // ── Parallel file reading: run all meta.json + first-line reads concurrently
      //    instead of serially (was ~400ms × N files, now ~400ms total)
      const jsonlFiles = files.filter((f) => f.endsWith(".jsonl"));
      const fileReads = jsonlFiles.map(async (file) => {
        // File name format: agent-<shortId>.jsonl
        const shortId = file.replace(/^agent-/, "").replace(/\.jsonl$/, "");
        const metaPath = path.join(dir, file.replace(".jsonl", ".meta.json"));
        const jsonlPath = path.join(dir, file);

        // ── Truly parallel: start meta.json read and first-line read at the same time
        const [metaRaw, firstLine] = await Promise.all([
          fs.promises.readFile(metaPath, "utf8").catch(() => null),
          readFirstLine(jsonlPath),
        ]);

        let meta = null;
        try {
          if (metaRaw) meta = JSON.parse(metaRaw);
        } catch {}

        let transcriptTimestamp = null;
        try {
          if (firstLine) transcriptTimestamp = JSON.parse(firstLine).timestamp || null;
        } catch {}

        const isCompact = shortId.startsWith("acompact-");
        return {
          id: shortId,
          name: isCompact ? "Context Compaction" : meta?.description || meta?.agentType || shortId,
          type: isCompact ? "compaction" : "subagent",
          subagent_type: meta?.agentType || null,
          has_transcript: true,
          db_agent_id: null,
          _timestamp: transcriptTimestamp,
        };
      });

      const parsed = await Promise.all(fileReads);
      for (const item of parsed) result.push(item);
      __mark("subagent_file_reads");
    } catch {
      /* ignore */
    }
  }

  __mark("before_matching");

  // Match database agents to transcripts using best-effort strategies
  // Strategy: sort both sides by time within each type, then match by index order.
  // This works because agents and transcripts are created in chronological order.

  // Step 1: Sort all non-main transcripts by timestamp
  for (const t of result) {
    if (t.type === "main") continue;
    // Store parseable timestamp for sorting
    t._sortTime = t._timestamp ? new Date(t._timestamp).getTime() : Infinity;
  }

  // Step 2: Sort DB agents by started_at within each subagent_type
  const agentsByType = {};
  for (const a of dbAgents) {
    const key = a.subagent_type || a.type;
    if (!agentsByType[key]) agentsByType[key] = [];
    agentsByType[key].push(a);
  }
  for (const key of Object.keys(agentsByType)) {
    agentsByType[key].sort((a, b) => (a.started_at || "").localeCompare(b.started_at || ""));
  }

  // Step 3: Sort transcripts by type+time, then match by index within each type group
  // Group transcripts by their effective type key
  const transcriptsByType = {};
  for (const t of result) {
    if (t.type === "main") continue;
    // Compaction transcripts have subagent_type=null, use type as key
    const key = t.subagent_type || t.type;
    if (!transcriptsByType[key]) transcriptsByType[key] = [];
    transcriptsByType[key].push(t);
  }
  // Sort each group by timestamp
  for (const key of Object.keys(transcriptsByType)) {
    transcriptsByType[key].sort((a, b) => (a._sortTime || Infinity) - (b._sortTime || Infinity));
  }

  // Step 4: Match by index within each type group
  // First try db_agent_id exact match, then fall back to positional match
  for (const key of Object.keys(transcriptsByType)) {
    const tGroup = transcriptsByType[key];
    const aGroup = agentsByType[key] || [];
    const usedAgentIds = new Set();

    for (let i = 0; i < tGroup.length; i++) {
      const t = tGroup[i];

      // Try exact db_agent_id match first (for non-compact sub-agents with meta.json data)
      if (t.db_agent_id) {
        usedAgentIds.add(t.db_agent_id);
        continue;
      }

      // Positional match: i-th transcript → i-th agent in the same type group
      if (i < aGroup.length && !usedAgentIds.has(aGroup[i].id)) {
        t.db_agent_id = aGroup[i].id;
        usedAgentIds.add(aGroup[i].id);
      }
      // If no agent at this position, db_agent_id stays null — client will show "info missing"
    }
  }

  // Clean up internal fields before sending response
  for (const t of result) {
    delete t._timestamp;
    delete t._sortTime;
  }

  // Sort transcripts: main first, then by time ascending (consistent with agents list order)
  result.sort((a, b) => {
    if (a.type === "main") return -1;
    if (b.type === "main") return 1;
    const aAgent = dbAgents.find((ag) => ag.id === a.db_agent_id);
    const bAgent = dbAgents.find((ag) => ag.id === b.db_agent_id);
    const aTime = aAgent?.started_at ? new Date(aAgent.started_at).getTime() : 0;
    const bTime = bAgent?.started_at ? new Date(bAgent.started_at).getTime() : 0;
    if (aTime && bTime) return aTime - bTime;
    if (aTime) return -1;
    if (bTime) return 1;
    return (a.name || "").localeCompare(b.name || "");
  });

  __mark("before_respond");
  // 慢请求才输出完整分阶段耗时；正常请求静默
  const __totalMs = __perf ? __perf.msBetween(__t0, __perf.nowNs()) : 0;
  if (__totalMs >= __TRANSCRIPTS_SLOW_MS) {
    try {
      __perf?.writeDiag(
        `[TRANSCRIPTS_TIMING] total=${__totalMs.toFixed(1)}ms ${__steps.join(" ")}`
      );
    } catch {}
  }
  __hEnd(req, __t0, `GET /:id/transcripts result=${result.length}`);
  res.json({ transcripts: result });
});

// GET /:id/transcript — Read session JSONL transcript, return structured message list
// Query params:
//   agent_id: file-level short ID ("main" or "ad18a79192af10ed1", "acompact-xxx")
//   limit: max messages to return (default 50, max 200)
//   after: JSONL line number, only return messages after this line (incremental mode)
//   before: JSONL line number, only return messages before this line (history mode)
//   offset: legacy pagination offset (compatible, mutually exclusive with after/before)
/**
 * Helper: Find session info from task JSON files when session is not in SQLite.
 * Uses getClaudeHome() for the primary search (respects MODE), falls back to
 * searching the other directory for compatibility with mixed setups.
 * Returns { jsonlPath, cwd } or null.
 */
function findSessionFromTasks(sessionId) {
  const { homedir } = require("node:os");
  const home = homedir();

  // Primary: use getClaudeHome() which respects MODE (COSIGHT_HOME/CLAUDE_HOME)
  // Fallback: search the other directory too for compatibility
  const claudeHome = getClaudeHome();
  const otherDirName = claudeHome.includes(DIR_NAMES.cosight)
    ? DIR_NAMES.claude
    : DIR_NAMES.cosight;
  const otherHome = path.join(home, otherDirName);

  // 搜索路径优先级:
  // 1. DASHBOARD_DATA_DIR (新数据目录:~/.cosight-harness/cosight-viewer)
  // 2. TASK_MANAGEMENT_ROOT (环境变量覆盖)
  // 3. 旧路径 (~/.claude/task-management, ~/.cosight/task-management)
  const newDashboardDir = path.join(os.homedir(), ".cosight-harness", "cosight-viewer");
  const taskRoots = [
    process.env.DASHBOARD_DATA_DIR || newDashboardDir,
    path.join(claudeHome, "task-management"),
    path.join(otherHome, "task-management"),
  ];

  if (process.env.TASK_MANAGEMENT_ROOT) {
    const envRoot = process.env.TASK_MANAGEMENT_ROOT.replace(/^~/, home);
    taskRoots.unshift(envRoot); // prioritize env var
  }

  for (const taskRoot of taskRoots) {
    const projectsDir = path.join(taskRoot, "projects");
    if (!fs.existsSync(projectsDir)) continue;

    try {
      const projectDirs = fs.readdirSync(projectsDir, { withFileTypes: true });
      for (const dir of projectDirs) {
        if (!dir.isDirectory()) continue;
        const dirPath = path.join(projectsDir, dir.name);
        try {
          const files = fs.readdirSync(dirPath);
          for (const file of files) {
            if (
              file.startsWith(`${sessionId}_`) &&
              file.endsWith(".json") &&
              !file.endsWith("-plan.json")
            ) {
              // Found a task with this sessionId
              try {
                const taskRaw = fs.readFileSync(path.join(dirPath, file), "utf-8");
                const task = JSON.parse(taskRaw);
                const cwd = task.projectDir || null;

                // Find JSONL: try getClaudeHome() first, then the other directory
                let jsonlPath = findTranscriptPath(sessionId);
                if (!jsonlPath) {
                  // Fallback: search the other home's projects directory
                  const otherProjects = path.join(otherHome, "projects");
                  if (fs.existsSync(otherProjects)) {
                    try {
                      const subdirs = fs.readdirSync(otherProjects, { withFileTypes: true });
                      for (const d of subdirs) {
                        if (!d.isDirectory()) continue;
                        const candidate = path.join(otherProjects, d.name, `${sessionId}.jsonl`);
                        if (fs.existsSync(candidate)) {
                          jsonlPath = candidate;
                          break;
                        }
                      }
                    } catch {}
                  }
                }

                return { jsonlPath, cwd };
              } catch {
                return { jsonlPath: null, cwd: null };
              }
            }
          }
        } catch {
          // ignore permission errors
        }
      }
    } catch {
      // ignore
    }
  }
  return null;
}

router.get("/:id/transcript", async (req, res) => {
  const __t0 = __hStart();
  let session = stmts.getSession.get(req.params.id);

  // Fallback: If session not in SQLite, try to find it via task JSON files
  let fallbackJsonlPath = null;
  if (!session) {
    const taskInfo = findSessionFromTasks(req.params.id);
    if (taskInfo && taskInfo.jsonlPath && fs.existsSync(taskInfo.jsonlPath)) {
      // Session exists as a task but not in SQLite — proceed with JSONL reading
      session = { id: req.params.id, cwd: taskInfo.cwd };
      fallbackJsonlPath = taskInfo.jsonlPath;
    }
  }

  if (!session) {
    __hEnd(req, __t0, `GET /:id/transcript NOT_FOUND`);
    return res.status(404).json({ error: { code: "NOT_FOUND", message: "Session not found" } });
  }

  const agentId = req.query.agent_id || null;
  const limit = Math.min(parseInt(req.query.limit) || 50, 200);
  const afterLine = req.query.after ? parseInt(req.query.after) : null;
  const beforeLine = req.query.before ? parseInt(req.query.before) : null;
  const offset = parseInt(req.query.offset) || 0;
  const aroundUuid = typeof req.query.around_uuid === "string" ? req.query.around_uuid : null;
  // Optional: client-reported file size (optimisation for polling — skip read if file unchanged)
  const clientFileSize = req.query.fileSize ? parseInt(req.query.fileSize) : null;

  // Determine the JSONL file path to read.
  // Main: the path recorded by hooks wins — it is the only candidate that works
  // when the session's source is not enabled for directory scanning. Then fall
  // back to the live projects dirs and finally the durable import snapshot
  // (Claude Code prunes old files under cleanupPeriodDays; the snapshot survives).
  const mainCandidates = [
    session.transcript_path,
    getTranscriptPath(req.params.id, session.cwd),
    findTranscriptPath(req.params.id),
    fallbackJsonlPath,
    getSnapshotTranscriptPath(req.params.id),
  ];
  let mainPath = null;
  for (const candidate of mainCandidates) {
    if (!candidate) continue;
    try {
      await fs.promises.access(candidate);
      mainPath = candidate;
      break;
    } catch {}
  }

  let jsonlPath = null;
  if (agentId && agentId !== "main") {
    // Subagent: derive from wherever the main transcript actually is first,
    // then fall back to the enabled sources / snapshot.
    const subagentCandidates = [];
    if (mainPath) {
      const subagentDir = path.join(
        path.dirname(mainPath),
        req.params.id,
        "subagents"
      );
      subagentCandidates.push(path.join(subagentDir, `agent-${agentId}.jsonl`));
      if (agentId.startsWith("acompact-")) {
        try {
          const match = fs
            .readdirSync(subagentDir)
            .find((f) => f.startsWith("agent-acompact-") && f.endsWith(".jsonl"));
          if (match) subagentCandidates.push(path.join(subagentDir, match));
        } catch {}
      }
    }
    subagentCandidates.push(
      getSubagentTranscriptPath(req.params.id, session.cwd, agentId),
      findSubagentTranscriptPath(req.params.id, agentId),
      getSnapshotSubagentTranscriptPath(req.params.id, agentId)
    );
    for (const candidate of subagentCandidates) {
      if (!candidate) continue;
      try {
        await fs.promises.access(candidate);
        jsonlPath = candidate;
        break;
      } catch {}
    }
  } else {
    jsonlPath = mainPath;
  }

  if (!jsonlPath || !fs.existsSync(jsonlPath)) {
    __hEnd(req, __t0, `GET /:id/transcript NO_JSONL`);
    return res.json({ messages: [], total: 0, has_more: false, last_line: 0, first_line: 0 });
  }

  // Stat the file once: used both for quick-size check (polling) and the
  // normal response so clients can skip the next poll cycle if nothing changed.
  const transcriptStat = fs.statSync(jsonlPath);
  const fileSize = transcriptStat.size;

  // Quick check for polling: if client reports a file size and the file hasn't
  // grown, skip parsing entirely — avoids O(n) scan for every empty poll cycle.
  if (clientFileSize !== null && afterLine !== null && fileSize === clientFileSize) {
    __hEnd(req, __t0, `GET /:id/transcript UNCHANGED`);
    return res.json({
      messages: [],
      total: 0,
      has_more: false,
      last_line: afterLine,
      first_line: 0,
      fileSize,
    });
  }

  try {
    // Stream-parse JSONL with early termination for efficiency.
    // Instead of loading all messages into memory, we use pagination-aware
    // strategies to stop reading as soon as we have enough data.
    const messages = [];
    let lineNum = 0;
    let total = 0; // total valid messages seen (exact for early-terminated streams, indicates >= actual)
    let hasMore = false;

    // ── Event-loop yield helper: every N iterations, yield to prevent
    // starving other requests. A 3140-line parse with yield every 100
    // adds ~40 ticks (~40ms overhead) but keeps the server responsive.
    const YIELD_INTERVAL = Number(process.env.TRANSCRIPT_YIELD_INTERVAL) || 100;
    let _yieldCounter = 0;
    const _yieldIfNeeded = async () => {
      if (++_yieldCounter % YIELD_INTERVAL === 0) {
        await new Promise((resolve) => setImmediate(resolve));
      }
    };

    const rl = readline.createInterface({
      input: fs.createReadStream(jsonlPath, { encoding: "utf8" }),
      crlfDelay: Infinity,
    });

    // Helper: parse a JSONL line into a message object, or null if not a displayable message
    function parseMessage(entry, num) {
      // System entries (turn_duration / compaction / api_error) render as
      // System-role messages in the timeline, at their natural JSONL position.
      // Detect them before the content-based parsing below (they carry no
      // message.content and would otherwise be dropped as empty).
      const ts = entry.timestamp
        ? typeof entry.timestamp === "number"
          ? new Date(entry.timestamp).toISOString()
          : entry.timestamp
        : null;
      if (entry.type === "system" && entry.subtype === "turn_duration" && entry.durationMs) {
        return {
          type: "system",
          subtype: "turn_duration",
          uuid: entry.uuid || null,
          timestamp: ts,
          content: [],
          data: {
            summary: `Turn completed in ${(entry.durationMs / 1000).toFixed(1)}s`,
            durationMs: entry.durationMs,
          },
          line: num,
        };
      }
      if (entry.isCompactSummary) {
        return {
          type: "system",
          subtype: "compaction",
          uuid: entry.uuid || null,
          timestamp: ts,
          content: [],
          data: {
            summary: "Context compacted — conversation history compressed",
            uuid: entry.uuid || null,
          },
          line: num,
        };
      }
      if (entry.isApiErrorMessage) {
        const errText = Array.isArray(entry.message?.content)
          ? entry.message.content
              .map((b) => (b && b.text ? b.text : ""))
              .filter(Boolean)
              .join(" ")
          : "";
        return {
          type: "system",
          subtype: "api_error",
          uuid: entry.uuid || null,
          timestamp: ts,
          content: [],
          data: {
            summary: `${entry.error || "unknown"}: ${errText || "API error"}`,
            error_type: entry.error || "unknown",
          },
          line: num,
        };
      }
      const msg = entry.type === "assistant" ? entry.message || {} : {};
      const content = [];

      if (entry.type === "user") {
        const msgContent = entry.message?.content;
        if (typeof msgContent === "string") {
          content.push({ type: "text", text: truncate(msgContent, 10240) });
        } else if (Array.isArray(msgContent)) {
          for (const block of msgContent) {
            if (block.type === "text" && block.text) {
              content.push({ type: "text", text: truncate(block.text, 10240) });
            } else if (block.type === "tool_result") {
              content.push({
                type: "tool_result",
                id: block.tool_use_id || null,
                output: truncate(
                  typeof block.content === "string"
                    ? block.content
                    : JSON.stringify(block.content || ""),
                  10240
                ),
                is_error: !!block.is_error,
              });
            }
          }
        } else if (msgContent === undefined || msgContent === null) {
          return null;
        }
      } else {
        const msgContent = msg.content || [];
        if (Array.isArray(msgContent)) {
          for (const block of msgContent) {
            if (block.type === "text" && block.text) {
              content.push({ type: "text", text: truncate(block.text, 10240) });
            } else if (block.type === "thinking" && block.thinking) {
              content.push({ type: "thinking", text: truncate(block.thinking, 10240) });
            } else if (block.type === "tool_use") {
              content.push({
                type: "tool_use",
                name: block.name || "unknown",
                id: block.id || null,
                input: truncateObj(block.input, 10240),
              });
            }
          }
        }
      }

      if (content.length === 0) return null;

      const message = {
        type: entry.type,
        // uuid aligns with step.uuid/messageUuid in task data — used by the
        // task-flow → chat scroll-to-message linkage.
        uuid: entry.uuid,
        // _messageId is the API-level message.id — stable across streaming
        // partial updates of the same assistant response. Used by TPS
        // post-processing to deduplicate same-message entries.
        _messageId: typeof msg.id === "string" && msg.id ? msg.id : null,
        timestamp: entry.timestamp
          ? typeof entry.timestamp === "number"
            ? new Date(entry.timestamp).toISOString()
            : entry.timestamp
          : null,
        content,
        line: num,
      };

      if (entry.type === "assistant") {
        if (msg.model) message.model = msg.model;
        if (msg.usage) {
          message.usage = {
            input_tokens: msg.usage.input_tokens || 0,
            output_tokens: msg.usage.output_tokens || 0,
            cache_read_input_tokens: msg.usage.cache_read_input_tokens || 0,
            cache_creation_input_tokens: msg.usage.cache_creation_input_tokens || 0,
          };
        }
      }

      return message;
    }

    /**
     * True for an assistant message whose content is exclusively thinking
     * blocks. In Claude mode the thinking-only entry and the text response are
     * written as two separate assistant JSONL entries, so the thinking bubble
     * itself never carries a tps — and the next text assistant's TPS must
     * measure from the real user prompt to include thinking time. The
     * detection is CONTENT-based only (output_tokens on the thinking entry
     * varies by model: qwen writes 0, deepseek-v4-flash writes the same usage
     * as the following text entry). Cosight mode writes one assistant per turn
     * with text/tool_use content, so this is always false there and behavior
     * is unchanged.
     */
    function isThinkingOnlyMessage(m) {
      if (!m || m.type !== "assistant") return false;
      const content = m.content;
      if (!Array.isArray(content) || content.length === 0) return false;
      return content.every((b) => b && b.type === "thinking");
    }

    /**
     * Compute per-model-call TPS using the "unified block rule".
     *
     * Consecutive assistant entries each carrying input_tokens form one
     * "model call block" — they are all part of the SAME model invocation's
     * stream (thinking → tool_use → text, or any sub-sequence). The block's
     * start time is the timestamp of the entry right before the block begins
     * (the "block boundary").
     *
     * Any entry that is NOT an assistant with input_tokens (user prompts,
     * tool_results, assistants without usage) breaks the block. The next
     * assistant with input_tokens starts a fresh block with blockBoundaryTs
     * set to that breaking entry's timestamp.
     *
     * This subsumes the previous wasThinkingOnly + prevRealUserTs dual-
     * baseline approach:
     *   * thinking → text: same block (both have input_tokens), so text
     *     measures from the user before thinking → thinking time counts.
     *   * tool_result → assistant: tool_result breaks the block, so the
     *     assistant measures from the tool_result → tool time excluded.
     *   * out=0 continuations: still in the same block (have input_tokens),
     *     so the next token-carrying entry keeps the original start.
     *
     * Special scenarios handled:
     *   ① First entry has out>0 (Cosight snapshot): blockBoundaryTs=null → no
     *     TPS sample (no predecessor to measure from). Correct.
     *   ② First entry has in>0 but out=0 (deepseek thinking at file start):
     *     block starts, no TPS sample (out=0), state established for later
     *     entries. Correct.
     */
    function computeTpsFromTimestamps(msgs, seedTs, seedBlockBoundaryTs, seedPrevIsAssistantCall) {
      let prevTs = seedTs ?? null;
      let blockBoundaryTs = seedBlockBoundaryTs ?? null;
      let prevIsAssistantCall = !!seedPrevIsAssistantCall;
      for (let i = 0; i < msgs.length; i++) {
        const m = msgs[i];
        if (m.type === "assistant") {
          const hasInputTokens = (m.usage?.input_tokens || 0) > 0;
          if (hasInputTokens) {
            const isThinkingOnly = isThinkingOnlyMessage(m);
            if (!prevIsAssistantCall) {
              // NEW BLOCK — the previous entry was not part of a model call
              // stream, so this assistant starts a fresh block measured from
              // the immediate predecessor (user prompt or tool_result).
              blockBoundaryTs = prevTs;
            }
            // A thinking-only bubble never carries a tps: it has no text
            // output of its own, and its usage (deepseek reports the same
            // tokens as the following text entry) would double-count here.
            if (!isThinkingOnly && m.timestamp && blockBoundaryTs) {
              const durationMs =
                new Date(m.timestamp).getTime() - new Date(blockBoundaryTs).getTime();
              if (durationMs > 0) {
                m.durationMs = durationMs;
                const outTokens = m.usage.output_tokens || 0;
                m.tps =
                  outTokens > 0
                    ? Math.round((outTokens / (durationMs / 1000)) * 100) / 100
                    : undefined;
              }
            }
            prevIsAssistantCall = true;
          } else {
            // Assistant without input_tokens (e.g. no usage) breaks the block.
            prevIsAssistantCall = false;
          }
        } else {
          // User or other type — breaks the block.
          prevIsAssistantCall = false;
        }
        prevTs = m.timestamp;
      }

      // Post-process: same-message-id streaming partials. When consecutive
      // assistant entries share a message.id, only the LAST entry carries the
      // final TPS (earlier ones are partials). Clear tps/durationMs from
      // earlier entries so the UI shows TPS only on the last entry per message.
      for (let i = 0; i < msgs.length - 1; i++) {
        const m = msgs[i];
        const next = msgs[i + 1];
        if (
          m.type === "assistant" &&
          next.type === "assistant" &&
          m._messageId &&
          m._messageId === next._messageId
        ) {
          delete m.tps;
          delete m.durationMs;
        }
      }
    }

    // TPS seed state, captured at each pagination boundary so the first message
    // of the returned batch can still compute TPS against its real predecessor:
    //   seedTs                — timestamp of the immediate predecessor (last user/assistant)
    //   seedBlockBoundaryTs   — block boundary timestamp (entry before current block)
    //   seedPrevIsAssistantCall — whether the last entry was an assistant with input_tokens
    let seedTs = null;
    let seedBlockBoundaryTs = null;
    let seedPrevIsAssistantCall = false;

    // Running block state, advanced on every displayable message in stream
    // order and stamped onto each message (_seedBlockBoundary/_seedPrevIsAssistantCall)
    // so a sliding-window shift (or boundary skip) can snapshot the state as of
    // that exact message. The transient fields are stripped before returning.
    let runningPrevTs = null;
    let runningBlockBoundaryTs = null;
    let runningPrevIsAssistantCall = false;

    function advanceSeedState(message) {
      if (message.type === "assistant") {
        const hasInputTokens = (message.usage?.input_tokens || 0) > 0;
        if (hasInputTokens) {
          if (!runningPrevIsAssistantCall) {
            // NEW BLOCK — this assistant starts a fresh model call stream.
            runningBlockBoundaryTs = runningPrevTs;
          }
          runningPrevIsAssistantCall = true;
        } else {
          runningPrevIsAssistantCall = false;
        }
      } else {
        // User or other type — breaks the block.
        runningPrevIsAssistantCall = false;
      }
      runningPrevTs = message.timestamp;
      message._seedBlockBoundary = runningBlockBoundaryTs;
      message._seedPrevIsAssistantCall = runningPrevIsAssistantCall;
    }

    if (afterLine !== null) {
      // Incremental mode: skip lines until after afterLine, collect up to limit, then stop
      let foundStart = false;
      for await (const line of rl) {
        lineNum++;
        await _yieldIfNeeded();
        if (!line.trim()) continue;
        let entry;
        try {
          entry = JSON.parse(line);
        } catch {
          continue;
        }
        if (
          entry.type !== "user" &&
          entry.type !== "assistant" &&
          entry.type !== "system" &&
          !entry.isCompactSummary &&
          !entry.isApiErrorMessage
        )
          continue;

        if (!foundStart) {
          if (lineNum <= afterLine) {
            // The last valid message at/before the boundary is this batch's
            // predecessor — carry its seed state forward as the TPS seed.
            const seedMsg = parseMessage(entry, lineNum);
            // System messages are timeline metadata — they don't seed the
            // next batch's TPS.
            if (seedMsg && seedMsg.type !== "system") {
              advanceSeedState(seedMsg);
              seedTs = seedMsg.timestamp;
              seedBlockBoundaryTs = seedMsg._seedBlockBoundary;
              seedPrevIsAssistantCall = seedMsg._seedPrevIsAssistantCall;
            }
            continue;
          }
          foundStart = true;
        }

        const message = parseMessage(entry, lineNum);
        if (!message) continue;
        // System messages are timeline metadata, not chat messages: they don't
        // advance the TPS seed state nor count toward the message total.
        if (message.type !== "system") {
          advanceSeedState(message);
          total++;
        }
        messages.push(message);
        if (messages.length >= limit) {
          // Check if there's at least one more valid message
          hasMore = true;
          rl.close();
          rl.removeAllListeners();
          break;
        }
      }
      // If we exhausted the stream without hitting limit, hasMore stays false
    } else if (beforeLine !== null) {
      // History mode: collect messages with line < beforeLine using a sliding window.
      // hasMore here means "more *older* messages exist before what we're returning"
      // — the only way to know that is if we shifted any out of the window
      // (total > limit). Hitting the boundary tells us nothing about older history.
      for await (const line of rl) {
        lineNum++;
        await _yieldIfNeeded();
        if (!line.trim()) continue;
        let entry;
        try {
          entry = JSON.parse(line);
        } catch {
          continue;
        }
        if (
          entry.type !== "user" &&
          entry.type !== "assistant" &&
          entry.type !== "system" &&
          !entry.isCompactSummary &&
          !entry.isApiErrorMessage
        )
          continue;
        if (lineNum >= beforeLine) {
          // Reached the boundary — stop reading
          rl.close();
          rl.removeAllListeners();
          break;
        }

        const message = parseMessage(entry, lineNum);
        if (!message) continue;
        // System messages are timeline metadata, not chat messages: they don't
        // advance the TPS seed state nor count toward the message total.
        if (message.type !== "system") {
          advanceSeedState(message);
          total++;
        }
        messages.push(message);
        // Sliding window: only keep the last `limit` messages
        if (messages.length > limit) {
          // The shifted-out message precedes the new window head — seed TPS from it.
          const shifted = messages.shift();
          if (shifted.type !== "system") {
            seedTs = shifted.timestamp;
            seedBlockBoundaryTs = shifted._seedBlockBoundary;
            seedPrevIsAssistantCall = shifted._seedPrevIsAssistantCall;
          }
        }
      }
      if (total > limit) hasMore = true;
    } else if (aroundUuid) {
      // Around-uuid mode: load messages centered on the entry whose uuid === aroundUuid.
      // Keep a sliding window of up to `limit` messages preceding the anchor (context),
      // then collect the anchor + following messages up to `limit` total. Guarantees the
      // anchor message is present in the result. Used by task-flow scroll-to-message linkage.
      const beforeBuffer = [];
      let anchorFound = false;
      for await (const line of rl) {
        lineNum++;
        await _yieldIfNeeded();
        if (!line.trim()) continue;
        let entry;
        try {
          entry = JSON.parse(line);
        } catch {
          continue;
        }
        if (
          entry.type !== "user" &&
          entry.type !== "assistant" &&
          entry.type !== "system" &&
          !entry.isCompactSummary &&
          !entry.isApiErrorMessage
        )
          continue;

        if (!anchorFound && entry.uuid === aroundUuid) {
          anchorFound = true;
        }

        const message = parseMessage(entry, lineNum);
        if (!message) continue;
        // System messages are timeline metadata, not chat messages: they don't
        // advance the TPS seed state nor count toward the message total.
        if (message.type !== "system") {
          advanceSeedState(message);
          total++;
        }

        if (!anchorFound) {
          // Collect context before the anchor (sliding window capped at limit)
          beforeBuffer.push(message);
          if (beforeBuffer.length > limit) {
            // The shifted-out context message precedes the buffer head — seed TPS from it.
            const shifted = beforeBuffer.shift();
            if (shifted.type !== "system") {
              seedTs = shifted.timestamp;
              seedUserTs = shifted._seedUserTs;
              seedWasThinkingOnly = shifted._seedWasThinking;
            }
          }
          continue;
        }

        // Anchor reached: flush context buffer, then collect anchor + following
        if (beforeBuffer.length > 0) {
          for (const b of beforeBuffer) messages.push(b);
          beforeBuffer.length = 0;
        }
        messages.push(message);
        if (messages.length >= limit) {
          hasMore = true; // more messages likely follow the window
          rl.close();
          rl.removeAllListeners();
          break;
        }
      }
      // If the anchor was never found, return whatever context we buffered (best effort)
      if (!anchorFound && messages.length === 0 && beforeBuffer.length > 0) {
        for (const b of beforeBuffer) messages.push(b);
      }
    } else if (offset > 0) {
      // Legacy offset pagination: skip `offset` valid messages, then collect `limit`
      let skipped = 0;
      for await (const line of rl) {
        lineNum++;
        await _yieldIfNeeded();
        if (!line.trim()) continue;
        let entry;
        try {
          entry = JSON.parse(line);
        } catch {
          continue;
        }
        if (
          entry.type !== "user" &&
          entry.type !== "assistant" &&
          entry.type !== "system" &&
          !entry.isCompactSummary &&
          !entry.isApiErrorMessage
        )
          continue;

        const message = parseMessage(entry, lineNum);
        if (!message) continue;
        // System messages are timeline metadata, not chat messages: they don't
        // advance the TPS seed state nor count toward the message total.
        if (message.type !== "system") {
          advanceSeedState(message);
          total++;
        }

        if (message.type !== "system" && skipped < offset) {
          skipped++;
          // The last skipped message is this batch's predecessor — seed TPS from it.
          seedTs = message.timestamp;
          seedBlockBoundaryTs = message._seedBlockBoundary;
          seedPrevIsAssistantCall = message._seedPrevIsAssistantCall;
          continue;
        }
        messages.push(message);
        if (messages.length >= limit) {
          hasMore = true; // assume more exist
          rl.close();
          rl.removeAllListeners();
          break;
        }
      }
    } else {
      // Default: return the latest N messages (chat-flow mode) using a sliding window
      for await (const line of rl) {
        lineNum++;
        await _yieldIfNeeded();
        if (!line.trim()) continue;
        let entry;
        try {
          entry = JSON.parse(line);
        } catch {
          continue;
        }
        if (
          entry.type !== "user" &&
          entry.type !== "assistant" &&
          entry.type !== "system" &&
          !entry.isCompactSummary &&
          !entry.isApiErrorMessage
        )
          continue;

        const message = parseMessage(entry, lineNum);
        if (!message) continue;
        // System messages are timeline metadata, not chat messages: they don't
        // advance the TPS seed state nor count toward the message total.
        if (message.type !== "system") {
          advanceSeedState(message);
          total++;
        }
        messages.push(message);
        // Sliding window: only keep the last `limit` messages in memory
        if (messages.length > limit) {
          // The shifted-out message precedes the new window head — seed TPS from it.
          const shifted = messages.shift();
          if (shifted.type !== "system") {
            seedTs = shifted.timestamp;
            seedBlockBoundaryTs = shifted._seedBlockBoundary;
            seedPrevIsAssistantCall = shifted._seedPrevIsAssistantCall;
          }
        }
      }
      // If we shifted any messages out, there are more
      hasMore = total > limit;
    }

    const lastLine = messages.length > 0 ? messages[messages.length - 1].line : 0;
    const firstLine = messages.length > 0 ? messages[0].line : 0;

    // Compute per-message TPS from consecutive timestamps (post-pagination)
    computeTpsFromTimestamps(messages, seedTs, seedBlockBoundaryTs, seedPrevIsAssistantCall);

    // Remove internal line field and transient seed markers from messages
    for (const m of messages) {
      delete m.line;
      delete m._seedBlockBoundary;
      delete m._seedPrevIsAssistantCall;
      delete m._messageId;
    }

    __hEnd(req, __t0, `GET /:id/transcript messages=${messages.length} total=${total}`);
    res.json({
      messages,
      total,
      has_more: hasMore,
      last_line: lastLine,
      first_line: firstLine,
      fileSize,
    });
  } catch (err) {
    __hEnd(req, __t0, `GET /:id/transcript ERROR`);
    res.json({ messages: [], total: 0, has_more: false, last_line: 0, first_line: 0 });
  }
});

function truncate(str, maxLen) {
  if (!str || str.length <= maxLen) return str;
  return str.slice(0, maxLen) + "[truncated]";
}

function truncateObj(obj, maxLen) {
  if (!obj) return obj;
  const json = JSON.stringify(obj);
  if (json.length <= maxLen) return obj;
  return { _truncated: truncate(json, maxLen) };
}

// POST /:id/watch — Start watching a session's transcript for real-time updates
router.post("/:id/watch", (req, res) => {
  const sessionId = req.params.id;
  const clientId = req.body.clientId || req.query.clientId;

  if (!clientId) {
    return res
      .status(400)
      .json({ error: { code: "MISSING_CLIENT_ID", message: "clientId is required" } });
  }

  // Find the JSONL file path
  const session = stmts.getSession.get(sessionId);
  if (!session) {
    return res.status(404).json({ error: { code: "NOT_FOUND", message: "Session not found" } });
  }

  const jsonlPath =
    getTranscriptPath(sessionId, session.cwd) ||
    findTranscriptPath(sessionId) ||
    getSnapshotTranscriptPath(sessionId);

  if (!jsonlPath || !fs.existsSync(jsonlPath)) {
    return res
      .status(404)
      .json({ error: { code: "NO_TRANSCRIPT", message: "Transcript file not found" } });
  }

  const started = fileWatcher.addClient(sessionId, jsonlPath, clientId);
  if (!started) {
    return res
      .status(500)
      .json({ error: { code: "WATCH_FAILED", message: "Failed to start watching" } });
  }

  res.json({ ok: true, sessionId, clientId });
});

// POST /:id/unwatch — Stop watching a session's transcript
router.post("/:id/unwatch", (req, res) => {
  const sessionId = req.params.id;
  const clientId = req.body.clientId || req.query.clientId;

  if (!clientId) {
    return res
      .status(400)
      .json({ error: { code: "MISSING_CLIENT_ID", message: "clientId is required" } });
  }

  fileWatcher.removeClient(sessionId, clientId);
  res.json({ ok: true, sessionId, clientId });
});

// POST /:id/heartbeat — Update client heartbeat for watched session
router.post("/:id/heartbeat", (req, res) => {
  const sessionId = req.params.id;
  const clientId = req.body.clientId || req.query.clientId;

  if (!clientId) {
    return res
      .status(400)
      .json({ error: { code: "MISSING_CLIENT_ID", message: "clientId is required" } });
  }

  fileWatcher.heartbeat(sessionId, clientId);
  res.json({ ok: true });
});

// GET /watch/status — Get file watcher status (for debugging)
router.get("/watch/status", (_req, res) => {
  res.json({ watchers: fileWatcher.getStatus() });
});

// ─────────────────────────────────────────────────────────────────────────────
// GET /:id/export — Export session data as ZIP
// ZIP structure:
//   session-{fullId}-{encodedCwd}/
//   ├── session/
//   │   ├── {fullId}.jsonl                    (main agent transcript)
//   │   └── {fullId}/                         (only if subagents exist)
//   │       └── subagents/
//   │           ├── agent-xxx.jsonl
//   │           └── agent-yyy.jsonl
//   └── tasks/
//       ├── {taskId-1}.json
//       └── {taskId-2}.json
// ─────────────────────────────────────────────────────────────────────────────
router.get("/:id/export", async (req, res) => {
  const sessionId = req.params.id;
  const session = stmts.getSession.get(sessionId);

  // Fallback: try to find session from task files if not in SQLite
  let fallbackSession = null;
  if (!session) {
    const taskInfo = findSessionFromTasks(sessionId);
    if (taskInfo) {
      fallbackSession = { id: sessionId, cwd: taskInfo.cwd };
    }
  }

  const effectiveSession = session || fallbackSession;
  if (!effectiveSession) {
    return res.status(404).json({ error: { code: "NOT_FOUND", message: "Session not found" } });
  }

  try {
    // Build top-level directory name: session-{fullId}-{encodedCwd}
    const cwd = effectiveSession.cwd;
    const encodedCwdPart = cwd ? encodeCwd(cwd) : "";
    const topDir = encodedCwdPart
      ? `session-${sessionId}-${encodedCwdPart}`
      : `session-${sessionId}`;

    // Sanitize topDir for use as ZIP filename (remove any problematic chars)
    const safeTopDir = topDir.replace(/[<>:"|?*]/g, "-");

    // Set response headers for ZIP download
    const zipFilename = `${safeTopDir}.zip`;
    res.setHeader("Content-Type", "application/zip");
    res.setHeader("Content-Disposition", `attachment; filename="${safeTopDir}.zip"`);

    // Create archiver with low compression for speed (JSONL files can be large)
    // archiver v8 uses class-based API: new ZipArchive(options)
    const archiverModule = require("archiver");
    const archive = new archiverModule.ZipArchive({ zlib: { level: 1 } });

    // Handle errors
    archive.on("error", (err) => {
      sessionsLog.error(`[export] Archive error: ${err.message}`);
      try {
        if (!res.headersSent) {
          res.status(500).json({ error: { code: "ARCHIVE_ERROR", message: err.message } });
        } else {
          res.end();
        }
      } catch {
        /* response already finished */
      }
    });

    archive.on("warning", (err) => {
      if (err.code !== "ENOENT") {
        sessionsLog.warn(`[export] Archive warning: ${err.message}`);
      }
    });

    // Pipe archive to response
    archive.pipe(res);

    // ── 1. Find and add main transcript JSONL ──
    const mainJsonlPath =
      getTranscriptPath(sessionId, cwd) ||
      findTranscriptPath(sessionId) ||
      getSnapshotTranscriptPath(sessionId);

    let mainJsonlAdded = false;
    if (mainJsonlPath && fs.existsSync(mainJsonlPath)) {
      archive.file(mainJsonlPath, { name: `${topDir}/session/${sessionId}.jsonl` });
      mainJsonlAdded = true;
    }

    // ── 2. Find and add subagent JSONL files ──
    // Only create {sessionId}/subagents/ hierarchy if subagent files exist
    let subagentDir = null;
    if (mainJsonlPath) {
      // Subagents are in {dirname(mainJsonl)}/{sessionId}/subagents/
      const candidate = path.join(path.dirname(mainJsonlPath), sessionId, "subagents");
      if (fs.existsSync(candidate)) {
        subagentDir = candidate;
      }
    }

    // Fallback: scan all project directories for subagent files (both native and imported)
    if (!subagentDir) {
      const searchDirs = [...getProjectsDirs(), getImportedSessionsDir()];
      for (const projectsDir of searchDirs) {
        if (!fs.existsSync(projectsDir)) continue;
        try {
          const dirs = fs.readdirSync(projectsDir, { withFileTypes: true });
          for (const d of dirs) {
            if (!d.isDirectory()) continue;
            const candidate = path.join(projectsDir, d.name, sessionId, "subagents");
            if (fs.existsSync(candidate)) {
              subagentDir = candidate;
              break;
            }
          }
          if (subagentDir) break;
        } catch {
          /* ignore */
        }
      }
    }

    // Also check snapshot directory for subagents
    if (!subagentDir) {
      const snapshotSubDir = path.join(getTranscriptSnapshotDir(), sessionId, "subagents");
      if (fs.existsSync(snapshotSubDir)) {
        subagentDir = snapshotSubDir;
      }
    }

    let subagentCount = 0;
    if (subagentDir) {
      try {
        const allFiles = fs.readdirSync(subagentDir);
        const jsonlFiles = allFiles.filter((f) => f.endsWith(".jsonl"));
        if (jsonlFiles.length > 0) {
          for (const file of jsonlFiles) {
            const filePath = path.join(subagentDir, file);
            // ZIP path: {topDir}/session/{sessionId}/subagents/{file}
            archive.file(filePath, { name: `${topDir}/session/${sessionId}/subagents/${file}` });
            subagentCount++;

            // Also include the corresponding meta.json if it exists
            const metaFile = file.replace(/\.jsonl$/, ".meta.json");
            if (allFiles.includes(metaFile)) {
              const metaPath = path.join(subagentDir, metaFile);
              archive.file(metaPath, {
                name: `${topDir}/session/${sessionId}/subagents/${metaFile}`,
              });
            }
          }
        }
      } catch {
        /* ignore */
      }
    }

    // ── 3. 任务文件导出已移除 - 会话监控不依赖任务管理功能 ──
    // 导出的 ZIP 文件只包含会话转录和子代理文件

    // Finalize the archive
    await archive.finalize();

    sessionsLog.info(
      `[export] Session ${sessionId}: mainJsonl=${mainJsonlAdded}, subagents=${subagentCount}`
    );
  } catch (err) {
    sessionsLog.error(`[export] Failed: ${err?.message || String(err)}`);
    if (!res.headersSent) {
      res.status(500).json({ error: { code: "EXPORT_FAILED", message: err.message } });
    }
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// POST /api/sessions/import — Import a session from an uploaded ZIP archive.
// Accepts multipart/form-data with a single file field "file" containing a ZIP.
// The ZIP structure must match the export format:
//   <topDir>/session/{sessionId}.jsonl
//   <topDir>/session/{sessionId}/subagents/... (optional)
//   <topDir>/tasks/*.json (optional)
//
// On success:
//   - Extracts the main JSONL to projects/{encodedCwd}/{sessionId}.jsonl
//   - Copies subagent files if present
//   - Inserts a session record with status='imported' into the database
//   - Creates a main agent record so session-list queries work
//
// Errors:
//   - 400: invalid file type, file too large, ZIP structure invalid
//   - 409: session with the same ID already exists
//   - 500: internal error during import
// ─────────────────────────────────────────────────────────────────────────────
let _sessionUpload;
function getSessionUploader() {
  if (_sessionUpload) return _sessionUpload;
  let multer;
  try {
    multer = require("multer");
  } catch {
    return null;
  }
  const os = require("os");
  const crypto = require("crypto");
  const storage = multer.diskStorage({
    destination: (_req, _file, cb) => {
      // Use data directory tmp/ instead of os.tmpdir() for container environments
      // where /tmp may be read-only or have restricted permissions
      const dir = path.join(getTaskManagementRoot(), "tmp", "session-import");
      fs.mkdirSync(dir, { recursive: true });
      cb(null, dir);
    },
    filename: (_req, _file, cb) => {
      const rand = crypto.randomBytes(4).toString("hex");
      cb(null, `session-${rand}.zip`);
    },
  });
  _sessionUpload = multer({
    storage,
    limits: { files: 1, fileSize: 100 * 1024 * 1024, fields: 10 },
    fileFilter: (_req, file, cb) => {
      const name = (file.originalname || "").toLowerCase();
      if (
        name.endsWith(".zip") ||
        file.mimetype === "application/zip" ||
        file.mimetype === "application/x-zip-compressed"
      ) {
        cb(null, true);
      } else {
        cb(new Error("仅支持 .zip 文件"));
      }
    },
  });
  return _sessionUpload;
}

router.post("/import", (req, res) => {
  const uploader = getSessionUploader();
  if (!uploader) {
    return res.status(500).json({
      error: { code: "MULTER_MISSING", message: "文件上传模块未安装，请运行 npm install" },
    });
  }

  uploader.single("file")(req, res, async (err) => {
    if (err) {
      return res.status(400).json({
        error: { code: "UPLOAD_ERROR", message: err.message },
      });
    }

    if (!req.file) {
      return res.status(400).json({
        error: { code: "NO_FILE", message: "请上传一个 ZIP 文件" },
      });
    }

    const zipPath = req.file.path;
    try {
      const result = await importSessionFromZip(zipPath);

      // Broadcast the new session to connected WebSocket clients
      try {
        const newSession = stmts.getSession.get(result.session.id);
        if (newSession) {
          broadcast("session_created", newSession);
        }
      } catch (broadcastErr) {
        sessionsLog.warn(`[import] Failed to broadcast new session: ${broadcastErr.message}`);
      }

      sessionsLog.info(
        `[import] Session ${result.session.id}: jsonl=${result.files.jsonl}, subagents=${result.files.subagents}, tasks=${result.files.tasks}`
      );

      res.json({
        success: true,
        session: result.session,
        files: result.files,
        message: "会话导入成功",
      });
    } catch (importErr) {
      sessionsLog.error(`[import] Failed: ${importErr?.message || String(importErr)}`);
      const message = importErr.message || "导入失败";
      const statusCode = message.includes("已存在") ? 409 : 500;
      res.status(statusCode).json({
        error: { code: "IMPORT_FAILED", message },
      });
    } finally {
      // Cleanup uploaded ZIP file
      try {
        if (fs.existsSync(zipPath)) fs.unlinkSync(zipPath);
      } catch {
        /* ignore cleanup errors */
      }
    }
  });
});

// ─────────────────────────────────────────────────────────────────────────────
module.exports = router;

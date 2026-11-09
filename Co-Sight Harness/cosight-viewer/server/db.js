// SPDX-License-Identifier: Apache-2.0
/**
 * @file Database setup and access layer using SQLite for storing sessions, agents, events, token usage, and model pricing. Handles schema creation, migrations, and provides prepared statements for all database operations.
 */

const path = require("path");
const fs = require("fs");

let Database;
try {
  Database = require("./compat-sqlite");
} catch (e) {
  console.error(
    "\n" +
      "╔══════════════════════════════════════════════════════════════╗\n" +
      "║  SQLite backend not available                                ║\n" +
      "║                                                              ║\n" +
      "║  node:sqlite is not available (requires Node.js >= 22.5).    ║\n" +
      "║                                                              ║\n" +
      "║  Fix: Upgrade to Node.js 22.5+                               ║\n" +
      "╚══════════════════════════════════════════════════════════════╝\n"
  );
  process.exit(1);
}

// Resolution order: explicit DASHBOARD_DB_PATH wins; otherwise the file lives
// in the viewer-owned data directory (DASHBOARD_DATA_DIR / COSIGHT_HOME).
const { getViewerDataDir } = require("./lib/claude-home");

const DB_PATH = process.env.DASHBOARD_DB_PATH || path.join(getViewerDataDir(), "dashboard.db");
const DB_DIR = path.dirname(DB_PATH);

fs.mkdirSync(DB_DIR, { recursive: true });

const db = new Database(DB_PATH);

// ─── [DIAG] DB初始化日志（已合并到 unified-logger） ───

db.pragma("journal_mode = WAL");
db.pragma("foreign_keys = ON");
db.pragma("busy_timeout = 5000");

db.exec(`
  CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    name TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','completed','error','abandoned','imported')),
    cwd TEXT,
    model TEXT,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ended_at TEXT,
    metadata TEXT,
    agent_runtime_session_id TEXT,
    source TEXT
  );

  CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'main' CHECK(type IN ('main','subagent')),
    subagent_type TEXT,
    status TEXT NOT NULL DEFAULT 'waiting' CHECK(status IN ('working','waiting','completed','error')),
    task TEXT,
    current_tool TEXT,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ended_at TEXT,
    parent_agent_id TEXT,
    metadata TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_agent_id) REFERENCES agents(id) ON DELETE SET NULL
  );

  CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id TEXT,
    event_type TEXT NOT NULL,
    tool_name TEXT,
    summary TEXT,
    data TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE SET NULL
  );

  CREATE TABLE IF NOT EXISTS token_usage (
    session_id TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT 'unknown',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, model),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS model_pricing (
    model_pattern TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    input_per_mtok REAL NOT NULL DEFAULT 0,
    output_per_mtok REAL NOT NULL DEFAULT 0,
    cache_read_per_mtok REAL NOT NULL DEFAULT 0,
    cache_write_per_mtok REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
  );

  CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint TEXT PRIMARY KEY,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
  );

  CREATE INDEX IF NOT EXISTS idx_agents_session ON agents(session_id);
  CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
  CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
  CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
  CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at DESC);
  CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
  CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);

  -- Composite indexes for frequent query patterns (columns that exist at table creation time)
  CREATE INDEX IF NOT EXISTS idx_events_session_type ON events(session_id, event_type);
  CREATE INDEX IF NOT EXISTS idx_agents_session_type ON agents(session_id, type);
`);

// Default model pricing — shared by initial seed + startup top-up + reset endpoint
// Columns: pattern, display_name, input, output, cache_read (hits & refreshes), cache_write (5m ephemeral)
// Each model gets its own explicit row — no catch-all grouping
const DEFAULT_PRICING = [
  // Opus family
  ["claude-opus-4-8%", "Claude Opus 4.8", 5, 25, 0.5, 6.25],
  ["claude-opus-4-7%", "Claude Opus 4.7", 5, 25, 0.5, 6.25],
  ["claude-opus-4-6%", "Claude Opus 4.6", 5, 25, 0.5, 6.25],
  ["claude-opus-4-5%", "Claude Opus 4.5", 5, 25, 0.5, 6.25],
  ["claude-opus-4-1%", "Claude Opus 4.1", 15, 75, 1.5, 18.75],
  ["claude-opus-4-2%", "Claude Opus 4", 15, 75, 1.5, 18.75],
  // Sonnet family
  ["claude-sonnet-4-6%", "Claude Sonnet 4.6", 3, 15, 0.3, 3.75],
  ["claude-sonnet-4-5%", "Claude Sonnet 4.5", 3, 15, 0.3, 3.75],
  ["claude-sonnet-4-2%", "Claude Sonnet 4", 3, 15, 0.3, 3.75],
  ["claude-3-7-sonnet%", "Claude Sonnet 3.7", 3, 15, 0.3, 3.75],
  ["claude-3-5-sonnet%", "Claude Sonnet 3.5", 3, 15, 0.3, 3.75],
  // Haiku family
  ["claude-haiku-4-5%", "Claude Haiku 4.5", 1, 5, 0.1, 1.25],
  ["claude-3-5-haiku%", "Claude Haiku 3.5", 0.8, 4, 0.08, 1],
  ["claude-3-haiku%", "Claude Haiku 3", 0.25, 1.25, 0.03, 0.3],
  // Legacy
  ["claude-3-opus%", "Claude Opus 3", 15, 75, 1.5, 18.75],
];

// Top-up: insert any default pattern that isn't already present. Preserves
// user edits to existing rows — we only add what's missing, never overwrite.
// This runs every startup so new default models (e.g. Opus 4.8) appear in the
// Settings UI automatically without requiring a manual "Reset Defaults".
{
  const existing = new Set(
    db
      .prepare("SELECT model_pattern FROM model_pricing")
      .all()
      .map((r) => r.model_pattern)
  );
  const insert = db.prepare(
    "INSERT OR IGNORE INTO model_pricing (model_pattern, display_name, input_per_mtok, output_per_mtok, cache_read_per_mtok, cache_write_per_mtok) VALUES (?, ?, ?, ?, ?, ?)"
  );
  const addMissing = db.transaction((rows) => {
    for (const [pattern, name, inp, out, cr, cw] of rows) {
      if (!existing.has(pattern)) insert.run(pattern, name, inp, out, cr, cw);
    }
  });
  addMissing(DEFAULT_PRICING);
}

// Migrate: if token_usage has rows without model column (old schema), add it
try {
  db.prepare("SELECT model FROM token_usage LIMIT 1").get();
} catch {
  // Old schema — recreate table with model column
  db.pragma("foreign_keys = OFF");
  db.prepare("ALTER TABLE token_usage RENAME TO token_usage_old").run();
  db.prepare(
    `
    CREATE TABLE token_usage (
      session_id TEXT NOT NULL,
      model TEXT NOT NULL DEFAULT 'unknown',
      input_tokens INTEGER NOT NULL DEFAULT 0,
      output_tokens INTEGER NOT NULL DEFAULT 0,
      cache_read_tokens INTEGER NOT NULL DEFAULT 0,
      cache_write_tokens INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (session_id, model),
      FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
    )
  `
  ).run();
  db.prepare(
    `
    INSERT INTO token_usage (session_id, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens)
      SELECT tu.session_id, COALESCE(s.model, 'unknown'), tu.input_tokens, tu.output_tokens, tu.cache_read_tokens, tu.cache_write_tokens
      FROM token_usage_old tu LEFT JOIN sessions s ON s.id = tu.session_id
  `
  ).run();
  db.prepare("DROP TABLE token_usage_old").run();
  db.pragma("foreign_keys = ON");
}

// Migrate: add updated_at columns to sessions and agents
try {
  db.prepare("SELECT updated_at FROM sessions LIMIT 1").get();
} catch {
  db.prepare("ALTER TABLE sessions ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''").run();
  db.prepare("UPDATE sessions SET updated_at = COALESCE(ended_at, started_at)").run();
}
try {
  db.prepare("SELECT updated_at FROM agents LIMIT 1").get();
} catch {
  db.prepare("ALTER TABLE agents ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''").run();
  db.prepare("UPDATE agents SET updated_at = COALESCE(ended_at, started_at)").run();
}

// Composite index on (status, updated_at) — must be AFTER migration adds updated_at
db.exec(
  `CREATE INDEX IF NOT EXISTS idx_sessions_status_updated ON sessions(status, updated_at DESC)`
);

// Migrate: add `awaiting_input_since` columns to sessions and agents.
// When Claude Code emits a Notification asking for permission or user input,
// we mark the session and its main agent as awaiting input by stamping this
// column with the notification's ISO timestamp. The underlying status enum
// stays unchanged (so existing CHECK constraints, queries, and aggregations
// keep working); the UI derives an effective "waiting" status whenever this
// column is non-null.
try {
  db.prepare("SELECT awaiting_input_since FROM sessions LIMIT 1").get();
} catch {
  db.prepare("ALTER TABLE sessions ADD COLUMN awaiting_input_since TEXT").run();
}
try {
  db.prepare("SELECT awaiting_input_since FROM agents LIMIT 1").get();
} catch {
  db.prepare("ALTER TABLE agents ADD COLUMN awaiting_input_since TEXT").run();
}

// Migrate: add `awaiting_reason` columns to sessions and agents. Explains WHY
// the awaiting_input_since flag was stamped ('notification' | 'stop' |
// 'session_start'). Used by the actor-aware clear: a genuine 'notification'
// wait (main agent blocked on the user) must NOT be cleared by a background
// subagent's tool events, while passive waits ('stop'/'session_start') can be.
try {
  db.prepare("SELECT awaiting_reason FROM sessions LIMIT 1").get();
} catch {
  db.prepare("ALTER TABLE sessions ADD COLUMN awaiting_reason TEXT").run();
}
try {
  db.prepare("SELECT awaiting_reason FROM agents LIMIT 1").get();
} catch {
  db.prepare("ALTER TABLE agents ADD COLUMN awaiting_reason TEXT").run();
}

// Migrate: add `transcript_path` to sessions for fast active-session sweep.
// Before this, the periodic compaction sweep had to do
//   SELECT DISTINCT json_extract(events.data, '$.transcript_path') ...
// across the entire events table (250k+ rows in mature DBs). Storing the
// path on sessions lets the sweep query touch only active session rows.
// Backfilled once from the events table; thereafter populated by
// routes/hooks.js ensureSession() and the first event that carries
// transcript_path.
try {
  db.prepare("SELECT transcript_path FROM sessions LIMIT 1").get();
} catch {
  db.prepare("ALTER TABLE sessions ADD COLUMN transcript_path TEXT").run();
  // Backfill: pull the first transcript_path we can find in events for each
  // session. Uses a correlated subquery so SQLite limits the inner scan to
  // each session's rows (still bounded by events row count, but only runs
  // once per DB lifetime).
  // json_valid guard: legacy events.data may hold non-JSON text. Without it,
  // json_extract throws "malformed JSON" mid-UPDATE and aborts startup.
  db.prepare(
    `UPDATE sessions SET transcript_path = (
       SELECT json_extract(e.data, '$.transcript_path')
       FROM events e
       WHERE e.session_id = sessions.id
         AND json_valid(e.data) = 1
         AND json_extract(e.data, '$.transcript_path') IS NOT NULL
       LIMIT 1
     ) WHERE transcript_path IS NULL`
  ).run();
}

// Migrate: add `source` to sessions. "claude" / "cosight" identifies which CLI
// produced the session. Nullable: rows created before dual-source support keep
// NULL, and readers fall back to transcript_path inference, then "claude".
try {
  db.prepare("SELECT source FROM sessions LIMIT 1").get();
} catch {
  db.prepare("ALTER TABLE sessions ADD COLUMN source TEXT").run();
}

// Migrate: add `first_prompt` to sessions for the session-list title column.
// One-write semantics: populated once (by hooks.js on UserPromptSubmit or by
// scripts/import-history.js during import), never overwritten. No backfill —
// old sessions keep first_prompt = NULL and the frontend shows "(Untitled)".
try {
  db.prepare("SELECT first_prompt FROM sessions LIMIT 1").get();
} catch {
  db.prepare("ALTER TABLE sessions ADD COLUMN first_prompt TEXT").run();
}

// Migrate: add `custom_title` and `ai_title` to sessions for session title display.
// custom_title: user-set title via /rename command (stored as custom-title in JSONL)
// ai_title: AI-generated title (stored as ai-title in JSONL)
// These are populated by scanning JSONL at SessionEnd. Priority: custom_title > ai_title > first_prompt.
try {
  db.prepare("SELECT custom_title FROM sessions LIMIT 1").get();
} catch {
  db.prepare("ALTER TABLE sessions ADD COLUMN custom_title TEXT").run();
}
try {
  db.prepare("SELECT ai_title FROM sessions LIMIT 1").get();
} catch {
  db.prepare("ALTER TABLE sessions ADD COLUMN ai_title TEXT").run();
}

// Migrate: add `last_scanned_line` to sessions for incremental JSONL scanning.
// Tracks the last line number scanned for title extraction to avoid re-scanning
// the entire file on each SessionEnd. Default 0 means never scanned.
try {
  db.prepare("SELECT last_scanned_line FROM sessions LIMIT 1").get();
} catch {
  db.prepare("ALTER TABLE sessions ADD COLUMN last_scanned_line INTEGER DEFAULT 0").run();
}

// Migrate: add `agent_runtime_session_id` to sessions for storing agent-runtime session ID.
// This allows direct mapping between viewer sessions and agent-runtime sessions,
// eliminating the need for fuzzy matching when resuming sessions.
try {
  db.prepare("SELECT agent_runtime_session_id FROM sessions LIMIT 1").get();
} catch {
  db.prepare("ALTER TABLE sessions ADD COLUMN agent_runtime_session_id TEXT").run();
}

// Migrate: add 'imported' to sessions.status CHECK constraint.
// SQLite doesn't allow modifying CHECK constraints directly, so we recreate the table.
// This is needed for the session import feature where imported sessions have status='imported'.
try {
  db.prepare(
    "INSERT INTO sessions (id, status, cwd, started_at, updated_at) VALUES ('__test_imported__', 'imported', '', '', '')"
  ).run();
  db.prepare("DELETE FROM sessions WHERE id = '__test_imported__'").run();
} catch {
  // CHECK constraint doesn't allow 'imported' — need to migrate
  db.pragma("foreign_keys = OFF");

  // Cleanup: drop sessions_old if it exists from a previous incomplete migration
  try {
    db.prepare("DROP TABLE IF EXISTS sessions_old").run();
  } catch {
    /* ignore */
  }

  db.prepare("ALTER TABLE sessions RENAME TO sessions_old").run();
  db.exec(`
    CREATE TABLE sessions (
      id TEXT PRIMARY KEY,
      name TEXT,
      status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','completed','error','abandoned','imported')),
      cwd TEXT,
      model TEXT,
      started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
      ended_at TEXT,
      metadata TEXT,
      updated_at TEXT NOT NULL DEFAULT '',
      awaiting_input_since TEXT,
      transcript_path TEXT,
      first_prompt TEXT,
      custom_title TEXT,
      ai_title TEXT,
      last_scanned_line INTEGER DEFAULT 0,
      source TEXT
    )
  `);
  db.prepare(
    `
    INSERT INTO sessions (id, name, status, cwd, model, started_at, ended_at, metadata, updated_at, awaiting_input_since, transcript_path, first_prompt, custom_title, ai_title, last_scanned_line, source)
    SELECT id, name, status, cwd, model, started_at, ended_at, metadata, updated_at, awaiting_input_since, transcript_path, first_prompt, custom_title, ai_title, last_scanned_line, NULL
    FROM sessions_old
  `
  ).run();
  db.prepare("DROP TABLE sessions_old").run();

  // Fix foreign key references in other tables that pointed to the old sessions table
  // agents table
  db.prepare("ALTER TABLE agents RENAME TO agents_old").run();
  db.exec(`
    CREATE TABLE agents (
      id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL,
      name TEXT NOT NULL,
      type TEXT NOT NULL DEFAULT 'main' CHECK(type IN ('main','subagent')),
      subagent_type TEXT,
      status TEXT NOT NULL DEFAULT 'waiting' CHECK(status IN ('working','waiting','completed','error')),
      task TEXT,
      current_tool TEXT,
      started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
      ended_at TEXT,
      parent_agent_id TEXT,
      metadata TEXT,
      updated_at TEXT NOT NULL DEFAULT '',
      awaiting_input_since TEXT,
      FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
      FOREIGN KEY (parent_agent_id) REFERENCES agents(id) ON DELETE SET NULL
    )
  `);
  db.prepare("INSERT INTO agents SELECT * FROM agents_old").run();
  db.prepare("DROP TABLE agents_old").run();

  // events table
  db.prepare("ALTER TABLE events RENAME TO events_old").run();
  db.exec(`
    CREATE TABLE events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL,
      agent_id TEXT,
      event_type TEXT NOT NULL,
      tool_name TEXT,
      summary TEXT,
      data TEXT,
      created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
      FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
      FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE SET NULL
    )
  `);
  db.prepare("INSERT INTO events SELECT * FROM events_old").run();
  db.prepare("DROP TABLE events_old").run();

  // token_usage table
  db.prepare("ALTER TABLE token_usage RENAME TO token_usage_old").run();
  db.exec(`
    CREATE TABLE token_usage (
      session_id TEXT NOT NULL,
      model TEXT NOT NULL DEFAULT 'unknown',
      input_tokens INTEGER NOT NULL DEFAULT 0,
      output_tokens INTEGER NOT NULL DEFAULT 0,
      cache_read_tokens INTEGER NOT NULL DEFAULT 0,
      cache_write_tokens INTEGER NOT NULL DEFAULT 0,
      baseline_input INTEGER NOT NULL DEFAULT 0,
      baseline_output INTEGER NOT NULL DEFAULT 0,
      baseline_cache_read INTEGER NOT NULL DEFAULT 0,
      baseline_cache_write INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (session_id, model),
      FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
    )
  `);
  db.prepare("INSERT INTO token_usage SELECT * FROM token_usage_old").run();
  db.prepare("DROP TABLE token_usage_old").run();

  db.pragma("foreign_keys = ON");
  // Recreate indexes
  db.exec(`
    CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
    CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);
    CREATE INDEX IF NOT EXISTS idx_sessions_status_updated ON sessions(status, updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_sessions_active_tp ON sessions(status, transcript_path) WHERE status='active' AND transcript_path IS NOT NULL;
  `);
}

// Migrate: null out legacy placeholder session names. The dashboard's "new
// session" button used to write name="新会话"; it now writes NULL so the
// detail-page header aligns with imported sessions (name=NULL). Idempotent.
db.prepare("UPDATE sessions SET name = NULL WHERE name = '新会话'").run();

// Partial index for the periodic active-session sweep — covers only the
// handful of rows the sweep actually reads.
db.exec(
  `CREATE INDEX IF NOT EXISTS idx_sessions_active_tp
   ON sessions(status, transcript_path)
   WHERE status='active' AND transcript_path IS NOT NULL`
);

// Migrate: replace legacy idle/connected agent statuses with waiting/working
// and update the CHECK constraint to the 4-status model.
// SQLite doesn't support ALTER CHECK, so we detect the old constraint and
// rebuild the table with rename-copy-drop when needed.
{
  const tableInfo = db
    .prepare("SELECT sql FROM sqlite_master WHERE type='table' AND name='agents'")
    .get();
  if (tableInfo && tableInfo.sql && tableInfo.sql.includes("'idle'")) {
    // Old constraint found — rebuild the table
    db.exec(`
      PRAGMA foreign_keys = OFF;
      BEGIN;
      -- Map old statuses to new ones in-place (still valid under old constraint isn't needed
      -- because we're about to drop the table — we do it in the INSERT below)
      CREATE TABLE agents_new (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        name TEXT NOT NULL,
        type TEXT NOT NULL DEFAULT 'main' CHECK(type IN ('main','subagent')),
        subagent_type TEXT,
        status TEXT NOT NULL DEFAULT 'waiting' CHECK(status IN ('working','waiting','completed','error')),
        task TEXT,
        current_tool TEXT,
        started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        ended_at TEXT,
        parent_agent_id TEXT,
        metadata TEXT,
        updated_at TEXT NOT NULL DEFAULT '',
        awaiting_input_since TEXT,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
        FOREIGN KEY (parent_agent_id) REFERENCES agents(id) ON DELETE SET NULL
      );
      INSERT INTO agents_new SELECT
        id, session_id, name, type, subagent_type,
        CASE status
          WHEN 'idle' THEN 'waiting'
          WHEN 'connected' THEN 'working'
          ELSE status
        END,
        task, current_tool, started_at, ended_at, parent_agent_id, metadata,
        updated_at, awaiting_input_since
      FROM agents;
      DROP TABLE agents;
      ALTER TABLE agents_new RENAME TO agents;
      COMMIT;
      PRAGMA foreign_keys = ON;
    `);
    // Recreate indexes that were on the old table
    db.exec(`
      CREATE INDEX IF NOT EXISTS idx_agents_session ON agents(session_id);
      CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
      CREATE INDEX IF NOT EXISTS idx_agents_parent ON agents(parent_agent_id);
    `);
  }
}

// Migrate: add compaction baseline columns to token_usage.
// When conversation compaction rewrites the JSONL, pre-compaction token counts
// are lost from the transcript. Baselines preserve those counts so the effective
// total = current + baseline.
try {
  db.prepare("SELECT baseline_input FROM token_usage LIMIT 1").get();
} catch {
  db.prepare("ALTER TABLE token_usage ADD COLUMN baseline_input INTEGER NOT NULL DEFAULT 0").run();
  db.prepare("ALTER TABLE token_usage ADD COLUMN baseline_output INTEGER NOT NULL DEFAULT 0").run();
  db.prepare(
    "ALTER TABLE token_usage ADD COLUMN baseline_cache_read INTEGER NOT NULL DEFAULT 0"
  ).run();
  db.prepare(
    "ALTER TABLE token_usage ADD COLUMN baseline_cache_write INTEGER NOT NULL DEFAULT 0"
  ).run();
}

// Startup cleanup: mark stale active sessions as completed.
// Legacy sessions (created before SessionEnd hook) will never receive a SessionEnd event,
// so they stay "active" forever. Complete any active session whose last event is older than
// 1 hour — the CLI process is certainly gone by then.
db.prepare(
  `
  UPDATE sessions SET
    status = 'completed',
    ended_at = COALESCE(ended_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
  WHERE status = 'active'
    AND started_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-1 hour')
    AND NOT EXISTS (
      SELECT 1 FROM events e
      WHERE e.session_id = sessions.id
        AND e.created_at > strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-1 hour')
    )
`
).run();

// Startup cleanup: complete orphaned agents on finished sessions
db.prepare(
  `
  UPDATE agents SET
    status = 'completed',
    ended_at = COALESCE(ended_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
  WHERE status IN ('working', 'waiting')
    AND session_id IN (SELECT id FROM sessions WHERE status IN ('completed', 'error', 'abandoned'))
`
).run();

// Startup repair: normalize compaction agents whose started_at > ended_at.
// Earlier hook ingestion (pre-#156) stamped started_at = NOW (ingestion wall
// clock) and ended_at = transcript timestamp (in the past), producing
// impossible negative durations that corrupted workflow analytics. Compaction
// is instantaneous from the user's perspective, so the transcript timestamp
// (preserved in ended_at) is the canonical value — collapse started_at to it.
// Idempotent: only touches rows where the invariant is broken.
db.prepare(
  `
  UPDATE agents SET
    started_at = ended_at,
    updated_at = ended_at
  WHERE subagent_type = 'compaction'
    AND ended_at IS NOT NULL
    AND julianday(ended_at) < julianday(started_at)
`
).run();

const stmts = {
  getSession: db.prepare("SELECT * FROM sessions WHERE id = ?"),
  listSessions: db.prepare(
    // Exclude compaction agents from the count — they're metadata events, not real agents.
    // Compaction is an inline event in the main transcript, not a separate subagent transcript.
    `SELECT s.*, COUNT(CASE WHEN COALESCE(a.subagent_type, '') != 'compaction' THEN a.id END) as agent_count, s.updated_at as last_activity
     FROM sessions s LEFT JOIN agents a ON a.session_id = s.id
     GROUP BY s.id ORDER BY s.updated_at DESC LIMIT ? OFFSET ?`
  ),
  listSessionsByStatus: db.prepare(
    `SELECT s.*, COUNT(CASE WHEN COALESCE(a.subagent_type, '') != 'compaction' THEN a.id END) as agent_count, s.updated_at as last_activity
     FROM sessions s LEFT JOIN agents a ON a.session_id = s.id
     WHERE s.status = ? GROUP BY s.id ORDER BY s.updated_at DESC LIMIT ? OFFSET ?`
  ),
  insertSession: db.prepare(
    "INSERT INTO sessions (id, name, status, cwd, model, started_at, updated_at, metadata) VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), ?)"
  ),
  // One-time writer for sessions.first_prompt (the session-list title column).
  // The `WHERE first_prompt IS NULL` guard enforces that only the first write
  // ever succeeds — subsequent UserPromptSubmit hooks for the same session
  // are SQL no-ops. Also bumps updated_at so last_activity stays in sync.
  setSessionFirstPrompt: db.prepare(
    "UPDATE sessions SET first_prompt = ?, updated_at = ? WHERE id = ? AND first_prompt IS NULL"
  ),
  // Writer for sessions.custom_title and sessions.ai_title.
  // These are populated by scanning JSONL at SessionEnd. Unlike first_prompt,
  // these CAN be overwritten — /rename can be called multiple times, and we
  // want the latest value. Also updates last_scanned_line for incremental scanning.
  updateSessionTitles: db.prepare(
    "UPDATE sessions SET custom_title = COALESCE(?, custom_title), ai_title = COALESCE(?, ai_title), last_scanned_line = ?, updated_at = ? WHERE id = ?"
  ),
  updateSession: db.prepare(
    "UPDATE sessions SET name = COALESCE(?, name), status = COALESCE(?, status), ended_at = COALESCE(?, ended_at), metadata = COALESCE(?, metadata), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?"
  ),
  // Update agent_runtime_session_id for direct mapping between viewer and agent-runtime sessions.
  updateAgentRuntimeSessionId: db.prepare(
    "UPDATE sessions SET agent_runtime_session_id = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?"
  ),
  reactivateSession: db.prepare(
    "UPDATE sessions SET status = 'active', ended_at = NULL, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?"
  ),
  // Updates session.model only when the new value differs from what's stored,
  // so the broadcast/refresh path stays quiet across the common no-op case.
  // Used by the hook ingestor to keep the displayed model in sync after the
  // user invokes /model mid-session.
  updateSessionModel: db.prepare(
    "UPDATE sessions SET model = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ? AND COALESCE(model, '') != ?"
  ),
  // Updates session.name only when the new value differs from what's stored.
  // Used by the hook ingestor to keep the displayed session name in sync with
  // the transcript's title (set via /rename, `claude -n`, or the auto-generated
  // ai-title). No-op (zero changes) on the common unchanged case so the
  // broadcast path stays quiet.
  updateSessionName: db.prepare(
    "UPDATE sessions SET name = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ? AND COALESCE(name, '') != ?"
  ),
  // One-shot writer for sessions.transcript_path. The NULL/'' guard makes
  // every subsequent hook event for the same session a SQL no-op, so the
  // periodic compaction sweep can read transcript_path off the row instead
  // of scanning events.
  setSessionTranscriptPath: db.prepare(
    "UPDATE sessions SET transcript_path = ? WHERE id = ? AND (transcript_path IS NULL OR transcript_path = '')"
  ),
  // Overwrites sessions.transcript_path when the stored value turns out to be
  // unusable — the hook payload reported the path as the *Claude process* sees
  // it, which can be unreadable here (in a container the agent runtime's HOME
  // differs from COSIGHT_HOME). Unlike setSessionTranscriptPath this is
  // deliberately NOT one-shot: the `!= ?` guard only keeps repeated hook events
  // a no-op, so the periodic sweep ends up holding a path that actually exists.
  overwriteSessionTranscriptPath: db.prepare(
    "UPDATE sessions SET transcript_path = ? WHERE id = ? AND COALESCE(transcript_path, '') != ?"
  ),
  // One-shot writer for sessions.source. Old rows (created before dual-source
  // support) get their source filled by the first hook event after upgrade.
  setSessionSource: db.prepare(
    "UPDATE sessions SET source = ? WHERE id = ? AND (source IS NULL OR source = '')"
  ),

  getAgent: db.prepare("SELECT * FROM agents WHERE id = ?"),
  listAgents: db.prepare("SELECT * FROM agents ORDER BY started_at DESC LIMIT ? OFFSET ?"),
  listAgentsBySession: db.prepare(
    "SELECT * FROM agents WHERE session_id = ? ORDER BY started_at DESC"
  ),
  // UI-facing agent list: excludes compaction entries. Compaction is a metadata
  // event (inline in the main transcript), not a real subagent with its own
  // transcript file. Including them in the count inflates stats and causes
  // "transcript not found" errors when the user clicks them.
  listAgentsBySessionForUI: db.prepare(
    "SELECT * FROM agents WHERE session_id = ? AND COALESCE(subagent_type, '') != 'compaction' ORDER BY started_at DESC"
  ),
  listAgentsByStatus: db.prepare(
    "SELECT * FROM agents WHERE status = ? ORDER BY started_at DESC LIMIT ? OFFSET ?"
  ),
  insertAgent: db.prepare(
    "INSERT INTO agents (id, session_id, name, type, subagent_type, status, task, started_at, updated_at, parent_agent_id, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), ?, ?)"
  ),
  updateAgent: db.prepare(
    "UPDATE agents SET name = COALESCE(?, name), status = COALESCE(?, status), task = COALESCE(?, task), current_tool = ?, ended_at = COALESCE(?, ended_at), metadata = COALESCE(?, metadata), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?"
  ),
  reactivateAgent: db.prepare(
    "UPDATE agents SET status = 'working', ended_at = NULL, current_tool = NULL, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?"
  ),
  // Awaiting-input state. Stamping awaiting_input_since marks the row as
  // "waiting" for user attention without touching the underlying status
  // enum (kept stable for legacy CHECK constraints and aggregations).
  // awaiting_reason records WHY ('notification' | 'stop' | 'session_start');
  // the actor-aware clear in routes/hooks.js reads it to decide whether a
  // subagent tool event may clear the flag.
  setSessionAwaitingInput: db.prepare(
    "UPDATE sessions SET awaiting_input_since = ?, awaiting_reason = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?"
  ),
  clearSessionAwaitingInput: db.prepare(
    "UPDATE sessions SET awaiting_input_since = NULL, awaiting_reason = NULL, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ? AND awaiting_input_since IS NOT NULL"
  ),
  setAgentAwaitingInput: db.prepare(
    "UPDATE agents SET awaiting_input_since = ?, awaiting_reason = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?"
  ),
  clearAgentAwaitingInput: db.prepare(
    "UPDATE agents SET awaiting_input_since = NULL, awaiting_reason = NULL, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ? AND awaiting_input_since IS NOT NULL"
  ),
  clearSessionAgentsAwaitingInput: db.prepare(
    "UPDATE agents SET awaiting_input_since = NULL, awaiting_reason = NULL, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE session_id = ? AND awaiting_input_since IS NOT NULL"
  ),
  // Find the deepest currently-working subagent in a session using a recursive CTE.
  // Used to infer which agent is spawning a new subagent when hook events don't
  // carry an explicit agent ID. Returns the most recently created deepest agent.
  findDeepestWorkingAgent: db.prepare(`
    WITH RECURSIVE agent_depth AS (
      SELECT id, parent_agent_id, 0 as depth
      FROM agents
      WHERE session_id = ? AND parent_agent_id IS NULL
      UNION ALL
      SELECT a.id, a.parent_agent_id, ad.depth + 1
      FROM agents a
      JOIN agent_depth ad ON a.parent_agent_id = ad.id
      WHERE a.session_id = ?
    )
    SELECT ad.id, ad.depth
    FROM agent_depth ad
    JOIN agents a ON a.id = ad.id
    WHERE a.status = 'working' AND a.type = 'subagent'
    ORDER BY ad.depth DESC, a.started_at DESC
    LIMIT 1
  `),

  touchSession: db.prepare(
    "UPDATE sessions SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?"
  ),
  findStaleSessions: db.prepare(
    `SELECT id FROM sessions
     WHERE status = 'active' AND id != ?
       AND updated_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-' || ? || ' minutes')`
  ),

  insertEvent: db.prepare(
    "INSERT INTO events (session_id, agent_id, event_type, tool_name, summary, data, created_at) VALUES (?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
  ),
  // Same as insertEvent but with an explicit created_at timestamp.
  // Used for events whose canonical time is NOT "now" — e.g. TurnDuration entries
  // parsed from the JSONL transcript, whose timestamp comes from the historical
  // system/turn_duration entry. Using 'now' would break the dedup query that
  // matches on created_at, causing duplicates on every transcript re-read.
  insertEventAt: db.prepare(
    "INSERT INTO events (session_id, agent_id, event_type, tool_name, summary, data, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
  ),
  listEvents: db.prepare("SELECT * FROM events ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"),
  listEventsBySession: db.prepare(
    "SELECT * FROM events WHERE session_id = ? ORDER BY created_at DESC, id DESC"
  ),
  countEvents: db.prepare("SELECT COUNT(*) as count FROM events"),
  countEventsSince: db.prepare("SELECT COUNT(*) as count FROM events WHERE created_at >= ?"),
  // Accepts tz modifier (e.g. '-420 minutes') to compute local midnight in UTC.
  // Pattern: shift now→local, truncate to day start, shift back→UTC.
  countEventsToday: db.prepare(
    "SELECT COUNT(*) as count FROM events WHERE created_at >= datetime('now', ?, 'start of day', ?)"
  ),

  stats: db.prepare(`
    SELECT
      (SELECT COUNT(*) FROM sessions) as total_sessions,
      (SELECT COUNT(*) FROM sessions WHERE status = 'active') as active_sessions,
      (SELECT COUNT(*) FROM agents WHERE status IN ('working', 'waiting')) as active_agents,
      (SELECT COUNT(*) FROM agents) as total_agents,
      (SELECT COUNT(*) FROM events) as total_events
  `),
  agentStatusCounts: db.prepare("SELECT status, COUNT(*) as count FROM agents GROUP BY status"),
  sessionStatusCounts: db.prepare("SELECT status, COUNT(*) as count FROM sessions GROUP BY status"),

  upsertTokenUsage: db.prepare(`
    INSERT INTO token_usage (session_id, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(session_id, model) DO UPDATE SET
      input_tokens = input_tokens + excluded.input_tokens,
      output_tokens = output_tokens + excluded.output_tokens,
      cache_read_tokens = cache_read_tokens + excluded.cache_read_tokens,
      cache_write_tokens = cache_write_tokens + excluded.cache_write_tokens
  `),
  replaceTokenUsage: db.prepare(`
    INSERT INTO token_usage (session_id, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
                             baseline_input, baseline_output, baseline_cache_read, baseline_cache_write)
    VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, 0)
    ON CONFLICT(session_id, model) DO UPDATE SET
      baseline_input = CASE WHEN excluded.input_tokens < input_tokens
        THEN baseline_input + input_tokens ELSE baseline_input END,
      baseline_output = CASE WHEN excluded.output_tokens < output_tokens
        THEN baseline_output + output_tokens ELSE baseline_output END,
      baseline_cache_read = CASE WHEN excluded.cache_read_tokens < cache_read_tokens
        THEN baseline_cache_read + cache_read_tokens ELSE baseline_cache_read END,
      baseline_cache_write = CASE WHEN excluded.cache_write_tokens < cache_write_tokens
        THEN baseline_cache_write + cache_write_tokens ELSE baseline_cache_write END,
      input_tokens = excluded.input_tokens,
      output_tokens = excluded.output_tokens,
      cache_read_tokens = excluded.cache_read_tokens,
      cache_write_tokens = excluded.cache_write_tokens
  `),
  getTokenTotals: db.prepare(`
    SELECT
      COALESCE(SUM(input_tokens + baseline_input), 0) as total_input,
      COALESCE(SUM(output_tokens + baseline_output), 0) as total_output,
      COALESCE(SUM(cache_read_tokens + baseline_cache_read), 0) as total_cache_read,
      COALESCE(SUM(cache_write_tokens + baseline_cache_write), 0) as total_cache_write
    FROM token_usage
  `),
  getTokensBySession: db.prepare(
    `SELECT model,
      input_tokens + baseline_input as input_tokens,
      output_tokens + baseline_output as output_tokens,
      cache_read_tokens + baseline_cache_read as cache_read_tokens,
      cache_write_tokens + baseline_cache_write as cache_write_tokens
    FROM token_usage WHERE session_id = ?`
  ),

  // Model pricing
  listPricing: db.prepare("SELECT * FROM model_pricing ORDER BY display_name ASC"),
  getPricing: db.prepare("SELECT * FROM model_pricing WHERE model_pattern = ?"),
  upsertPricing: db.prepare(`
    INSERT INTO model_pricing (model_pattern, display_name, input_per_mtok, output_per_mtok, cache_read_per_mtok, cache_write_per_mtok, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    ON CONFLICT(model_pattern) DO UPDATE SET
      display_name = excluded.display_name,
      input_per_mtok = excluded.input_per_mtok,
      output_per_mtok = excluded.output_per_mtok,
      cache_read_per_mtok = excluded.cache_read_per_mtok,
      cache_write_per_mtok = excluded.cache_write_per_mtok,
      updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
  `),
  deletePricing: db.prepare("DELETE FROM model_pricing WHERE model_pattern = ?"),
  matchPricing: db.prepare(
    "SELECT * FROM model_pricing WHERE ? LIKE REPLACE(model_pattern, '%', '%') LIMIT 1"
  ),
  toolUsageCounts: db.prepare(`
    SELECT tool_name, COUNT(*) as count
    FROM events
    WHERE tool_name IS NOT NULL
    GROUP BY tool_name
    ORDER BY count DESC
    LIMIT 20
  `),
  // Accept a timezone modifier (e.g. '-420 minutes') so GROUP BY uses local dates
  dailyEventCounts: db.prepare(`
    SELECT DATE(created_at, ?) as date, COUNT(*) as count
    FROM events
    WHERE created_at >= DATE('now', '-365 days')
    GROUP BY 1
    ORDER BY date ASC
  `),
  dailySessionCounts: db.prepare(`
    SELECT DATE(started_at, ?) as date, COUNT(*) as count
    FROM sessions
    WHERE started_at >= DATE('now', '-365 days')
    GROUP BY 1
    ORDER BY date ASC
  `),
  agentTypeDistribution: db.prepare(`
    SELECT subagent_type, COUNT(*) as count
    FROM agents
    WHERE type = 'subagent' AND subagent_type IS NOT NULL
    GROUP BY subagent_type
    ORDER BY count DESC
  `),
  totalSubagentCount: db.prepare("SELECT COUNT(*) as count FROM agents WHERE type = 'subagent'"),
  eventTypeCounts: db.prepare(`
    SELECT event_type, COUNT(*) as count
    FROM events
    GROUP BY event_type
    ORDER BY count DESC
  `),
  avgEventsPerSession: db.prepare(`
    SELECT ROUND(CAST(COUNT(*) AS REAL) / MAX(1, (SELECT COUNT(*) FROM sessions)), 1) as avg
    FROM events
  `),

  // Per-session aggregations powering the SessionOverview panel.
  sessionEventCount: db.prepare("SELECT COUNT(*) as count FROM events WHERE session_id = ?"),
  sessionEventTypeCounts: db.prepare(`
    SELECT event_type, COUNT(*) as count
    FROM events
    WHERE session_id = ?
    GROUP BY event_type
    ORDER BY count DESC
  `),
  sessionToolUsageCounts: db.prepare(`
    SELECT tool_name, COUNT(*) as count
    FROM events
    WHERE session_id = ? AND tool_name IS NOT NULL
    GROUP BY tool_name
    ORDER BY count DESC
    LIMIT 15
  `),
  // Errors are surfaced via a couple of conventions: event_type containing
  // "error" (case-insensitive) OR a summary prefixed with "Error" / "Failed".
  // We accept both so legacy and current hook conventions both count.
  sessionErrorCount: db.prepare(`
    SELECT COUNT(*) as count
    FROM events
    WHERE session_id = ?
      AND (
        LOWER(event_type) LIKE '%error%'
        OR LOWER(event_type) LIKE '%failed%'
        OR LOWER(summary) LIKE 'error%'
        OR LOWER(summary) LIKE 'failed%'
      )
  `),
  sessionEventTimeRange: db.prepare(`
    SELECT MIN(created_at) as first_at, MAX(created_at) as last_at
    FROM events
    WHERE session_id = ?
  `),
  sessionAgentTypeCounts: db.prepare(`
    SELECT
      COALESCE(subagent_type, 'unknown') as subagent_type,
      COUNT(*) as count
    FROM agents
    WHERE session_id = ? AND type = 'subagent'
    GROUP BY COALESCE(subagent_type, 'unknown')
    ORDER BY count DESC
  `),
  sessionAgentStatusCounts: db.prepare(`
    SELECT status, COUNT(*) as count
    FROM agents
    WHERE session_id = ?
    GROUP BY status
  `),
  sessionTokenTotals: db.prepare(`
    SELECT
      COALESCE(SUM(input_tokens + baseline_input), 0) as input_tokens, 
      COALESCE(SUM(output_tokens + baseline_output), 0) as output_tokens, 
      COALESCE(SUM(cache_read_tokens + baseline_cache_read), 0) as cache_read_tokens, 
      COALESCE(SUM(cache_write_tokens + baseline_cache_write), 0) as cache_write_tokens 
    FROM token_usage
    WHERE session_id = ?
  `),
};

module.exports = { db, stmts, DB_PATH, DEFAULT_PRICING };

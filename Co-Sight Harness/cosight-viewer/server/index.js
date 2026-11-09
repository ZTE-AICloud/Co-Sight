// SPDX-License-Identifier: Apache-2.0
/**
 * @file Sets up the Express server with API routes and WebSocket, serves the React client in production, and includes periodic maintenance tasks like session cleanup and compaction scanning.
 */

// API base path - configurable via API_BASE_PATH env var, see server/lib/hook-config.js

if (!process.env.NODE_ENV) process.env.NODE_ENV = "production";

// ── Increase libuv thread pool from default 4 to 32.
//    The dashboard does many concurrent file I/O operations (transcript scans,
//    JSONL reads, meta.json checks). With only 4 threads, concurrent ops queue
//    up and cause 2-3s stalls on first access. 32 threads covers all realistic
//    concurrency without needing a warmup phase.
//    NOTE: this env var must be set BEFORE the first require('fs') call —
//    libuv reads UV_THREADPOOL_SIZE at startup and never checks it again.
if (!process.env.UV_THREADPOOL_SIZE) process.env.UV_THREADPOOL_SIZE = "32";

// Load .env file (simple key=value, no external dependency needed)
(function loadDotEnv() {
  const fs = require("fs");
  const os = require("os");
  const envPath = require("path").resolve(__dirname, "..", ".env");
  if (!fs.existsSync(envPath)) return;
  for (const line of fs.readFileSync(envPath, "utf8").split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eqIdx = trimmed.indexOf("=");
    if (eqIdx === -1) continue;
    const key = trimmed.slice(0, eqIdx).trim();
    let val = trimmed.slice(eqIdx + 1).trim();
    // Strip surrounding quotes (single or double)
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1);
    }
    if (!process.env[key]) {
      process.env[key] = val.replace(/^~(?=\/)/, os.homedir());
    }
  }
})();

// ── Data directory migration: 将旧位置(~/.cosight/)的数据文件迁移到新的数据目录 ──
(function migrateDataDir() {
  const fs = require("fs");
  const path = require("path");

  const newDir = process.env.DASHBOARD_DATA_DIR;
  if (!newDir) return;

  const oldDir = path.dirname(newDir);
  const oldDb = path.join(oldDir, "dashboard.db");
  const newDb = path.join(newDir, "dashboard.db");

  // 迁移条件：旧 DB 存在，且新位置没有 DB（或为空文件——刚被 db.js 创建）
  if (!fs.existsSync(oldDb)) return;
  if (fs.existsSync(newDb)) {
    try {
      if (fs.statSync(newDb).size > 0) return; // 新 DB 已有数据，跳过
      fs.unlinkSync(newDb); // 空文件，删掉以便迁移
    } catch {
      return;
    }
  }

  fs.mkdirSync(newDir, { recursive: true });

  const items = [
    "dashboard.db",
    "dashboard.db-shm",
    "dashboard.db-wal",
    ".legacy-import.done",
    "vapid-keys.json",
    "transcripts",
  ];

  let count = 0;
  for (const name of items) {
    const src = path.join(oldDir, name);
    const dest = path.join(newDir, name);
    if (fs.existsSync(src)) {
      try {
        fs.renameSync(src, dest);
        console.log(`  ✓ 已迁移 ${name} → ${path.basename(newDir)}/`);
        count++;
      } catch (err) {
        console.error(`  ✗ 迁移失败 ${name}: ${err.message}`);
      }
    }
  }
  if (count > 0) console.log(`[migrate] 已将 ${count} 个文件迁移到 ${newDir}`);
})();

const express = require("express");
const cors = require("cors");
const path = require("path");
const fs = require("fs");
const os = require("os");
const http = require("http");
const swaggerUi = require("swagger-ui-express");
const { initWebSocket } = require("./websocket");
const { createOpenApiSpec } = require("./openapi");
const { writeServerInfo, removeServerInfo } = require("./lib/server-info");
const {
  getViewerDataDir,
  getTranscriptSnapshotDir,
  getProjectsDirs,
  getImportedSessionsDir,
  inferSourceFromPath,
} = require("./lib/claude-home");
const { extractSessionMetadata } = require("./lib/session-metadata");
const { getApiBasePath } = require("./lib/hook-config");
const { createProxy } = require("./lib/upstream-proxy");
const { attachWsProxy } = require("./lib/ws-proxy");
const { readSettings, readSettingsState } = require("./lib/settings-store");
const { updateAutoCleanupState } = require("./lib/state-store");

const sessionsRouter = require("./routes/sessions");
const agentsRouter = require("./routes/agents");
const eventsRouter = require("./routes/events");
const statsRouter = require("./routes/stats");
const hooksRouter = require("./routes/hooks");
const pricingRouter = require("./routes/pricing");
const pushRouter = require("./routes/push");
const updatesRouter = require("./routes/updates");
const runRouter = require("./routes/run");
const workspacesRouter = require("./routes/workspaces");
const settingsRouter = require("./routes/settings");
const sessionFilesRouter = require("./routes/session-files");
const fsRouter = require("./routes/fs");

function createApp() {
  const app = express();
  const BASE_PATH = getApiBasePath();
  const openApiSpec = createOpenApiSpec();

  app.use(cors());

  // 同源 REST 反代：viewer 以 iframe 从 :4830 访问框架 :4300 与 smart-factory :4100。
  // 代理后浏览器只发同源请求（无 CORS），上游固定走回环，不再依赖前端写死地址。
  // 必须放在 express.json 之前：要保持原始请求体可流式转发。
  app.use(
    "/framework-api",
    createProxy({
      target: "http://127.0.0.1:4300",
      rewritePath: (p) => `/api${p.slice("/framework-api".length)}`,
    }),
  );
  app.use(
    "/api/smart-factory/v1",
    createProxy({
      target: "http://127.0.0.1:4100",
    }),
  );

  app.use(express.json({ limit: "1mb" }));

  // ───── [PERF-DIAG] 请求级埋点:测量排队时长 & handler 耗时 ─────
  let perf;
  try {
    perf = require("./lib/perf-trace");
  } catch {
    perf = null;
  }
  if (perf) {
    // 1) 进入中间件即打戳 —— 此刻到 handler 开始的差值 = 在 Express 队列里的等待时间
    app.use((req, res, next) => {
      req.__perfEnterNs = perf.nowNs();
      req.__perfEnterWall = Date.now();
      // 2) 响应结束时算总耗时(包含排队 + 处理)
      res.on("finish", () => {
        try {
          const totalMs = perf.msBetween(req.__perfEnterNs, perf.nowNs());
          const handlerMs = req.__perfHandlerMs || 0;
          const queueMs = totalMs - handlerMs;
          const slow = totalMs > 500;
          const method = req.method;
          const url = req.originalUrl || req.url;
          if (slow || url.includes("/run/") || url.includes("/tasks")) {
            perf.writeDiag(
              `[REQ] ${method} ${url} → ${res.statusCode}  total=${totalMs.toFixed(1)}ms ` +
                `queue≈${queueMs.toFixed(1)}ms handler≈${handlerMs.toFixed(1)}ms`,
            );
          }
        } catch {
          /* ignore */
        }
      });
      next();
    });
  }
  // ───── [PERF-DIAG] end ─────

  app.use(`${BASE_PATH}/sessions`, sessionsRouter);
  app.use(`${BASE_PATH}/agents`, agentsRouter);
  app.use(`${BASE_PATH}/events`, eventsRouter);
  app.use(`${BASE_PATH}/stats`, statsRouter);
  app.use(`${BASE_PATH}/hooks`, hooksRouter);
  app.use(`${BASE_PATH}/pricing`, pricingRouter);
  app.use(`${BASE_PATH}/push`, pushRouter);
  app.use(`${BASE_PATH}/updates`, updatesRouter);
  app.use(`${BASE_PATH}/run`, runRouter);
  app.use(`${BASE_PATH}/workspaces`, workspacesRouter);
  app.use(`${BASE_PATH}/settings`, settingsRouter);
  app.use(`${BASE_PATH}/session-files`, sessionFilesRouter);
  app.use(`${BASE_PATH}/fs`, fsRouter);

  app.get(`${BASE_PATH}/openapi.json`, (_req, res) => {
    res.json(openApiSpec);
  });
  app.use(
    `${BASE_PATH}/docs`,
    swaggerUi.serve,
    swaggerUi.setup(openApiSpec, {
      customSiteTitle: "Co-Sight Viewer API Docs",
    }),
  );

  app.get(`${BASE_PATH}/health`, (_req, res) => {
    res.json({ status: "ok", timestamp: new Date().toISOString() });
  });

  // ── 前端静态文件服务（生产环境）──
  const isProduction = process.env.NODE_ENV === "production";
  if (isProduction) {
    const clientDist = path.join(__dirname, "..", "client", "dist");
    // 前端挂载在根路径 /（API 也在根路径，靠 HashRouter 避免冲突）
    //
    // HashRouter 确保浏览器不会向服务器发送 hash 路由（如 #/sessions），
    // 所以不需要 catch-all 回退，只需提供 index.html 和静态资源。
    //
    // Cache policy designed to survive client rebuilds without forcing a hard
    // refresh:
    //   - Hashed bundles under /assets/ never change for a given URL, so cache
    //     them aggressively (immutable).
    //   - index.html, /sw.js, and /manifest.json *are* the cache-bust signal,
    //     so they must revalidate every load — without this the browser's
    //     heuristic cache happily serves a stale index.html that references
    //     asset hashes that no longer exist on disk.
    //
    // 拦截 index.html 请求，注入运行时配置（零延迟，避免导航闪烁）：
    //   - window.__API_BASE__ — API 基础路径
    const staticMountPath = "/";
    const injectRuntimeConfig = (req, res, next) => {
      const reqPath = req.path.replace(/\/+$/, "") || "/";
      if (reqPath !== "/" && reqPath !== "/index.html") return next();

      const indexPath = path.join(clientDist, "index.html");
      // 注入绝对 URL（含协议和主机）
      const apiBase = `${req.protocol}://${req.get("host")}${BASE_PATH}`;
      fs.readFile(indexPath, "utf8", (err, html) => {
        if (err) return next();
        // 注入到 <head> 最开始，确保在任何其他脚本之前执行
        const injected = html.replace(
          "<head>",
          `<head><script>window.__API_BASE__="${apiBase}";</script>`,
        );
        res.type("text/html").send(injected);
      });
    };
    app.use(staticMountPath, injectRuntimeConfig);

    const staticCacheHandler = (res, filePath) => {
      if (filePath.includes(`${path.sep}assets${path.sep}`)) {
        res.setHeader("Cache-Control", "public, max-age=31536000, immutable");
        return;
      }
      const base = path.basename(filePath);
      if (base === "index.html" || base === "sw.js" || base === "manifest.json") {
        res.setHeader("Cache-Control", "no-cache, must-revalidate");
        return;
      }
      res.setHeader("Cache-Control", "public, max-age=300, must-revalidate");
    };
    app.use(
      staticMountPath,
      express.static(clientDist, {
        etag: true,
        lastModified: true,
        setHeaders: staticCacheHandler,
      }),
    );
  }

  return app;
}

function startServer(app, port) {
  const server = http.createServer(app);
  initWebSocket(server);

  // 同源 WS 反代：对话 WebSocket 由浏览器连 viewer（:4830），服务端转发到本机
  // smart-factory（:4100）。与上面的 viewer 自身 /ws 按路径精确分工，互不影响。
  attachWsProxy(server, {
    path: "/api/smart-factory/v1/ws",
    target: "ws://127.0.0.1:4100",
  });

  const isProduction = process.env.NODE_ENV === "production";
  return new Promise((resolve) => {
    server.listen(port, () => {
      // Publish the live port so the Claude Code hook handler can find this server.
      writeServerInfo(port);
      const mode = isProduction ? "production" : "development";
      console.log(`Co-Sight Viewer server running on http://localhost:${port} (${mode})`);
      if (!isProduction) {
        console.log(`Client dev server expected at http://localhost:5173`);
      }
      resolve(server);
    });
  });
}

/**
 * One-time bootstrap import of legacy Claude Code sessions from `~/.claude/`.
 *
 * Runs at most once per data directory, tracked by a `.legacy-import.done`
 * marker file written next to the database. A marker — rather than an "is the
 * DB empty?" check — ensures the import runs even if the DB has data from
 * other sources. The import itself is idempotent (per-session dedup), so
 * running it against a DB that already holds some sessions simply adds the
 * missing ones.
 *
 * Fire-and-forget — the server does not await it.
 */
function autoImportLegacySessions() {
  const { log: fileLog } = require("./watch/logger");
  function log(tag, msg) {
    try {
      fileLog("startup", `[${tag}] ${msg}`);
    } catch {}
  }
  log("START", `autoImportLegacySessions called, COSIGHT_HOME=${process.env.COSIGHT_HOME}`);
  try {
    const fs = require("fs");
    const dbModule = require("./db");
    const markerPath = path.join(path.dirname(dbModule.DB_PATH), ".legacy-import.done");
    log(
      "MARKER",
      `markerPath=${markerPath}, exists=${fs.existsSync(markerPath)}, DB_PATH=${dbModule.DB_PATH}`,
    );
    if (fs.existsSync(markerPath)) {
      log("SKIP", "marker exists, skipping import");
      return;
    }
    log("IMPORT", "no marker found, starting import");

    const { importAllSessions } = require("../scripts/import-history");
    log("IMPORT", "calling importAllSessions...");
    importAllSessions(dbModule)
      .then(({ imported, errors }) => {
        log("IMPORT", `importAllSessions done: imported=${imported}, errors=${errors}`);
        if (imported > 0) console.log(`Imported ${imported} legacy sessions from ~/.claude/`);
        if (errors > 0) console.log(`${errors} session files had errors during import`);
      })
      .then(() => {
        log("MARKER", "writing marker file...");
        try {
          fs.writeFileSync(markerPath, `${new Date().toISOString()}\n`);
          log("MARKER", "marker written");
        } catch (e) {
          log("MARKER", `marker write failed: ${e.message}`);
        }
      })
      .catch((err) => {
        log("ERROR", `import failed: ${err.message || err}`);
      });
  } catch (err) {
    log("ERROR", `autoImportLegacySessions caught: ${err.message}`);
    console.warn("legacy session auto-import failed:", err.message);
  }
}

/**
 * Sync new sessions to database on every startup.
 * Scans all JSONL files and imports only sessions that don't exist in database yet.
 * This ensures sessions created while viewer was off are still visible.
 * Uses async file operations to avoid blocking the event loop.
 */
async function syncNewSessionsToDatabase() {
  const { log: fileLog } = require("./watch/logger");
  const fsp = require("fs").promises;
  function log(tag, msg) {
    try {
      fileLog("sync-sessions", `[${tag}] ${msg}`);
    } catch {}
  }

  log("START", "Scanning for new sessions to sync...");

  try {
    const { db, stmts } = require("./db");

    // Scan every CLI source's projects directory plus the viewer's imported store.
    const dirsToScan = [
      ...getProjectsDirs().map((projectsDir, index) => ({
        path: projectsDir,
        name: `source-${index + 1}`,
      })),
      { path: getImportedSessionsDir(), name: "imported" },
    ];

    const allSessionIds = new Set();
    const sessionToPath = new Map();

    for (const { path: baseDir, name } of dirsToScan) {
      // Check if directory exists (async version)
      try {
        await fsp.access(baseDir);
      } catch {
        log("SKIP", `${name} directory does not exist: ${baseDir}`);
        continue;
      }

      // Read directory (async version)
      let dirs;
      try {
        dirs = await fsp.readdir(baseDir, { withFileTypes: true });
      } catch (err) {
        log("ERROR", `Failed to read ${name} directory: ${err.message}`);
        continue;
      }

      for (const dir of dirs) {
        if (!dir.isDirectory()) continue;

        const dirPath = path.join(baseDir, dir.name);
        try {
          // Read files in subdirectory (async version)
          const files = await fsp.readdir(dirPath);
          for (const file of files) {
            if (!file.endsWith(".jsonl")) continue;
            const sessionId = file.replace(".jsonl", "");
            allSessionIds.add(sessionId);
            sessionToPath.set(sessionId, path.join(dirPath, file));
          }
        } catch (err) {
          log("ERROR", `Failed to read ${name} directory ${dir.name}: ${err.message}`);
        }
      }
    }

    log("SCAN", `Found ${allSessionIds.size} JSONL files across all directories`);

    // Get all existing session IDs from database (batch query for performance)
    const existingRows = db.prepare("SELECT id FROM sessions").all();
    const existingIds = new Set(existingRows.map((row) => row.id));

    log("DB", `Database has ${existingIds.size} existing sessions`);

    // Find new sessions (not in database)
    const newIds = Array.from(allSessionIds).filter((id) => !existingIds.has(id));

    if (newIds.length === 0) {
      log("DONE", "No new sessions to import");
      return;
    }

    log("IMPORT", `Found ${newIds.length} new sessions to import`);

    // Import new sessions
    let imported = 0;
    let errors = 0;

    for (const sessionId of newIds) {
      const jsonlPath = sessionToPath.get(sessionId);
      try {
        // Parse metadata from JSONL — shared with the ZIP importer so that both
        // tolerate any transcript header shape (see lib/session-metadata.js).
        const meta = await extractSessionMetadata(jsonlPath, { sessionId });

        // Determine status based on path
        const status = jsonlPath.includes("imported-sessions") ? "imported" : "completed";

        // Insert to database
        const insertSession = db.prepare(`
          INSERT OR IGNORE INTO sessions (id, name, status, cwd, model, started_at, updated_at, first_prompt, transcript_path, source)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        `);

        const result = insertSession.run(
          sessionId,
          meta.name,
          status,
          meta.cwd,
          meta.model,
          meta.started_at,
          new Date().toISOString(),
          meta.first_prompt,
          jsonlPath,
          inferSourceFromPath(jsonlPath),
        );

        if (result.changes > 0) {
          // Also insert main agent record
          const insertAgent = db.prepare(`
            INSERT OR IGNORE INTO agents (id, session_id, name, type, status, started_at, ended_at)
            VALUES (?, ?, ?, 'main', 'completed', ?, ?)
          `);
          insertAgent.run(
            `agent-${sessionId}-main`,
            sessionId,
            "Main Agent",
            meta.started_at,
            meta.started_at,
          );
          imported++;
        }
      } catch (err) {
        log("ERROR", `Failed to import ${sessionId}: ${err.message}`);
        errors++;
      }
    }

    log("DONE", `Imported ${imported} new sessions, ${errors} errors`);
    if (imported > 0) {
      console.log(`[startup] Synced ${imported} new sessions to database`);
    }
  } catch (err) {
    log("ERROR", `syncNewSessionsToDatabase failed: ${err.message}`);
    console.error("[sync-sessions] Failed:", err.message);
  }
}

/**
 * Start the background services the dashboard relies on once the HTTP server
 * is listening: a one-time legacy-session import, the upstream update
 * scheduler, and a one-time reconciliation of orphaned run rows.
 */
function startBackgroundServices() {
  const { log: fileLog } = require("./watch/logger");
  try {
    fileLog("startup", "startBackgroundServices called");
  } catch {}

  // ── Pre-warm libuv thread pool: the first fs.promises.open/readFile calls
  //    can take 2-3s due to thread pool initialization (UV_THREADPOOL_SIZE
  //    defaults to 4; concurrent file opens need the pool to grow). By doing
  //    several concurrent file operations at startup, we ensure the pool is
  //    already grown before the first real request arrives.
  (async () => {
    try {
      const path = require("path");
      const tmpDir = require("os").tmpdir();
      const warmupFiles = Array.from({ length: 8 }, (_, i) =>
        path.join(tmpDir, `cosight-warmup-${i}`),
      );
      await Promise.all(
        warmupFiles.map(async (f) => {
          await require("fs").promises.writeFile(f, "warmup");
          const fh = await require("fs").promises.open(f, "r");
          await fh.read(Buffer.alloc(64), 0, 64, 0);
          await fh.close();
          await require("fs").promises.unlink(f);
        }),
      );
      try {
        fileLog("startup", "libuv thread pool warmed");
      } catch {}
    } catch (e) {
      try {
        fileLog("startup", `warmup failed: ${e.message}`);
      } catch {}
    }
  })();

  // One-time legacy-session backfill (a no-op once its marker file exists).
  autoImportLegacySessions();

  // Sync new sessions to database (runs every startup to catch sessions created while viewer was off)
  syncNewSessionsToDatabase().catch((err) => {
    console.error("[startup] syncNewSessionsToDatabase failed:", err.message);
  });

  const { startUpdateScheduler } = require("./update-scheduler");
  const { broadcast } = require("./websocket");
  startUpdateScheduler({ broadcast });
  try {
    fileLog("startup", "startBackgroundServices done");
  } catch {}
}

if (require.main === module) {
  const PORT = Number(process.env.PORT || process.env.DASHBOARD_PORT) || 4830;
  const { log: fileLog } = require("./watch/logger");
  try {
    fileLog(
      "startup",
      `=== Server starting, PORT=${PORT}, PID=${process.pid}, COSIGHT_HOME=${process.env.COSIGHT_HOME} ===`,
    );
  } catch {}

  // ─── [DIAG] Server启动日志（已合并到 unified-logger） ───

  const app = createApp();
  let httpServer = null;

  startServer(app, PORT).then((server) => {
    httpServer = server;
    try {
      fileLog("startup", `HTTP server listening on port ${PORT}`);
    } catch {}

    // 双源观测：不再需要模式选择，启动即初始化数据库与后台服务。
    // Claude / Cosight 两个 CLI 的 hook 都会写进同一个库。
    startBackgroundServices();

    // ───── [PERF-DIAG] 启动事件循环延迟监控 ─────
    try {
      const perf = require("./lib/perf-trace");
      perf.writeDiag(
        `[BOOT] server PID=${process.pid} PORT=${PORT} dataDir=${getViewerDataDir()}`,
      );
      perf.startEventLoopMonitor();
      perf.startMemoryHeartbeat();
    } catch (e) {
      console.error("[perf-trace] start failed:", e.message);
    }
    // ───── [PERF-DIAG] end ─────

    // Watch daemon 已移除 - 会话监控通过 Hook 机制实现，不需要文件监控守护进程
  });

  // Graceful shutdown — close connections and DB cleanly
  let shutdownInProgress = false;
  const shutdown = (signal) => {
    if (shutdownInProgress) {
      console.log(`\n${signal} received again — forcing immediate exit.`);
      process.exit(1);
    }
    shutdownInProgress = true;
    console.log(`\n${signal} received — shutting down gracefully… (hit Ctrl+C again to force)`);
    if (httpServer) {
      httpServer.close(() => {
        console.log("HTTP server closed.");
      });
    }
    try {
      require("./db").db.close();
    } catch {
      /* already closed */
    }
    // Drop the port discovery file so a later run on a different port is not
    // shadowed by a stale entry. (A crash skips this — the PID-liveness check
    // in resolveDashboardPort() is the backstop for that case.)
    removeServerInfo();
    // Give in-flight work 5s to finish, then force exit
    setTimeout(() => process.exit(0), 5000).unref();
  };
  process.on("SIGTERM", () => shutdown("SIGTERM"));
  process.on("SIGINT", () => shutdown("SIGINT"));

  // Auto-install hooks into every detected CLI source on every startup.
  // Idempotent: replaces only our own entries, never the user's other hooks.
  try {
    const { installHooks } = require("../scripts/install-hooks");
    installHooks(true);
    console.log("CLI hooks auto-configured (claude / cosight).");
  } catch {
    // Non-fatal — user can run npm run install-hooks manually
  }

  // Periodic maintenance sweep:
  // 1. Mark abandoned sessions that slipped through event-based detection
  // 2. Scan active sessions' JSONL files for new compaction entries
  //    (/compact fires no hooks, so compaction agents only appear on next hook event
  //    without this scanner)
  //
  // Stale threshold: 用户在 settings.json 里显式配置过 autoCleanup.abandonHours 时
  // 以它为准（小时 → 分钟）；否则回退 DASHBOARD_STALE_MINUTES，再回退 180（3 小时）。
  // 每次扫描都重新读，改配置无需重启。
  function getStaleMinutes() {
    try {
      const { settings, hasAutoCleanup } = readSettingsState();
      const hours = settings.autoCleanup.abandonHours;
      if (hasAutoCleanup && hours > 0) {
        return hours * 60; // Convert hours to minutes
      }
    } catch {
      // Ignore config read errors, fall through to env var
    }
    // Fall back to environment variable
    const raw = parseInt(process.env.DASHBOARD_STALE_MINUTES, 10);
    return Number.isFinite(raw) && raw > 0 ? raw : 180;
  }

  // Sweep interval: 1/4 of the stale threshold, clamped to [60s, 5 min].
  // Frequent enough to catch real abandonments quickly, cheap enough that
  // we're not hammering SQLite for nothing.
  // Use default 180 minutes for interval calculation; actual threshold is dynamic.
  const SWEEP_INTERVAL_MS = Math.max(60_000, Math.min(300_000, (180 * 60_000) / 4));

  const cleanupDb = require("./db");
  const { broadcast } = require("./websocket");
  const { transcriptCache } = require("./routes/hooks");
  setInterval(() => {
    // 1. Stale session cleanup — batch agent updates to avoid N+1 queries
    const staleMinutes = getStaleMinutes();
    const stale = cleanupDb.stmts.findStaleSessions.all("__periodic__", staleMinutes);
    const now = new Date().toISOString();
    if (stale.length > 0) {
      const staleIds = stale.map((s) => s.id);
      const placeholders = staleIds.map(() => "?").join(",");

      // Batch update all non-terminal agents across all stale sessions
      cleanupDb.db
        .prepare(
          `UPDATE agents SET status = 'completed', ended_at = COALESCE(ended_at, ?), updated_at = ?
           WHERE session_id IN (${placeholders}) AND status NOT IN ('completed', 'error')`,
        )
        .run(now, now, ...staleIds);

      for (const s of stale) {
        cleanupDb.stmts.updateSession.run(null, "abandoned", now, null, s.id);
        broadcast("session_updated", cleanupDb.stmts.getSession.get(s.id));

        // Evict transcript cache for abandoned sessions to bound memory growth.
        // Reads transcript_path off the session row (populated by hooks
        // ensureSession + one-time db.js backfill) instead of scanning events.
        const tpRow = cleanupDb.db
          .prepare("SELECT transcript_path AS tp FROM sessions WHERE id = ?")
          .get(s.id);
        if (tpRow?.tp) transcriptCache.invalidate(tpRow.tp);
      }

      // Broadcast updated agents once per stale session (not per-agent)
      for (const s of stale) {
        const agents = cleanupDb.stmts.listAgentsBySession.all(s.id);
        for (const agent of agents) {
          if (agent.status === "completed") {
            broadcast("agent_updated", agent);
          }
        }
      }
    }
  }, SWEEP_INTERVAL_MS);

  // ─── Auto-cleanup timer: runs every 24 hours ───
  // 默认启用：没有配置文件时按 90 天保留策略执行；用户显式关闭后才跳过。
  const AUTO_CLEANUP_INTERVAL_MS = 24 * 60 * 60 * 1000;
  setInterval(() => {
    let config;
    try {
      // 默认启用：settings.json 不存在时 readSettings() 会给出默认值（90 天）。
      config = readSettings().autoCleanup;
    } catch {
      return;
    }

    if (!config.enabled || !config.purgeDays || config.purgeDays <= 0) return;

    const cleanupDb = require("./db");
    const cutoff = new Date(Date.now() - config.purgeDays * 86400 * 1000).toISOString();
    const toDelete = cleanupDb.db
      .prepare(
        "SELECT id FROM sessions WHERE status IN ('completed','error','abandoned') AND updated_at < ?",
      )
      .all(cutoff);

    const result = {
      purged_sessions: 0,
      purged_events: 0,
      purged_agents: 0,
      purged_runs: 0,
    };

    if (toDelete.length > 0) {
      const ids = toDelete.map((r) => r.id);
      const placeholders = ids.map(() => "?").join(",");

      result.purged_events = cleanupDb.db
        .prepare(`DELETE FROM events WHERE session_id IN (${placeholders})`)
        .run(...ids).changes;
      result.purged_agents = cleanupDb.db
        .prepare(`DELETE FROM agents WHERE session_id IN (${placeholders})`)
        .run(...ids).changes;
      cleanupDb.db
        .prepare(`DELETE FROM token_usage WHERE session_id IN (${placeholders})`)
        .run(...ids);
      cleanupDb.db.prepare(`DELETE FROM sessions WHERE id IN (${placeholders})`).run(...ids);
      result.purged_sessions = toDelete.length;

      // Clean up transcript files (JSONL backups) — same logic as manual cleanup
      try {
        const transcriptDir = getTranscriptSnapshotDir();
        let transcriptsDeleted = 0;
        for (const sessionId of ids) {
          // Delete main session transcript
          const transcriptPath = path.join(transcriptDir, `${sessionId}.jsonl`);
          try {
            if (fs.existsSync(transcriptPath)) {
              fs.unlinkSync(transcriptPath);
              transcriptsDeleted++;
            }
          } catch (err) {
            console.error(
              `[auto-cleanup] Failed to delete transcript ${sessionId}.jsonl: ${err.message}`,
            );
          }

          // Delete subagent transcripts directory
          const subagentDir = path.join(transcriptDir, sessionId, "subagents");
          try {
            if (fs.existsSync(subagentDir)) {
              fs.rmSync(subagentDir, { recursive: true, force: true });
            }
            // Also remove the session directory if it's empty
            const sessionDir = path.join(transcriptDir, sessionId);
            if (fs.existsSync(sessionDir)) {
              const contents = fs.readdirSync(sessionDir);
              if (contents.length === 0) {
                fs.rmdirSync(sessionDir);
              }
            }
          } catch (err) {
            console.error(
              `[auto-cleanup] Failed to delete subagent transcripts for ${sessionId}: ${err.message}`,
            );
          }
        }
        if (transcriptsDeleted > 0) {
          console.log(`[auto-cleanup] Deleted ${transcriptsDeleted} transcript files`);
        }
      } catch (err) {
        console.error(`[auto-cleanup] Failed to cleanup transcripts: ${err.message}`);
      }
    }

    // Save last run to state.json（运行状态与用户配置分开存放）
    try {
      updateAutoCleanupState({
        lastRun: {
          time: new Date().toISOString(),
          type: "auto",
          ...result,
        },
      });
    } catch {
      /* ignore */
    }

    console.log(
      `[auto-cleanup] 删除了 ${result.purged_sessions} 个会话` +
        `（${result.purged_events} 条事件, ${result.purged_agents} 个 agent）`,
    );
  }, AUTO_CLEANUP_INTERVAL_MS);

  // The one-time legacy-session import runs from startBackgroundServices().
}

module.exports = { createApp, startServer, startBackgroundServices };

// SPDX-License-Identifier: Apache-2.0
/**
 * @file run.js
 * @description 新建会话弹窗需要的工作目录建议。
 *
 * 历史上这里还负责直接 spawn `claude` 进程（start/message/kill），该链路已从
 * UI 下线；续聊与恢复会话统一走 smart-factory 的 WebSocket（`/chat`）。
 * 仅保留 `GET /run/cwds`，供新建会话选择 cwd。
 */

const { Router } = require("express");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const router = Router();

const ALLOWED_ORIGIN_HOSTS = new Set(["localhost", "127.0.0.1", "::1", "0.0.0.0"]);

/**
 * Loopback-Origin guard. Browser requests carry Origin; if it's not localhost,
 * we reject. Server/CLI requests (curl) typically don't carry Origin and pass.
 *
 * Referer is checked as a fallback for older browsers / fetch with credentials
 * disabled — the same loopback-host rule applies.
 */
function sameOriginGuard(req, res, next) {
  const checkHost = (raw) => {
    try {
      const u = new URL(raw);
      return ALLOWED_ORIGIN_HOSTS.has(u.hostname);
    } catch {
      return false;
    }
  };
  const origin = req.headers.origin;
  if (origin) {
    if (!checkHost(origin)) {
      return res.status(403).json({
        error: { code: "EBADORIGIN", message: "cross-origin requests are not allowed" },
      });
    }
    return next();
  }
  const referer = req.headers.referer;
  if (referer && !checkHost(referer)) {
    return res.status(403).json({
      error: { code: "EBADORIGIN", message: "cross-origin requests are not allowed" },
    });
  }
  return next();
}

router.use(sameOriginGuard);

function isExistingDir(p) {
  try {
    return fs.statSync(p).isDirectory();
  } catch {
    return false;
  }
}

/**
 * Suggest plausible working directories. Pulls from:
 *   - "dashboard": the dashboard server's cwd (always shown first)
 *   - "home": $HOME
 *   - "recent": distinct cwds Claude Code has been used in, sourced from the
 *     dashboard's own sessions table. Filtered to dirs that still exist.
 */
router.get("/cwds", (_req, res) => {
  const out = [];
  const seen = new Set();
  const push = (kind, p, label) => {
    if (!p) return;
    const abs = path.resolve(p);
    if (seen.has(abs)) return;
    if (!isExistingDir(abs)) return;
    seen.add(abs);
    out.push({ kind, path: abs, label: label || path.basename(abs) || abs });
  };

  push("dashboard", process.cwd(), "Dashboard server");
  push("home", os.homedir(), "Home");

  // Pull recent cwds from the sessions DB (best-effort; if the DB isn't
  // ready or has a different schema, just return what we have).
  try {
    const { db } = require("../db");
    const rows = db
      .prepare(
        `SELECT cwd, MAX(started_at) AS last_at FROM sessions
         WHERE cwd IS NOT NULL AND cwd <> ''
         GROUP BY cwd ORDER BY last_at DESC LIMIT 30`
      )
      .all();
    for (const row of rows) {
      push("recent", row.cwd, path.basename(row.cwd));
    }
  } catch {
    /* ignore — DB may not be ready in tests */
  }

  res.json({ items: out });
});

module.exports = router;

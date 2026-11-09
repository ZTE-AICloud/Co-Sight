// SPDX-License-Identifier: Apache-2.0
/**
 * @file workspaces.js
 * @description Workspaces API — proxies to smart-factory directories/list API.
 * Returns workspace objects (id, name, directory, defaultModelId, kind) + activeId.
 */

const express = require("express");
const router = express.Router();
const fs = require("fs");
const path = require("path");
const os = require("os");

const { createChildLogger } = require("../lib/unified-logger");

const workspacesLog = createChildLogger("workspaces");

/**
 * Read module token from file (每次现读，不缓存).
 * 令牌文件位置: $COSIGHT_HOME/.module-token
 *
 * NOTE: smart-factory API does not require authentication, but we keep this
 * function for potential future use or debugging.
 */
// function readModuleToken() { ... } // REMOVED: not needed

/**
 * GET /workspaces
 * Fetch workspaces from smart-factory directories/list API.
 * Returns: { items: [{ id, name, directory, defaultModelId, kind }], activeId: string | null }
 *
 * The "default" workspace (kind === "default") is always present and is
 * implicitly included in session filters on the frontend.
 */
router.get("/", async (req, res) => {
  const smartFactoryBase =
    process.env.SMART_FACTORY_BASE_URL || "http://127.0.0.1:4100";
  const apiUrl = `${smartFactoryBase}/api/smart-factory/v1/workspaces/directories/list`;

  try {
    // smart-factory API does not require authentication
    const response = await fetch(apiUrl, {
      method: "GET",
    });

    if (!response.ok) {
      workspacesLog.warn(`[workspaces] smart-factory API returned ${response.status}`);
      return res.json({ items: [], activeId: null });
    }

    const body = await response.json();
    // The smart-factory API returns `{ items, activeId }` directly (no
    // `{ success, data }` wrapper). Tolerate both shapes for robustness.
    const data = body && body.data ? body.data : body;
    if (!data || !Array.isArray(data.items)) {
      workspacesLog.warn("[workspaces] Unexpected response format");
      return res.json({ items: [], activeId: null });
    }

    // Return workspace objects with the fields the frontend needs,
    // including the new `kind` and `defaultModelId` fields.
    const items = data.items.map((item) => ({
      id: item.id,
      name: item.name,
      directory: item.directory,
      defaultModelId: item.defaultModelId ?? null,
      kind: item.kind || "workspace",
    }));

    res.json({ items, activeId: data.activeId || null });
  } catch (err) {
    workspacesLog.warn(`[workspaces] Failed to fetch from smart-factory: ${err.message}`);
    res.json({ items: [], activeId: null });
  }
});

module.exports = router;

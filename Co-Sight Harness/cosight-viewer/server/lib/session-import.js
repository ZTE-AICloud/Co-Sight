// SPDX-License-Identifier: Apache-2.0
/**
 * @file Session import module - imports a session from a ZIP archive.
 * Mirrors the export structure: session/{id}.jsonl, session/{id}/subagents/, tasks/*.json
 */
const fs = require("fs");
const path = require("path");
const AdmZip = require("adm-zip");
const { encodeCwd, getImportedSessionsDir, getTaskManagementRoot } = require("./claude-home");
const { extractSessionMetadata } = require("./session-metadata");
const { db, stmts } = require("../db");

const MAX_FILE_SIZE = 100 * 1024 * 1024; // 100MB
const MAX_UNCOMPRESSED_SIZE = 500 * 1024 * 1024; // 500MB

/**
 * Validate and extract a ZIP archive for session import.
 * @param {string} zipPath - Path to the uploaded ZIP file
 * @returns {Object} Import result with session info and file counts
 */
async function importSessionFromZip(zipPath) {
  // 1. Validate ZIP file
  if (!fs.existsSync(zipPath)) {
    throw new Error("ZIP 文件不存在");
  }
  const stat = fs.statSync(zipPath);
  if (stat.size > MAX_FILE_SIZE) {
    throw new Error(`文件过大（${(stat.size / 1024 / 1024).toFixed(1)}MB），最大支持 100MB`);
  }

  // 2. Extract ZIP
  let zip;
  try {
    zip = new AdmZip(zipPath);
  } catch (err) {
    throw new Error(`无法解析 ZIP 文件：${err.message}`);
  }

  const entries = zip.getEntries();
  if (!entries || entries.length === 0) {
    throw new Error("ZIP 文件为空");
  }

  // Validate total uncompressed size (ZIP bomb prevention)
  const totalSize = entries.reduce((sum, e) => sum + e.header.size, 0);
  if (totalSize > MAX_UNCOMPRESSED_SIZE) {
    throw new Error(`ZIP 解压后过大（${(totalSize / 1024 / 1024).toFixed(1)}MB），最大支持 500MB`);
  }

  // 3. Find and validate entries
  // Expected structure:
  //   <topDir>/session/{sessionId}.jsonl
  //   <topDir>/session/{sessionId}/subagents/agent-*.jsonl (optional)
  //   <topDir>/tasks/*.json (optional)
  const topDir = inferTopDir(entries);
  if (!topDir) {
    throw new Error("无法识别 ZIP 结构，期望顶层目录名为 session-{id}-*");
  }

  // Find main JSONL
  const jsonlEntry = entries.find((e) => {
    const rel = e.entryName.replace(topDir + "/", "");
    return rel.match(/^session\/[a-f0-9-]{36}\.jsonl$/i);
  });
  if (!jsonlEntry) {
    throw new Error("ZIP 中未找到主会话 JSONL 文件");
  }

  // Extract session ID from filename
  const jsonlRel = jsonlEntry.entryName.replace(topDir + "/", "");
  const sessionIdMatch = jsonlRel.match(/^session\/([a-f0-9-]{36})\.jsonl$/i);
  if (!sessionIdMatch) {
    throw new Error("无法从文件名解析会话 ID");
  }
  const sessionId = sessionIdMatch[1];

  // 4. Check if session already exists
  const existing = stmts.getSession.get(sessionId);
  if (existing) {
    throw new Error(`会话 ${sessionId} 已存在，无法重复导入`);
  }

  // 5. Create temp extraction directory under data directory
  // This ensures write permissions in both container and local environments
  const taskMgmtRoot = getTaskManagementRoot();
  const tmpBase = path.join(taskMgmtRoot, "tmp");
  fs.mkdirSync(tmpBase, { recursive: true });
  const extractDir = fs.mkdtempSync(path.join(tmpBase, "session-import-"));
  try {
    // 6. Extract all files safely
    let extractedCount = 0;
    for (const entry of entries) {
      if (entry.isDirectory) continue;
      // Path traversal protection
      const extractPath = path.resolve(extractDir, entry.entryName);
      if (!extractPath.startsWith(extractDir)) {
        throw new Error(`非法路径：${entry.entryName}`);
      }
      // Extract the file
      const destPath = extractPath;
      fs.mkdirSync(path.dirname(destPath), { recursive: true });
      fs.writeFileSync(destPath, entry.getData());
      extractedCount++;
    }

    // 7. Parse main JSONL to extract session metadata
    const mainJsonlPath = path.join(extractDir, topDir, "session", `${sessionId}.jsonl`);
    const sessionMeta = await parseSessionMetadata(mainJsonlPath, sessionId);

    // 8. Copy files to destination locations
    // Imported sessions go to imported-sessions/ directory (separate from native sessions)
    const importedDir = getImportedSessionsDir();
    const encodedCwd = encodeCwd(sessionMeta.cwd || "unknown");
    const destProjectDir = path.join(importedDir, encodedCwd);
    fs.mkdirSync(destProjectDir, { recursive: true });

    // 8a. Copy main JSONL
    const destJsonlPath = path.join(destProjectDir, `${sessionId}.jsonl`);
    fs.copyFileSync(mainJsonlPath, destJsonlPath);
    let subagentCount = 0;
    let taskCount = 0;

    // 8b. Copy subagent files (if any)
    const srcSubagentDir = path.join(extractDir, topDir, "session", sessionId, "subagents");
    if (fs.existsSync(srcSubagentDir)) {
      const destSubagentDir = path.join(destProjectDir, sessionId, "subagents");
      fs.mkdirSync(destSubagentDir, { recursive: true });
      copyDirRecursive(srcSubagentDir, destSubagentDir);
      subagentCount = fs.readdirSync(srcSubagentDir).length;
    }

    // 8c. Copy task files (if any) — rename to include sessionId prefix
    const srcTasksDir = path.join(extractDir, topDir, "tasks");
    if (fs.existsSync(srcTasksDir)) {
      const taskFiles = fs.readdirSync(srcTasksDir).filter((f) => f.endsWith(".json"));
      if (taskFiles.length > 0) {
        // Determine task destination directory
        const destTasksDir = path.join(getTaskManagementRoot(), "projects", encodedCwd);
        fs.mkdirSync(destTasksDir, { recursive: true });
        for (const taskFile of taskFiles) {
          // Rename task files to include sessionId prefix for tasks API compatibility
          // Original: task_{taskId}.json → Renamed: {sessionId}_task_{taskId}.json
          let destFileName = taskFile;
          if (!taskFile.startsWith(`${sessionId}_`)) {
            destFileName = `${sessionId}_${taskFile}`;
          }
          fs.copyFileSync(path.join(srcTasksDir, taskFile), path.join(destTasksDir, destFileName));
        }
        taskCount = taskFiles.length;
      }
    }

    // 9. Insert into database (with transcript_path pointing to imported location)
    const transcriptPath = path.join(destProjectDir, `${sessionId}.jsonl`);
    const insertResult = insertSessionToDatabase(sessionId, sessionMeta, transcriptPath);

    // 10. Return result
    return {
      success: true,
      session: {
        id: sessionId,
        name: sessionMeta.name,
        cwd: sessionMeta.cwd,
        status: "imported",
        started_at: sessionMeta.started_at,
        model: sessionMeta.model,
      },
      files: {
        jsonl: 1,
        subagents: subagentCount,
        tasks: taskCount,
      },
      db: insertResult,
    };
  } finally {
    // Cleanup temp directory
    try {
      fs.rmSync(extractDir, { recursive: true, force: true });
    } catch {
      // Ignore cleanup errors
    }
  }
}

/**
 * Infer the top directory name from ZIP entries.
 * Expects entries like "<topDir>/session/..." or "<topDir>/tasks/..."
 */
function inferTopDir(entries) {
  for (const entry of entries) {
    const parts = entry.entryName.split("/");
    if (parts.length >= 2 && parts[0].startsWith("session-")) {
      return parts[0];
    }
  }
  return null;
}

/**
 * Parse a JSONL file to extract session metadata.
 *
 * Thin wrapper over the shared extractor — transcripts from newer Claude Code
 * builds start with control records that have no cwd/model/timestamp, so the
 * fields cannot be read off the first line (see lib/session-metadata.js).
 *
 * @param {string} jsonlPath
 * @param {string} sessionId
 * @returns {Promise<{id: string, name: string, cwd: string|null, model: string|null,
 *   started_at: string|null, first_prompt: string|null}>}
 */
async function parseSessionMetadata(jsonlPath, sessionId) {
  const meta = await extractSessionMetadata(jsonlPath, { sessionId });
  return { ...meta, id: meta.id || sessionId };
}

/**
 * Insert session record into database with status='imported'.
 * Also creates the main agent record.
 */
function insertSessionToDatabase(sessionId, meta, transcriptPath) {
  const result = {
    sessions_inserted: 0,
    agents_inserted: 0,
    events_inserted: 0,
  };

  const now = new Date().toISOString();

  // Insert session (with transcript_path for imported sessions)
  const insertSession = db.prepare(`
    INSERT INTO sessions (id, name, status, cwd, model, started_at, updated_at, first_prompt, transcript_path)
    VALUES (?, ?, 'imported', ?, ?, ?, ?, ?, ?)
  `);
  const sessionResult = insertSession.run(
    sessionId,
    meta.name,
    meta.cwd,
    meta.model,
    meta.started_at,
    now,
    meta.first_prompt,
    transcriptPath || null
  );
  result.sessions_inserted = sessionResult.changes;

  // Insert main agent (so session list queries work properly)
  const insertAgent = db.prepare(`
    INSERT INTO agents (id, session_id, name, type, status, started_at, ended_at)
    VALUES (?, ?, ?, 'main', 'completed', ?, ?)
  `);
  const agentResult = insertAgent.run(
    `agent-${sessionId}-main`,
    sessionId,
    `Main Agent`,
    meta.started_at,
    meta.started_at
  );
  result.agents_inserted = agentResult.changes;

  return result;
}

/**
 * Recursively copy a directory.
 */
function copyDirRecursive(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  const entries = fs.readdirSync(src, { withFileTypes: true });
  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyDirRecursive(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

module.exports = {
  importSessionFromZip,
  parseSessionMetadata,
  MAX_FILE_SIZE,
  MAX_UNCOMPRESSED_SIZE,
};

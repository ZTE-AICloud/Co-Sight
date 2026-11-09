// SPDX-License-Identifier: Apache-2.0
/**
 * @file Single source of truth for the session metadata the dashboard stores for
 * a Claude Code transcript: name, cwd, model, started_at, first_prompt.
 *
 * Transcripts are not uniform. Newer Claude Code builds prefix the file with
 * control records that carry nothing but a sessionId:
 *
 *   {"type":"mode","mode":"normal","sessionId":"…"}
 *   {"type":"permission-mode","permissionMode":"default","sessionId":"…"}
 *   {"type":"system","subtype":"informational","cwd":"…","timestamp":"…"}   <- line 3
 *
 * and `model` is no longer a top-level field at all — it lives on
 * `message.model` of assistant entries. Reading line 1 as "the session init
 * record" therefore yields cwd=null / model=null / started_at=<now>, which is
 * how imports ended up in an `imported-sessions/unknown/` folder dated today.
 *
 * This module scans until each field is resolved instead of trusting the first
 * line — the same approach scripts/import-history.js already uses for bulk
 * imports. Credit for the field sources:
 *   - cwd        : first entry with `cwd`, else attachment.snapshot.workingDirectory
 *   - timestamp  : first entry with `timestamp`, else the file mtime
 *   - model      : first `message.model`, else legacy top-level `model`
 *   - titles     : LAST `custom-title` / `ai-title`, matching lib/extract-prompt.js
 *                  (which scans backwards for exactly this reason: a title can
 *                  be regenerated later in the session, and the newest is the
 *                  one the UI shows)
 *
 * Because titles are last-occurrence, the transcript is always read to EOF.
 * Streaming still keeps peak memory flat on multi-megabyte transcripts.
 */

const fs = require("fs");
const readline = require("readline");

/**
 * Cap on the stored first prompt. Unchanged from the historical importer so
 * names/prompts already in the database keep their shape.
 */
const MAX_FIRST_PROMPT_LENGTH = 200;

/**
 * Fold a single parsed transcript entry into the running result.
 * First occurrence wins for every field.
 *
 * @param {object} entry - Parsed JSONL line
 * @param {object} acc - Mutable accumulator
 */
function absorbEntry(entry, acc) {
  if (!acc.sessionId && typeof entry.sessionId === "string" && entry.sessionId) {
    acc.sessionId = entry.sessionId;
  }

  if (!acc.cwd) {
    if (typeof entry.cwd === "string" && entry.cwd) {
      acc.cwd = entry.cwd;
    } else if (
      entry.attachment &&
      entry.attachment.snapshot &&
      typeof entry.attachment.snapshot.workingDirectory === "string" &&
      entry.attachment.snapshot.workingDirectory
    ) {
      acc.cwd = entry.attachment.snapshot.workingDirectory;
    }
  }

  if (!acc.started_at && typeof entry.timestamp === "string" && entry.timestamp) {
    acc.started_at = entry.timestamp;
  }

  if (!acc.model) {
    const messageModel = entry.message && entry.message.model;
    if (typeof messageModel === "string" && messageModel) {
      acc.model = messageModel;
    } else if (typeof entry.model === "string" && entry.model) {
      // Legacy transcripts carried the model on the top-level init record.
      acc.model = entry.model;
    }
  }

  // Titles are last-occurrence-wins on purpose: a session's title can be
  // regenerated later, and the newest is the one the UI displays.
  if (entry.type === "custom-title" && entry.customTitle) {
    acc.customTitle = entry.customTitle;
  }
  if (entry.type === "ai-title" && entry.aiTitle) {
    acc.aiTitle = entry.aiTitle;
  }

  if (!acc.first_prompt && entry.type === "user") {
    const content = entry.message && entry.message.content;
    if (typeof content === "string") {
      if (content.trim()) acc.first_prompt = content.slice(0, MAX_FIRST_PROMPT_LENGTH);
    } else if (Array.isArray(content)) {
      const textPart = content.find(
        (part) => part && part.type === "text" && typeof part.text === "string" && part.text.trim()
      );
      if (textPart) acc.first_prompt = textPart.text.slice(0, MAX_FIRST_PROMPT_LENGTH);
    }
  }
}

/**
 * Extract session metadata from a transcript, tolerating any header shape.
 *
 * Fields are resolved independently. The whole file is streamed once — the
 * same number of passes the code this replaces made, but with flat memory —
 * because titles use last-occurrence semantics and can only be settled at EOF.
 *
 * @param {string} jsonlPath - Absolute path to the session JSONL transcript
 * @param {{ sessionId?: string|null }} [options] - Session id used for the name fallback
 * @returns {Promise<{id: string|null, name: string, cwd: string|null, model: string|null,
 *   started_at: string|null, first_prompt: string|null}>}
 */
async function extractSessionMetadata(jsonlPath, { sessionId = null } = {}) {
  const acc = {
    sessionId: null,
    cwd: null,
    model: null,
    started_at: null,
    first_prompt: null,
    customTitle: null,
    aiTitle: null,
  };

  if (fs.existsSync(jsonlPath)) {
    const stream = fs.createReadStream(jsonlPath, { encoding: "utf8" });
    const reader = readline.createInterface({ input: stream, crlfDelay: Infinity });
    try {
      for await (const line of reader) {
        if (!line.trim()) continue;
        let entry;
        try {
          entry = JSON.parse(line);
        } catch {
          continue; // Skip malformed lines rather than abandoning the whole scan
        }
        absorbEntry(entry, acc);
      }
    } finally {
      reader.close();
      stream.destroy();
    }
  }

  // Only fall back to the file's mtime when the transcript itself carries no
  // timestamp — never to "now", so an import cannot claim to have happened at
  // the transcript's time (the old code assigned now() first, which silently
  // disabled this fallback).
  if (!acc.started_at) {
    try {
      acc.started_at = fs.statSync(jsonlPath).mtime.toISOString();
    } catch {
      acc.started_at = null;
    }
  }

  const id = acc.sessionId || sessionId || null;
  const shortId = String(sessionId || acc.sessionId || "").slice(0, 8);

  return {
    id,
    // A custom title always wins over the auto-generated one, matching how the
    // live path applies these two (see routes/hooks.js).
    name: acc.customTitle || acc.aiTitle || `Session ${shortId}`,
    cwd: acc.cwd,
    model: acc.model,
    started_at: acc.started_at,
    first_prompt: acc.first_prompt,
  };
}

module.exports = {
  extractSessionMetadata,
  MAX_FIRST_PROMPT_LENGTH,
};

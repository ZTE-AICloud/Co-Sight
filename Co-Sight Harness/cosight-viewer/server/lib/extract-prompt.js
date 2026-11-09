// SPDX-License-Identifier: Apache-2.0
"use strict";

/**
 * @file Pure-function extractors for the session title (first_prompt) feature.
 *
 * - formatPromptForTitle(rawContent): beautifies a raw user message into a
 *   one-line title (parses slash-command XML, collapses whitespace, truncates
 *   to 2000 chars).
 * - extractFirstPromptFromTranscript(jsonlPath): reads a JSONL transcript and
 *   returns the first user-typed prompt (skipping compact summaries and
 *   tool-result array content).
 *
 * Both functions are used by the two write channels (hook realtime + import).
 */

const fs = require("fs");

const MAX_FIRST_PROMPT_LENGTH = 2000;

/**
 * Format a raw user message content into a readable one-line title.
 * - Parses <command-name>/<command-args> XML into "/cmd args" form
 * - Collapses multi-line / multi-space to single spaces
 * - Truncates to MAX_FIRST_PROMPT_LENGTH
 * Returns null for blank / non-string input.
 */
function formatPromptForTitle(rawContent) {
  if (typeof rawContent !== "string") return null;
  let text = rawContent.trim();
  if (!text) return null;

  // Parse slash-command XML wrapper
  if (text.includes("<command-name>")) {
    const cmdMatch = text.match(/<command-name>(.*?)<\/command-name>/);
    const argsMatch = text.match(/<command-args>([\s\S]*?)<\/command-args>/);
    if (cmdMatch) {
      let cmd = cmdMatch[1].trim();
      if (!cmd.startsWith("/")) cmd = "/" + cmd;
      const args = (argsMatch ? argsMatch[1] : "").trim();
      text = args ? `${cmd} ${args}` : cmd;
    }
  }

  // Collapse whitespace to single spaces
  text = text.replace(/\s+/g, " ").trim();

  if (!text) return null;
  return text.slice(0, MAX_FIRST_PROMPT_LENGTH);
}

/**
 * Read the first user-typed prompt from a JSONL transcript file.
 * - Skips isCompactSummary entries
 * - Skips blank-string content
 * - Skips array content (tool results from user turns)
 * - Returns { content, timestamp } | null
 * - File-not-found or unreadable returns null (never throws).
 */
function extractFirstPromptFromTranscript(jsonlPath) {
  if (!jsonlPath) return null;
  try {
    const raw = fs.readFileSync(jsonlPath, "utf-8");
    for (const line of raw.split("\n")) {
      if (!line.trim()) continue;
      let parsed;
      try {
        parsed = JSON.parse(line);
      } catch {
        continue;
      }
      if (parsed.type !== "user") continue;
      if (parsed.isCompactSummary === true) continue;
      const content = parsed.message && parsed.message.content;
      if (typeof content !== "string") continue;
      if (!content.trim()) continue;
      return { content, timestamp: parsed.timestamp || null };
    }
  } catch {
    // file not readable — return null
  }
  return null;
}

/**
 * Extract custom_title and ai_title from a JSONL transcript file.
 * - Scans for the LAST occurrence of each type (custom-title and ai-title)
 * - Returns { customTitle, aiTitle } where each is string | null
 * - File-not-found or unreadable returns { customTitle: null, aiTitle: null }
 *
 * JSONL entries:
 * - custom-title: { type: "custom-title", customTitle: "...", sessionId: "..." }
 * - ai-title: { type: "ai-title", aiTitle: "...", sessionId: "..." }
 */
function extractTitlesFromTranscript(jsonlPath) {
  const result = { customTitle: null, aiTitle: null };
  if (!jsonlPath) return result;

  try {
    const raw = fs.readFileSync(jsonlPath, "utf-8");
    const lines = raw.split("\n");

    // Scan from end to find the LAST occurrence of each title type
    for (let i = lines.length - 1; i >= 0; i--) {
      const line = lines[i];
      if (!line.trim()) continue;

      let parsed;
      try {
        parsed = JSON.parse(line);
      } catch {
        continue;
      }

      // Found custom-title and haven't found one yet
      if (parsed.type === "custom-title" && !result.customTitle) {
        result.customTitle = parsed.customTitle || null;
      }

      // Found ai-title and haven't found one yet
      if (parsed.type === "ai-title" && !result.aiTitle) {
        result.aiTitle = parsed.aiTitle || null;
      }

      // Early exit if both found
      if (result.customTitle && result.aiTitle) {
        break;
      }
    }
  } catch {
    // file not readable — return null values
  }

  return result;
}

/**
 * Async incremental version of extractTitlesFromTranscript.
 * - Starts scanning from lastScannedLine (0-based line index)
 * - Only scans new lines added since last scan
 * - Returns { customTitle, aiTitle, lastLine } where lastLine is the total lines scanned
 * - Uses fs.promises for non-blocking file I/O
 *
 * @param {string} jsonlPath - Path to JSONL file
 * @param {number} lastScannedLine - Line number to start scanning from (0 = beginning)
 * @returns {Promise<{customTitle: string|null, aiTitle: string|null, lastLine: number}>}
 */
async function extractTitlesFromTranscriptAsync(jsonlPath, lastScannedLine = 0) {
  const result = { customTitle: null, aiTitle: null, lastLine: lastScannedLine };
  if (!jsonlPath) return result;

  try {
    // Use fs.promises for async I/O
    const raw = await fs.promises.readFile(jsonlPath, "utf-8");
    const lines = raw.split("\n");

    // Only scan lines from lastScannedLine onwards
    const startIndex = Math.max(0, lastScannedLine);
    const endIndex = lines.length;

    // Scan from end to find the LAST occurrence of each title type
    for (let i = endIndex - 1; i >= startIndex; i--) {
      const line = lines[i];
      if (!line.trim()) continue;

      let parsed;
      try {
        parsed = JSON.parse(line);
      } catch {
        continue;
      }

      // Found custom-title and haven't found one yet
      if (parsed.type === "custom-title" && !result.customTitle) {
        result.customTitle = parsed.customTitle || null;
      }

      // Found ai-title and haven't found one yet
      if (parsed.type === "ai-title" && !result.aiTitle) {
        result.aiTitle = parsed.aiTitle || null;
      }

      // Early exit if both found
      if (result.customTitle && result.aiTitle) {
        break;
      }
    }

    // Update lastLine to current total
    result.lastLine = lines.length;
  } catch {
    // file not readable — return null values with lastLine unchanged
  }

  return result;
}

module.exports = {
  formatPromptForTitle,
  extractFirstPromptFromTranscript,
  extractTitlesFromTranscript,
  extractTitlesFromTranscriptAsync,
  MAX_FIRST_PROMPT_LENGTH,
};

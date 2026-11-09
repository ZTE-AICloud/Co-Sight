// SPDX-License-Identifier: Apache-2.0
/**
 * @fileoverview File watcher manager for real-time transcript updates.
 * Monitors JSONL file changes and broadcasts updates via WebSocket.
 * Used by ChatPanel for viewing external sessions in real-time.
 */

const {
  watchFile,
  unwatchFile,
  existsSync,
  statSync,
  createReadStream,
  readFileSync,
} = require("node:fs");
const { broadcast } = require("../websocket");

/**
 * True when a raw JSONL assistant entry is thinking-only: content made
 * exclusively of {type:"thinking"} blocks. The detection is content-based only
 * because output_tokens on the thinking entry varies by model — qwen writes 0,
 * deepseek-v4-flash writes the same usage as the following text entry. Claude
 * mode writes the thinking-only entry and the text response as two separate
 * assistant entries; the next text assistant's TPS must measure from the real
 * user prompt so thinking time counts. Cosight mode never splits, so this is
 * always false there.
 * @param {object} entry
 * @returns {boolean}
 */
function isThinkingOnlyAssistant(entry) {
  if (!entry || entry.type !== "assistant") return false;
  const msg = entry.message || entry;
  const content = msg.content;
  if (!Array.isArray(content) || content.length === 0) return false;
  return content.every((b) => b && b.type === "thinking");
}

class FileWatcherManager {
  constructor() {
    // sessionId -> { filePath, lastLine, fileSize, clients: Set<clientId> }
    this.watchers = new Map();
    this.DEBOUNCE_MS = 500;
    this.cleanupInterval = null;
    this.CLIENT_TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes
    this.startCleanupTimer();
  }

  /**
   * Start watching a session's JSONL file
   * @param {string} sessionId
   * @param {string} filePath - JSONL file path
   * @param {string} clientId - Unique client identifier
   */
  addClient(sessionId, filePath, clientId) {
    let state = this.watchers.get(sessionId);

    if (!state) {
      // First client for this session, start watching
      if (!existsSync(filePath)) {
        console.warn(`[FileWatcher] File not found: ${filePath}`);
        return false;
      }

      const stats = statSync(filePath);
      const seed = this._scanSeed(filePath);
      state = {
        filePath,
        // Seed the watch position so the first broadcast only carries lines
        // appended AFTER watching began (the client already loaded existing
        // messages via the transcript endpoint). prevTs/blockBoundaryTs/
        // prevIsAssistantCall seed TPS for the first new assistant message
        // via the unified block rule.
        lastLine: seed.lastLine,
        prevTs: seed.prevTs,
        blockBoundaryTs: seed.blockBoundaryTs,
        prevIsAssistantCall: seed.prevIsAssistantCall,
        fileSize: stats.size,
        clients: new Map(), // clientId -> lastSeen timestamp
        debounceTimer: null,
      };

      // Start file watching
      watchFile(filePath, { interval: 3000, persistent: false }, (curr, prev) => {
        if (curr.size <= state.fileSize) return;

        if (state.debounceTimer) clearTimeout(state.debounceTimer);
        state.debounceTimer = setTimeout(() => {
          this.processNewLines(sessionId);
        }, this.DEBOUNCE_MS);
      });

      this.watchers.set(sessionId, state);
    }

    state.clients.set(clientId, Date.now());
    return true;
  }

  /**
   * Remove a client from watching
   * @param {string} sessionId
   * @param {string} clientId
   */
  removeClient(sessionId, clientId) {
    const state = this.watchers.get(sessionId);
    if (!state) return;

    state.clients.delete(clientId);

    // Last client left, stop watching
    if (state.clients.size === 0) {
      this.stopWatching(sessionId);
    }
  }

  /**
   * Stop watching a session
   * @param {string} sessionId
   */
  stopWatching(sessionId) {
    const state = this.watchers.get(sessionId);
    if (!state) return;

    unwatchFile(state.filePath);
    if (state.debounceTimer) clearTimeout(state.debounceTimer);
    this.watchers.delete(sessionId);
  }

  /**
   * Determine the current line count and the TPS block state at the end of a
   * JSONL file. Used at watch-start so processNewLines only broadcasts lines
   * appended after watching began, and so the first assistant of the next batch
   * can compute TPS via the unified block rule.
   * @param {string} filePath
   * @returns {{ lastLine: number, prevTs: string|null, blockBoundaryTs: string|null, prevIsAssistantCall: boolean }}
   */
  _scanSeed(filePath) {
    const content = readFileSync(filePath, "utf8");
    const segments = content.split("\n");
    segments.pop();
    let lastLine = 0;
    let prevTs = null;
    let blockBoundaryTs = null;
    let prevIsAssistantCall = false;
    for (const line of segments) {
      lastLine++;
      if (!line.trim()) continue;
      try {
        const entry = JSON.parse(line);
        if (
          entry &&
          (entry.type === "user" || entry.type === "assistant") &&
          typeof entry.timestamp === "string"
        ) {
          if (entry.type === "assistant") {
            const hasInputTokens = (entry.message?.usage?.input_tokens || 0) > 0;
            if (hasInputTokens) {
              if (!prevIsAssistantCall) {
                blockBoundaryTs = prevTs;
              }
              prevIsAssistantCall = true;
            } else {
              prevIsAssistantCall = false;
            }
          } else {
            prevIsAssistantCall = false;
          }
          prevTs = entry.timestamp;
        }
      } catch {
        // Ignore unparseable lines while seeding.
      }
    }
    return { lastLine, prevTs, blockBoundaryTs, prevIsAssistantCall };
  }
  /**
   * Process new lines from a watched file
   * @param {string} sessionId
   */
  async processNewLines(sessionId) {
    const state = this.watchers.get(sessionId);
    if (!state) return;

    try {
      const { messages, lastLine, prevTs, blockBoundaryTs, prevIsAssistantCall } =
        await this._readNewLines(
          state.filePath,
          state.lastLine,
          state.prevTs ?? null,
          state.blockBoundaryTs ?? null,
          state.prevIsAssistantCall ?? false
        );

      // Update state
      state.lastLine = lastLine;
      state.prevTs = prevTs;
      state.blockBoundaryTs = blockBoundaryTs;
      state.prevIsAssistantCall = prevIsAssistantCall;
      const stats = statSync(state.filePath);
      state.fileSize = stats.size;

      // Broadcast via WebSocket
      if (messages.length > 0) {
        broadcast("transcript_update", {
          sessionId,
          messages,
          lastLine: state.lastLine,
        });
      }
    } catch (err) {
      console.error(`[FileWatcher] Error processing ${sessionId}:`, err.message);
    }
  }

  /**
   * Read lines from a JSONL file beyond the given watch position, computing TPS
   * for assistant messages via the unified block rule (seeded across the watch
   * boundary via prevTs/blockBoundaryTs/prevIsAssistantCall). Mirrors
   * sessions.js computeTpsFromTimestamps so the live transcript_update path
   * carries the same tps/durationMs as the transcript endpoint.
   * @param {string} filePath
   * @param {number} lastLine - highest already-seen line number
   * @param {string|null} prevTs - timestamp of the last user/assistant line seen
   * @param {string|null} blockBoundaryTs - block boundary timestamp
   * @param {boolean} prevIsAssistantCall - whether the last entry was an assistant with input_tokens
   * @returns {Promise<{ messages: object[], lastLine: number, prevTs: string|null, blockBoundaryTs: string|null, prevIsAssistantCall: boolean }>}
   */
  async _readNewLines(filePath, lastLine, prevTs, blockBoundaryTs, prevIsAssistantCall) {
    const newMessages = [];
    const stream = createReadStream(filePath, {
      encoding: "utf8",
    });

    let currentLine = 0;
    let buffer = "";
    let runningBlockBoundaryTs = blockBoundaryTs ?? null;
    let runningPrevIsAssistantCall = !!prevIsAssistantCall;

    for await (const chunk of stream) {
      buffer += chunk;
      const lines = buffer.split("\n");
      buffer = lines.pop() || ""; // Last line might be incomplete

      for (const line of lines) {
        currentLine++;
        if (currentLine <= lastLine) continue;

        if (!line.trim()) continue;

        try {
          const entry = JSON.parse(line);
          const message = this.parseJsonlEntry(entry);

          if (message) {
            // TPS for assistant messages via the unified block rule.
            // A thinking-only bubble never carries a tps. When the entry is
            // part of a model call block (has input_tokens), measure from the
            // block boundary (entry before the block started).
            const currentIsThinkingOnly =
              entry.type === "assistant" && isThinkingOnlyAssistant(entry);
            const hasInputTokens =
              entry.type === "assistant" && (entry.message?.usage?.input_tokens || 0) > 0;
            if (hasInputTokens) {
              if (!runningPrevIsAssistantCall) {
                // NEW BLOCK: start measuring from the immediate predecessor.
                runningBlockBoundaryTs = prevTs;
              }
              if (
                message.type === "assistant" &&
                message.usage &&
                message.timestamp &&
                !currentIsThinkingOnly &&
                runningBlockBoundaryTs
              ) {
                const durationMs =
                  new Date(message.timestamp).getTime() -
                  new Date(runningBlockBoundaryTs).getTime();
                if (durationMs > 0) {
                  message.durationMs = durationMs;
                  const outTokens = message.usage.output_tokens || 0;
                  message.tps =
                    outTokens > 0
                      ? Math.round((outTokens / (durationMs / 1000)) * 100) / 100
                      : undefined;
                }
              }
              runningPrevIsAssistantCall = true;
            } else if (entry.type === "assistant") {
              runningPrevIsAssistantCall = false;
            }
            newMessages.push(message);
          }

          // Advance the running block state for every user/assistant line.
          if (
            entry &&
            (entry.type === "user" || entry.type === "assistant") &&
            typeof entry.timestamp === "string"
          ) {
            if (entry.type === "assistant") {
              const hasInput = (entry.message?.usage?.input_tokens || 0) > 0;
              if (hasInput) {
                if (!runningPrevIsAssistantCall) {
                  runningBlockBoundaryTs = entry.timestamp;
                }
                runningPrevIsAssistantCall = true;
              } else {
                runningPrevIsAssistantCall = false;
              }
            } else {
              runningPrevIsAssistantCall = false;
            }
            prevTs = entry.timestamp;
          }
        } catch {
          // Ignore parse errors
        }
      }
    }

    // Post-process: same-message-id streaming partials. When consecutive
    // assistant entries share a message.id, only the LAST carries the final
    // TPS. Clear tps/durationMs from earlier partials so the UI shows TPS
    // only on the last entry per message.
    // NOTE: _messageId is intentionally kept in the broadcast so the client
    // can also do cross-batch dedup (when entries arrive in different batches).
    for (let i = 0; i < newMessages.length - 1; i++) {
      const m = newMessages[i];
      const next = newMessages[i + 1];
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

    return {
      messages: newMessages,
      lastLine: currentLine,
      prevTs,
      blockBoundaryTs: runningBlockBoundaryTs,
      prevIsAssistantCall: runningPrevIsAssistantCall,
    };
  }

  /**
   * Parse JSONL entry to TranscriptMessage format
   * @param {object} entry
   * @returns {object|null}
   */
  parseJsonlEntry(entry) {
    // Filter out non-displayable types
    if (["attachment", "last-prompt", "file-history-snapshot"].includes(entry.type)) {
      return null;
    }

    if (entry.type === "user") {
      const content = entry.message?.content;
      if (typeof content === "string") {
        return {
          type: "user",
          uuid: entry.uuid,
          content: [{ type: "text", text: content }],
          timestamp: entry.timestamp,
        };
      } else if (Array.isArray(content)) {
        const blocks = [];
        for (const block of content) {
          if (block.type === "text") {
            blocks.push({ type: "text", text: block.text });
          }
        }
        if (blocks.length > 0) {
          return {
            type: "user",
            uuid: entry.uuid,
            content: blocks,
            timestamp: entry.timestamp,
          };
        }
      }
    }

    if (entry.type === "assistant") {
      const msg = entry.message || {};
      const content = [];

      for (const block of msg.content || []) {
        if (block.type === "text") {
          content.push({ type: "text", text: block.text });
        } else if (block.type === "thinking") {
          // Canonical shape used by MessageList/ChatPanel (same as the
          // transcript endpoint): the thinking text lives under `text`.
          content.push({ type: "thinking", text: block.thinking });
        } else if (block.type === "tool_use") {
          content.push({
            type: "tool_use",
            id: block.id,
            name: block.name,
            input: block.input,
          });
        }
      }

      if (content.length > 0) {
        return {
          type: "assistant",
          uuid: entry.uuid,
          _messageId: typeof msg.id === "string" && msg.id ? msg.id : null,
          content,
          usage: msg.usage,
          model: msg.model,
          timestamp: entry.timestamp,
        };
      }
    }

    return null;
  }

  /**
   * Start cleanup timer to remove stale clients
   */
  startCleanupTimer() {
    if (this.cleanupInterval) return;

    this.cleanupInterval = setInterval(() => {
      const now = Date.now();
      for (const [sessionId, state] of this.watchers.entries()) {
        for (const [clientId, lastSeen] of state.clients.entries()) {
          if (now - lastSeen > this.CLIENT_TIMEOUT_MS) {
            state.clients.delete(clientId);
          }
        }

        if (state.clients.size === 0) {
          this.stopWatching(sessionId);
        }
      }
    }, 60000); // Check every minute

    // Don't keep process alive just for this timer
    if (this.cleanupInterval.unref) {
      this.cleanupInterval.unref();
    }
  }

  /**
   * Update client heartbeat
   * @param {string} sessionId
   * @param {string} clientId
   */
  heartbeat(sessionId, clientId) {
    const state = this.watchers.get(sessionId);
    if (state && state.clients.has(clientId)) {
      state.clients.set(clientId, Date.now());
    }
  }

  /**
   * Get watcher status (for debugging)
   */
  getStatus() {
    const status = {};
    for (const [sessionId, state] of this.watchers.entries()) {
      status[sessionId] = {
        filePath: state.filePath,
        lastLine: state.lastLine,
        fileSize: state.fileSize,
        clientCount: state.clients.size,
      };
    }
    return status;
  }

  /**
   * Cleanup on shutdown
   */
  shutdown() {
    if (this.cleanupInterval) {
      clearInterval(this.cleanupInterval);
      this.cleanupInterval = null;
    }
    for (const sessionId of this.watchers.keys()) {
      this.stopWatching(sessionId);
    }
  }
}

// Singleton
module.exports = new FileWatcherManager();

// SPDX-License-Identifier: Apache-2.0
/**
 * @file TranscriptCache class for efficient extraction of token usage, compaction, error, and turn duration data from JSONL transcript files, with stat-based caching and incremental reads to handle append-only growth without re-reading the entire file.
 */

const fs = require("fs");
const {
  bucketKey,
  emptyBucket,
  extractUsageFields,
  normalizeSpeed,
  normalizeGeo,
  normalizeTier,
  accumulateBucket,
  subtractBucket,
  rememberUsageContribution,
} = require("./token-usage");

const MAX_CACHE_ENTRIES = 200;

// Hard cap on the length of each per-entry growable array (turnDurations,
// errors, compaction.entries).
// Past this point we keep the *tail* — the most recent N items — so the
// cache reflects current state. Older items are NOT lost from the system:
// they are already persisted to the events table by routes/hooks.js, with
// dedup logic that prevents re-insertion when the cache re-reads them.
// Configurable via TRANSCRIPT_CACHE_MAX_ARRAY_LEN env var.
const MAX_ARRAY_LEN = (() => {
  const raw = parseInt(process.env.TRANSCRIPT_CACHE_MAX_ARRAY_LEN, 10);
  return Number.isFinite(raw) && raw > 0 ? raw : 1000;
})();

// Watermark for in-flight trimming during _consumeLine. We trim back to
// MAX_ARRAY_LEN whenever an array reaches 2*MAX_ARRAY_LEN, so a full-file
// parse cannot accumulate an unbounded transient before _finalizeState runs.
// Amortized O(N): each item is touched by a splice at most ~once.
const PARSE_TRIM_WATERMARK = MAX_ARRAY_LEN * 2;

// Cap on the captured first-user-message text. 500 chars matches the task
// truncation the hook ingestor already applies to subagent prompts, so the
// descriptor can be reused verbatim as an agent task downstream.
const FIRST_USER_MESSAGE_MAX_LEN = 500;
const RECENT_USER_MESSAGES_LIMIT = 2;

// Synthetic user entries whose text is CLI plumbing, not something the human
// typed: local slash-command invocations/output and the caveat preamble
// Claude Code writes before locally-generated messages. These must never
// become a session descriptor.
const SYNTHETIC_USER_TEXT_RE =
  /^<(?:command-name|command-message|local-command-stdout|local-command-caveat)>/;

/**
 * Extract the human-typed text of a user transcript entry, or null when the
 * entry is not a real prompt: tool-result entries, meta/caveat lines, local
 * slash-command plumbing, compact summaries, and user-interrupt markers are
 * all skipped. Shared with scripts/import-history.js so imported and live
 * sessions derive the identical descriptor.
 */
function extractFirstUserText(entry) {
  if (entry.isMeta || entry.isCompactSummary) return null;
  const msg = entry.message;
  if (!msg || typeof msg !== "object" || msg.role !== "user") return null;
  const content = msg.content;
  let text = null;
  if (typeof content === "string") {
    text = content;
  } else if (Array.isArray(content)) {
    // Tool-result entries are `role:"user"` too — skip any entry carrying a
    // tool_result block rather than mining text out of a mixed payload.
    if (content.some((b) => b && b.type === "tool_result")) return null;
    text = content
      .filter((b) => b && b.type === "text" && typeof b.text === "string")
      .map((b) => b.text)
      .join(" ");
  }
  if (typeof text !== "string") return null;
  // Collapse newlines/runs of whitespace so the descriptor reads as one line.
  text = text.replace(/\s+/g, " ").trim();
  if (!text || SYNTHETIC_USER_TEXT_RE.test(text)) return null;
  return text.length > FIRST_USER_MESSAGE_MAX_LEN
    ? text.slice(0, FIRST_USER_MESSAGE_MAX_LEN)
    : text;
}

/**
 * Keep the two newest distinct human prompts in their original chronological
 * order. Repeating a prompt should refresh its position instead of consuming a
 * second card row, and callers never receive more text than the compact cards
 * can truthfully render.
 */
function appendRecentUserMessage(messages, value) {
  const text = typeof value === "string" ? value.trim() : "";
  if (!text) return Array.isArray(messages) ? messages.slice(-RECENT_USER_MESSAGES_LIMIT) : [];
  const key = text.toLocaleLowerCase();
  const prior = Array.isArray(messages) ? messages : [];
  return [...prior.filter((message) => message.toLocaleLowerCase() !== key), text].slice(
    -RECENT_USER_MESSAGES_LIMIT
  );
}

class TranscriptCache {
  constructor(maxEntries = MAX_CACHE_ENTRIES) {
    this._cache = new Map();
    this._maxEntries = maxEntries;
    this._hits = 0;
    this._misses = 0;
  }

  /**
   * Extract token usage and compaction data from a JSONL transcript file.
   * Uses stat-based caching with incremental reads for append-only growth.
   * Returns null if file doesn't exist or has no data.
   */
  extract(transcriptPath) {
    if (!transcriptPath) return null;
    try {
      let stat;
      try {
        stat = fs.statSync(transcriptPath);
      } catch {
        return null;
      }
      const key = transcriptPath;
      const cached = this._cache.get(key);

      // Cache hit: file unchanged (same mtime + size)
      if (cached && cached.mtimeMs === stat.mtimeMs && cached.size === stat.size) {
        this._hits++;
        return cached.result;
      }

      this._misses++;
      // File shrunk or first read → full re-read
      if (!cached || stat.size < cached.bytesRead) {
        const result = this._fullRead(transcriptPath);
        this._set(key, { mtimeMs: stat.mtimeMs, size: stat.size, bytesRead: stat.size, result });
        return result;
      }

      // File grew → incremental read from last position
      if (stat.size > cached.bytesRead) {
        const incremental = this._streamRange(transcriptPath, cached.bytesRead, stat.size);
        if (incremental) {
          const merged = this._merge(cached, incremental);
          const hasTokens = Object.keys(merged.tokensByModel).length > 0;
          const hasTurnDurations = merged.turnDurations && merged.turnDurations.length > 0;
          const result = {
            tokensByModel: hasTokens ? merged.tokensByModel : null,
            compaction: merged.compaction,
            errors: merged.errors,
            turnDurations: hasTurnDurations ? merged.turnDurations : null,
            turnDurationsComplete: merged.turnDurationsComplete,
            turnDurationCount: merged.turnDurationCount,
            latestModel: merged.latestModel || null,
            customTitle: merged.customTitle || null,
            aiTitle: merged.aiTitle || null,
            firstUserMessage: merged.firstUserMessage || null,
            recentUserMessages: merged.recentUserMessages || [],
            lastTurnTs: merged.lastTurnTs || null,
          };
          if (
            !result.tokensByModel &&
            !result.compaction &&
            !result.errors &&
            !result.turnDurations &&
            !result.latestModel &&
            !result.customTitle &&
            !result.aiTitle &&
            !result.firstUserMessage &&
            result.recentUserMessages.length === 0 &&
            !result.lastTurnTs
          ) {
            this._set(key, {
              mtimeMs: stat.mtimeMs,
              size: stat.size,
              bytesRead: stat.size,
              result: null,
            });
            return null;
          }
          this._set(key, { mtimeMs: stat.mtimeMs, size: stat.size, bytesRead: stat.size, result });
          return result;
        }

        // Only whitespace/newlines appended
        this._set(key, {
          ...cached,
          mtimeMs: stat.mtimeMs,
          size: stat.size,
          bytesRead: stat.size,
        });
        return cached.result;
      }

      // Same size, different mtime — content may have been rewritten (compaction)
      const result = this._fullRead(transcriptPath);
      this._set(key, { mtimeMs: stat.mtimeMs, size: stat.size, bytesRead: stat.size, result });
      return result;
    } catch {
      return null;
    }
  }

  /**
   * Extract only compaction entries from a JSONL file.
   * Replacement for findCompactionsInFile — uses the same cache, no duplicate reads.
   */
  extractCompactions(transcriptPath) {
    const result = this.extract(transcriptPath);
    if (!result || !result.compaction) return [];
    return result.compaction.entries.map((e) => ({ ...e }));
  }

  /**
   * Full re-read using chunked streaming. Avoids materializing the whole file
   * as a single JS string, so files larger than V8's max string length
   * (~512 MiB on 64-bit Node) parse without aborting the process with
   * "FATAL ERROR: v8::ToLocalChecked Empty MaybeLocal".
   */
  _fullRead(filePath) {
    let size;
    try {
      size = fs.statSync(filePath).size;
    } catch {
      return null;
    }
    return this._streamRange(filePath, 0, size);
  }

  /**
   * Sync chunked range reader + line parser.
   * Reads [startOffset, endOffset) in fixed-size chunks, splits on 0x0A bytes,
   * decodes each complete line as UTF-8 (safe: 0x0A never appears inside a
   * UTF-8 multibyte sequence), and feeds it to _consumeLine. Partial trailing
   * bytes between chunks are held in a byte buffer so multibyte characters
   * straddling a chunk boundary are not corrupted. Never builds a string
   * larger than a single line, so V8 string-length limits cannot be hit.
   */
  _streamRange(filePath, startOffset, endOffset) {
    const state = this._initParseState();
    if (endOffset <= startOffset) return this._finalizeState(state);

    const CHUNK = 4 * 1024 * 1024; // 4 MiB
    const MAX_PENDING = 64 * 1024 * 1024; // hard cap on a single line
    const buf = Buffer.allocUnsafe(CHUNK);
    let pending = null; // bytes of partial trailing line not yet terminated by \n
    let pendingLen = 0;
    let pendingStart = null; // absolute file offset where `pending` begins
    let pos = startOffset;
    let fd;
    try {
      try {
        fd = fs.openSync(filePath, "r");
      } catch {
        return this._finalizeState(state);
      }

      while (pos < endOffset) {
        const want = Math.min(CHUNK, endOffset - pos);
        let got;
        try {
          got = fs.readSync(fd, buf, 0, want, pos);
        } catch {
          break;
        }
        if (got <= 0) break;
        pos += got;

        const chunkStart = pos - got;
        let lineStart = 0;
        for (let i = 0; i < got; i++) {
          if (buf[i] !== 0x0a) continue;

          let line;
          if (pendingLen) {
            const need = pendingLen + (i - lineStart);
            const lineBuf = Buffer.allocUnsafe(need);
            pending.copy(lineBuf, 0, 0, pendingLen);
            buf.copy(lineBuf, pendingLen, lineStart, i);
            line = lineBuf.toString("utf8");
            pending = null;
            pendingLen = 0;
          } else {
            line = buf.toString("utf8", lineStart, i);
          }
          if (line.length && line.charCodeAt(line.length - 1) === 13) {
            line = line.slice(0, -1); // strip CR
          }
          const sourceOffset = pendingStart ?? chunkStart + lineStart;
          if (line) this._consumeLine(line, state, sourceOffset);
          pendingStart = null;
          lineStart = i + 1;
        }

        if (lineStart < got) {
          const tailLen = got - lineStart;
          const newLen = pendingLen + tailLen;
          if (newLen > MAX_PENDING) {
            // Pathological single line — drop accumulated bytes and skip
            // forward to the next newline rather than OOM. Loss is bounded
            // to one malformed line.
            pending = null;
            pendingLen = 0;
            pendingStart = null;
          } else {
            if (pendingLen === 0) pendingStart = chunkStart + lineStart;
            if (!pending) {
              pending = Buffer.allocUnsafe(Math.max(newLen, 8192));
            } else if (pending.length < newLen) {
              const grow = Buffer.allocUnsafe(Math.max(newLen, pending.length * 2));
              pending.copy(grow, 0, 0, pendingLen);
              pending = grow;
            }
            buf.copy(pending, pendingLen, lineStart, got);
            pendingLen = newLen;
          }
        }
      }

      if (pendingLen) {
        let line = pending.toString("utf8", 0, pendingLen);
        if (line.length && line.charCodeAt(line.length - 1) === 13) {
          line = line.slice(0, -1);
        }
        if (line) this._consumeLine(line, state, pendingStart ?? startOffset);
      }
    } finally {
      if (fd !== undefined) {
        try {
          fs.closeSync(fd);
        } catch {
          /* ignore */
        }
      }
    }

    return this._finalizeState(state);
  }

  _initParseState() {
    return {
      tokensByModel: {},
      // Per-message usage reconciliation window. A single API response's records
      // are written ADJACENTLY in the transcript (partial usage first, then the
      // final). This map tracks each message.id's current contribution so a
      // later record for the same id can retract it via subtractBucket before
      // accumulating the final value. Bounded tail window (see token-usage.js).
      usageByMessageId: new Map(),
      compaction: null,
      errors: [],
      turnDurations: [],
      // Running count of every turn_duration entry seen, even those trimmed
      // out of turnDurations by MAX_ARRAY_LEN. Lets _finalizeState distinguish
      // a complete parse (count <= MAX_ARRAY_LEN ⇒ turnDurationsComplete) from
      // a capped tail parse (count > MAX_ARRAY_LEN ⇒ append-only semantics).
      turnDurationCount: 0,
      // Track the model of the most recent assistant entry. JSONL is
      // append-only and parsed in file order, so the last value seen here is
      // the user's *current* model — used downstream to keep session.model in
      // sync when the user invokes /model mid-session.
      latestModel: null,
      // Track the latest human-readable session title. Two sources, both
      // append-only metadata lines: `custom-title` (explicit /rename, claude
      // -n, picker Ctrl+R) and `ai-title` (auto-generated / plan-accept).
      // Last value wins. Used downstream to keep session.name in sync in real
      // time — custom titles take precedence over ai titles.
      customTitle: null,
      aiTitle: null,
      // First real user prompt of the session (tool-result / meta / command
      // entries skipped), whitespace-collapsed and length-capped. Used
      // downstream as a fallback descriptor for placeholder-named sessions
      // and their main agent — first value wins (it describes what the
      // session set out to do), unlike the last-wins titles above.
      firstUserMessage: null,
      // The two newest distinct human prompts complement the first-message
      // descriptor: compact session and agent cards use them as a bounded
      // chronological context, so a terse follow-up is still intelligible.
      recentUserMessages: [],
      // Timestamp (ISO 8601, from Claude Code's clock) of the most recent real
      // turn activity (assistant output or a genuine user prompt). Compared
      // against errors[].timestamp by the hook ingestor's isErrorAtTail to
      // decide whether the transcript TAIL is an unrecovered API error.
      lastTurnTs: null,
      // Usage extras: track distinct service tiers, speeds, and inference geos
      // for pricing visibility.
      usageExtras: {
        service_tiers: new Set(),
        speeds: new Set(),
        inference_geos: new Set(),
      },
    };
  }

  _consumeLine(line, state, sourceOffset = null) {
    if (!line) return;
    let entry;
    try {
      entry = JSON.parse(line);
    } catch {
      return;
    }

    // Session title metadata lines — sparse, no usage payload. Capture the
    // latest value of each kind (append-only → last wins) and bail early.
    if (entry.type === "custom-title") {
      if (typeof entry.customTitle === "string" && entry.customTitle.trim()) {
        state.customTitle = entry.customTitle;
      }
      return;
    }
    if (entry.type === "ai-title") {
      if (typeof entry.aiTitle === "string" && entry.aiTitle.trim()) {
        state.aiTitle = entry.aiTitle;
      }
      return;
    }

    // Real turn activity — assistant output or a genuine (non-interrupt) user
    // prompt. Tracking its latest timestamp lets the hook ingestor's
    // isErrorAtTail decide whether an API error at the transcript tail is
    // unrecovered (error timestamp >= last turn activity) or was already
    // retried past.
    if ((entry.type === "assistant" || entry.type === "user") && entry.timestamp) {
      if (!state.lastTurnTs || entry.timestamp > state.lastTurnTs)
        state.lastTurnTs = entry.timestamp;
    }

    // First real user prompt — captured once (first wins; the file is parsed
    // in order). extractFirstUserText filters out tool-result, meta, and
    // slash-command plumbing entries so only human-typed text qualifies.
    if (entry.type === "user") {
      const userText = extractFirstUserText(entry);
      if (userText) {
        if (state.firstUserMessage === null) state.firstUserMessage = userText;
        state.recentUserMessages = appendRecentUserMessage(state.recentUserMessages, userText);
      }
    }

    if (entry.isCompactSummary) {
      if (!state.compaction) state.compaction = { count: 0, entries: [] };
      state.compaction.count++;
      state.compaction.entries.push({
        uuid: entry.uuid || null,
        timestamp: entry.timestamp || null,
      });
      if (state.compaction.entries.length >= PARSE_TRIM_WATERMARK) {
        this._trimArray(state.compaction.entries);
      }
    }

    if (entry.type === "system" && entry.subtype === "turn_duration" && entry.durationMs) {
      state.turnDurationCount++;
      const turnTs = entry.timestamp
        ? typeof entry.timestamp === "number"
          ? new Date(entry.timestamp).toISOString()
          : entry.timestamp
        : null;
      state.turnDurations.push({
        durationMs: entry.durationMs,
        timestamp: turnTs,
        turnId:
          typeof entry.uuid === "string" && entry.uuid
            ? `uuid:${entry.uuid}`
            : sourceOffset !== null
              ? `offset:${sourceOffset}`
              : `ordinal:${state.turnDurationCount}`,
      });
      if (state.turnDurations.length >= PARSE_TRIM_WATERMARK) {
        this._trimArray(state.turnDurations);
      }
    }

    const msg = entry.message || entry;
    if (msg.type === "error" && msg.error) {
      state.errors.push({
        type: msg.error.type || "unknown_error",
        message: msg.error.message || "Unknown API error",
        timestamp: entry.timestamp || null,
      });
      if (state.errors.length >= PARSE_TRIM_WATERMARK) {
        this._trimArray(state.errors);
      }
      return;
    }

    if (entry.isApiErrorMessage) {
      const errContent = Array.isArray(entry.message?.content) ? entry.message.content : [];
      const errText = errContent[0]?.text ? errContent[0].text.slice(0, 500) : "Unknown error";
      state.errors.push({
        type: entry.error || "unknown_error",
        message: errText,
        timestamp: entry.timestamp || null,
      });
      if (state.errors.length >= PARSE_TRIM_WATERMARK) {
        this._trimArray(state.errors);
      }
      return;
    }

    const model = msg.model;
    if (!model || model === "<synthetic>" || !msg.usage) return;
    state.latestModel = model;

    // Message-id reconciliation: streaming writes may emit partial usage first
    // (e.g. output_tokens 5, then the final 742), so the same message.id can
    // appear twice. The later record is authoritative — retract the earlier
    // contribution and count this one instead. Records without an id are
    // counted unconditionally.
    const usageMsgId = typeof msg.id === "string" && msg.id ? msg.id : null;
    const speed = normalizeSpeed(msg.usage);
    const geo = normalizeGeo(msg.usage);
    const tier = normalizeTier(msg.usage);
    const key = bucketKey(model, speed, geo, tier);
    if (usageMsgId) {
      const prev = state.usageByMessageId.get(usageMsgId);
      if (prev) {
        // Retract the earlier contribution — possibly into a bucket that only
        // exists in the cached result of a previous incremental parse; a
        // transiently negative local bucket nets out at merge time.
        if (!state.tokensByModel[prev.key]) {
          state.tokensByModel[prev.key] = emptyBucket(prev.model, prev.speed, prev.geo, prev.tier);
        }
        subtractBucket(state.tokensByModel[prev.key], prev.fields);
      }
    }
    if (!state.tokensByModel[key]) {
      state.tokensByModel[key] = emptyBucket(model, speed, geo, tier);
    }
    const fields = extractUsageFields(msg.usage);
    accumulateBucket(state.tokensByModel[key], fields);

    if (usageMsgId) {
      rememberUsageContribution(
        state.usageByMessageId,
        usageMsgId,
        { key, model, speed, geo, tier, fields },
        MAX_ARRAY_LEN
      );
    }

    if (msg.usage.service_tier) state.usageExtras.service_tiers.add(msg.usage.service_tier);
    if (msg.usage.speed) state.usageExtras.speeds.add(msg.usage.speed);
    if (msg.usage.inference_geo && msg.usage.inference_geo !== "not_available") {
      state.usageExtras.inference_geos.add(msg.usage.inference_geo);
    }
  }

  _finalizeState(state) {
    const hasTokens = Object.keys(state.tokensByModel).length > 0;
    const hasErrors = state.errors.length > 0;
    const hasTurnDurations = state.turnDurations.length > 0;
    if (
      !hasTokens &&
      !state.compaction &&
      !hasErrors &&
      !hasTurnDurations &&
      !state.latestModel &&
      !state.customTitle &&
      !state.aiTitle &&
      !state.firstUserMessage &&
      state.recentUserMessages.length === 0 &&
      !state.lastTurnTs
    ) {
      return null;
    }

    this._trimArray(state.errors);
    this._trimArray(state.turnDurations);
    if (state.compaction) this._trimArray(state.compaction.entries);

    return {
      tokensByModel: hasTokens ? state.tokensByModel : null,
      compaction: state.compaction,
      errors: hasErrors ? state.errors : null,
      turnDurations: hasTurnDurations ? state.turnDurations : null,
      // A complete parse (every turn_duration line fits under MAX_ARRAY_LEN)
      // is authoritative and may be used to reconcile persisted rows; a capped
      // parse only contains the newest turns and must append, never rebuild.
      turnDurationsComplete: state.turnDurationCount <= MAX_ARRAY_LEN,
      turnDurationCount: state.turnDurationCount,
      latestModel: state.latestModel,
      customTitle: state.customTitle,
      aiTitle: state.aiTitle,
      firstUserMessage: state.firstUserMessage,
      recentUserMessages: state.recentUserMessages,
      lastTurnTs: state.lastTurnTs,
      usageExtras: {
        service_tiers: Array.from(state.usageExtras.service_tiers),
        speeds: Array.from(state.usageExtras.speeds),
        inference_geos: Array.from(state.usageExtras.inference_geos),
      },
    };
  }

  /**
   * Parse an in-memory JSONL string. Retained for callers that already have
   * the content as a string. Internal extraction paths now use _streamRange
   * directly to avoid the V8 string-length limit on multi-hundred-MiB files.
   */
  _parseContent(content) {
    const state = this._initParseState();
    let start = 0;
    for (let i = 0; i < content.length; i++) {
      if (content.charCodeAt(i) !== 10) continue;
      let line = content.slice(start, i);
      if (line.length && line.charCodeAt(line.length - 1) === 13) line = line.slice(0, -1);
      if (line) this._consumeLine(line, state, start);
      start = i + 1;
    }
    if (start < content.length) {
      let line = content.slice(start);
      if (line.length && line.charCodeAt(line.length - 1) === 13) line = line.slice(0, -1);
      if (line) this._consumeLine(line, state, start);
    }
    return this._finalizeState(state);
  }

  _merge(cached, incremental) {
    const tokensByModel = cached.result?.tokensByModel
      ? this._cloneTokens(cached.result.tokensByModel)
      : {};
    if (incremental && incremental.tokensByModel) {
      for (const [key, tokens] of Object.entries(incremental.tokensByModel)) {
        if (!tokensByModel[key]) {
          tokensByModel[key] = emptyBucket(tokens.model, tokens.speed, tokens.geo, tokens.tier);
        }
        accumulateBucket(tokensByModel[key], tokens);
      }
    }

    let compaction = cached.result?.compaction
      ? this._cloneCompaction(cached.result.compaction)
      : null;
    if (incremental && incremental.compaction) {
      if (!compaction) compaction = { count: 0, entries: [] };
      compaction.count += incremental.compaction.count;
      compaction.entries.push(...incremental.compaction.entries);
      this._trimArray(compaction.entries);
    }

    let errors = cached.result?.errors ? [...cached.result.errors] : null;
    if (incremental && incremental.errors) {
      if (!errors) errors = [];
      errors.push(...incremental.errors);
      this._trimArray(errors);
    }

    let turnDurations = cached.result?.turnDurations ? [...cached.result.turnDurations] : null;
    if (incremental && incremental.turnDurations) {
      if (!turnDurations) turnDurations = [];
      turnDurations.push(...incremental.turnDurations);
      this._trimArray(turnDurations);
    }
    // Running count across incremental parses. Fall back to the cached array
    // length for legacy cache entries that predate turnDurationCount.
    const turnDurationCount =
      (cached.result?.turnDurationCount || cached.result?.turnDurations?.length || 0) +
      (incremental?.turnDurationCount || incremental?.turnDurations?.length || 0);
    const turnDurationsComplete = Boolean(
      cached.result?.turnDurationsComplete !== false &&
      (!incremental || incremental.turnDurationsComplete !== false) &&
      turnDurationCount <= MAX_ARRAY_LEN
    );

    // JSONL is append-only and parsed in order, so the incremental block's
    // latestModel (when present) is the newest reading — fall back to the
    // previously-cached value when the new chunk had no assistant entries.
    const latestModel =
      (incremental && incremental.latestModel) || cached.result?.latestModel || null;

    // Same append-only logic for the session titles: the newest title line in
    // the incremental chunk wins, else keep what was cached.
    const customTitle =
      (incremental && incremental.customTitle) || cached.result?.customTitle || null;
    const aiTitle = (incremental && incremental.aiTitle) || cached.result?.aiTitle || null;

    // First user message is first-wins (the opposite of the titles): the
    // cached value was parsed from earlier in the file, so it stays; the
    // incremental chunk only fills it when nothing was captured before.
    const firstUserMessage =
      cached.result?.firstUserMessage || (incremental && incremental.firstUserMessage) || null;

    // Both arrays are chronological and already bounded to two entries. Fold
    // them through the same distinctness rule so an appended duplicate does
    // not evict the earlier, useful request from the compact card context.
    let recentUserMessages = [];
    for (const prompt of [
      ...(cached.result?.recentUserMessages || []),
      ...(incremental?.recentUserMessages || []),
    ]) {
      recentUserMessages = appendRecentUserMessage(recentUserMessages, prompt);
    }

    // Append-only: a newer turn-activity timestamp in the incremental chunk
    // supersedes the cached one, otherwise keep what was already known.
    const lastTurnTs = (incremental && incremental.lastTurnTs) || cached.result?.lastTurnTs || null;

    return {
      tokensByModel,
      compaction,
      errors,
      turnDurations,
      turnDurationCount,
      turnDurationsComplete,
      latestModel,
      customTitle,
      aiTitle,
      firstUserMessage,
      recentUserMessages,
      lastTurnTs,
    };
  }

  _cloneTokens(tokensByModel) {
    if (!tokensByModel) return null;
    const clone = {};
    for (const [model, t] of Object.entries(tokensByModel)) {
      clone[model] = { ...t };
    }
    return clone;
  }

  _cloneCompaction(compaction) {
    if (!compaction) return null;
    return { count: compaction.count, entries: compaction.entries.map((e) => ({ ...e })) };
  }

  /** Set cache entry with LRU eviction when at capacity */
  _set(key, entry) {
    // Delete first so re-insertion moves key to end of Map iteration order
    this._cache.delete(key);
    this._cache.set(key, entry);
    // Evict oldest entries (first in Map iteration order) if over limit
    while (this._cache.size > this._maxEntries) {
      const oldest = this._cache.keys().next().value;
      this._cache.delete(oldest);
    }
  }

  /** Trim an array in-place to keep only the last `maxLen` items. No-op on falsy. */
  _trimArray(arr, maxLen = MAX_ARRAY_LEN) {
    if (!arr || !Array.isArray(arr) || arr.length <= maxLen) return;
    arr.splice(0, arr.length - maxLen);
  }

  /** Number of entries currently cached */
  get size() {
    return this._cache.size;
  }

  /** Remove a specific path from cache */
  invalidate(transcriptPath) {
    this._cache.delete(transcriptPath);
  }

  /** Clear all cached entries */
  clear() {
    this._cache.clear();
  }

  /** Return cache stats for diagnostics */
  stats() {
    const total = this._hits + this._misses;
    return {
      size: this._cache.size,
      maxSize: this._maxEntries,
      hits: this._hits,
      misses: this._misses,
      hitRate: total > 0 ? +((this._hits / total) * 100).toFixed(1) : 0,
      keys: [...this._cache.keys()],
    };
  }
}

module.exports = TranscriptCache;

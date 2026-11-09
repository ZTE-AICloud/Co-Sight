// SPDX-License-Identifier: Apache-2.0
/**
 * @file Shared helpers for normalizing Claude transcript `usage` records into
 * per-bucket token tallies. Used by BOTH ingestion paths — the live server-side
 * parser (`server/lib/transcript-cache.js`) and the history importer
 * (`scripts/import-history.js`) — so the two stay in lockstep.
 *
 * A "bucket" is the unit cost is computed against: tokens are grouped by
 * (model, speed, inference_geo, service_tier) because those four dimensions
 * change the per-token RATE (fast mode, US data residency, Batch API). The
 * dimensions are normalized to the small set of values that actually move
 * price; anything unknown collapses to the standard/global default so old
 * transcripts (which lack `speed` / `inference_geo` / `cache_creation`
 * breakdown / `server_tool_use`) price exactly as they did before.
 */

// Separator for composite bucket keys — U+0001 (SOH) cannot occur in a model id.
const BUCKET_SEP = String.fromCharCode(1);

/** Pricing-relevant speed. Anything other than the fast research-preview tier is standard. */
function normalizeSpeed(usage) {
  return usage && usage.speed === "fast" ? "fast" : "standard";
}

/**
 * Pricing-relevant inference geography. Only US-pinned routing carries the 1.1x
 * data-residency premium; "global", "not_available", and absent all map to the
 * standard "global" rate.
 */
function normalizeGeo(usage) {
  return usage && usage.inference_geo === "us" ? "us" : "global";
}

/** Pricing-relevant service tier. Only "batch" changes the rate (50% off). */
function normalizeTier(usage) {
  return usage && usage.service_tier === "batch" ? "batch" : "standard";
}

/** Composite bucket key — stable string usable as an object property. */
function bucketKey(model, speed, geo, tier) {
  return [model, speed, geo, tier].join(BUCKET_SEP);
}

/** A zeroed bucket carrying its four pricing dimensions. */
function emptyBucket(model, speed, geo, tier) {
  return {
    model,
    speed,
    geo,
    tier,
    input: 0,
    output: 0,
    cacheRead: 0,
    cacheWrite: 0, // TOTAL ephemeral cache-creation tokens (5m + 1h)
    cacheWrite1h: 0, // subset of cacheWrite that is the 1h tier; 5m = cacheWrite - cacheWrite1h
    webSearch: 0, // server_tool_use.web_search_requests (billed per 1k)
    webFetch: 0, // server_tool_use.web_fetch_requests (free; tracked for visibility)
    codeExec: 0, // server_tool_use.code_execution_requests (time-billed; estimated)
  };
}

/**
 * Pull the numeric token / request fields out of a single `usage` record.
 * Tolerant of the older shape: when `cache_creation` breakdown is absent the
 * whole cache-write amount is treated as 5m (cacheWrite1h = 0), and a missing
 * `server_tool_use` yields zero tool requests.
 */
function extractUsageFields(usage) {
  if (!usage || typeof usage !== "object") {
    return {
      input: 0,
      output: 0,
      cacheRead: 0,
      cacheWrite: 0,
      cacheWrite1h: 0,
      webSearch: 0,
      webFetch: 0,
      codeExec: 0,
    };
  }
  const cc =
    usage.cache_creation && typeof usage.cache_creation === "object" ? usage.cache_creation : null;
  const ephem5m = cc ? cc.ephemeral_5m_input_tokens || 0 : 0;
  const ephem1h = cc ? cc.ephemeral_1h_input_tokens || 0 : 0;
  // Prefer the explicit total; fall back to the breakdown sum when only that is present.
  const cacheWrite =
    usage.cache_creation_input_tokens != null
      ? usage.cache_creation_input_tokens || 0
      : ephem5m + ephem1h;
  // Never let the 1h subset exceed the recorded total (guards malformed records).
  const cacheWrite1h = Math.min(ephem1h, cacheWrite);
  const stu =
    usage.server_tool_use && typeof usage.server_tool_use === "object"
      ? usage.server_tool_use
      : null;
  return {
    input: usage.input_tokens || 0,
    output: usage.output_tokens || 0,
    cacheRead: usage.cache_read_input_tokens || 0,
    cacheWrite,
    cacheWrite1h,
    webSearch: stu ? stu.web_search_requests || 0 : 0,
    webFetch: stu ? stu.web_fetch_requests || 0 : 0,
    codeExec: stu ? stu.code_execution_requests || 0 : 0,
  };
}

/** Add the numeric fields of `src` into `target` in place. */
function accumulateBucket(target, src) {
  target.input += src.input || 0;
  target.output += src.output || 0;
  target.cacheRead += src.cacheRead || 0;
  target.cacheWrite += src.cacheWrite || 0;
  target.cacheWrite1h += src.cacheWrite1h || 0;
  target.webSearch += src.webSearch || 0;
  target.webFetch += src.webFetch || 0;
  target.codeExec += src.codeExec || 0;
  return target;
}

/**
 * Default size of the per-message reconciliation window (see
 * `rememberUsageContribution`). A single API response's records are written
 * ADJACENTLY: measured across a 295-transcript corpus, all 13,115 duplicate
 * usage records sat exactly one distinct message.id apart — the span was never
 * greater than 1. A 1000-entry tail window therefore reconciles every real
 * transcript with a ~1000x margin while keeping memory flat on
 * multi-hundred-MiB files. Past the window a message's earlier record can no
 * longer be retracted, which over-counts that one record rather than drifting
 * without bound.
 */
const USAGE_RECONCILE_WINDOW = 1000;

/**
 * Inverse of accumulateBucket. Used to retract a message's earlier usage
 * contribution when a later record for the same message.id carries the
 * final (larger) usage — streaming writes partial usage first. A bucket may
 * go transiently negative when the retracted contribution was counted in a
 * previous incremental parse; the merge step nets it out.
 */
function subtractBucket(target, src) {
  target.input -= src.input || 0;
  target.output -= src.output || 0;
  target.cacheRead -= src.cacheRead || 0;
  target.cacheWrite -= src.cacheWrite || 0;
  target.cacheWrite1h -= src.cacheWrite1h || 0;
  target.webSearch -= src.webSearch || 0;
  target.webFetch -= src.webFetch || 0;
  target.codeExec -= src.codeExec || 0;
  return target;
}

/**
 * Record `contribution` as the usage currently counted for `messageId`, so a
 * later record for the same id can retract it via subtractBucket. Re-inserts
 * on update (Map iterates in insertion order) and evicts the oldest entries
 * past `maxEntries`, keeping the window a bounded tail. Both ingestion paths
 * call this so their reconciliation windows behave identically.
 */
function rememberUsageContribution(
  map,
  messageId,
  contribution,
  maxEntries = USAGE_RECONCILE_WINDOW
) {
  map.delete(messageId);
  map.set(messageId, contribution);
  while (map.size > maxEntries) {
    const oldest = map.keys().next().value;
    map.delete(oldest);
  }
  return map;
}

module.exports = {
  BUCKET_SEP,
  USAGE_RECONCILE_WINDOW,
  normalizeSpeed,
  normalizeGeo,
  normalizeTier,
  bucketKey,
  emptyBucket,
  extractUsageFields,
  accumulateBucket,
  subtractBucket,
  rememberUsageContribution,
};

// SPDX-License-Identifier: Apache-2.0
/**
 * @file core.ts
 * @description Core HTTP request utilities shared by all domain API modules.
 * Provides `request` (raw fetch wrapper) and `dedupedRequest` (short-lived TTL
 * cache for idempotent metadata endpoints so concurrent component mounts share
 * a single in-flight Promise).
 */

import { API_BASE } from "../config";

export const BASE = API_BASE;

/**
 * Short-lived dedup cache for idempotent metadata endpoints.
 * Within TTL, concurrent callers reuse the same Promise; on failure the entry
 * is evicted so the next call retries.
 */
const _dedupCache = new Map<string, { promise: Promise<unknown>; expires: number }>();

async function _request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.error?.message || `HTTP ${res.status}`);
  }
  return res.json();
}

/**
 * Bare fetch wrapper. All domain APIs route through this so error handling and
 * headers stay consistent.
 */
export const request = _request;

/**
 * Deduped variant of `request`. Use for read-only metadata endpoints that
 * multiple components may mount simultaneously (e.g. facets, mode-status).
 */
export function dedupedRequest<T>(path: string, ttlMs = 30_000): Promise<T> {
  const now = Date.now();
  const cached = _dedupCache.get(path);
  if (cached && cached.expires > now) {
    return cached.promise as Promise<T>;
  }
  const promise = _request<T>(path);
  _dedupCache.set(path, { promise: promise as Promise<unknown>, expires: now + ttlMs });
  // Evict on failure so the next call retries rather than serving a stale error.
  promise.catch(() => _dedupCache.delete(path));
  return promise;
}

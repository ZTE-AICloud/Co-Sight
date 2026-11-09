// SPDX-License-Identifier: Apache-2.0
/**
 * @file format.ts
 * @description Provides utility functions for formatting dates, times, durations, and numbers in the agent dashboard application. It includes functions to parse ISO timestamp strings while normalizing UTC, format time and date-time strings for display, calculate and format durations between timestamps, and format large numbers with appropriate suffixes (K/M/B) for better readability. These utilities help ensure consistent and user-friendly presentation of temporal and numerical data throughout the application.
 */

import i18n from "../i18n";

/**
 * Parse a timestamp string into a Date, normalizing UTC.
 * SQLite datetime('now') returns 'YYYY-MM-DD HH:MM:SS' (no timezone).
 * JS treats that as local time, causing offset bugs. This ensures
 * timestamps without a timezone indicator are treated as UTC.
 */
function parseDate(iso: string): Date {
  // Already has timezone info (Z or +/- offset) — parse directly
  if (/[Zz]$/.test(iso) || /[+-]\d{2}:\d{2}$/.test(iso)) {
    return new Date(iso);
  }
  // No timezone — treat as UTC by appending Z
  // Handle both 'YYYY-MM-DD HH:MM:SS' and 'YYYY-MM-DDTHH:MM:SS' formats
  return new Date(iso.replace(" ", "T") + "Z");
}

type SupportedLanguage = "en" | "zh";

function getCurrentLanguage(): SupportedLanguage {
  const language = (i18n.resolvedLanguage ?? i18n.language ?? "en").toLowerCase().split("-")[0];
  if (language === "zh" || language === "en") {
    return language;
  }
  return "en";
}

export function getCurrentLocale(): string {
  const language = getCurrentLanguage();
  if (language === "zh") return "zh-CN";
  return "en-US";
}

export function formatTime(iso: string): string {
  const d = parseDate(iso);
  return d.toLocaleTimeString(getCurrentLocale(), { hour: "2-digit", minute: "2-digit" });
}

export function formatDateTime(iso: string): string {
  const d = parseDate(iso);
  return d.toLocaleString(getCurrentLocale(), {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Date only, e.g. "Apr 18" — paired with formatTime as a small second line in
 *  narrow list rows (timeline, activity feed) so the date is visible too. */
export function formatDateShort(iso: string): string {
  const d = parseDate(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleString(getCurrentLocale(), { month: "short", day: "numeric" });
}

/** Fully detailed timestamp with weekday, full date, seconds, and timezone —
 *  e.g. "Sat, Apr 18, 2026, 08:49:13 AM PDT". For detail panels. */
export function formatDateTimeFull(iso: string): string {
  const d = parseDate(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString(getCurrentLocale(), {
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  });
}

export function formatDuration(start: string, end: string): string {
  const ms = parseDate(end).getTime() - parseDate(start).getTime();
  return formatMs(ms);
}

export function formatMs(ms: number): string {
  if (ms < 0) return "0s";
  const totalSec = Math.floor(ms / 1000);
  const hours = Math.floor(totalSec / 3600);
  const minutes = Math.floor((totalSec % 3600) / 60);
  const seconds = totalSec % 60;

  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

export function timeAgo(iso: string): string {
  const ms = Date.now() - parseDate(iso).getTime();
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return i18n.t("common:time.justNow");
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return i18n.t("common:time.mAgo", { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return i18n.t("common:time.hAgo", { count: hours });
  const days = Math.floor(hours / 24);
  return i18n.t("common:time.dAgo", { count: days });
}

export function truncate(str: string, max: number): string {
  if (str.length <= max) return str;
  return str.slice(0, max - 1) + "\u2026";
}

/** Format large numbers with B/M/K suffixes. */
export function fmt(n: number): string {
  if (!Number.isFinite(n)) return "0";
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

/** Format dollar amounts with K/M suffixes. */
export function fmtCost(n: number): string {
  if (!Number.isFinite(n) || n < 0) return "$0.00";
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(2)}K`;
  return `$${n.toFixed(2)}`;
}


const MODEL_BRANDS: Record<string, string> = {
  claude: "Claude",
  gpt: "GPT",
  gemini: "Gemini",
};

/** Human-friendly model name:
 *  "claude-opus-4-7-20260101" → "Claude Opus 4.7"
 *  "gpt-4o-mini"              → "GPT-4o Mini"
 *  Returns null for falsy input. */
export function formatModelName(model: string | null | undefined): string | null {
  if (!model) return null;

  // Strip provider prefix ("anthropic/claude-opus-4-7" → "claude-opus-4-7")
  let name = model.includes("/") ? model.split("/").pop()! : model;

  // Extract bracketed context-window tag like "[1m]" → suffix " (1M)"
  let ctxSuffix = "";
  const ctxMatch = name.match(/\[(\d+[mk])\]$/i);
  if (ctxMatch) {
    ctxSuffix = ` (${(ctxMatch[1] as string).toUpperCase()})`;
    name = name.slice(0, -ctxMatch[0].length);
  }

  // Strip date suffix and "-latest"
  name = name.replace(/-\d{8}$/, "").replace(/-latest$/i, "");

  const parts: string[] = name.split("-");
  const first = parts[0] ?? name;
  const brand = MODEL_BRANDS[first.toLowerCase()];

  // GPT-style names keep the brand hyphenated with the version token:
  // "gpt-4o-mini" → "GPT-4o Mini"
  if (brand === "GPT" && parts.length >= 2) {
    const versionToken = parts[1] as string;
    const rest = parts.slice(2);
    const suffix = rest
      .map((seg) => (/^\d+$/.test(seg) ? seg : seg.charAt(0).toUpperCase() + seg.slice(1)))
      .join(" ");
    const base = suffix ? `${brand}-${versionToken} ${suffix}` : `${brand}-${versionToken}`;
    return base + ctxSuffix;
  }

  // Claude / Gemini / generic: title-case words, dot-join version digits
  const result: string[] = [brand ?? first.charAt(0).toUpperCase() + first.slice(1)];

  let i = 1;
  while (i < parts.length) {
    const seg = parts[i] as string;
    if (/^\d+$/.test(seg)) {
      const ver = [seg];
      while (i + 1 < parts.length && /^\d+$/.test(parts[i + 1] as string)) {
        i++;
        ver.push(parts[i] as string);
      }
      result.push(ver.join("."));
    } else if (/^\d+\w+$/.test(seg)) {
      result.push(seg);
    } else {
      result.push(seg.charAt(0).toUpperCase() + seg.slice(1));
    }
    i++;
  }

  return result.join(" ") + ctxSuffix;
}

/** Last segment of a filesystem path. Supports both POSIX and Windows paths.
 *  "/Users/dav/code/my-project" → "my-project"
 *  "C:\\Users\\dav\\code\\my-project" → "my-project" */
export function pathBasename(p: string | null | undefined): string | null {
  if (!p) return null;
  // Split by both POSIX (/) and Windows (\) separators, filter empty segments
  const parts = p.split(/[/\\]/).filter(Boolean);
  return parts.length > 0 ? (parts[parts.length - 1] ?? p) : p;
}

// SPDX-License-Identifier: Apache-2.0
/**
 * @file event-summary.ts
 * @description Produces a short, human-readable summary of a DashboardEvent
 * for the top of the expanded EventDetail panel. Purely data-driven — parses
 * `tool_input` / `tool_response` and extracts the most useful facts. Returns
 * null for events where a summary would add nothing (e.g. unknown tools with
 * empty payloads).
 *
 */

import type { DashboardEvent } from "./types";

export type EventSummary = {
  icon: string;
  headline: string;
  bullets: string[];
};

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function obj(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

function shortPath(path: string): string {
  const parts = path.split(/[/\\]/).filter(Boolean);
  if (parts.length <= 1) return parts[0] ?? path;
  return parts.slice(-2).join("/");
}

function trunc(text: string, max: number): string {
  return text.length > max ? text.slice(0, max) + "..." : text;
}

function parseData(event: DashboardEvent): Record<string, unknown> | null {
  if (!event.data) return null;
  try {
    const v = JSON.parse(event.data);
    return obj(v);
  } catch {
    return null;
  }
}

function countHunks(structuredPatch: unknown): { hunks: number; added: number; removed: number } {
  if (!Array.isArray(structuredPatch)) return { hunks: 0, added: 0, removed: 0 };
  let added = 0;
  let removed = 0;
  for (const raw of structuredPatch) {
    const r = obj(raw);
    if (!r || !Array.isArray(r.lines)) continue;
    for (const line of r.lines) {
      if (typeof line !== "string") continue;
      if (line.startsWith("+")) added++;
      else if (line.startsWith("-")) removed++;
    }
  }
  return { hunks: structuredPatch.length, added, removed };
}

function firstEnclosingContext(structuredPatch: unknown): string | null {
  // Look for a context line that looks like a function/class/const definition.
  if (!Array.isArray(structuredPatch)) return null;
  const defPattern =
    /^\s+(?:function\s+\w+|def\s+\w+|class\s+\w+|(?:const|let|var)\s+\w+|\w+\s*=\s*\()/;
  for (const raw of structuredPatch) {
    const r = obj(raw);
    if (!r || !Array.isArray(r.lines)) continue;
    for (const line of r.lines) {
      if (typeof line === "string" && defPattern.test(line)) {
        return line.trim();
      }
    }
  }
  return null;
}

function lineCount(text: string): number {
  if (!text) return 0;
  return text.split(/\r?\n/).length;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60_000)}m ${Math.floor((ms % 60_000) / 1000)}s`;
}

export function buildEventSummary(event: DashboardEvent): EventSummary | null {
  const data = parseData(event);

  // ── Non-tool events first ──────────────────────────────────────────
  if (event.event_type === "Stop" || event.event_type === "SubagentStop") {
    const stopHookActive = data?.stop_hook_active === true;
    const msg = str(data?.last_assistant_message);
    const bullets: string[] = [];
    if (stopHookActive) bullets.push("stop hook active");
    if (msg) bullets.push(`Last message: ${trunc(msg.split(/\r?\n/)[0] ?? "", 80)}`);
    return {
      icon: "🛑",
      headline: event.event_type === "SubagentStop" ? "Subagent turn ended" : "Turn ended",
      bullets,
    };
  }

  if (event.event_type === "TurnDuration") {
    const durationMs = typeof data?.durationMs === "number" ? data.durationMs : null;
    return {
      icon: "⏱️",
      headline: durationMs != null ? `Turn took ${formatDuration(durationMs)}` : "Turn finished",
      bullets: [],
    };
  }

  if (event.event_type === "Compaction") {
    return {
      icon: "🗜️",
      headline: "Transcript compacted",
      bullets: ["Token usage reset for the following turn"],
    };
  }

  if (event.event_type === "Notification") {
    const msg = str(data?.message);
    const type = str(data?.notification_type);
    return {
      icon: "🔔",
      headline: msg ? `Notification: ${trunc(msg, 80)}` : "Notification",
      bullets: type ? [`Type: ${type}`] : [],
    };
  }

  if (event.event_type === "SessionStart" || event.event_type === "SessionEnd") {
    const source = str(data?.source);
    const model = str(data?.model);
    return {
      icon: event.event_type === "SessionStart" ? "🎬" : "🏁",
      headline: event.event_type === "SessionStart" ? "Session started" : "Session ended",
      bullets: [source && `Source: ${source}`, model && `Model: ${model}`].filter(
        Boolean
      ) as string[],
    };
  }

  if (event.event_type === "APIError") {
    return {
      icon: "⚠️",
      headline: "API error recorded",
      bullets: [],
    };
  }

  // ── Tool events ────────────────────────────────────────────────────
  const tool = event.tool_name;
  if (!tool) return null;
  const input = obj(data?.tool_input);
  const response = obj(data?.tool_response);

  // MCP tools — generic summary
  if (tool.startsWith("mcp__")) {
    const headline = humanizeMcp(tool);
    const bullets: string[] = [];
    if (input) {
      const top = firstStringField(input, ["title", "query", "q", "url", "name", "id"]);
      if (top) bullets.push(`Called with: ${trunc(top, 80)}`);
    }
    if (response) {
      const resTop = firstStringField(response, ["title", "name", "state", "status", "url"]);
      if (resTop) bullets.push(`Response: ${trunc(resTop, 80)}`);
      else bullets.push(`Returned ${Object.keys(response).length} fields`);
    }
    return { icon: "🧩", headline, bullets };
  }

  switch (tool) {
    case "Bash":
    case "PowerShell": {
      const cmd = str(input?.command);
      const desc = str(input?.description);
      const stdout = str(response?.stdout);
      const stderr = str(response?.stderr);
      const interrupted = response?.interrupted === true;
      const bullets: string[] = [];
      if (desc) bullets.push(`"${desc}"`);
      if (stdout) bullets.push(`${lineCount(stdout)} lines stdout`);
      if (stderr) bullets.push(`${lineCount(stderr)} lines stderr`);
      else if (stdout || response) bullets.push("no stderr");
      if (interrupted) bullets.push("⚠ interrupted");
      return {
        icon: "💻",
        headline: cmd ? `Ran ${trunc(firstWord(cmd), 40)}: ${trunc(cmd, 80)}` : `${tool} call`,
        bullets,
      };
    }

    case "Edit":
    case "NotebookEdit": {
      const path = str(input?.file_path);
      const { hunks, added, removed } = countHunks(response?.structuredPatch);
      const ctx = firstEnclosingContext(response?.structuredPatch);
      const replaceAll = input?.replace_all === true;
      const bullets: string[] = [];
      if (ctx) bullets.push(`Inside: ${trunc(ctx, 80)}`);
      if (hunks > 0) bullets.push(`${hunks} hunk${hunks === 1 ? "" : "s"} · +${added} −${removed}`);
      if (replaceAll) bullets.push("replace_all mode");
      return {
        icon: "✏️",
        headline: path ? `Edited ${shortPath(path)}` : `${tool} call`,
        bullets,
      };
    }

    case "Write": {
      const path = str(input?.file_path);
      const content = str(input?.content);
      const bullets: string[] = [];
      if (content) bullets.push(`${lineCount(content)} lines · ${content.length} bytes`);
      return {
        icon: "📝",
        headline: path ? `Wrote ${shortPath(path)}` : `Write call`,
        bullets,
      };
    }

    case "Read": {
      const path = str(input?.file_path);
      const offset = input?.offset;
      const limit = input?.limit;
      const bullets: string[] = [];
      if (offset != null || limit != null) {
        const parts: string[] = [];
        if (offset != null) parts.push(`offset ${offset}`);
        if (limit != null) parts.push(`limit ${limit}`);
        bullets.push(`Range: ${parts.join(", ")}`);
      } else {
        bullets.push("Full file");
      }
      if (typeof response === "string") {
        bullets.push(`${lineCount(response)} lines returned`);
      }
      return {
        icon: "📖",
        headline: path ? `Read ${shortPath(path)}` : "Read call",
        bullets,
      };
    }

    case "Grep": {
      const pattern = str(input?.pattern);
      const path = str(input?.path);
      const bullets: string[] = [];
      const matchCount = countGrepMatches(response);
      if (matchCount != null) bullets.push(`${matchCount} match${matchCount === 1 ? "" : "es"}`);
      return {
        icon: "🔍",
        headline: pattern
          ? `Searched "${trunc(pattern, 50)}"${path ? ` in ${shortPath(path)}` : ""}`
          : "Grep call",
        bullets,
      };
    }

    case "Glob": {
      const pattern = str(input?.pattern);
      const bullets: string[] = [];
      const fileCount = countFiles(response);
      if (fileCount != null) bullets.push(`${fileCount} file${fileCount === 1 ? "" : "s"}`);
      return {
        icon: "🗂️",
        headline: pattern ? `Listed files matching "${pattern}"` : "Glob call",
        bullets,
      };
    }

    case "WebFetch": {
      const url = str(input?.url);
      const prompt = str(input?.prompt);
      const bullets: string[] = [];
      if (prompt) bullets.push(`Prompt: ${trunc(prompt, 80)}`);
      if (typeof response === "string") bullets.push(`${lineCount(response)} lines returned`);
      let host = "";
      try {
        host = new URL(url).host;
      } catch {
        host = url;
      }
      return {
        icon: "🌐",
        headline: url ? `Fetched ${host}` : "WebFetch call",
        bullets,
      };
    }

    case "Task":
    case "Agent": {
      const subtype = str(input?.subagent_type);
      const desc = str(input?.description);
      const bullets: string[] = [];
      if (subtype) bullets.push(`Subagent: ${subtype}`);
      if (desc) bullets.push(`Description: ${trunc(desc, 80)}`);
      if (typeof response === "string") bullets.push(`${lineCount(response)} lines output`);
      return { icon: "🤖", headline: `Spawned subagent`, bullets };
    }

    case "TaskCreate": {
      const d = str(input?.description);
      return {
        icon: "✅",
        headline: d ? `Created task: ${trunc(d, 80)}` : "TaskCreate",
        bullets: [],
      };
    }
    case "TaskUpdate": {
      const d = str(input?.description) || str(input?.id);
      return {
        icon: "🔄",
        headline: d ? `Updated task: ${trunc(d, 80)}` : "TaskUpdate",
        bullets: [],
      };
    }

    case "AskUserQuestion": {
      const qs = Array.isArray(input?.questions) ? input?.questions : null;
      const first = qs && qs.length > 0 ? obj(qs[0]) : null;
      const q = first ? str(first.question) : "";
      return {
        icon: "❓",
        headline: q ? `Asked: "${trunc(q, 80)}"` : "Asked user",
        bullets: [],
      };
    }

    case "ScheduleWakeup": {
      const delay = input?.delaySeconds;
      const reason = str(input?.reason);
      return {
        icon: "😴",
        headline: typeof delay === "number" ? `Scheduled wakeup in ${delay}s` : "Scheduled wakeup",
        bullets: reason ? [`Reason: ${trunc(reason, 80)}`] : [],
      };
    }

    default: {
      // Unknown native tool — minimal summary.
      if (!input && !response) return null;
      return {
        icon: "🔧",
        headline: `${tool} call`,
        bullets: input ? [`${Object.keys(input).length} input fields`] : [],
      };
    }
  }
}

function humanizeMcp(toolName: string): string {
  const parts = toolName.split("__").filter(Boolean);
  if (parts.length < 3) return toolName;
  const rawServer = parts[1] ?? "";
  const rest = parts.slice(2).join(" ");
  // Reuse the same server-humanization logic as elsewhere: split, dedupe, last token.
  const tokens = rawServer.split(/[_-]+/).filter(Boolean);
  const dedup: string[] = [];
  for (const t of tokens) if (dedup[dedup.length - 1] !== t) dedup.push(t);
  const last = dedup[dedup.length - 1] ?? rawServer;
  const server = last.toLowerCase() === last ? last.charAt(0).toUpperCase() + last.slice(1) : last;
  const toolPart = rest.replace(/_+/g, " ").trim().toLowerCase();
  return `${server} · ${toolPart}`;
}

function firstWord(command: string): string {
  const m = command.trim().match(/^(\S+)/);
  return m ? (m[1] ?? command) : command;
}

function firstStringField(obj: Record<string, unknown>, priority: string[]): string | null {
  for (const k of priority) {
    const v = obj[k];
    if (typeof v === "string" && v.length > 0) return v;
  }
  return null;
}

function countGrepMatches(response: unknown): number | null {
  if (!response) return null;
  if (Array.isArray(response)) return response.length;
  const r = obj(response);
  if (!r) return null;
  if (Array.isArray(r.matches)) return r.matches.length;
  if (Array.isArray(r.files)) return r.files.length;
  if (typeof r.count === "number") return r.count;
  if (typeof r.numFiles === "number") return r.numFiles;
  return null;
}

function countFiles(response: unknown): number | null {
  if (Array.isArray(response)) return response.length;
  const r = obj(response);
  if (!r) return null;
  if (Array.isArray(r.files)) return r.files.length;
  if (Array.isArray(r.paths)) return r.paths.length;
  return null;
}

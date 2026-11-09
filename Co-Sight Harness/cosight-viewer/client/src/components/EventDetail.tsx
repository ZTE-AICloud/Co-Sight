// SPDX-License-Identifier: Apache-2.0
/**
 * @file EventDetail.tsx
 * @description Inline detail view rendered below an event row when expanded.
 * Shows a human-readable summary at the top, then every top-level JSON key
 * from the hook payload as a single row. For `tool_input` and `tool_response`
 * on recognised tools, rows use tool-aware renderers (terminal blocks, diffs,
 * line-numbered code, match lists) instead of the generic JSON code view.
 */

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { DashboardEvent } from "../lib/types";
import type { AgentInfo } from "../lib/event-grouping";
import { buildEventSummary } from "../lib/event-summary";
import { formatModelName, formatDateTimeFull } from "../lib/format";
import { CopyButton } from "./event-views/primitives";
import { ToolInputView, ToolResponseView } from "./event-views/tool-views";

type EventDetailProps = {
  event: DashboardEvent;
  /** Optional lookup so the panel can surface a human-friendly agent name
   *  (e.g. "technical-researcher · Subagent 14") next to the raw agent_id.
   *  Callers that already have the session's agent map (EventGroupRow,
   *  SessionDetail) should pass it; older callers can omit it and the panel
   *  falls back to id-only display. */
  agentInfoById?: Map<string, AgentInfo>;
  /** Optional lookup so the panel can surface a human-friendly session
   *  label (e.g. "AI-Assistant-Chatbot (enumerated-wandering-jellyfish)")
   *  next to the raw session_id. Same fallback rules as agentInfoById. */
  sessionNameById?: Map<string, string>;
};

/** Human-friendly label for an agent — `subagent_type · name` when both add
 *  signal, else whichever single field is present. Returns null for main
 *  agents whose name is just the session label (the agent_id row already
 *  carries the structural marker `<session>-main`, no need to repeat it). */
function agentDisplayLabel(info: AgentInfo): string | null {
  if (info.type === "main") {
    return info.name && info.name.trim().length > 0 ? info.name : null;
  }
  const type = info.subagent_type?.trim();
  const name = info.name?.trim();
  if (type && name && name !== type) return `${type} · ${name}`;
  if (type) return type;
  if (name) return name;
  return null;
}

// Keys from the payload that are already rendered from event-level fields —
// skip them to avoid showing the same value twice. Includes `id` and
// `event_id` defensively in case a future hook payload surfaces them.
const DUPLICATE_KEYS = new Set(["id", "event_id", "session_id", "agent_id"]);

/** Map raw payload keys to localized i18n labels under common:eventDetail.
 *  Anything not in this map falls back to humanizeKey() so users still see
 *  a tidy "Tool Name" rather than "tool_name". */
const PAYLOAD_LABEL_KEYS: Record<string, string> = {
  tool_name: "eventDetail.toolName",
  tool_use_id: "eventDetail.toolUseId",
  tool_input: "eventDetail.toolInput",
  tool_response: "eventDetail.toolResponse",
  is_error: "eventDetail.isError",
  cwd: "eventDetail.cwd",
  permission_mode: "eventDetail.permissionMode",
  transcript_path: "eventDetail.transcriptPath",
  agent_transcript_path: "eventDetail.agentTranscriptPath",
  hook_event_name: "eventDetail.hookEventName",
  stop_reason: "eventDetail.stopReason",
  stop_hook_active: "eventDetail.stopHookActive",
  subagent_type: "eventDetail.subagentType",
  agent_type: "eventDetail.agentType",
  notification_type: "eventDetail.notificationType",
  message: "eventDetail.message",
  prompt: "eventDetail.prompt",
  model: "eventDetail.model",
  reason: "eventDetail.reason",
  source: "eventDetail.source",
  imported: "eventDetail.imported",
  type: "eventDetail.type",
  timestamp: "eventDetail.timestamp",
  uuid: "eventDetail.uuid",
  duration_ms: "eventDetail.durationMs",
  durationMs: "eventDetail.durationMs",
  compaction_number: "eventDetail.compactionNumber",
  total_compactions: "eventDetail.totalCompactions",
  last_assistant_message: "eventDetail.lastAssistantMessage",
};

/** Convert `snake_case` / `camelCase` to a human-readable Title Case label
 *  for any payload key not in PAYLOAD_LABEL_KEYS. Defensive fallback so
 *  every row reads naturally even when a new hook field appears. */
function humanizeKey(key: string): string {
  return key
    .replace(/[_-]+/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

type Row = { key: string; label: string; value: unknown };

export function EventDetail({ event, agentInfoById, sessionNameById }: EventDetailProps) {
  const { t } = useTranslation("common");

  const parsed = useMemo<Record<string, unknown> | null>(() => {
    if (!event.data) return null;
    try {
      const v = JSON.parse(event.data);
      return v && typeof v === "object" && !Array.isArray(v)
        ? (v as Record<string, unknown>)
        : null;
    } catch {
      return null;
    }
  }, [event.data]);

  const summary = useMemo(() => buildEventSummary(event), [event]);

  const rows = useMemo<Row[]>(() => {
    const result: Row[] = [{ key: "event_id", label: t("eventDetail.eventId"), value: event.id }];
    // Full date + time + timezone — list rows only show a short time, so the
    // detail panel spells out exactly when the event was recorded.
    if (event.created_at) {
      result.push({
        key: "recorded_at",
        label: t("eventDetail.recordedAt", "Recorded at"),
        value: formatDateTimeFull(event.created_at),
      });
    }
    // Surface the session name above the raw id when we can resolve it —
    // makes "f2f3c568-..." recognisable as e.g. "AI-Assistant-Chatbot
    // (enumerated-wandering-jellyfish)" without losing the id below.
    const sessionName = sessionNameById?.get(event.session_id);
    if (sessionName && sessionName.trim().length > 0) {
      result.push({ key: "session_name", label: t("eventDetail.session"), value: sessionName });
    }
    result.push({
      key: "session_id",
      label: t("eventDetail.sessionId"),
      value: event.session_id,
    });
    if (event.agent_id) {
      // Surface the agent name above the raw id when we can resolve it —
      // makes "f2f3c568-...-subagent-14" recognisable as e.g.
      // "technical-researcher · Subagent 14" without losing the id below.
      const info = agentInfoById?.get(event.agent_id);
      const displayName = info ? agentDisplayLabel(info) : null;
      if (displayName) {
        result.push({ key: "agent_name", label: t("eventDetail.agent"), value: displayName });
      }
      result.push({ key: "agent_id", label: t("eventDetail.agentId"), value: event.agent_id });
    }

    const payloadEntries: Array<[string, unknown]> = parsed
      ? Object.entries(parsed).filter(([k]) => !DUPLICATE_KEYS.has(k))
      : [];
    for (const [k, v] of payloadEntries) {
      // Known keys → localized label; unknown keys → humanized fallback
      // (snake_case → "Snake Case") so the panel never surfaces raw JSON
      // identifiers in the row labels.
      const i18nKey = PAYLOAD_LABEL_KEYS[k];
      const label = i18nKey ? t(i18nKey) : humanizeKey(k);
      result.push({
        key: k,
        label,
        value: k === "model" && typeof v === "string" ? (formatModelName(v) ?? v) : v,
      });
    }

    // If JSON parse failed, show the raw data as a single row using the
    // localized raw-payload label rather than a hardcoded "data" string.
    if (!parsed && event.data) {
      result.push({ key: "data", label: t("eventDetail.rawPayload"), value: event.data });
    }

    return result;
  }, [
    event.id,
    event.session_id,
    event.agent_id,
    event.data,
    parsed,
    agentInfoById,
    sessionNameById,
    t,
  ]);

  const hasToolInput = parsed != null && "tool_input" in parsed;
  const hasToolResponse = parsed != null && "tool_response" in parsed;

  return (
    <div className="bg-surface-2 border-t border-border/40 px-5 py-4 animate-slide-up space-y-3">
      {summary && (
        <SummaryBlock
          summary={summary}
          hasToolInput={hasToolInput}
          hasToolResponse={hasToolResponse}
        />
      )}
      <div className="space-y-2">
        {rows.map((row) => (
          <FieldRow
            key={row.key}
            rowKey={row.key}
            label={row.label}
            value={row.value}
            toolName={event.tool_name}
          />
        ))}
      </div>
    </div>
  );
}

// ───────────────────────── Summary block ─────────────────────────

function SummaryBlock({
  summary,
  hasToolInput,
  hasToolResponse,
}: {
  summary: { icon: string; headline: string; bullets: string[] };
  hasToolInput: boolean;
  hasToolResponse: boolean;
}) {
  const { t } = useTranslation("common");
  const refs: string[] = [];
  if (hasToolInput) refs.push("tool_input");
  if (hasToolResponse) refs.push("tool_response");
  const hint =
    refs.length > 0 ? t("eventDetail.seeDetailsBelow", { fields: refs.join(" · ") }) : null;
  return (
    <div className="border border-border/50 rounded overflow-hidden bg-surface-2">
      <div className="px-3 py-1 border-b border-border/40 bg-surface-3">
        <span className="text-faint text-[10px] uppercase tracking-wide font-semibold">
          {t("eventDetail.summary")}
        </span>
      </div>
      <div className="p-3 space-y-1.5">
        <div className="flex items-start gap-2">
          <span className="text-base leading-none" aria-hidden="true">
            {summary.icon}
          </span>
          <span className="text-[12px] text-secondary font-medium break-words">
            {summary.headline}
          </span>
        </div>
        {summary.bullets.length > 0 && (
          <ul className="list-disc pl-6 space-y-0.5 text-[11px] text-muted">
            {summary.bullets.map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
        )}
        {hint && (
          <div className="text-[11px] text-faint italic pt-1 border-t border-border/50/40">
            ↓ {hint}
          </div>
        )}
      </div>
    </div>
  );
}

// ───────────────────────── Field row ─────────────────────────

function FieldRow({
  rowKey,
  label,
  value,
  toolName,
}: {
  /** Raw payload key — used for tool-aware routing decisions so the renderer
   *  doesn't break when the user-visible label is translated. */
  rowKey: string;
  label: string;
  value: unknown;
  toolName: string | null;
}) {
  // Route tool_input / tool_response through tool-aware renderers when the
  // tool is known. Unknown tools (or unknown shape for known tools) fall back
  // to the generic CodeView below.
  if (rowKey === "tool_input") {
    const view = ToolInputView({ toolName, input: value });
    if (view) {
      return (
        <div className="grid grid-cols-[160px_1fr] gap-x-4 items-start text-[11px]">
          <div className="text-faint font-mono pt-2">{label}</div>
          <div>{view}</div>
        </div>
      );
    }
  }
  if (rowKey === "tool_response") {
    const view = ToolResponseView({ toolName, response: value });
    if (view) {
      return (
        <div className="grid grid-cols-[160px_1fr] gap-x-4 items-start text-[11px]">
          <div className="text-faint font-mono pt-2">{label}</div>
          <div>{view}</div>
        </div>
      );
    }
  }

  if (isInlineScalar(value)) {
    return (
      <div className="grid grid-cols-[160px_1fr] gap-x-4 items-start text-[11px]">
        <div className="text-faint font-mono pt-0.5">{label}</div>
        <div className="text-faint font-mono break-all">
          <ScalarValue value={value} />
        </div>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-[160px_1fr] gap-x-4 items-start text-[11px]">
      <div className="text-faint font-mono pt-2">{label}</div>
      <CodeView value={value} />
    </div>
  );
}

function isInlineScalar(value: unknown): boolean {
  if (value == null) return true;
  if (typeof value === "boolean" || typeof value === "number") return true;
  if (typeof value === "string") return !value.includes("\n") && value.length <= 120;
  return false;
}

function ScalarValue({ value }: { value: unknown }) {
  if (value == null) return <span className="text-muted italic">null</span>;
  if (typeof value === "boolean") {
    const color = value
      ? "text-green-400 border-green-500/30 bg-green-500/10"
      : "text-tertiary border-muted/30 bg-muted/10";
    return (
      <span className={`inline-block px-2 py-0.5 rounded border ${color}`}>{String(value)}</span>
    );
  }
  return <>{String(value)}</>;
}

// ───────────────────────── Terminal-styled JSON code view (fallback) ─────────────────────────

function CodeView({ value }: { value: unknown }) {
  const text = typeof value === "string" ? value : safeStringify(value);

  return (
    <div className="relative bg-surface-2/60 border border-border/50 rounded font-mono text-[11px] overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border bg-surface-1/40">
        <span className="text-muted text-[10px] uppercase tracking-wide">
          {typeof value === "string" ? "text" : Array.isArray(value) ? "array" : "json"}
        </span>
        <CopyButton text={text} />
      </div>
      <pre className="px-3 py-2 text-secondary whitespace-pre-wrap break-words max-h-96 overflow-auto">
        {text}
      </pre>
    </div>
  );
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

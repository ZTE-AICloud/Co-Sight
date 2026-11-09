// SPDX-License-Identifier: Apache-2.0
/**
 * @file EventFilters.tsx
 * @description Filter toolbar for the event list. Surfaces every filter the
 * backend supports on /api/events — event_type, tool_name, agent_id,
 * session_id, free-text search, and an ISO date range — as a single
 * controlled component. Parent owns the filter state; this component only
 * renders the inputs and emits change events.
 */

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { Search, X, Filter } from "lucide-react";
import { api } from "../lib/api";
import { DateTimePicker } from "./DateTimePicker";

export type EventFiltersValue = {
  event_type: string[];
  tool_name: string[];
  agent_id: string[];
  session_id: string[];
  status: string[];
  q: string;
  from: string;
  to: string;
};

export const EMPTY_FILTERS: EventFiltersValue = {
  event_type: [],
  tool_name: [],
  agent_id: [],
  session_id: [],
  status: [],
  q: "",
  from: "",
  to: "",
};

export function isEmptyFilters(f: EventFiltersValue): boolean {
  return (
    f.event_type.length === 0 &&
    f.tool_name.length === 0 &&
    f.agent_id.length === 0 &&
    f.session_id.length === 0 &&
    f.status.length === 0 &&
    f.q === "" &&
    f.from === "" &&
    f.to === ""
  );
}

// Status preset → event_type values. Mirrors the status badges shown on event
// rows (see ActivityFeed/SessionDetail statusFromEventType). "Idle" is handled
// as everything not covered by the other presets, which translates to an empty
// preset that doesn't restrict the query (same as no selection).
export const STATUS_TO_EVENT_TYPES: Record<string, string[]> = {
  working: ["PreToolUse"],
  waiting: ["PostToolUse", "Stop"],
  completed: ["Stop", "SubagentStop", "Compaction"],
  error: ["error", "APIError"],
};

export const STATUS_OPTIONS = ["working", "waiting", "completed", "error"] as const;

// Expand the selected status presets into a union of event_type values. The
// consumer merges this with any explicit event_type selection so both layers
// can be combined (selecting "Working" AND a specific event_type still works
// as an OR inside the single `event_type` API param).
export function expandStatusToEventTypes(statuses: string[]): string[] {
  const out = new Set<string>();
  for (const s of statuses) {
    const list = STATUS_TO_EVENT_TYPES[s];
    if (list) for (const et of list) out.add(et);
  }
  return Array.from(out);
}

type EventFiltersProps = {
  value: EventFiltersValue;
  onChange: (next: EventFiltersValue) => void;
  // If set, hides the session filter — useful inside SessionDetail where the
  // session is already implicit.
  hideSessionFilter?: boolean;
  // Optional pre-known agent ids (SessionDetail passes the agents from its
  // parent query instead of fetching /agents again).
  agentOptions?: Array<{ id: string; label: string }>;
  // Optional pre-known session ids (ActivityFeed passes session options).
  sessionOptions?: Array<{ id: string; label: string }>;
};

export function EventFilters({
  value,
  onChange,
  hideSessionFilter,
  agentOptions,
  sessionOptions,
}: EventFiltersProps) {
  const { t } = useTranslation("common");
  const [facets, setFacets] = useState<{ event_types: string[]; tool_names: string[] }>({
    event_types: [],
    tool_names: [],
  });
  const [searchDraft, setSearchDraft] = useState(value.q);

  // Debounce text search — only push up after 300ms of inactivity.
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => {
      if (searchDraft !== value.q) onChange({ ...value, q: searchDraft });
    }, 300);
    return () => {
      if (searchTimer.current) clearTimeout(searchTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchDraft]);

  // Keep draft in sync when parent clears filters.
  useEffect(() => {
    if (value.q !== searchDraft) setSearchDraft(value.q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value.q]);

  useEffect(() => {
    let cancelled = false;
    api.events
      .facets()
      .then((data) => {
        if (!cancelled) setFacets(data);
      })
      .catch(() => {
        // Non-fatal: filters still work via text input.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const toggle = (field: keyof EventFiltersValue, item: string) => {
    const current = value[field];
    if (!Array.isArray(current)) return;
    const next = current.includes(item) ? current.filter((x) => x !== item) : [...current, item];
    onChange({ ...value, [field]: next });
  };

  const empty = isEmptyFilters(value);

  return (
    <div className="rounded-lg border border-border/50 dark:border-border/30 bg-surface-2 dark:bg-surface-3/30 p-3 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Filter className="w-3.5 h-3.5 text-faint dark:text-faint/80 flex-shrink-0" />
        <div className="relative flex-1 min-w-[180px]">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-faint" />
          <input
            type="text"
            value={searchDraft}
            onChange={(e) => setSearchDraft(e.target.value)}
            placeholder={t("eventFilters.searchPlaceholder")}
            aria-label={t("eventFilters.searchPlaceholder")}
            className="w-full bg-surface-1 dark:bg-surface-2 border border-border/50 dark:border-border/30 rounded pl-7 pr-2 py-1.5 text-xs text-tertiary dark:text-secondary placeholder-gray-400 dark:placeholder:text-faint/60 focus:outline-none focus:border-indigo-300 dark:focus:border-indigo-500/50"
          />
        </div>
        <DateTimePicker
          value={value.from}
          onChange={(val: string) => onChange({ ...value, from: val })}
          aria-label={t("eventFilters.from")}
          title={t("eventFilters.from")}
          placeholder={t("eventFilters.from")}
          defaultTime={{ hours: 0, minutes: 0 }}
        />
        <span className="text-xs text-faint">→</span>
        <DateTimePicker
          value={value.to}
          onChange={(val: string) => onChange({ ...value, to: val })}
          aria-label={t("eventFilters.to")}
          title={t("eventFilters.to")}
          placeholder={t("eventFilters.to")}
          defaultTime={{ hours: 23, minutes: 59 }}
        />
        {!empty && (
          <button
            type="button"
            onClick={() => onChange(EMPTY_FILTERS)}
            className="flex items-center gap-1 text-[11px] px-2 py-1 rounded text-faint hover:text-tertiary hover:bg-surface-3 cursor-pointer"
            aria-label={t("eventFilters.clearAll")}
          >
            <X className="w-3 h-3" />
            {t("eventFilters.clearAll")}
          </button>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <ChipGroup
          label={t("eventFilters.status")}
          options={[...STATUS_OPTIONS]}
          labels={{
            working: t("status.working"),
            waiting: t("status.waiting"),
            completed: t("status.completed"),
            error: t("status.error"),
          }}
          selected={value.status}
          onToggle={(item) => toggle("status", item)}
        />
        <ChipGroup
          label={t("eventFilters.eventType")}
          options={facets.event_types}
          selected={value.event_type}
          onToggle={(item) => toggle("event_type", item)}
        />
        <ChipGroup
          label={t("eventFilters.toolName")}
          options={facets.tool_names}
          selected={value.tool_name}
          onToggle={(item) => toggle("tool_name", item)}
        />
        {agentOptions && agentOptions.length > 0 && (
          <ChipGroup
            label={t("eventFilters.agentId")}
            options={agentOptions.map((a) => a.id)}
            labels={Object.fromEntries(agentOptions.map((a) => [a.id, a.label]))}
            selected={value.agent_id}
            onToggle={(item) => toggle("agent_id", item)}
          />
        )}
        {!hideSessionFilter && sessionOptions && sessionOptions.length > 0 && (
          <ChipGroup
            label={t("eventFilters.sessionId")}
            options={sessionOptions.map((s) => s.id)}
            labels={Object.fromEntries(sessionOptions.map((s) => [s.id, s.label]))}
            selected={value.session_id}
            onToggle={(item) => toggle("session_id", item)}
          />
        )}
      </div>
    </div>
  );
}

function ChipGroup({
  label,
  options,
  selected,
  onToggle,
  labels,
}: {
  label: string;
  options: string[];
  selected: string[];
  onToggle: (item: string) => void;
  labels?: Record<string, string>;
}) {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  const updatePos = () => {
    const rect = btnRef.current?.getBoundingClientRect();
    if (rect) setPos({ top: rect.bottom + 4, left: rect.left });
  };

  // Click-outside dismiss + reposition on scroll/resize while open.
  useEffect(() => {
    if (!open) return;
    updatePos();
    const handler = (e: MouseEvent) => {
      // Keep open if clicking the toggle button or inside the portal dropdown.
      if (btnRef.current?.contains(e.target as Node)) return;
      const listbox = document.getElementById(`chip-listbox-${label}`);
      if (listbox && listbox.contains(e.target as Node)) return;
      setOpen(false);
    };
    const onScroll = () => updatePos();
    document.addEventListener("mousedown", handler);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => {
      document.removeEventListener("mousedown", handler);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, [open, label]);

  const selectedCount = selected.length;

  return (
    <div className="relative">
      <button
        ref={btnRef}
        type="button"
        onClick={() => {
          updatePos();
          setOpen((v) => !v);
        }}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={`text-[11px] px-2 py-1 rounded border cursor-pointer flex items-center gap-1.5 transition-colors ${
          selectedCount > 0
            ? "border-indigo-300 dark:border-indigo-500/50 bg-indigo-50 dark:bg-indigo-500/15 text-indigo-700 dark:text-indigo-300"
            : "border-border/30 dark:border-border/30 bg-surface-1 dark:bg-surface-3/50 text-faint dark:text-faint/80 hover:text-tertiary dark:hover:text-secondary hover:bg-surface-2 dark:hover:bg-surface-3"
        }`}
      >
        <span>{label}</span>
        {selectedCount > 0 && (
          <span className="bg-indigo-100 dark:bg-indigo-500/25 text-indigo-700 dark:text-indigo-300 rounded px-1.5 font-mono">{selectedCount}</span>
        )}
      </button>
      {open && createPortal(
        <div
          id={`chip-listbox-${label}`}
          role="listbox"
          aria-label={label}
          className="fixed z-[9999] min-w-[220px] max-h-64 overflow-auto bg-surface-1 dark:bg-surface-3 border border-border/50 dark:border-border/40 rounded-lg shadow-xl dark:shadow-black/50 p-1.5"
          style={{ top: pos.top, left: pos.left }}
        >
          {options.length === 0 ? (
            <p className="text-[11px] text-faint dark:text-faint/70 px-2 py-1 italic">
              {t("eventFilters.noOptions")}
            </p>
          ) : (
            options.map((opt) => {
              const checked = selected.includes(opt);
              const display = labels?.[opt] ?? opt;
              return (
                <label
                  key={opt}
                  className="flex items-center gap-2 px-2 py-1 text-[11px] text-muted dark:text-secondary rounded hover:bg-surface-3 dark:hover:bg-surface-4/70 cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => onToggle(opt)}
                    className="accent-indigo-500"
                  />
                  <span className="font-mono break-all">{display}</span>
                </label>
              );
            })
          )}
        </div>,
        document.body
      )}
    </div>
  );
}

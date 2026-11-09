// SPDX-License-Identifier: Apache-2.0
/**
 * @file EventGroupRow.tsx
 * @description Compact row that represents one EventGroup (one tool_use_id, or
 * a single standalone event). Shows a status progression of the underlying
 * events — e.g. 🟢 → 🔵 for a Pre/Post pair — plus tool name, summary, and
 * the wall-clock duration between first and last event. Clicking the chevron
 * expands the group inline to reveal each underlying event row.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronRight } from "lucide-react";
import { AgentStatusBadge } from "./StatusBadge";
import { EventDetail } from "./EventDetail";
import { formatTime, formatDateShort, timeAgo } from "../lib/format";
import {
  agentOriginLabel,
  buildEventTitle,
  buildGroupTitle,
  buildOriginLabel,
  formatGroupDuration,
  projectFromEvent,
  statusFromEventType,
} from "../lib/event-grouping";
import type { AgentInfo, EventGroup } from "../lib/event-grouping";

type EventGroupRowProps = {
  group: EventGroup;
  /** Called when the row's click area (time/summary) is activated. Allows
   *  callers to navigate to the session or do nothing. */
  onRowActivate?: () => void;
  /** Optional map of session_id → session name, used to render a session pill
   *  next to the row. Pass empty / omit to hide the pill. */
  sessionNameById?: Map<string, string>;
  /** Optional map of agent_id → AgentInfo, used to render a subagent pill
   *  showing the subagent_type (e.g. "frontend-reviewer") rather than the raw
   *  ID. Omit to fall back to a truncated ID label. */
  agentInfoById?: Map<string, AgentInfo>;
};

export function EventGroupRow({
  group,
  onRowActivate,
  sessionNameById,
  agentInfoById,
}: EventGroupRowProps) {
  const { t } = useTranslation("common");
  const [expanded, setExpanded] = useState(false);
  const [expandedInner, setExpandedInner] = useState<Set<number>>(() => new Set());

  const statusSequence = dedupeConsecutive(
    group.events.map((e) => statusFromEventType(e.event_type))
  );
  const duration = formatGroupDuration(group.durationMs);
  // Every group is expandable — single-event groups show the EventDetail
  // directly; multi-event groups show a nested list where each event can be
  // expanded individually.
  const canExpand = group.events.length >= 1;
  const isSingleEvent = group.events.length === 1;

  function toggleInner(id: number) {
    setExpandedInner((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // Multi-event groups (actual Pre/Post pairs, tool-call chains) get a subtle
  // teal left-border and tinted background so they're visually distinct from
  // standalone single-event rows at a glance.
  const isMultiGroup = !isSingleEvent;
  const rowBg = isMultiGroup
    ? "bg-surface-2 hover:bg-surface-3 border-l-2 border-border/60"
    : "hover:bg-surface-2 border-l-2 border-transparent";

  return (
    <div>
      <div className={`flex items-center px-5 py-3 gap-4 transition-colors min-w-0 ${rowBg}`}>
        <button
          type="button"
          onClick={() => canExpand && setExpanded((v) => !v)}
          aria-expanded={expanded}
          aria-label={expanded ? "Collapse group" : "Expand group"}
          disabled={!canExpand}
          className={`p-1 rounded flex-shrink-0 -mr-3 ${
            canExpand ? "text-faint hover:text-muted cursor-pointer" : "text-transparent"
          }`}
        >
          <ChevronRight
            className={`w-3.5 h-3.5 transition-transform ${expanded ? "rotate-90" : ""}`}
          />
        </button>

        <div
          className="flex items-center gap-2.5 flex-1 min-w-0 cursor-pointer"
          onClick={() => (onRowActivate ? onRowActivate() : canExpand && setExpanded((v) => !v))}
        >
          <div className="w-16 flex-shrink-0 text-right font-mono leading-tight">
            <div className="text-[11px] text-faint">{formatTime(group.firstAt)}</div>
            <div className="text-[9px] text-faint">{formatDateShort(group.firstAt)}</div>
          </div>

          <div className="flex items-center gap-1 flex-shrink-0">
            {statusSequence.map((status, i) => (
              <div key={i} className="flex items-center gap-1">
                {i > 0 && <span className="text-faint text-[10px]">→</span>}
                <AgentStatusBadge status={status} />
              </div>
            ))}
          </div>

          {(() => {
            const first = group.events[0];
            const sid = first?.session_id;
            const sname = sid ? sessionNameById?.get(sid) : undefined;
            const agentId = first?.agent_id ?? null;
            const project = first ? projectFromEvent(first) : null;
            const origin = buildOriginLabel(
              project,
              sname ?? null,
              agentOriginLabel(agentId, agentInfoById)
            );
            return (
              <div className="flex-1 min-w-0">
                <p className="text-sm text-faint truncate">
                  {origin && (
                    <span className="text-faint mr-1" title={`${sid ?? ""} · ${agentId ?? ""}`}>
                      {origin} ·
                    </span>
                  )}
                  {buildGroupTitle(group)}
                </p>
              </div>
            );
          })()}

          {group.tool_name && (
            <span className="text-[11px] px-2 py-0.5 bg-surface-3 rounded text-muted font-mono flex-shrink-0">
              {group.tool_name}
            </span>
          )}

          {duration && (
            <span className="text-[11px] text-faint font-mono flex-shrink-0">{duration}</span>
          )}

          <span className="text-[11px] text-faint flex-shrink-0 w-16 text-right">
            {timeAgo(group.firstAt)}
          </span>
        </div>
      </div>

      {expanded && isSingleEvent && group.events[0] && (
        <EventDetail
          event={group.events[0]}
          agentInfoById={agentInfoById}
          sessionNameById={sessionNameById}
        />
      )}

      {expanded && !isSingleEvent && (
        <div className="bg-surface-2 border-t border-border/40 divide-y divide-gray-100">
          <div className="px-5 py-1.5 text-[10px] text-faint uppercase tracking-wide">
            {t("eventFilters.groupEventCount", { count: group.events.length })}
          </div>
          {group.events.map((event) => {
            const innerOpen = event.id != null && expandedInner.has(event.id);
            return (
              <div key={event.id}>
                <button
                  type="button"
                  onClick={() => event.id != null && toggleInner(event.id)}
                  aria-expanded={innerOpen}
                  aria-label={innerOpen ? t("eventDetail.collapse") : t("eventDetail.expand")}
                  className="w-full text-left px-5 py-2 flex items-center gap-4 min-w-0 hover:bg-surface-3 transition-colors cursor-pointer"
                >
                  <span
                    className={`text-faint text-[10px] w-3 flex-shrink-0 transition-transform ${innerOpen ? "rotate-90" : ""}`}
                    aria-hidden="true"
                  >
                    ▶
                  </span>
                  <div className="w-20 flex-shrink-0 text-right font-mono leading-tight">
                    <div className="text-[11px] text-faint">{formatTime(event.created_at)}</div>
                    <div className="text-[9px] text-faint">{formatDateShort(event.created_at)}</div>
                  </div>
                  <AgentStatusBadge status={statusFromEventType(event.event_type)} />
                  <span className="text-[11px] text-faint font-mono flex-shrink-0">
                    {event.event_type}
                  </span>
                  <span className="text-[11px] text-faint flex-1 truncate">
                    {buildEventTitle(event)}
                  </span>
                </button>
                {innerOpen && (
                  <EventDetail
                    event={event}
                    agentInfoById={agentInfoById}
                    sessionNameById={sessionNameById}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function dedupeConsecutive<T>(arr: T[]): T[] {
  const out: T[] = [];
  for (const item of arr) {
    if (out.length === 0 || out[out.length - 1] !== item) out.push(item);
  }
  return out;
}

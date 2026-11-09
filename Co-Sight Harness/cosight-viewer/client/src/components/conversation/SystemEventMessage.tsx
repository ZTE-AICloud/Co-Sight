// SPDX-License-Identifier: Apache-2.0
/**
 * @file SystemEventMessage.tsx
 * @description Renders system events (TurnDuration, Compaction, APIError) as
 * System-role messages in the conversation timeline. Visually distinct from
 * User/Assistant messages with muted colors and a settings icon.
 */
import { Settings, Zap, AlertTriangle, RefreshCw } from "lucide-react";
import type { SystemEvent } from "../../lib/types";

interface SystemEventMessageProps {
  event: SystemEvent;
}

/** Compact local time formatter (e.g. "14:23:01"). */
function formatLocalTime(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return "";
  }
}

const ICONS = {
  turn_duration: RefreshCw,
  compaction: Zap,
  api_error: AlertTriangle,
};

const COLORS = {
  turn_duration: {
    bar: "before:bg-cyan-400",
    ring: "bg-gradient-to-br from-cyan-100 to-teal-100 text-cyan-600 ring-1 ring-cyan-200",
    label: "text-cyan-600",
  },
  compaction: {
    bar: "before:bg-amber-400",
    ring: "bg-gradient-to-br from-amber-100 to-orange-100 text-amber-600 ring-1 ring-amber-200",
    label: "text-amber-600",
  },
  api_error: {
    bar: "before:bg-red-400",
    ring: "bg-gradient-to-br from-red-100 to-rose-100 text-red-600 ring-1 ring-red-200",
    label: "text-red-600",
  },
};

/**
 * System event rendered as a message in the conversation timeline.
 * Layout matches User/Assistant messages; subtype color accents distinguish
 * TurnDuration / Compaction / APIError.
 */
export function SystemEventMessage({ event }: SystemEventMessageProps) {
  const Icon = ICONS[event.subtype] || Settings;
  const colors = COLORS[event.subtype] || COLORS.turn_duration;

  return (
    <div
      className={`relative flex gap-3 rounded-xl px-3 py-2.5 hover:bg-surface-2/30 transition-colors before:absolute before:left-0 before:top-3 before:bottom-3 before:w-0.5 before:rounded-full before:opacity-60 ${colors.bar}`}
    >
      {/* Avatar */}
      <div
        className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center mt-0.5 shadow-sm ${colors.ring}`}
      >
        <Icon className="w-4 h-4" />
      </div>

      {/* Message body */}
      <div className="flex-1 min-w-0 space-y-1">
        {/* Header line */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-xs font-semibold tracking-wide ${colors.label}`}>
            System
          </span>
          <span className="text-[10px] text-faint font-mono">
            {event.subtype.replace("_", " ")}
          </span>
          {event.timestamp && (
            <span className="text-[10px] text-faint font-mono ml-auto">
              {formatLocalTime(event.timestamp)}
            </span>
          )}
        </div>

        {/* Summary */}
        <div className="text-sm text-muted leading-relaxed">
          {event.data.summary}
        </div>

        {/* Additional details for turn_duration */}
        {event.subtype === "turn_duration" && event.data.durationMs != null && (
          <div className="text-[11px] text-faint font-mono">
            Duration: {(event.data.durationMs / 1000).toFixed(2)}s
          </div>
        )}

        {/* Additional details for compaction */}
        {event.subtype === "compaction" && event.data.compaction_number != null && (
          <div className="text-[11px] text-faint font-mono">
            #{event.data.compaction_number}
            {event.data.total_compactions != null &&
              ` of ${event.data.total_compactions}`}
          </div>
        )}

        {/* Additional details for api_error */}
        {event.subtype === "api_error" && event.data.error_type && (
          <div className="text-[11px] text-faint font-mono">
            Type: {event.data.error_type}
          </div>
        )}
      </div>
    </div>
  );
}

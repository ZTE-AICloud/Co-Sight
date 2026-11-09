// SPDX-License-Identifier: Apache-2.0
/**
 * @file SessionOverview.tsx
 * @description Real-time stats panel rendered at the top of the Agents tab on the
 * Session detail page. Shows tile counters (events, tool calls, subagents, errors,
 * compactions, duration), top-tool usage bars, subagent-type breakdown, and a token
 * flow strip. Live-refreshes on `new_event` (debounced) so counters track the running
 * session without spamming the backend.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  Wrench,
  GitBranch,
  AlertTriangle,
  Layers,
  Clock,
  Coins,
  Bot,
} from "lucide-react";
import { api } from "../lib/api";
import { eventBus } from "../lib/eventBus";
import { fmt, formatDuration } from "../lib/format";
import { styleForTool } from "./conversation/toolStyle";
import type { Agent, Session, SessionStats } from "../lib/types";

interface SessionOverviewProps {
  session: Session;
  agents: Agent[];
}

/** Debounce window for stats refresh — coalesces bursts of hook events into one fetch. */
const REFRESH_DEBOUNCE_MS = 600;

/** Compact tile used in the top stat row. */
function StatTile({
  label,
  value,
  hint,
  icon,
  tone = "default",
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  icon: React.ReactNode;
  tone?: "default" | "violet" | "emerald" | "amber" | "rose" | "cyan" | "blue";
}) {
  const palette = {
    default: "border-border/30 dark:border-border/20 bg-surface-2 dark:bg-surface-3/40 text-tertiary dark:text-secondary",
    violet: "border-violet-200 dark:border-violet-500/30 bg-violet-50 dark:bg-violet-500/10 text-violet-700 dark:text-violet-300",
    emerald: "border-emerald-200 dark:border-emerald-500/30 bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
    amber: "border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300",
    rose: "border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-300",
    cyan: "border-cyan-200 dark:border-cyan-500/30 bg-cyan-50 dark:bg-cyan-500/10 text-cyan-700 dark:text-cyan-300",
    blue: "border-blue-200 dark:border-blue-500/30 bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-300",
  }[tone];

  const iconTone = {
    default: "text-faint dark:text-faint",
    violet: "text-violet-500 dark:text-violet-400",
    emerald: "text-emerald-500 dark:text-emerald-400",
    amber: "text-amber-500 dark:text-amber-400",
    rose: "text-red-500 dark:text-red-400",
    cyan: "text-cyan-500 dark:text-cyan-400",
    blue: "text-blue-500 dark:text-blue-400",
  }[tone];

  return (
    <div className={`rounded-lg border px-3 py-2.5 transition-colors ${palette}`}>
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-faint dark:text-faint/80">
        <span className={iconTone}>{icon}</span>
        {label}
      </div>
      <div className="mt-1 font-mono text-lg font-semibold text-secondary dark:text-primary leading-tight">
        {value}
      </div>
      {hint && <div className="text-[10px] text-faint dark:text-faint/70 mt-0.5">{hint}</div>}
    </div>
  );
}

function ToolUsageRow({ toolName, count, max }: { toolName: string; count: number; max: number }) {
  const style = styleForTool(toolName);
  const Icon = style.Icon;
  const pct = max > 0 ? Math.max(2, Math.round((count / max) * 100)) : 0;

  return (
    <div className="flex items-center gap-3 group/tool">
      <div className={`flex items-center gap-2 w-32 flex-shrink-0 ${style.text}`}>
        <span
          className={`inline-flex items-center justify-center w-5 h-5 rounded ${style.chip} flex-shrink-0`}
        >
          <Icon className="w-3 h-3" />
        </span>
        <span className="font-mono text-xs truncate" title={toolName}>
          {toolName}
        </span>
      </div>
      <div className="flex-1 h-1.5 rounded-full bg-gray-200 dark:bg-surface-4 overflow-hidden">
        <div
          className={`h-full rounded-full ${style.bar} transition-all duration-500`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="font-mono text-xs text-faint w-14 text-right flex-shrink-0">
        {count.toLocaleString()}
      </span>
    </div>
  );
}

export function SessionOverview({ session, agents }: SessionOverviewProps) {
  const [stats, setStats] = useState<SessionStats | null>(null);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fetchingRef = useRef(false);

  // Tick clock every 30s so a still-active session's "duration" tile stays current.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (session.status !== "active") return;
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, [session.status]);

  const fetchStats = async () => {
    if (fetchingRef.current) return;
    fetchingRef.current = true;
    try {
      const result = await api.sessions.stats(session.id);
      setStats(result);
    } catch {
      // Non-fatal — overview just won't update this round.
    } finally {
      fetchingRef.current = false;
    }
  };

  // Initial load + reload when the session id changes.
  useEffect(() => {
    fetchStats();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.id]);

  // Live refresh on websocket events (debounced).
  useEffect(() => {
    const unsubscribe = eventBus.subscribe((msg) => {
      const isRelevant =
        msg.type === "new_event" ||
        msg.type === "agent_created" ||
        msg.type === "agent_updated" ||
        msg.type === "session_updated";
      if (!isRelevant) return;
      const data = msg.data as { session_id?: string; id?: string };
      // Match either by session_id (events) or by id (session_updated)
      const matchesSession = data.session_id === session.id || data.id === session.id;
      if (!matchesSession) return;
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = setTimeout(() => {
        refreshTimerRef.current = null;
        fetchStats();
      }, REFRESH_DEBOUNCE_MS);
    });
    return () => {
      unsubscribe();
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.id]);

  // Tool calls = sum of all tool counts (PreToolUse+PostToolUse events have a tool_name).
  // We approximate "tool calls" as half of that (each call produces a Pre + Post event).
  const toolCallCount = useMemo(() => {
    if (!stats) return 0;
    const total = stats.tools_used.reduce((s, t) => s + t.count, 0);
    return Math.round(total / 2);
  }, [stats]);

  const maxToolCount = useMemo(() => {
    if (!stats) return 0;
    return stats.tools_used.reduce((m, t) => Math.max(m, t.count), 0);
  }, [stats]);

  // Active agent (if any)
  const activeAgent = useMemo(() => agents.find((a) => a.status === "working") ?? null, [agents]);

  // Duration: ended_at - started_at, or now - started_at if active
  const durationLabel = useMemo(() => {
    if (!session.started_at) return "—";
    const end = session.ended_at ?? new Date(now).toISOString();
    return formatDuration(session.started_at, end);
  }, [session.started_at, session.ended_at, now]);

  // Avg event rate (events / minute)
  const eventRate = useMemo(() => {
    if (!stats || !session.started_at) return null;
    const start = new Date(session.started_at).getTime();
    const end = session.ended_at
      ? new Date(session.ended_at).getTime()
      : stats.last_event_at
        ? new Date(stats.last_event_at).getTime()
        : now;
    const minutes = Math.max(1, (end - start) / 60_000);
    return stats.total_events / minutes;
  }, [stats, session.started_at, session.ended_at, now]);

  if (!stats) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5 mb-6 animate-pulse">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-[68px] rounded-lg border border-border/50 bg-surface-3" />
        ))}
      </div>
    );
  }

  const tokens = stats.tokens;
  const totalTokens =
    tokens.input_tokens +
    tokens.output_tokens +
    tokens.cache_read_tokens +
    tokens.cache_write_tokens;

  return (
    <div className="space-y-5 mb-6">
      {/* Active-agent banner — only shows when session is running */}
      {activeAgent && (
        <div className="flex items-center gap-2.5 px-3 py-2 rounded-lg border border-emerald-200 dark:border-emerald-500/30 bg-emerald-50 dark:bg-emerald-500/10">
          <span className="relative flex h-2 w-2 flex-shrink-0">
            <span className="animate-ping-finite absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
          </span>
          <Bot className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400 flex-shrink-0" />
          <span className="text-xs text-emerald-700 dark:text-emerald-300 font-medium flex-shrink-0">
            {activeAgent.name || "Agent"}
          </span>
          {activeAgent.current_tool && (
            <span className="text-[11px] text-faint dark:text-faint/80 font-mono inline-flex items-center gap-1">
              <span className="text-faint dark:text-faint/80">running</span>
              <span className="text-emerald-600 dark:text-emerald-400">{activeAgent.current_tool}</span>
            </span>
          )}
          {activeAgent.task && (
            <span className="text-[11px] text-faint truncate min-w-0" title={activeAgent.task}>
              · {activeAgent.task}
            </span>
          )}
        </div>
      )}

      {/* Stat tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
        <StatTile
          label="Events"
          value={stats.total_events.toLocaleString()}
          hint={
            eventRate !== null && eventRate > 0
              ? `${eventRate < 1 ? eventRate.toFixed(2) : Math.round(eventRate)}/min`
              : undefined
          }
          icon={<Activity className="w-3 h-3" />}
        />
        <StatTile
          label="Tool calls"
          value={toolCallCount.toLocaleString()}
          hint={stats.tools_used.length > 0 ? `${stats.tools_used.length} unique` : undefined}
          icon={<Wrench className="w-3 h-3" />}
          tone="violet"
        />
        <StatTile
          label="Subagents"
          value={stats.agents.subagent.toLocaleString()}
          hint={stats.agents.main > 0 ? `+${stats.agents.main} main` : undefined}
          icon={<GitBranch className="w-3 h-3" />}
          tone="cyan"
        />
        <StatTile
          label="Compactions"
          value={stats.compaction_count.toLocaleString()}
          icon={<Layers className="w-3 h-3" />}
          tone="blue"
        />
        <StatTile
          label="Errors"
          value={stats.error_count.toLocaleString()}
          icon={<AlertTriangle className="w-3 h-3" />}
          tone={stats.error_count > 0 ? "rose" : "default"}
        />
        <StatTile
          label="Duration"
          value={durationLabel}
          hint={session.status === "active" ? "running" : "completed"}
          icon={<Clock className="w-3 h-3" />}
          tone={session.status === "active" ? "emerald" : "default"}
        />
      </div>

      {/* Two-column layout: tools + subagent breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Tool usage */}
        <div className="lg:col-span-2 rounded-lg border border-border/50 dark:border-border/30 bg-surface-2 dark:bg-surface-3/30 p-3.5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-semibold text-faint dark:text-faint/80 uppercase tracking-wider flex items-center gap-1.5">
              <Wrench className="w-3.5 h-3.5 text-violet-500 dark:text-violet-400" />
              Top tools
            </h3>
            <span className="text-[10px] text-faint dark:text-faint/70 font-mono">
              {stats.tools_used.length} total
            </span>
          </div>
          {stats.tools_used.length === 0 ? (
            <div className="text-center py-6 text-xs text-faint dark:text-faint/70">No tool calls yet.</div>
          ) : (
            <div className="space-y-1.5">
              {stats.tools_used.slice(0, 8).map((t) => (
                <ToolUsageRow
                  key={t.tool_name}
                  toolName={t.tool_name}
                  count={t.count}
                  max={maxToolCount}
                />
              ))}
            </div>
          )}
        </div>

        {/* Subagent breakdown.
         *
         * The /api/sessions/:id/stats endpoint deliberately strips compaction
         * agents from `subagent_types` so the workflow analytics don't lump
         * them in. But on this overview a session with only compactions still
         * has *something* to show — surfacing zero subagents while the agents
         * tab below clearly lists "Context Compaction" cards is confusing.
         *
         * We synthesize a compaction row from `stats.compaction_count` (from
         * the JSONL transcript, not agent records) and render it alongside any
         * real subagent types, distinguished by an amber bar (matching the
         * compaction iconography elsewhere in the app) instead of cyan. */}
        <div className="rounded-lg border border-border/50 dark:border-border/30 bg-surface-2 dark:bg-surface-3/30 p-3.5">
          {(() => {
            type SubRow = { key: string; label: string; count: number; isCompaction: boolean };
            const rows: SubRow[] = stats.subagent_types.map((s) => ({
              key: s.subagent_type,
              label: s.subagent_type,
              count: s.count,
              isCompaction: false,
            }));
            if (stats.compaction_count > 0) {
              rows.push({
                key: "__compaction__",
                label: "Context Compaction",
                count: stats.compaction_count,
                isCompaction: true,
              });
            }
            const totalRuns = rows.reduce((s, r) => s + r.count, 0);
            const max = rows.reduce((m, r) => Math.max(m, r.count), 0);

            return (
              <>
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-xs font-semibold text-faint dark:text-faint/80 uppercase tracking-wider flex items-center gap-1.5">
                    <GitBranch className="w-3.5 h-3.5 text-cyan-500 dark:text-cyan-400" />
                    Subagents
                  </h3>
                  <span className="text-[10px] text-faint dark:text-faint/70 font-mono">{totalRuns} runs</span>
                </div>
                {rows.length === 0 ? (
                  <div className="text-center py-6 text-xs text-faint dark:text-faint/70">
                    No subagents in this session.
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    {rows.slice(0, 8).map((r) => {
                      const pct = max > 0 ? Math.max(4, Math.round((r.count / max) * 100)) : 0;
                      const barClass = r.isCompaction ? "bg-amber-500" : "bg-cyan-500";
                      return (
                        <div key={r.key} className="flex items-center gap-2">
                          <span
                            className={`font-mono text-xs truncate flex-1 min-w-0 ${
                              r.isCompaction ? "text-amber-600 dark:text-amber-400" : "text-muted dark:text-secondary"
                            }`}
                            title={r.label}
                          >
                            {r.label}
                          </span>
                          <div className="w-16 h-1.5 rounded-full bg-gray-200 dark:bg-surface-4 overflow-hidden flex-shrink-0">
                            <div
                              className={`h-full rounded-full ${barClass}`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <span className="font-mono text-xs text-faint dark:text-faint/70 w-8 text-right flex-shrink-0">
                            {r.count}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </>
            );
          })()}
        </div>
      </div>

      {/* Token flow strip */}
      {totalTokens > 0 && (
        <div className="rounded-lg border border-border/50 dark:border-border/30 bg-surface-2 dark:bg-surface-3/30 p-3.5">
          <div className="flex items-center justify-between mb-2.5">
            <h3 className="text-xs font-semibold text-faint dark:text-faint/80 uppercase tracking-wider flex items-center gap-1.5">
              <Coins className="w-3.5 h-3.5 text-amber-500 dark:text-amber-400" />
              Token flow
            </h3>
            <span className="text-[10px] text-faint dark:text-faint/70 font-mono">{fmt(totalTokens)} total</span>
          </div>
          <TokenFlowBar tokens={tokens} total={totalTokens} />
        </div>
      )}

      {/* Event-type breakdown — secondary, only top 6 */}
      {stats.events_by_type.length > 0 && (
        <div className="rounded-lg border border-border/50 dark:border-border/30 bg-surface-2 dark:bg-surface-3/30 p-3.5">
          <h3 className="text-xs font-semibold text-faint dark:text-faint/80 uppercase tracking-wider mb-3 flex items-center gap-1.5">
            <Activity className="w-3.5 h-3.5 text-faint dark:text-faint/70" />
            Event mix
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {stats.events_by_type.slice(0, 12).map((e) => (
              <span
                key={e.event_type}
                className="inline-flex items-center gap-1.5 text-[11px] font-mono bg-surface-1 dark:bg-surface-4/50 border border-border/40 dark:border-border/30 rounded-md px-2 py-0.5"
              >
                <span className="text-muted dark:text-secondary">{e.event_type}</span>
                <span className="text-faint dark:text-faint/70">·</span>
                <span className="text-tertiary dark:text-secondary">{e.count.toLocaleString()}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function TokenFlowBar({ tokens, total }: { tokens: SessionStats["tokens"]; total: number }) {
  const segments = [
    {
      key: "cache_read",
      label: "Cache read",
      value: tokens.cache_read_tokens,
      cls: "bg-sky-500",
      text: "text-sky-600",
    },
    {
      key: "cache_write",
      label: "Cache write",
      value: tokens.cache_write_tokens,
      cls: "bg-violet-500",
      text: "text-violet-600",
    },
    {
      key: "input",
      label: "Input",
      value: tokens.input_tokens,
      cls: "bg-emerald-500",
      text: "text-emerald-600",
    },
    {
      key: "output",
      label: "Output",
      value: tokens.output_tokens,
      cls: "bg-orange-500",
      text: "text-orange-600",
    },
  ];

  return (
    <>
      <div className="flex w-full h-2 rounded-full overflow-hidden bg-gray-200 dark:bg-surface-4 mb-3">
        {segments.map((s) => {
          const pct = total > 0 ? (s.value / total) * 100 : 0;
          if (pct === 0) return null;
          return (
            <div
              key={s.key}
              className={`${s.cls} opacity-80 hover:opacity-100 transition-opacity`}
              style={{ width: `${pct}%` }}
              title={`${s.label}: ${s.value.toLocaleString()} (${pct.toFixed(1)}%)`}
            />
          );
        })}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
        {segments.map((s) => {
          const pct = total > 0 ? (s.value / total) * 100 : 0;
          return (
            <div key={s.key} className="flex items-center gap-2">
              <span className={`block w-2 h-2 rounded-full ${s.cls}`} />
              <span className="text-faint text-[11px]">{s.label}</span>
              <span className={`font-mono ml-auto ${s.text}`}>
                {fmt(s.value)}
                {pct > 0 && (
                  <span className="text-faint text-[10px] ml-1">
                    {pct >= 1 ? Math.round(pct) : pct.toFixed(1)}%
                  </span>
                )}
              </span>
            </div>
          );
        })}
      </div>
    </>
  );
}

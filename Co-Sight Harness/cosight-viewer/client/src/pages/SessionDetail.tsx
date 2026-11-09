// SPDX-License-Identifier: Apache-2.0
/**
 * @file SessionDetail.tsx
 * @description Displays detailed information about a specific session, including its agents, events, and cost breakdown, with real-time updates and an expandable agent hierarchy view.
 */
import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  Bot,
  Clock,
  Cpu,
  ChevronDown,
  ChevronRight,
  GitBranch,
  MessageSquare,
  List,
  AlertCircle,
  RotateCcw,
} from "lucide-react";
import { api } from "../lib/api";
import { resolveResumeTarget } from "./chat/resume-target";
import { eventBus } from "../lib/eventBus";
import { AgentCard } from "../components/AgentCard";
import { SessionOverview } from "../components/SessionOverview";
import { ChatPanel } from "../components/task/ChatPanel";
import { SessionStatusBadge, AgentStatusBadge } from "../components/StatusBadge";
import { effectiveSessionStatus } from "../lib/types";
import { EventDetail } from "../components/EventDetail";
import { EventFilters, isEmptyFilters, expandStatusToEventTypes } from "../components/EventFilters";
import type { EventFiltersValue } from "../components/EventFilters";
import { EventFiltersInfo } from "../components/EventFiltersInfo";
import { EventGroupRow } from "../components/EventGroupRow";
import { Skeleton } from "../components/Skeleton";
import {
  agentOriginLabel,
  buildEventTitle,
  buildOriginLabel,
  groupEvents,
  projectFromEvent,
  statusFromEventType,
} from "../lib/event-grouping";
import type { AgentInfo } from "../lib/event-grouping";
import { formatDateTime, timeAgo, formatModelName } from "../lib/format";
import type { Session, Agent, DashboardEvent, CostResult, TranscriptInfo } from "../lib/types";

type DetailTab = "agents" | "conversation" | "timeline";

const EVENTS_INITIAL_BATCH = 50; // 初始加载，分页加载更多
const EVENTS_MORE_BATCH = 500;
// Live-refresh: fetch enough to preserve the user's loaded history.
// Without this, a fast-producing session would reset to 500 on every refresh
// and the user could never review older events. Cap at 5000 to bound CPU.
const EVENTS_MAX_REFRESH = 5000;
const EVENTS_REFRESH_DEBOUNCE_MS = 500;

export function SessionDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation("sessions");
  const [searchParams, setSearchParams] = useSearchParams();
  const [session, setSession] = useState<Session | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [events, setEvents] = useState<DashboardEvent[]>([]);
  const [eventsTotal, setEventsTotal] = useState(0);
  const [eventsLoadingMore, setEventsLoadingMore] = useState(false);
  const [selectedAgentId, setSelectedAgentId] = useState<string | undefined>();
  const handleAgentChange = useCallback((agentId: string | undefined) => {
    setSelectedAgentId(agentId);
  }, []);
  // 从 URL 参数构建 filters 对象。
  // 必须用 useMemo 缓存并依赖原始字符串值：若每次渲染都新建对象字面量，
  // filters 引用总是变化 → eventApiParams → loadEvents → useEffect 依赖链层层重建，
  // 加上 setEvents 每次写入新数组又触发重渲染，会形成无限循环请求（空闲 CPU 高占用的根因）。
  const eventTypeRaw = searchParams.get("event_type");
  const toolNameRaw = searchParams.get("tool_name");
  const agentIdRaw = searchParams.get("agent_id");
  const sessionIdRaw = searchParams.get("session_id");
  const statusRaw = searchParams.get("status");
  const qRaw = searchParams.get("q");
  const fromRaw = searchParams.get("from");
  const toRaw = searchParams.get("to");
  const filters = useMemo<EventFiltersValue>(
    () => ({
      event_type: eventTypeRaw ? eventTypeRaw.split(",") : [],
      tool_name: toolNameRaw ? toolNameRaw.split(",") : [],
      agent_id: agentIdRaw ? agentIdRaw.split(",") : [],
      session_id: sessionIdRaw ? sessionIdRaw.split(",") : [],
      status: statusRaw ? statusRaw.split(",") : [],
      q: qRaw || "",
      from: fromRaw || "",
      to: toRaw || "",
    }),
    [eventTypeRaw, toolNameRaw, agentIdRaw, sessionIdRaw, statusRaw, qRaw, fromRaw, toRaw]
  );

  const setFilters = (newFilters: EventFiltersValue) => {
    const params = new URLSearchParams(searchParams);

    // 清除旧的 filter 参数
    ["event_type", "tool_name", "agent_id", "session_id", "status", "q", "from", "to"].forEach(
      (key) => params.delete(key)
    );

    // 写入新的 filter 参数（非空值）
    if (newFilters.event_type.length > 0) params.set("event_type", newFilters.event_type.join(","));
    if (newFilters.tool_name.length > 0) params.set("tool_name", newFilters.tool_name.join(","));
    if (newFilters.agent_id.length > 0) params.set("agent_id", newFilters.agent_id.join(","));
    if (newFilters.session_id.length > 0) params.set("session_id", newFilters.session_id.join(","));
    if (newFilters.status.length > 0) params.set("status", newFilters.status.join(","));
    if (newFilters.q) params.set("q", newFilters.q);
    if (newFilters.from) params.set("from", newFilters.from);
    if (newFilters.to) params.set("to", newFilters.to);

    setSearchParams(params, { replace: true });
  };
  const grouped = searchParams.get("grouped") !== "false"; // 默认 true

  const setGrouped = (value: boolean) => {
    const newParams = new URLSearchParams(searchParams);
    if (value) {
      newParams.delete("grouped"); // 默认 true，不写入
    } else {
      newParams.set("grouped", "false");
    }
    setSearchParams(newParams, { replace: true });
  };
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [_cost, _setCost] = useState<CostResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedAgents, setExpandedAgents] = useState<Set<string>>(() => {
    return new Set<string>();
  });

  const VALID_TABS: DetailTab[] = ["agents", "conversation", "timeline"];
  const rawTab = searchParams.get("tab");
  const activeTab: DetailTab =
    rawTab && VALID_TABS.includes(rawTab as DetailTab) ? (rawTab as DetailTab) : "agents";

  const setActiveTab = (tab: DetailTab) => {
    const newParams = new URLSearchParams(searchParams);
    if (tab === "agents") {
      newParams.delete("tab");
    } else {
      newParams.set("tab", tab);
    }
    setSearchParams(newParams, { replace: true });
  };
  // Keep tabs mounted once visited so switching between them doesn't unmount/
  // remount their subtrees (which causes a perceptible flash on click).
  const [visitedTabs, setVisitedTabs] = useState<Set<DetailTab>>(() => new Set(["agents"]));
  useEffect(() => {
    setVisitedTabs((prev) => (prev.has(activeTab) ? prev : new Set(prev).add(activeTab)));
  }, [activeTab]);

  const [transcripts, setTranscripts] = useState<TranscriptInfo[]>([]);
  const [transcriptNotFound, setTranscriptNotFound] = useState(false);
  /** 恢复会话的解析/跳转进行中；按钮据此禁用并显示转圈。 */
  const [resuming, setResuming] = useState(false);
  /** 恢复失败提示：iframe 里 alert 会被浏览器吞掉，必须画在页面上 */
  const [resumeError, setResumeError] = useState<string | null>(null);
  const notFoundTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [expandedEvents, setExpandedEvents] = useState<Set<number>>(() => new Set());

  function toggleEvent(id: number) {
    setExpandedEvents((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // Refs let the websocket handler access latest state without re-subscribing.
  const eventApiParamsRef = useRef<Record<string, unknown> | null>(null);
  const eventsLoadedCountRef = useRef(0);
  const eventsRefreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  eventsLoadedCountRef.current = events.length;
  const goBack = useCallback(() => {
    const historyState =
      typeof window !== "undefined" ? (window.history.state as { idx?: number } | null) : null;
    if ((historyState?.idx ?? 0) > 0) {
      navigate(-1);
      return;
    }
    navigate("/sessions");
  }, [navigate]);

  // Auto-dismiss not-found warning after 8 seconds
  useEffect(() => {
    if (transcriptNotFound) {
      notFoundTimerRef.current = setTimeout(() => setTranscriptNotFound(false), 8000);
      return () => {
        if (notFoundTimerRef.current) clearTimeout(notFoundTimerRef.current);
      };
    }
  }, [transcriptNotFound]);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [data, costData] = await Promise.all([
        api.sessions.get(id),
        api.pricing.sessionCost(id).catch(() => null),
      ]);
      setSession(data.session);
      setAgents(data.agents);
      _setCost(costData);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("detail.failedLoad"));
    } finally {
      setLoading(false);
    }
  }, [id, t]);

  useEffect(() => {
    load();
  }, [load]);

  // Load transcripts list (for Agent → Conversation navigation ID mapping)
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    api.sessions
      .transcripts(id)
      .then((result) => {
        if (!cancelled) setTranscripts(result.transcripts);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [id]);

  // Navigate to Conversation tab and select the matching transcript when clicking an agent
  const navigateToAgentConversation = useCallback(
    (agent: Agent) => {
      // Clear any previous not-found warning
      setTranscriptNotFound(false);

      const findTranscriptId = (ts: TranscriptInfo[]): string | null => {
        // 1. Exact match via db_agent_id (most reliable)
        const exactMatch = ts.find((t) => t.db_agent_id === agent.id);
        if (exactMatch) return exactMatch.id;

        // 2. Main agent fallback
        if (agent.type === "main") return "main";

        // 3. Fallback: match by subagent_type or type, then narrow by name
        let candidates = ts.filter((t) => t.type !== "main");
        if (agent.subagent_type) {
          const byType = candidates.filter(
            (t) => t.subagent_type === agent.subagent_type || t.type === agent.subagent_type
          );
          if (byType.length > 0) candidates = byType;
        }
        if (agent.name && candidates.length > 1) {
          const byName = candidates.filter((t) => t.name === agent.name);
          if (byName.length > 0) candidates = byName;
        }
        if (candidates.length === 1) return candidates[0]!.id;

        return null;
      };

      // Hand the resolved transcript to ChatPanel, which drives both the agent
      // dropdown and the transcript it loads. A transcript id doubles as that
      // selector's value, except for the main agent: ChatPanel represents it as
      // "" (undefined), while findTranscriptId returns the "main" sentinel —
      // normalise so the dropdown highlights the right entry.
      const applyTranscriptId = (transcriptId: string | null): boolean => {
        if (!transcriptId) return false;
        setSelectedAgentId(transcriptId === "main" ? undefined : transcriptId);
        return true;
      };

      // Always switch to the conversation tab — the user clicked a leaf agent
      // and expects to see its conversation. If no exact transcript match is
      // found, the tab still opens and the not-found banner explains why.
      setActiveTab("conversation");

      if (applyTranscriptId(findTranscriptId(transcripts))) return;

      if (transcripts.length === 0 && id) {
        // Transcripts not loaded yet — fetch them and resolve again, so the
        // click still lands on the right agent instead of falling back to main.
        api.sessions
          .transcripts(id)
          .then((result) => {
            setTranscripts(result.transcripts);
            if (!applyTranscriptId(findTranscriptId(result.transcripts))) {
              setTranscriptNotFound(true);
            }
          })
          .catch(() => {
            setTranscriptNotFound(true);
          });
        return;
      }

      // Transcripts are loaded but no specific match for this agent.
      setTranscriptNotFound(true);
    },
    [transcripts, id]
  );

  // Compute compaction labels: "#1", "#2", etc. based on started_at order
  const compactionLabels = useMemo(() => {
    const map = new Map<string, string>();
    const compactions = agents
      .filter((a) => a.subagent_type === "compaction")
      .sort((a, b) => (a.started_at || "").localeCompare(b.started_at || ""));
    compactions.forEach((a, i) => {
      const time = a.started_at
        ? new Date(a.started_at).toLocaleTimeString(undefined, {
            hour: "2-digit",
            minute: "2-digit",
          })
        : "";
      map.set(a.id, `#${i + 1}${time ? ` · ${time}` : ""}`);
    });
    return map;
  }, [agents]);

  // Event list is fetched separately from the session metadata so it can
  // respect the user's filters and use the server-driven pagination. Status
  // presets expand into event_type values and merge with any explicit
  // event_type selection.
  const eventApiParams = useMemo(() => {
    if (!id) return null;
    const statusExpanded = expandStatusToEventTypes(filters.status);
    const eventTypeMerged = Array.from(new Set<string>([...filters.event_type, ...statusExpanded]));
    return {
      session_id: [id],
      event_type: eventTypeMerged.length > 0 ? eventTypeMerged : undefined,
      tool_name: filters.tool_name.length > 0 ? filters.tool_name : undefined,
      agent_id: filters.agent_id.length > 0 ? filters.agent_id : undefined,
      q: filters.q || undefined,
      from: filters.from ? new Date(filters.from).toISOString() : undefined,
      to: filters.to ? new Date(filters.to).toISOString() : undefined,
    };
  }, [id, filters]);

  eventApiParamsRef.current = eventApiParams;

  const eventGroups = useMemo(() => groupEvents(events), [events]);

  // Build an AgentInfo map from the already-fetched agents list so rows can
  // render the subagent pill (subagent_type) without an extra fetch.
  const agentInfoById = useMemo(() => {
    const map = new Map<string, AgentInfo>();
    for (const a of agents) {
      map.set(a.id, {
        type: a.type,
        subagent_type: a.subagent_type,
        name: a.name,
        parent_agent_id: a.parent_agent_id,
      });
    }
    return map;
  }, [agents]);

  // Single-entry session-name lookup so EventDetail can surface the session
  // label above the raw id, mirroring the agentInfoById pattern. Falls back
  // to "Session abcdefgh" when session.name is null/empty so the row always
  // shows *something* identifiable — matches the header's display logic.
  const sessionNameById = useMemo(() => {
    const map = new Map<string, string>();
    if (session?.id) {
      const label = session.name?.trim() || `Session ${session.id.slice(0, 8)}`;
      map.set(session.id, label);
    }
    return map;
  }, [session?.id, session?.name]);

  // Precompute project per event so flat-row rendering doesn't re-parse JSON.
  const projectByEventId = useMemo(() => {
    const map = new Map<number, string | null>();
    for (const e of events) map.set(e.id, projectFromEvent(e));
    return map;
  }, [events]);

  const loadEvents = useCallback(async () => {
    if (!eventApiParams) return;
    try {
      const { events: data, total } = await api.events.list({
        ...eventApiParams,
        limit: EVENTS_INITIAL_BATCH,
        offset: 0,
      });
      setEvents(data);
      setEventsTotal(total);
    } catch (err) {
      console.error("Failed to load session events:", err);
    }
  }, [eventApiParams]);

  useEffect(() => {
    loadEvents();
  }, [loadEvents]);

  const loadMoreEvents = useCallback(async () => {
    if (!eventApiParams) return;
    setEventsLoadingMore(true);
    try {
      const { events: data, total } = await api.events.list({
        ...eventApiParams,
        limit: EVENTS_MORE_BATCH,
        offset: events.length,
      });
      setEvents((prev) => [...prev, ...data]);
      setEventsTotal(total);
    } catch (err) {
      console.error("Failed to load more session events:", err);
    } finally {
      setEventsLoadingMore(false);
    }
  }, [eventApiParams, events.length]);
  // Auto-expand agents that have working subagents (at any depth)
  useEffect(() => {
    const parentsWithActiveChildren = new Set<string>();
    for (const a of agents) {
      if (a.parent_agent_id && a.status === "working") {
        parentsWithActiveChildren.add(a.parent_agent_id);
      }
    }
    if (parentsWithActiveChildren.size > 0) {
      const agentMap = new Map(agents.map((a) => [a.id, a]));
      const toExpand = new Set<string>();
      for (const pid of parentsWithActiveChildren) {
        let cur = pid;
        while (cur) {
          toExpand.add(cur);
          const parent = agentMap.get(cur);
          cur = parent?.parent_agent_id ?? "";
        }
      }
      setExpandedAgents((prev) => new Set([...prev, ...toExpand]));
    }
  }, [agents]);

  // Pagination-preserving filtered refresh, mirrors ActivityFeed's behavior.
  const refreshEventsWithPagination = useCallback(async () => {
    const params = eventApiParamsRef.current;
    if (!params) return;
    const target = Math.max(
      eventsLoadedCountRef.current || EVENTS_INITIAL_BATCH,
      EVENTS_INITIAL_BATCH
    );
    const size = Math.min(target, EVENTS_MAX_REFRESH);
    try {
      const { events: data, total } = await api.events.list({
        ...params,
        limit: size,
        offset: 0,
      });
      setEvents(data);
      setEventsTotal(total);
    } catch (err) {
      console.error("Failed to refresh session events:", err);
    }
  }, []);

  useEffect(() => {
    const unsubscribe = eventBus.subscribe((msg) => {
      // Optimization: Only react to events for THIS session.
      // Without this check, events from other sessions would trigger
      // unnecessary API calls and re-renders.
      if (
        msg.type === "agent_created" ||
        msg.type === "agent_updated" ||
        msg.type === "session_updated"
      ) {
        // Check if this event is for our session or agents
        const data = msg.data as { id?: string; session_id?: string };
        if (data?.id !== id && data?.session_id !== id) return;
        load();
      }
      if (msg.type === "new_event") {
        const event = msg.data as { session_id?: string };
        // Only refresh if the event is for this session
        if (event?.session_id !== id) return;

        // Debounce bursts into one filter-aware refetch that preserves the
        // current "Load more" pagination size.
        if (eventsRefreshTimerRef.current) clearTimeout(eventsRefreshTimerRef.current);
        eventsRefreshTimerRef.current = setTimeout(() => {
          eventsRefreshTimerRef.current = null;
          refreshEventsWithPagination();
        }, EVENTS_REFRESH_DEBOUNCE_MS);
      }
    });
    return () => {
      unsubscribe();
      if (eventsRefreshTimerRef.current) {
        clearTimeout(eventsRefreshTimerRef.current);
        eventsRefreshTimerRef.current = null;
      }
    };
  }, [load, refreshEventsWithPagination, id]);

  /**
   * 恢复会话：带着 smart-factory 的会话 id 回到 `/chat` 继续对话。
   *
   * 与列表页同一套换算（见 `resolveResumeTarget`）：优先用会话上记录的 id，
   * 老数据才按看板 id 反查。查不到就留在详情页提示。
   */
  const handleResume = useCallback(async () => {
    if (!session || resuming) return;
    setResuming(true);
    setResumeError(null);
    try {
      const agentRuntimeSessionId = await resolveResumeTarget(session);
      if (!agentRuntimeSessionId) {
        setResumeError(t("common:errors.resumeNoHarnessSession"));
        return;
      }
      navigate(`/chat?agentRuntimeSessionId=${encodeURIComponent(agentRuntimeSessionId)}`);
    } finally {
      setResuming(false);
    }
  }, [session, resuming, navigate, t]);

  if (loading) {
    return (
      <div className="animate-fade-in space-y-8" aria-busy="true">
        <div className="flex items-start gap-4">
          <Skeleton className="w-8 h-8" rounded="md" />
          <div className="flex-1 space-y-3">
            <div className="flex items-center gap-3">
              <Skeleton className="h-6 w-64" />
              <Skeleton className="h-5 w-16" rounded="full" />
            </div>
            <div className="flex flex-wrap gap-3">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-5 w-32" />
              <Skeleton className="h-5 w-24" />
            </div>
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="card p-5 space-y-2">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-7 w-24" />
            </div>
          ))}
        </div>
        {Array.from({ length: 2 }).map((_, i) => (
          <div key={i} className="card p-5 space-y-3">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-11/12" />
            <Skeleton className="h-3 w-5/6" />
          </div>
        ))}
      </div>
    );
  }

  if (error || !session) {
    return (
      <div className="text-center py-20">
        <p className="text-red-400 mb-2">{error || t("detail.notFound")}</p>
        <button onClick={goBack} className="btn-ghost mt-4">
          <ArrowLeft className="w-4 h-4" /> {t("detail.backToSessions")}
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5 animate-fade-in pb-8">
      {/* Header */}
      <div className="rounded-2xl border border-border/50 bg-surface-1 p-5">
        <div className="flex items-start gap-4">
          <button
            onClick={goBack}
            className="p-2 rounded-lg border border-border/40 text-faint hover:text-tertiary hover:bg-surface-2 transition-colors mt-0.5"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div className="flex-1">
            <div className="flex items-center gap-3 mb-1">
              <h2 className="text-lg font-semibold text-secondary">
                {session.name || `Session ${session.id.slice(0, 8)}`}
              </h2>
              {(() => {
                const title = session.custom_title || session.ai_title;
                const displayText = title || session.first_prompt;
                if (!displayText) return null;
                const isAi = !title && !!session.ai_title;
                const isFirstPrompt = !title && !!session.first_prompt;
                return (
                  <span
                    title={displayText}
                    className="inline-flex items-center gap-1.5 max-w-[360px] text-sm font-medium px-2.5 py-1 rounded-md border border-border/30 bg-surface-3/70 text-muted dark:bg-surface-3/40 dark:border-border/20 dark:text-faint"
                  >
                    {isAi && <Bot className="w-3 h-3 shrink-0 text-faint" />}
                    {isFirstPrompt && <MessageSquare className="w-3 h-3 shrink-0 text-faint" />}
                    <span className="truncate min-w-0">{displayText}</span>
                  </span>
                );
              })()}
              <SessionStatusBadge status={effectiveSessionStatus(session)} />
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-2">
              <span className="text-xs text-faint font-mono">{session.id.slice(0, 16)}</span>
              {session.model && (
                <span className="inline-flex items-center gap-1 text-xs text-faint bg-surface-3 px-2 py-0.5 rounded">
                  <Cpu className="w-3 h-3" />
                  {formatModelName(session.model)}
                </span>
              )}
              <span className="inline-flex items-center gap-1 text-xs text-faint bg-surface-3 px-2 py-0.5 rounded">
                <Clock className="w-3 h-3" />
                {formatDateTime(session.started_at)}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => void handleResume()}
              disabled={resuming}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-border/40 text-xs text-faint hover:text-emerald-600 hover:border-emerald-400/50 hover:bg-emerald-500/10 transition-colors disabled:opacity-40"
              title={t("common:session.resumeChat")}
              aria-label={t("common:session.resumeChat")}
            >
              <RotateCcw className={`w-4 h-4 ${resuming ? "animate-spin" : ""}`} />
              {t("common:session.resumeChat")}
            </button>
          </div>
        </div>
      </div>

      {/* 恢复会话失败：页面内提示（iframe 会屏蔽 alert） */}
      {resumeError && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-400"
        >
          <span className="min-w-0 flex-1">{resumeError}</span>
          <button
            type="button"
            aria-label={t("common:close")}
            onClick={() => setResumeError(null)}
            className="text-xs opacity-60 transition-opacity hover:opacity-100"
          >
            ✕
          </button>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="flex items-center gap-1.5 rounded-xl bg-surface-2 border border-border/40 p-1.5">
        <button
          onClick={() => {
            setActiveTab("agents");
            setTranscriptNotFound(false);
          }}
          className={`flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 ${
            activeTab === "agents"
              ? "bg-violet-100 text-violet-700 ring-1 ring-violet-300"
              : "text-faint hover:text-tertiary hover:bg-surface-1"
          }`}
        >
          <Bot className="w-4 h-4" />
          Agent ({agents.length})
        </button>
        <button
          onClick={() => {
            setActiveTab("conversation");
            setTranscriptNotFound(false);
          }}
          className={`flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 ${
            activeTab === "conversation"
              ? "bg-blue-100 text-blue-700 ring-1 ring-blue-300"
              : "text-faint hover:text-tertiary hover:bg-surface-1"
          }`}
        >
          <MessageSquare className="w-4 h-4" />
          {t("common:session.conversation")}
        </button>
        <button
          onClick={() => {
            setActiveTab("timeline");
            setTranscriptNotFound(false);
          }}
          className={`flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 ${
            activeTab === "timeline"
              ? "bg-amber-100 text-amber-700 ring-1 ring-amber-300"
              : "text-faint hover:text-tertiary hover:bg-surface-1"
          }`}
        >
          <List className="w-4 h-4" />
          {t("common:session.timeline", { count: eventsTotal })}
        </button>
      </div>

      {/* Tab Content */}
      <div className="rounded-2xl border border-border/50 bg-surface-1 p-5">
        {transcriptNotFound && (
          <div className="flex items-center gap-2 px-4 py-2.5 mb-3 text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg">
            <AlertCircle className="w-4 h-4 flex-shrink-0 text-amber-500" />
            <span>{t("detail.transcriptNotFound")}</span>
            <button
              onClick={() => setTranscriptNotFound(false)}
              className="ml-auto text-amber-500 hover:text-amber-700 transition-colors"
            >
              <List className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {visitedTabs.has("agents") && (
          <div hidden={activeTab !== "agents"}>
            <SessionOverview session={session} agents={agents} />

            {agents.length === 0 ? (
              <p className="text-sm text-faint">{t("detail.noAgents")}</p>
            ) : (
              <>
                <h3 className="text-xs font-semibold text-faint uppercase tracking-wider mb-3 flex items-center gap-1.5">
                  <Bot className="w-3.5 h-3.5 text-violet-400" />
                  {t("detail.agents")}
                  <span className="text-faint font-mono">· {agents.length}</span>
                </h3>
                <div className="space-y-2" data-testid="agent-tree">
                  {(() => {
                    // Build parent→children map for the full tree (works at any depth)
                    const agentMap = new Map(agents.map((a) => [a.id, a]));
                    const childrenByParent = new Map<string, Agent[]>();
                    const rootAgents: Agent[] = [];
                    for (const a of agents) {
                      if (a.parent_agent_id && agentMap.has(a.parent_agent_id)) {
                        const list = childrenByParent.get(a.parent_agent_id) || [];
                        list.push(a);
                        childrenByParent.set(a.parent_agent_id, list);
                      } else if (!a.parent_agent_id || !agentMap.has(a.parent_agent_id)) {
                        rootAgents.push(a);
                      }
                    }
                    // Sort roots and children by started_at ascending (chronological order)
                    rootAgents.sort((a, b) =>
                      (a.started_at || "").localeCompare(b.started_at || "")
                    );
                    for (const key of childrenByParent.keys()) {
                      childrenByParent
                        .get(key)!
                        .sort((a, b) => (a.started_at || "").localeCompare(b.started_at || ""));
                    }

                    // Count all descendants (recursive) for collapsed badge
                    function countDescendants(id: string): number {
                      const kids = childrenByParent.get(id) || [];
                      return kids.reduce((sum, k) => sum + 1 + countDescendants(k.id), 0);
                    }

                    // Recursive agent node renderer
                    function renderAgentNode(agent: Agent, depth: number) {
                      const children = childrenByParent.get(agent.id) || [];
                      const isExpanded = expandedAgents.has(agent.id);
                      const hasChildren = children.length > 0;
                      const isSubagent = depth > 0;
                      const totalDesc = hasChildren ? countDescendants(agent.id) : 0;
                      const toggleExpanded = () =>
                        setExpandedAgents((prev) => {
                          const next = new Set(prev);
                          if (next.has(agent.id)) next.delete(agent.id);
                          else next.add(agent.id);
                          return next;
                        });

                      return (
                        <div key={agent.id}>
                          <div className="flex items-center gap-1 min-w-0">
                            {hasChildren && (
                              <button
                                onClick={toggleExpanded}
                                className="p-1 text-faint hover:text-muted transition-colors flex-shrink-0"
                                aria-label={isExpanded ? "Collapse subagents" : "Expand subagents"}
                                aria-expanded={isExpanded}
                              >
                                {isExpanded ? (
                                  <ChevronDown className="w-4 h-4" />
                                ) : (
                                  <ChevronRight className="w-4 h-4" />
                                )}
                              </button>
                            )}
                            {isSubagent && !hasChildren && <span className="w-6 flex-shrink-0" />}
                            {isSubagent && (
                              <GitBranch className="w-3 h-3 text-violet-400 flex-shrink-0" />
                            )}
                            <div className="flex-1 min-w-0">
                              <AgentCard
                                agent={agent}
                                session={session ?? undefined}
                                label={compactionLabels.get(agent.id)}
                                onClick={
                                  hasChildren
                                    ? toggleExpanded
                                    : () => navigateToAgentConversation(agent)
                                }
                              />
                            </div>
                          </div>

                          {/* Recursive children (collapsible) */}
                          {hasChildren && isExpanded && (
                            <div className="ml-6 mt-1 space-y-1 border-l-2 border-violet-500/20 pl-3">
                              {children.map((child) => renderAgentNode(child, depth + 1))}
                            </div>
                          )}

                          {/* Descendant count badge when collapsed */}
                          {hasChildren && !isExpanded && (
                            <button
                              onClick={() =>
                                setExpandedAgents((prev) => new Set([...prev, agent.id]))
                              }
                              className="ml-7 mt-1 text-[11px] text-violet-400 hover:text-violet-300 transition-colors"
                            >
                              {t("common:subagent_label", { count: totalDesc })}
                            </button>
                          )}
                        </div>
                      );
                    }

                    // Separate true orphans (subagent whose parent_agent_id references a missing agent)
                    const orphans = rootAgents.filter(
                      (a) =>
                        a.type === "subagent" &&
                        a.parent_agent_id &&
                        !agentMap.has(a.parent_agent_id)
                    );
                    const roots = rootAgents.filter(
                      (a) =>
                        !(
                          a.type === "subagent" &&
                          a.parent_agent_id &&
                          !agentMap.has(a.parent_agent_id)
                        )
                    );

                    return (
                      <>
                        {roots.map((agent) => renderAgentNode(agent, 0))}

                        {/* Orphaned subagents */}
                        {orphans.length > 0 && (
                          <div className="mt-4">
                            <p className="text-[11px] text-muted mb-2 uppercase tracking-wider">
                              {t("detail.unparented")}
                            </p>
                            <div className="space-y-1">
                              {orphans.map((agent) => renderAgentNode(agent, 1))}
                            </div>
                          </div>
                        )}
                      </>
                    );
                  })()}
                </div>
              </>
            )}

            {/* Cost Breakdown — hidden */}
          </div>
        )}

        {visitedTabs.has("conversation") && (
          <div hidden={activeTab !== "conversation"} className="h-[calc(100dvh-17rem)]">
            {/* 所有会话都使用 ChatPanel 渲染对话：
              - 新会话（first_prompt=null）：初次聊天
              - 有历史的会话（active/completed/error/abandoned）：续聊 */}
            <ChatPanel
              sessionId={session.id}
              selectedAgentId={selectedAgentId}
              onAgentChange={handleAgentChange}
            />
          </div>
        )}

        {visitedTabs.has("timeline") && (
          <div hidden={activeTab !== "timeline"}>
            <div className="mb-3">
              <EventFiltersInfo />
            </div>
            <div className="mb-3 relative z-30">
              <EventFilters
                value={filters}
                onChange={setFilters}
                hideSessionFilter
                agentOptions={agents.map((a) => ({ id: a.id, label: a.name || a.id }))}
              />
            </div>
            <div className="flex items-center gap-2 mb-3 px-1">
              <div
                role="group"
                aria-label="view mode"
                className="inline-flex rounded-md border border-border/40 overflow-hidden"
              >
                <button
                  type="button"
                  onClick={() => setGrouped(true)}
                  aria-pressed={grouped}
                  className={`text-[11px] px-3 py-1 cursor-pointer ${
                    grouped
                      ? "bg-indigo-100 text-indigo-700"
                      : "bg-surface-2 text-faint hover:text-tertiary"
                  }`}
                >
                  {t("common:eventFilters.grouped")}
                </button>
                <button
                  type="button"
                  onClick={() => setGrouped(false)}
                  aria-pressed={!grouped}
                  className={`text-[11px] px-3 py-1 border-l border-border/40 cursor-pointer ${
                    !grouped
                      ? "bg-indigo-100 text-indigo-700"
                      : "bg-surface-2 text-faint hover:text-tertiary"
                  }`}
                >
                  {t("common:eventFilters.flat")}
                </button>
              </div>
            </div>
            {events.length === 0 ? (
              <p className="text-sm text-faint">
                {isEmptyFilters(filters)
                  ? t("detail.noEvents")
                  : t("common:eventFilters.noResults")}
              </p>
            ) : (
              <div className="rounded-lg border border-border/40 overflow-hidden">
                <div className="divide-y divide-border-light max-h-[600px] overflow-y-auto overflow-x-auto">
                  {grouped
                    ? eventGroups.map((group) => (
                        <EventGroupRow
                          key={group.key}
                          group={group}
                          agentInfoById={agentInfoById}
                          sessionNameById={sessionNameById}
                        />
                      ))
                    : events.map((event, i) => {
                        const key = event.id ?? i;
                        const isOpen = event.id != null && expandedEvents.has(event.id);
                        return (
                          <div key={key}>
                            <button
                              type="button"
                              onClick={() => event.id != null && toggleEvent(event.id)}
                              aria-expanded={isOpen}
                              aria-label={
                                isOpen
                                  ? t("common:eventDetail.collapse")
                                  : t("common:eventDetail.expand")
                              }
                              className="w-full text-left px-5 py-3 flex items-center gap-4 hover:bg-surface-2 transition-colors min-w-0 cursor-pointer"
                            >
                              <span
                                className={`text-faint text-[10px] w-3 flex-shrink-0 transition-transform ${isOpen ? "rotate-90" : ""}`}
                                aria-hidden="true"
                              >
                                ▶
                              </span>
                              <div className="w-16 text-[11px] text-faint font-mono flex-shrink-0">
                                {timeAgo(event.created_at)}
                              </div>
                              <AgentStatusBadge status={statusFromEventType(event.event_type)} />
                              {(() => {
                                // Session is implicit on this page — project is
                                // still shown so the row identifies the working
                                // directory when you share / search.
                                const project = projectByEventId.get(event.id) ?? null;
                                const origin = buildOriginLabel(
                                  project,
                                  null,
                                  agentOriginLabel(event.agent_id, agentInfoById)
                                );
                                return (
                                  <span className="text-sm text-faint flex-1 truncate">
                                    {origin && (
                                      <span
                                        className="text-muted mr-1"
                                        title={event.agent_id ?? undefined}
                                      >
                                        {origin} ·
                                      </span>
                                    )}
                                    {buildEventTitle(event)}
                                  </span>
                                );
                              })()}
                              {event.tool_name && (
                                <span className="text-[11px] px-2 py-0.5 bg-surface-2 rounded text-muted font-mono">
                                  {event.tool_name}
                                </span>
                              )}
                            </button>
                            {isOpen && (
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
              </div>
            )}
            {events.length < eventsTotal && (
              <div className="flex items-center justify-between mt-3 px-1">
                <span className="text-xs text-muted">
                  {t("common:eventFilters.showing", { shown: events.length, total: eventsTotal })}
                </span>
                <button
                  type="button"
                  onClick={loadMoreEvents}
                  disabled={eventsLoadingMore}
                  className="px-3 py-1.5 text-xs font-medium rounded-md bg-accent/15 text-accent hover:bg-accent/25 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                >
                  {eventsLoadingMore
                    ? t("common:eventFilters.loading")
                    : t("common:eventFilters.loadMore")}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// SPDX-License-Identifier: Apache-2.0
// @ts-nocheck
// @ts-nocheck
// @ts-nocheck
/**
 * @file Sessions.tsx
 * @description Premium session list with stats, filtering, and real-time updates
 */

import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import {
  FolderOpen,
  Search,
  RefreshCw,
  SortDesc,
  SortAsc,
  ChevronDown,
  Plus,
  Download,
  Upload,
  RotateCcw,
  Check,
  Lock,
} from "lucide-react";
import { api } from "../lib/api";
import { resolveResumeTarget } from "./chat/resume-target";
import { eventBus } from "../lib/eventBus";
import { EmptyState } from "../components/EmptyState";
import { TableRowSkeleton } from "../components/Skeleton";
import { SessionStatusBadge } from "../components/StatusBadge";
import { formatDateShort, formatTime, formatDuration } from "../lib/format";
import { effectiveSessionStatus, isSessionAwaitingInput } from "../lib/types";
import type { Session, DashboardEvent, Workspace } from "../lib/types";

const PAGE_SIZE = 10;

// Valid values for URL parameters (type safety)
const VALID_FILTERS = ["", "active", "waiting", "completed", "error", "abandoned"];
const VALID_SORT_FIELDS = ["time", "cost", "tokens", "duration"];

// Helper to extract project name from path
function getProjectNameFromPath(path: string, t?: (key: string) => string): string {
  if (!path) return t?.("common:session.allProjects") || "全部项目";
  const parts = path.split("/").filter(Boolean);
  return parts[parts.length - 1] || path;
}

// Helper to highlight matching text
function HighlightText({ text, query }: { text: string; query: string }) {
  if (!query.trim()) return <>{text}</>;

  const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi");
  const parts = text.split(regex);

  return (
    <>
      {parts.map((part, i) =>
        regex.test(part) ? (
          <mark key={i} className="bg-accent/20 text-accent rounded px-0.5">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  );
}

export function Sessions() {
  const navigate = useNavigate();
  const { t } = useTranslation("sessions");
  const [searchParams, setSearchParams] = useSearchParams();

  // Filter state backed by URL params
  const rawFilter = searchParams.get("status");
  const filter = rawFilter && VALID_FILTERS.includes(rawFilter) ? rawFilter : "";

  const setFilter = (value: string) => {
    const newParams = new URLSearchParams(searchParams);
    if (value === "") {
      newParams.delete("status");
    } else {
      newParams.set("status", value);
    }
    setSearchParams(newParams, { replace: true });
  };

  // Search input state backed by URL params
  const searchInput = searchParams.get("q") || "";

  const setSearchInput = (value: string) => {
    const newParams = new URLSearchParams(searchParams);
    if (value === "") {
      newParams.delete("q");
    } else {
      newParams.set("q", value);
    }
    setSearchParams(newParams, { replace: true });
  };

  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  /** 正在解析/跳转的会话；非空时其它行的恢复按钮一起禁用，避免连点。 */
  const [resumingId, setResumingId] = useState<string | null>(null);
  /** 恢复失败提示：iframe 里 alert 会被浏览器吞掉，必须画在页面上 */
  const [resumeError, setResumeError] = useState<string | null>(null);

  // Page state backed by URL params
  const page = parseInt(searchParams.get("page") || "0", 10);

  const setPage = (value: number) => {
    const newParams = new URLSearchParams(searchParams);
    if (value === 0) {
      newParams.delete("page");
    } else {
      newParams.set("page", value.toString());
    }
    setSearchParams(newParams, { replace: true });
  };

  // Selected workspaces state backed by URL param `project` (comma-separated).
  // The default workspace (kind === "default") is always included in filters
  // implicitly — it is NOT stored in this list and cannot be deselected.
  // useMemo keeps the array reference stable across renders so useCallback
  // deps don't thrash and trigger an infinite fetch loop.
  const projectParam = searchParams.get("project") || "";
  const selectedCwds = useMemo(
    () => (projectParam ? projectParam.split(",").filter(Boolean) : []),
    [projectParam]
  );

  const setSelectedCwds = (values: string[]) => {
    const newParams = new URLSearchParams(searchParams);
    if (values.length === 0) {
      newParams.delete("project");
    } else {
      newParams.set("project", values.join(","));
    }
    setSearchParams(newParams, { replace: true });
  };

  const toggleCwd = (value: string) => {
    if (selectedCwds.includes(value)) {
      setSelectedCwds(selectedCwds.filter((v) => v !== value));
    } else {
      setSelectedCwds([...selectedCwds, value]);
    }
  };

  // Sort state backed by URL params
  const rawSort = searchParams.get("sort");
  const sortBy = rawSort && VALID_SORT_FIELDS.includes(rawSort) ? rawSort : "time";
  const sortDesc = searchParams.get("order") !== "asc";

  const setSortBy = (value: string) => {
    const newParams = new URLSearchParams(searchParams);
    if (value === "time") {
      newParams.delete("sort");
    } else {
      newParams.set("sort", value);
    }
    setSearchParams(newParams, { replace: true });
  };

  const setSortDesc = (value: boolean) => {
    const newParams = new URLSearchParams(searchParams);
    if (value) {
      newParams.delete("order");
    } else {
      newParams.set("order", "asc");
    }
    setSearchParams(newParams, { replace: true });
  };

  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(null);
  const [workspacesLoading, setWorkspacesLoading] = useState(true);

  // Identify the default workspace (always included in filters).
  // Must be declared AFTER the workspaces state (const TDZ).
  const defaultWorkspace = workspaces.find((ws) => ws.kind === "default") || null;
  const defaultCwd = defaultWorkspace?.directory || "";
  const [sessions, setSessions] = useState<Session[]>([]);
  const [total, setTotal] = useState(0);

  // Dropdown state for project selector
  const [showDropdown, setShowDropdown] = useState(false);
  const dropdownBtnRef = useRef<HTMLButtonElement>(null);
  const [dropdownPos, setDropdownPos] = useState({ top: 0, left: 0 });
  const [searchQuery, setSearchQuery] = useState("");

  // Close dropdown when page scrolls
  useEffect(() => {
    if (!showDropdown) return;
    const handleScroll = () => setShowDropdown(false);
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, [showDropdown]);

  // Filter workspaces based on search
  const filteredWorkspaces = workspaces.filter((ws) => {
    if (!searchQuery.trim()) return true;
    const query = searchQuery.toLowerCase();
    return ws.name.toLowerCase().includes(query) || (ws.directory || "").toLowerCase().includes(query);
  });

  const FILTER_OPTIONS: Array<{ label: string; value: string; color?: string }> = [
    { label: t("filterAll"), value: "", color: "bg-gray-400 dark:bg-gray-500" },
    { label: t("filterActive"), value: "active", color: "bg-blue-500" },
    { label: t("filterWaiting"), value: "waiting", color: "bg-amber-500" },
    { label: t("filterCompleted"), value: "completed", color: "bg-emerald-500" },
    { label: t("filterError"), value: "error", color: "bg-red-500" },
    { label: t("filterAbandoned"), value: "abandoned", color: "bg-gray-500" },
  ];

  // Custom sort dropdown state
  const [showSortDropdown, setShowSortDropdown] = useState(false);
  const sortDropdownBtnRef = useRef<HTMLButtonElement>(null);
  const [sortDropdownPos, setSortDropdownPos] = useState({ top: 0, left: 0, width: 0 });

  const sortOptions = [
    {
      value: "time",
      label: t("common:sort.byTime"),
      desc: sortDesc ? t("common:sort.newest") : t("common:sort.oldest"),
    },
    {
      value: "duration",
      label: t("common:sort.byDuration"),
      desc: sortDesc ? t("common:sort.longest") : t("common:sort.shortest"),
    },
  ];

  // Close sort dropdown on page scroll
  useEffect(() => {
    if (!showSortDropdown) return;
    const handleScroll = () => setShowSortDropdown(false);
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, [showSortDropdown]);

  useEffect(() => {
    const id = window.setTimeout(() => setSearch(searchInput.trim()), 300);
    return () => window.clearTimeout(id);
  }, [searchInput]);

  // Fetch workspaces and auto-select active workspace
  useEffect(() => {
    setWorkspacesLoading(true);
    api.workspaces
      .list()
      .then((res) => {
        setWorkspaces(res.items);
        setActiveWorkspaceId(res.activeId);
        // Auto-select active workspace on first load if URL has no project param.
        // Skip if the active workspace IS the default workspace (it's always
        // included implicitly — no need to add it to the URL).
        const currentProject = searchParams.get("project");
        if (!currentProject && res.activeId) {
          const activeWs = res.items.find((ws) => ws.id === res.activeId);
          const defaultWs = res.items.find((ws) => ws.kind === "default");
          if (
            activeWs?.directory &&
            activeWs.directory !== defaultWs?.directory
          ) {
            setSelectedCwds([activeWs.directory]);
          }
        }
      })
      .catch(console.error)
      .finally(() => setWorkspacesLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const load = useCallback(async () => {
    // Skip loading while workspaces are still loading to avoid showing all DB sessions
    if (workspacesLoading) return;

    try {
      // Build directory filter: default workspace is always included, plus any
      // explicitly selected non-default workspaces. If the user selected
      // nothing and there's no default workspace, fall back to ALL workspace
      // directories (preserves the old "全部工作区" behavior as a safety net).
      const filterDirs: string[] = [];
      if (defaultCwd) filterDirs.push(defaultCwd);
      for (const d of selectedCwds) {
        if (d && d !== defaultCwd && !filterDirs.includes(d)) filterDirs.push(d);
      }
      // Fallback: no default workspace and no selection → use all workspace dirs
      if (filterDirs.length === 0) {
        for (const ws of workspaces) {
          if (ws.directory && !filterDirs.includes(ws.directory)) {
            filterDirs.push(ws.directory);
          }
        }
      }

      if (filterDirs.length === 0) {
        // Truly no workspace directories available → empty result
        setSessions([]);
        setTotal(0);
        return;
      }

      const cwdsParam = filterDirs.join(",");

      if (filter === "waiting") {
        const res = await api.sessions.list({
          status: "active",
          q: search || undefined,
          cwds: cwdsParam,
          sort_by: sortBy,
          sort_desc: sortDesc,
          limit: 10000,
          offset: 0,
        });
        const waiting = res.sessions.filter(isSessionAwaitingInput);
        setTotal(waiting.length);
        setSessions(waiting.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE));
        return;
      }
      const params: any = {
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
        sort_by: sortBy,
        sort_desc: sortDesc,
        cwds: cwdsParam,
      };
      if (filter) params.status = filter;
      if (search) params.q = search;
      const res = await api.sessions.list(params);
      setSessions(res.sessions);
      setTotal(res.total);
    } finally {
      setLoading(false);
    }
  }, [filter, search, selectedCwds, defaultCwd, sortBy, sortDesc, page, workspaces, workspacesLoading]);

  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    setPage(0);
  }, [filter, search, selectedCwds, defaultCwd, sortBy, sortDesc]);

  useEffect(() => {
    // 尾部节流：session_updated 几乎在每个 hook 事件后都会到达，
    // 不加节流的 load() 会大量请求服务端并触发频繁重渲染。
    // 将突发请求合并到固定窗口内最多一次 load，尾部调用保证列表最终一致。
    const THROTTLE_MS = 2_000;
    const throttleRef = { timer: null as ReturnType<typeof setTimeout> | null, lastRun: 0 };
    const scheduleLoad = () => {
      if (throttleRef.timer) return; // 已有尾部调用排队
      const wait = Math.max(0, THROTTLE_MS - (Date.now() - throttleRef.lastRun));
      throttleRef.timer = setTimeout(() => {
        throttleRef.timer = null;
        throttleRef.lastRun = Date.now();
        load();
      }, wait);
    };

    const unsubscribe = eventBus.subscribe((msg) => {
      if (msg.type === "session_created" || msg.type === "session_updated") {
        scheduleLoad();
      }
      if (msg.type === "new_event") {
        const ev = msg.data as DashboardEvent;
        if (ev.event_type === "Stop" || ev.event_type === "SessionEnd") scheduleLoad();
      }
    });

    return () => {
      unsubscribe();
      // 取消排队的尾部调用，避免使用过期的 load 闭包
      if (throttleRef.timer) clearTimeout(throttleRef.timer);
    };
  }, [load]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const paged = sessions;
  const filtered = sessions;

  // 新建会话
  const [showNewSessionModal, setShowNewSessionModal] = useState(false);
  const [selectedCwd, setSelectedCwd] = useState("");
  const [cwdOptions, setCwdOptions] = useState<
    Array<{ path: string; label: string; kind: string }>
  >([]);
  const [manualCwd, setManualCwd] = useState("");
  const [useManualCwd, setUseManualCwd] = useState(false);

  // Import session state
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);
  const [importToast, setImportToast] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  const handleImportClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    // Reset input so the same file can be re-selected
    e.target.value = "";

    if (!file.name.toLowerCase().endsWith(".zip")) {
      setImportToast({ type: "error", message: t("common:session.onlyZipSupported") });
      setTimeout(() => setImportToast(null), 4000);
      return;
    }

    setImporting(true);
    setImportToast(null);
    try {
      const result = await api.sessions.import(file);
      setImportToast({
        type: "success",
        message: t("common:session.importSuccess"),
      });
      // Refresh the session list
      load();
    } catch (err: any) {
      setImportToast({
        type: "error",
        message: `${t("common:session.importFailed")}${err.message || t("common:unexpectedError")}`,
      });
    } finally {
      setImporting(false);
      setTimeout(() => setImportToast(null), 5000);
    }
  };

  const openNewSessionModal = useCallback(async () => {
    try {
      // 获取工作目录选项（包括 dashboard cwd、home、历史 cwd）
      const res = await api.run.cwds();
      setCwdOptions(res.items || []);
      // 默认选第一个（dashboard cwd）
      setSelectedCwd(res.items?.[0]?.path || "");
      setManualCwd("");
      setUseManualCwd(false);
      setShowNewSessionModal(true);
    } catch (err) {
      console.error("获取工作目录失败:", err);
      alert(
        t("common:errors.getCwdFailed", {
          message: err instanceof Error ? err.message : String(err),
        })
      );
    }
  }, []);

  const handleNewSession = async () => {
    try {
      const newId = crypto.randomUUID();
      const finalCwd = useManualCwd ? manualCwd : selectedCwd;
      if (!finalCwd) {
        alert(t("common:session.selectCwdFirst"));
        return;
      }
      await api.sessions.create({
        id: newId,
        cwd: finalCwd,
        status: "active",
      });
      setShowNewSessionModal(false);
      navigate(`/sessions/${newId}?tab=conversation`);
    } catch (err) {
      console.error("创建会话失败:", err);
      alert(
        t("common:errors.createFailed", {
          message: err instanceof Error ? err.message : String(err),
        })
      );
    }
  };

  /**
   * 恢复会话：跳回 `/chat` 继续这条看板会话对应的智能体会话。
   *
   * 看板 id 与 smart-factory 的 `sess_…` 不是一回事，`resolveResumeTarget`
   * 负责换算出后者；算不出来时留在列表页提示，而不是带着空 id 跳过去。
   */
  const handleResume = useCallback(
    async (session: Session) => {
      if (resumingId !== null) return;
      setResumingId(session.id);
      setResumeError(null);
      try {
        const agentRuntimeSessionId = await resolveResumeTarget(session);
        if (!agentRuntimeSessionId) {
          setResumeError(t("common:errors.resumeNoHarnessSession"));
          return;
        }
        navigate(`/chat?agentRuntimeSessionId=${encodeURIComponent(agentRuntimeSessionId)}`);
      } finally {
        setResumingId(null);
      }
    },
    [navigate, resumingId, t]
  );

  return (
    <div className="flex flex-col gap-5 animate-fade-in pb-8">
      {/* 恢复会话失败：页面内提示（iframe 会屏蔽 alert） */}
      {resumeError && (
        <div
          role="alert"
          className="fixed top-4 right-4 z-[1000] max-w-md rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-red-600 shadow-lg backdrop-blur-sm animate-fade-in dark:text-red-400"
        >
          <div className="flex items-start gap-2">
            <div className="flex-1 text-sm">{resumeError}</div>
            <button
              type="button"
              aria-label={t("common:close")}
              onClick={() => setResumeError(null)}
              className="text-xs opacity-60 transition-opacity hover:opacity-100"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Import Toast Notification */}
      {importToast && (
        <div
          className={`fixed top-4 right-4 z-[1000] max-w-md px-4 py-3 rounded-lg shadow-lg border backdrop-blur-sm transition-all animate-fade-in ${
            importToast.type === "success"
              ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-600 dark:text-emerald-400"
              : "bg-red-500/10 border-red-500/30 text-red-600 dark:text-red-400"
          }`}
        >
          <div className="flex items-start gap-2">
            <div className="flex-1 text-sm">
              <div className="font-medium mb-0.5">
                {importToast.type === "success"
                  ? `✅ ${t("common:session.importSuccess")}`
                  : `❌ ${t("common:session.importFailed")}`}
              </div>
              <div className="text-xs opacity-90">{importToast.message}</div>
            </div>
            <button
              onClick={() => setImportToast(null)}
              className="text-xs opacity-60 hover:opacity-100 transition-opacity"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Stats Bar - Premium Design */}
      <div className="relative overflow-hidden rounded-2xl border border-border/50 bg-gradient-to-br from-surface-2 via-surface-2 to-surface-3 p-6 shadow-lg dark:shadow-indigo-500/5">
        {/* Subtle gradient overlay for depth */}
        <div className="absolute inset-0 bg-gradient-to-tr from-indigo-500/5 via-transparent to-purple-500/5 dark:from-indigo-500/10 dark:to-purple-500/10" />
        <div className="relative flex items-center gap-5">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500/20 to-purple-500/20 dark:from-indigo-500/30 dark:to-purple-500/30 flex items-center justify-center flex-shrink-0 shadow-inner ring-1 ring-white/10 dark:ring-white/5">
            <FolderOpen className="w-6 h-6 text-indigo-500 dark:text-indigo-400" />
          </div>
          <div className="flex flex-col">
            <span className="text-xs font-medium text-tertiary dark:text-secondary uppercase tracking-wider">
              {t("common:session.totalSessions")}
            </span>
            <span className="text-4xl font-bold text-secondary dark:text-primary tabular-nums mt-0.5 bg-gradient-to-r from-secondary to-primary dark:from-white dark:to-indigo-200 bg-clip-text text-transparent">
              {total}
            </span>
          </div>
        </div>
      </div>

      {/* Filter Bar - Premium Glass Effect */}
      <div className="flex flex-wrap lg:flex-nowrap items-center gap-3 bg-surface-1/80 dark:bg-surface-2/60 backdrop-blur-sm rounded-xl border border-border/50 dark:border-border/30 p-3 shadow-sm dark:shadow-black/10">
        {/* Workspace Selector (multi-select; default workspace is always included) */}
        <div className="relative shrink-0 w-[220px]">
          <button
            ref={dropdownBtnRef}
            onClick={() => {
              if (workspacesLoading) return; // Disable while loading
              const rect = dropdownBtnRef.current?.getBoundingClientRect();
              if (rect) setDropdownPos({ top: rect.bottom + 6, left: rect.left });
              if (!showDropdown) setSearchQuery(""); // Clear search when opening
              setShowDropdown(!showDropdown);
            }}
            disabled={workspacesLoading}
            className="w-full h-10 text-sm text-gray-200 dark:text-secondary bg-surface-2 dark:bg-surface-3/50 border border-border/50 dark:border-border/30 rounded-lg pl-3 pr-9 text-left cursor-pointer hover:border-indigo-400 dark:hover:border-indigo-500/50 transition-all duration-200 dark:hover:bg-surface-3/70 flex items-center gap-2 min-w-0 disabled:opacity-50 disabled:cursor-wait"
          >
            <span className="truncate">
              {workspacesLoading
                ? "..."
                : (() => {
                    // Button label: show ONLY non-default selection summary.
                    // The default workspace is always included in filters but
                    // is NOT surfaced in the button label — it's shown locked
                    // inside the dropdown instead.
                    if (selectedCwds.length === 0) {
                      // No non-default workspace selected (only default is filtered).
                      // Show "all workspaces" label — don't fall back to activeId,
                      // otherwise unchecking the active workspace would still show it.
                      return t("common:session.allProjects");
                    }
                    const allNonDefault = workspaces
                      .filter((ws) => ws.kind !== "default" && ws.directory)
                      .map((ws) => ws.directory!);
                    const allSelected =
                      allNonDefault.length > 0 &&
                      allNonDefault.every((d) => selectedCwds.includes(d));
                    if (allSelected) return t("common:session.allProjects");
                    const firstName =
                      workspaces.find((ws) => ws.directory === selectedCwds[0])?.name ||
                      getProjectNameFromPath(selectedCwds[0], t);
                    return selectedCwds.length > 1
                      ? `${firstName} +${selectedCwds.length - 1}`
                      : firstName;
                  })()}
            </span>
          </button>
          <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500 pointer-events-none" />
          {showDropdown &&
            createPortal(
              <>
                <div className="fixed inset-0 z-[998]" onClick={() => setShowDropdown(false)} />
                <div
                  className="fixed z-[999] rounded-xl shadow-2xl border border-border/50 py-1.5 overflow-hidden"
                  style={{
                    top: dropdownPos.top,
                    left: dropdownPos.left,
                    minWidth: 300,
                    maxWidth: "min(520px, 90vw)",
                    backgroundColor: "rgb(var(--surface-1, 255, 255, 255))",
                  }}
                  onWheel={(e) => e.stopPropagation()}
                >
                  {/* Search input */}
                  <div className="px-3 py-2 border-b border-border/40">
                    <div className="relative">
                      <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-faint" />
                      <input
                        type="text"
                        placeholder={t("settings:searchProjects")}
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        onClick={(e) => e.stopPropagation()}
                        className="w-full h-8 text-sm bg-surface-2 border border-border/50 rounded-lg pl-8 pr-3 placeholder:text-faint focus:outline-none focus:border-indigo-300"
                        autoFocus
                      />
                    </div>
                  </div>
                  {/* "All projects" option — selects every non-default workspace */}
                  <button
                    onClick={() => {
                      const allNonDefault = workspaces
                        .filter((ws) => ws.kind !== "default" && ws.directory)
                        .map((ws) => ws.directory!);
                      const allSelected =
                        allNonDefault.length > 0 &&
                        allNonDefault.every((d) => selectedCwds.includes(d));
                      setSelectedCwds(allSelected ? [] : allNonDefault);
                      setSearchQuery("");
                    }}
                    className={`flex items-center gap-2 w-full text-left px-4 py-2.5 text-sm transition-colors duration-150 ${
                      (() => {
                        const allNonDefault = workspaces
                          .filter((ws) => ws.kind !== "default" && ws.directory)
                          .map((ws) => ws.directory!);
                        return allNonDefault.length > 0 &&
                          allNonDefault.every((d) => selectedCwds.includes(d))
                          ? "text-indigo-600 font-semibold bg-surface-3"
                          : "text-tertiary hover:bg-surface-2";
                      })()
                    }`}
                  >
                    <span className="flex-1">{t("common:session.allProjects")}</span>
                  </button>
                  {/* Default workspace — always shown first, always selected */}
                  {defaultWorkspace && (
                    <div
                      className="flex items-center gap-2 min-w-0 w-full text-left px-4 py-2.5 text-sm text-indigo-600 bg-surface-3/50 cursor-default"
                      title={defaultWorkspace.directory || ""}
                    >
                      <span className="flex items-center justify-center w-4 h-4 rounded border border-indigo-400 bg-indigo-500 flex-shrink-0">
                        <Check className="w-3 h-3 text-white" />
                      </span>
                      <Lock className="w-3 h-3 text-indigo-400 flex-shrink-0" />
                      <span className="shrink-0 font-medium">
                        <HighlightText text={defaultWorkspace.name} query={searchQuery} />
                      </span>
                      {defaultWorkspace.directory && (
                        <span className="text-faint text-xs truncate min-w-0 flex-1" title={defaultWorkspace.directory}>
                          <HighlightText text={defaultWorkspace.directory} query={searchQuery} />
                        </span>
                      )}
                      <span className="text-[10px] text-indigo-400 shrink-0">
                        {t("common:session.alwaysIncluded", { defaultValue: "始终包含" })}
                      </span>
                    </div>
                  )}
                  {/* Filtered non-default workspaces (scrollable) */}
                  <div className="max-h-[50vh] overflow-y-auto">
                    {(() => {
                      const list = filteredWorkspaces.filter((ws) => ws.kind !== "default");
                      if (list.length === 0) {
                        return (
                          <div className="px-4 py-3 text-sm text-faint text-center">
                            {t("common:session.noProjectFound")}
                          </div>
                        );
                      }
                      return list.map((ws) => {
                      const checked = !!ws.directory && selectedCwds.includes(ws.directory);
                      return (
                        <button
                          key={ws.id}
                          onClick={() => {
                            if (ws.directory) {
                              toggleCwd(ws.directory);
                            }
                          }}
                          disabled={!ws.directory}
                          className={`flex items-center gap-2 min-w-0 w-full text-left px-4 py-2.5 text-sm transition-colors duration-150 ${
                            checked
                              ? "text-indigo-600 font-semibold bg-surface-3"
                              : "text-tertiary hover:bg-surface-2"
                          } ${!ws.directory ? "opacity-50 cursor-not-allowed" : ""}`}
                          title={ws.directory || ws.name}
                        >
                          <span
                            className={`flex items-center justify-center w-4 h-4 rounded border flex-shrink-0 ${
                              checked
                                ? "border-indigo-400 bg-indigo-500"
                                : "border-border/60 bg-surface-1"
                            }`}
                          >
                            {checked && <Check className="w-3 h-3 text-white" />}
                          </span>
                          <span className="shrink-0">
                            <HighlightText text={ws.name} query={searchQuery} />
                          </span>
                          {ws.directory && (
                            <span className="text-faint text-xs truncate min-w-0 flex-1" title={ws.directory}>
                              <HighlightText text={ws.directory} query={searchQuery} />
                            </span>
                          )}
                        </button>
                      );
                    });
                  })()}
                  </div>
                </div>
              </>,
              document.body
            )}
        </div>

        {/* Search */}
        <div className="relative flex-1 min-w-[180px] max-w-[340px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            type="text"
            placeholder={t("searchPlaceholder")}
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className="w-full h-10 text-sm text-gray-200 dark:text-secondary bg-surface-2 dark:bg-surface-3/50 border border-border/50 dark:border-border/30 rounded-lg pl-10 pr-3 placeholder:text-gray-500 dark:placeholder:text-faint focus:outline-none focus:border-indigo-400 dark:focus:border-indigo-500/60 focus:ring-2 dark:focus:ring-indigo-500/20 transition-all duration-200"
          />
        </div>

        {/* Sort - Custom Dropdown */}
        <div
          className="relative flex items-center gap-1.5 bg-surface-2 dark:bg-surface-3/50 border border-border/40 dark:border-border/30 rounded-lg h-10 px-2 flex-1 min-w-[180px]"
        >
          <button
            ref={sortDropdownBtnRef}
            onClick={() => {
              const rect = sortDropdownBtnRef.current?.getBoundingClientRect();
              if (rect) {
                setSortDropdownPos({ top: rect.bottom + 6, left: rect.left, width: rect.width });
              }
              setShowSortDropdown(!showSortDropdown);
            }}
            className="flex-1 text-left text-sm text-gray-200 dark:text-secondary pl-2 pr-2 cursor-pointer hover:text-white dark:hover:text-primary transition-colors"
          >
            {sortOptions.find((o) => o.value === sortBy)?.label}
            <span className="text-faint ml-1">
              ({sortOptions.find((o) => o.value === sortBy)?.desc})
            </span>
          </button>
          <div className="w-px h-4 bg-border/40" />
          <button
            onClick={() => setSortDesc(!sortDesc)}
            className="p-1 rounded hover:bg-surface-3 dark:hover:bg-surface-4 text-gray-400 dark:text-faint hover:text-gray-200 dark:hover:text-secondary transition-colors shrink-0"
            title={sortDesc ? t("common:sort.descending") : t("common:sort.ascending")}
          >
            {sortDesc ? <SortDesc className="w-3.5 h-3.5" /> : <SortAsc className="w-3.5 h-3.5" />}
          </button>
        </div>

        {/* Sort Dropdown Menu — portal to body so it isn't clipped by ancestor stacking contexts */}
        {showSortDropdown &&
          createPortal(
            <>
              <div className="fixed inset-0 z-[998]" onClick={() => setShowSortDropdown(false)} />
              <div
                className="fixed z-[999] rounded-lg border border-border/50 dark:border-border/30 shadow-xl dark:shadow-black/30 overflow-hidden"
                style={{
                  top: sortDropdownPos.top,
                  left: sortDropdownPos.left,
                  minWidth: Math.max(sortDropdownPos.width, 180),
                  backgroundColor: "rgb(var(--surface-1, 255, 255, 255))",
                }}
                onWheel={(e) => e.stopPropagation()}
              >
                {sortOptions.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => {
                      setSortBy(opt.value);
                      setShowSortDropdown(false);
                    }}
                    className={`w-full text-left px-4 py-2.5 text-sm transition-colors ${
                      sortBy === opt.value
                        ? "bg-indigo-500/10 dark:bg-indigo-500/20 text-indigo-600 dark:text-indigo-400"
                        : "text-gray-200 dark:text-secondary hover:bg-surface-2 dark:hover:bg-surface-4"
                    }`}
                  >
                    {opt.label}
                    <span className="text-faint ml-1">({opt.desc})</span>
                  </button>
                ))}
              </div>
            </>,
            document.body
          )}

        {/* Import Session Button - Hidden */}
        {/* <button
          onClick={handleImportClick}
          disabled={importing}
          className="px-3 py-1.5 text-xs font-medium rounded-md transition-all duration-200 whitespace-nowrap flex items-center gap-1.5 text-gray-500 dark:text-faint hover:text-gray-300 dark:hover:text-secondary hover:bg-surface-3 dark:hover:bg-surface-3/70 disabled:opacity-50 disabled:cursor-not-allowed"
          title={t("importSession")}
        >
          {importing ? (
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Upload className="w-3.5 h-3.5" />
          )}
          {importing ? t("importing") : t("importSession")}
        </button> */}

        {/* Hidden file input for import */}
        <input
          type="file"
          ref={fileInputRef}
          accept=".zip"
          onChange={handleFileSelect}
          style={{ display: "none" }}
        />

        {/* Status Filters - With colored dots */}
        <div className="flex gap-1 bg-surface-2 dark:bg-surface-3/50 rounded-lg p-1 ml-auto shrink-0 ring-1 dark:ring-white/5">
          {FILTER_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setFilter(opt.value)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all duration-200 whitespace-nowrap flex items-center gap-1.5 ${
                filter === opt.value
                  ? "bg-gradient-to-r from-indigo-500 to-indigo-600 dark:from-indigo-500/90 dark:to-indigo-600/90 text-white shadow-sm dark:shadow-indigo-500/20"
                  : "text-gray-500 dark:text-faint hover:text-gray-300 dark:hover:text-secondary hover:bg-surface-3 dark:hover:bg-surface-3/70"
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${filter === opt.value ? "bg-white/80" : opt.color} transition-colors`}
              />
              {opt.label}
            </button>
          ))}
        </div>

        <button
          onClick={async () => {
            if (refreshing) return;
            setRefreshing(true);
            try {
              await load();
            } finally {
              setRefreshing(false);
            }
          }}
          disabled={refreshing}
          className="p-2.5 rounded-lg text-gray-400 dark:text-faint hover:text-gray-200 dark:hover:text-secondary hover:bg-surface-2 dark:hover:bg-surface-3/70 transition-all duration-200 shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
          title={t("common:refresh")}
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin" : ""}`} />
        </button>
      </div>

      {/* 新建会话模态框 */}
      {showNewSessionModal &&
        createPortal(
          <>
            <div
              className="fixed inset-0 z-[998] bg-black/30 backdrop-blur-sm"
              onClick={() => setShowNewSessionModal(false)}
            />
            <div
              className="fixed z-[999] rounded-xl shadow-2xl bg-surface-1 border border-border/60 w-full max-w-md"
              style={{
                top: "50%",
                left: "50%",
                transform: "translate(-50%, -50%)",
              }}
            >
              <div className="px-5 py-4 border-b border-border/40">
                <h3 className="text-base font-semibold text-secondary">
                  {t("common:session.newSession")}
                </h3>
                <p className="text-xs text-faint mt-1">{t("common:session.selectOrInputCwd")}</p>
              </div>
              <div className="px-5 py-4">
                <div className="flex items-center gap-2 mb-3">
                  <label className="flex items-center gap-1.5 text-sm text-tertiary cursor-pointer">
                    <input
                      type="radio"
                      checked={!useManualCwd}
                      onChange={() => setUseManualCwd(false)}
                      className="text-indigo-500 focus:ring-indigo-400"
                    />
                    {t("common:session.selectFromList")}
                  </label>
                  <label className="flex items-center gap-1.5 text-sm text-tertiary cursor-pointer">
                    <input
                      type="radio"
                      checked={useManualCwd}
                      onChange={() => setUseManualCwd(true)}
                      className="text-indigo-500 focus:ring-indigo-400"
                    />
                    {t("common:session.manualInput")}
                  </label>
                </div>

                {!useManualCwd ? (
                  // 列表选择模式
                  <div className="space-y-1.5 max-h-64 overflow-y-auto">
                    {cwdOptions.length === 0 ? (
                      <div className="text-sm text-faint bg-surface-2 rounded-lg px-3 py-4 border border-border/30 text-center">
                        {t("common:session.noAvailableDir")}
                      </div>
                    ) : (
                      cwdOptions.map((opt) => (
                        <button
                          key={opt.path}
                          onClick={() => setSelectedCwd(opt.path)}
                          className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors border ${
                            selectedCwd === opt.path
                              ? "border-indigo-300 bg-indigo-50 text-indigo-700"
                              : "border-border/30 bg-surface-1 hover:bg-surface-2 text-tertiary"
                          }`}
                          title={opt.path}
                        >
                          <div className="flex items-center gap-2">
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-3 text-faint font-mono uppercase">
                              {opt.kind}
                            </span>
                            <span className="font-medium truncate">{opt.label}</span>
                          </div>
                          <div className="text-xs text-faint truncate mt-0.5 ml-10">{opt.path}</div>
                        </button>
                      ))
                    )}
                  </div>
                ) : (
                  // 手动输入模式
                  <div>
                    <input
                      type="text"
                      placeholder={t("common:session.inputAbsolutePath")}
                      value={manualCwd}
                      onChange={(e) => setManualCwd(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleNewSession();
                      }}
                      className="w-full h-9 text-sm bg-surface-2 border border-border/50 rounded-lg px-3 placeholder:text-faint focus:outline-none focus:border-indigo-300"
                      autoFocus
                    />
                    <p className="text-xs text-faint mt-1.5">
                      {t("common:session.claudeWillStartHere")}
                    </p>
                  </div>
                )}
              </div>
              <div className="px-5 py-3 border-t border-border/40 flex justify-end gap-2">
                <button
                  onClick={() => setShowNewSessionModal(false)}
                  className="px-3 py-1.5 text-sm text-muted hover:bg-surface-3 rounded-md transition-colors"
                >
                  {t("common:cancel")}
                </button>
                <button
                  onClick={handleNewSession}
                  className="px-4 py-1.5 text-sm font-medium text-white bg-indigo-500 hover:bg-indigo-600 rounded-md transition-colors"
                >
                  {t("common:session.createAndOpen")}
                </button>
              </div>
            </div>
          </>,
          document.body
        )}

      {!loading && filtered.length === 0 ? (
        <EmptyState
          icon={FolderOpen}
          title={t("noSessions")}
          description={search || filter || selectedCwds.length > 0 ? t("noSessionsDesc") : t("noSessionsHint")}
        />
      ) : (
        <>
          <div className="rounded-2xl border border-border/50 dark:border-border/30 bg-surface-1 dark:bg-surface-2/40 overflow-x-auto shadow-lg dark:shadow-black/20 ring-1 dark:ring-white/5">
            <table className="w-full min-w-[1000px]">
              <thead>
                <tr className="border-b border-border/60 dark:border-border/30 text-left bg-gradient-to-r from-surface-2/50 to-surface-3/30 dark:from-surface-3/40 dark:to-surface-2/20">
                  <th className="px-5 py-4 text-[11px] font-semibold text-gray-500 dark:text-faint uppercase tracking-wider">
                    {t("tableSession")}
                  </th>
                  <th className="px-5 py-4 text-[11px] font-semibold text-gray-500 dark:text-faint uppercase tracking-wider">
                    {t("tableTitle")}
                  </th>
                  <th className="px-5 py-4 text-[11px] font-semibold text-gray-500 dark:text-faint uppercase tracking-wider">
                    {t("tableStatus")}
                  </th>
                  <th className="px-5 py-4 text-[11px] font-semibold text-gray-500 dark:text-faint uppercase tracking-wider">
                    {t("tableDuration")}
                  </th>
                  <th className="px-5 py-4 text-[11px] font-semibold text-gray-500 dark:text-faint uppercase tracking-wider">
                    {t("tableStartTime")}
                  </th>
                  <th className="px-5 py-4 text-[11px] font-semibold text-gray-500 dark:text-faint uppercase tracking-wider">
                    {t("tableActiveTime")}
                  </th>
                  <th className="px-5 py-4 text-[11px] font-semibold text-gray-500 dark:text-faint uppercase tracking-wider">
                    {t("tableAgents")}
                  </th>
                  <th className="px-5 py-4 text-[11px] font-semibold text-gray-500 dark:text-faint uppercase tracking-wider">
                    {t("tableDirectory")}
                  </th>
                  <th className="px-5 py-4 text-[11px] font-semibold text-gray-500 dark:text-faint uppercase tracking-wider w-20">
                    {t("tableActions")}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40 dark:divide-border/20">
                {loading && paged.length === 0
                  ? Array.from({ length: 8 }).map((_, i) => (
                      <TableRowSkeleton
                        key={`sk-${i}`}
                        columns={10}
                        widths={[
                          "w-40",
                          "w-48",
                          "w-20",
                          "w-20",
                          "w-28",
                          "w-28",
                          "w-10",
                          "w-16",
                          "w-44",
                          "w-4",
                        ]}
                      />
                    ))
                  : null}
                {paged.map((session) => {
                  const status = effectiveSessionStatus(session);
                  return (
                    <tr
                      key={session.id}
                      onClick={() => navigate(`/sessions/${session.id}`)}
                      className="hover:bg-gradient-to-r hover:from-indigo-500/5 hover:to-purple-500/5 dark:hover:from-indigo-500/10 dark:hover:to-purple-500/10 transition-all duration-200 cursor-pointer group"
                    >
                      <td className="px-5 py-4">
                        <div className="max-w-[260px]">
                          <span className="text-sm font-medium text-gray-200 dark:text-secondary truncate block group-hover:text-indigo-600 dark:group-hover:text-indigo-400 transition-colors duration-200">
                            {session.name || `Session ${session.id.slice(0, 8)}`}
                          </span>
                          <span className="text-[11px] text-gray-600 dark:text-faint font-mono mt-1 opacity-70">
                            {session.id.slice(0, 12)}
                          </span>
                        </div>
                      </td>
                      <td className="px-5 py-4">
                        <div className="max-w-[280px]">
                          {/* 上行：自定义标题（降级到 ai_title 带前缀） */}
                          <span
                            title={session.custom_title || session.ai_title || ""}
                            className={`text-sm block truncate ${
                              session.custom_title || session.ai_title
                                ? "text-gray-200 dark:text-secondary"
                                : "text-gray-500 dark:text-faint/60"
                            }`}
                          >
                            {session.custom_title
                              ? session.custom_title.length > 30
                                ? session.custom_title.slice(0, 30) + "..."
                                : session.custom_title
                              : session.ai_title
                                ? "ai-" +
                                  (session.ai_title.length > 27
                                    ? session.ai_title.slice(0, 27) + "..."
                                    : session.ai_title)
                                : t("noCustomTitle")}
                          </span>

                          {/* 下行：首次输入 */}
                          <span
                            title={session.first_prompt || ""}
                            className={`text-xs block truncate mt-1 ${
                              session.first_prompt
                                ? "text-gray-500 dark:text-faint"
                                : "text-gray-500 dark:text-faint italic"
                            }`}
                          >
                            {session.first_prompt
                              ? session.first_prompt.length > 30
                                ? session.first_prompt.slice(0, 30) + "..."
                                : session.first_prompt
                              : t("noFirstPrompt")}
                          </span>
                        </div>
                      </td>
                      <td className="px-5 py-4">
                        <SessionStatusBadge status={status} />
                      </td>
                      <td className="px-5 py-4 text-sm text-gray-400 dark:text-muted font-mono whitespace-nowrap">
                        {session.ended_at
                          ? formatDuration(session.started_at, session.ended_at)
                          : t("common:running")}
                      </td>
                      <td className="px-5 py-4 text-sm text-gray-400 dark:text-muted">
                        <div className="flex flex-col items-start text-left leading-tight">
                          <span>{formatDateShort(session.started_at)}</span>
                          <span className="text-xs text-faint">
                            {formatTime(session.started_at)}
                          </span>
                        </div>
                      </td>
                      <td className="px-5 py-4 text-sm text-gray-400 dark:text-muted">
                        <div className="flex flex-col items-start text-left leading-tight">
                          <span>
                            {formatDateShort(session.last_activity || session.started_at)}
                          </span>
                          <span className="text-xs text-faint">
                            {formatTime(session.last_activity || session.started_at)}
                          </span>
                        </div>
                      </td>
                      <td className="px-5 py-4 text-sm text-gray-400 dark:text-muted font-mono">
                        {session.agent_count ?? "-"}
                      </td>
                      <td className="px-5 py-4 max-w-[280px]" title={session.cwd || ""}>
                        {session.cwd ? (
                          <>
                            <span className="text-sm text-gray-500 dark:text-faint font-mono block truncate">
                              {getProjectNameFromPath(session.cwd)}
                            </span>
                            <span className="text-[11px] text-gray-600 dark:text-faint/70 font-mono block truncate mt-0.5">
                              {session.cwd}
                            </span>
                          </>
                        ) : (
                          <span className="text-xs text-gray-500 dark:text-faint">—</span>
                        )}
                      </td>
                      <td className="px-3 py-4">
                        <div className="flex items-center gap-1">
                          {/* 恢复会话：回到 /chat 继续该会话对应的智能体对话 */}
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              void handleResume(session);
                            }}
                            disabled={resumingId !== null}
                            title={t("common:session.resumeChat")}
                            aria-label={t("common:session.resumeChat")}
                            className="p-1.5 rounded-lg text-gray-500 dark:text-faint hover:text-emerald-600 dark:hover:text-emerald-400 hover:bg-emerald-500/10 dark:hover:bg-emerald-500/20 transition-all duration-200 disabled:opacity-40"
                          >
                            <RotateCcw
                              size={14}
                              className={resumingId === session.id ? "animate-spin" : undefined}
                            />
                          </button>
                          {/* 导出按钮 - Hidden */}
                          {/* <button
                            onClick={(e) => {
                              e.stopPropagation();
                              const url = api.sessions.exportUrl(session.id);
                              const a = document.createElement('a');
                              a.href = url;
                              a.download = '';
                              document.body.appendChild(a);
                              a.click();
                              document.body.removeChild(a);
                            }}
                            title={t("exportSession")}
                            className="p-1.5 rounded-lg text-gray-500 dark:text-faint hover:text-indigo-600 dark:hover:text-indigo-400 hover:bg-indigo-500/10 dark:hover:bg-indigo-500/20 transition-all duration-200"
                          >
                            <Download size={14} />
                          </button> */}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination - Premium */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 mt-6">
              <button
                disabled={page === 0}
                onClick={() => setPage(Math.max(0, page - 1))}
                className="px-4 py-2 text-sm rounded-lg border border-border/40 dark:border-border/30 bg-surface-1 dark:bg-surface-2/50 text-gray-400 dark:text-faint disabled:opacity-30 hover:bg-surface-2 dark:hover:bg-surface-3/70 hover:border-indigo-400 dark:hover:border-indigo-500/40 transition-all duration-200"
              >
                {t("common:pagination.previous")}
              </button>
              {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                const start = Math.max(0, Math.min(page - 3, totalPages - 7));
                const p = start + i;
                if (p >= totalPages) return null;
                return (
                  <button
                    key={p}
                    onClick={() => setPage(p)}
                    className={`w-9 h-9 text-sm rounded-lg transition-all duration-200 ${
                      p === page
                        ? "bg-gradient-to-r from-indigo-500 to-indigo-600 dark:from-indigo-500 dark:to-indigo-600 text-white shadow-md dark:shadow-indigo-500/20"
                        : "text-gray-400 dark:text-faint hover:bg-surface-3 dark:hover:bg-surface-3/70"
                    }`}
                  >
                    {p + 1}
                  </button>
                );
              })}
              <button
                disabled={page >= totalPages - 1}
                onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
                className="px-4 py-2 text-sm rounded-lg border border-border/40 dark:border-border/30 bg-surface-1 dark:bg-surface-2/50 text-gray-400 dark:text-faint disabled:opacity-30 hover:bg-surface-2 dark:hover:bg-surface-3/70 hover:border-indigo-400 dark:hover:border-indigo-500/40 transition-all duration-200"
              >
                {t("common:pagination.next")}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

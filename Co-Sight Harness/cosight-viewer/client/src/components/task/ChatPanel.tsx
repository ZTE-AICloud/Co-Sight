// SPDX-License-Identifier: Apache-2.0
// @ts-nocheck
/**
 * ChatPanel — 会话详情页的只读对话转录视图
 *
 * 续聊/恢复会话走 `/chat` 的 WebSocket 链路；这里只负责展示历史转录与
 * 实时 transcript_update，不直接启动 CLI 进程。
 */
import { memo, useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown } from "lucide-react";
import { api } from "../../lib/api";
import { eventBus } from "../../lib/eventBus";
import type { WSMessage, TranscriptMessage, TranscriptInfo } from "../../lib/types";
import { MessageList } from "../conversation/MessageList";

// Heartbeat interval to keep the file watcher alive
const HEARTBEAT_INTERVAL_MS = 60000;
// Rescan the transcripts list periodically so new subagents that spawn
// mid-session appear in the dropdown without a page reload.
const TRANSCRIPTS_REFRESH_MS = 15000;
// Catch-up poll interval for subagent message refresh. The file watcher
// only monitors the main session JSONL file, so subagent conversations
// need polling to stay current in read-only mode.
const MESSAGE_POLL_INTERVAL_MS = 6000;

// Generate a unique client ID for this component instance
function generateClientId(): string {
  return `client-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
}

// ── ChatPanel 主组件 ─────────────────────────────────────────────────

interface ChatPanelProps {
  sessionId: string;
  selectedAgentId?: string;
  onAgentChange?: (agentId: string | undefined) => void;
  /** External request to scroll the chat to the message with this uuid (task-flow linkage) */
  scrollToUuid?: string;
  /** External request to scroll the chat to the top (task-flow subagent linkage) */
  scrollToTop?: boolean;
  /** Called once the targeted uuid has been located & highlighted */
  onScrolled?: (uuid: string) => void;
  /** Called once the chat has been scrolled to the top */
  onScrolledToTop?: () => void;
}

export const ChatPanel = memo(function ChatPanel({
  sessionId,
  selectedAgentId,
  onAgentChange,
  scrollToUuid,
  scrollToTop,
  onScrolled,
  onScrolledToTop,
}: ChatPanelProps) {
  const { t } = useTranslation();
  const [messages, setMessages] = useState<TranscriptMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [transcripts, setTranscripts] = useState<TranscriptInfo[]>([]);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // Tracks whether we've already attempted the around_uuid fallback for the
  // current scrollToUuid, to avoid a reload loop when the uuid is genuinely absent.
  const fallbackAttemptedForRef = useRef<string | undefined>(undefined);
  // 追踪当前 scrollToUuid prop 的最新值，供 transcript load effect 异步回调读取
  // （避免闭包捕获旧值导致的竞态问题）
  const scrollToUuidRef = useRef<string | undefined>(undefined);
  scrollToUuidRef.current = scrollToUuid;
  const [pinnedToBottom, setPinnedToBottom] = useState(true);
  // Client ID for file watcher registration (unique per component instance)
  const clientIdRef = useRef(generateClientId());
  // Track last-loaded line number per agent for incremental polling
  const lastLineRef = useRef(0);
  // Track file size to skip server-side O(n) scan when file hasn't grown
  const fileSizeRef = useRef(0);
  // Track first-loaded line number for history (scroll-up) loading
  const firstLineRef = useRef(0);
  const [hasMore, setHasMore] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  // Refs for scroll handler to avoid stale closures
  const hasMoreRef = useRef(false);
  const loadingHistoryRef = useRef(false);

  // Scroll-up to load history: fetch older messages and prepend them
  const loadHistory = useCallback(async () => {
    if (loadingHistory || !hasMore) return;
    try {
      setLoadingHistory(true);
      loadingHistoryRef.current = true;
      const container = scrollRef.current;
      const prevScrollHeight = container?.scrollHeight ?? 0;

      const result = await api.sessions.transcript(sessionId, {
        agent_id: selectedAgentId || undefined,
        before: firstLineRef.current || undefined,
        limit: 50,
      });

      if (result.messages.length === 0) {
        setHasMore(false);
        hasMoreRef.current = false;
        setLoadingHistory(false);
        loadingHistoryRef.current = false;
        return;
      }

      firstLineRef.current = result.first_line;

      setMessages((prev) => [...result.messages, ...prev]);
      setHasMore(result.has_more);
      hasMoreRef.current = result.has_more;

      // Preserve scroll position
      requestAnimationFrame(() => {
        if (container) {
          const newScrollHeight = container.scrollHeight;
          container.scrollTop = newScrollHeight - prevScrollHeight;
        }
      });
    } catch {
      // Non-fatal
    } finally {
      setLoadingHistory(false);
      loadingHistoryRef.current = false;
    }
  }, [sessionId, selectedAgentId, loadingHistory, hasMore]);

  // Scroll handler: detect bottom for auto-scroll, detect top for history loading
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      const distance = el.scrollHeight - (el.scrollTop + el.clientHeight);
      setPinnedToBottom(distance < 80);

      // Load history when scrolled to top (use refs to avoid stale closures)
      if (el.scrollTop < 50 && hasMoreRef.current && !loadingHistoryRef.current) {
        loadHistory();
      }
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [loadHistory]);

  useEffect(() => {
    // 任务流联动：点击 subagent 步骤时 scrollToTop=true，此时不自动滚底
    if (!pinnedToBottom || scrollToTop) return;
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages.length, pinnedToBottom, scrollToTop]);

  // WebSocket subscription
  useEffect(() => {
    const unsub = eventBus.subscribe((msg: WSMessage) => {
      if (msg.type === "transcript_update") {
        const data = msg.data as {
          sessionId: string;
          messages: TranscriptMessage[];
          lastLine: number;
        };
        if (data.sessionId !== sessionId) return;
        // The file watcher only monitors the main session JSONL file, so
        // transcript_update events contain main-agent messages only. When
        // viewing a subagent, ignore these — the polling effect handles
        // subagent message refresh instead.
        if (selectedAgentId) return;

        if (data.messages.length > 0) {
          // Sync lastLineRef so the polling mechanism doesn't re-fetch
          // lines already delivered via WebSocket.
          if (data.lastLine > lastLineRef.current) {
            lastLineRef.current = data.lastLine;
          }

          setMessages((prev) => {
            // 去重策略：基于 uuid + 内容文本
            const existingUuids = new Set(prev.map((m) => m.uuid).filter(Boolean));
            const result = [...prev];
            for (const newMsg of data.messages) {
              // 1. 如果 uuid 已存在，跳过
              if (newMsg.uuid && existingUuids.has(newMsg.uuid)) continue;

              // 2. 如果是 user 消息，查找内容相同但 uuid 不同的消息（如本地乐观消息）
              if (newMsg.type === "user") {
                const newText = newMsg.content?.find((c: any) => c.type === "text")?.text;
                const dupIdx = result.findIndex(
                  (m) =>
                    m.type === "user" &&
                    m.content.some(
                      (c) => c.type === "text" && (c as { text: string }).text === newText
                    )
                );
                if (dupIdx >= 0) {
                  // 替换为有真实 uuid 的消息
                  result[dupIdx] = newMsg;
                  if (newMsg.uuid) existingUuids.add(newMsg.uuid);
                  continue;
                }
              }

              // 3. 跨批次同 msgId 去重：新 entry 到达时，清除前一条同 msgId
              //    entry 的 tps/durationMs（那些是冗余的中间值）。
              //    这样无论分多少批到达，TPS 始终只在最后一条上显示。
              if (newMsg.type === "assistant" && newMsg._messageId) {
                for (let j = result.length - 1; j >= 0; j--) {
                  const prev2 = result[j];
                  if (
                    prev2.type === "assistant" &&
                    prev2._messageId === newMsg._messageId &&
                    prev2.uuid !== newMsg.uuid
                  ) {
                    delete prev2.tps;
                    delete prev2.durationMs;
                    break; // 只清最近的一条
                  }
                }
              }

              result.push(newMsg);
              if (newMsg.uuid) existingUuids.add(newMsg.uuid);
            }
            return result;
          });

          // Auto-scroll to bottom if needed (skip when scrollToTop is active)
          if (pinnedToBottom && !scrollToTop) {
            requestAnimationFrame(() => {
              if (scrollRef.current) {
                scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
              }
            });
          }
        }
      }
      // Immediately refresh the transcript list when agents change so the
      // dropdown reflects new subagents without waiting for the next poll.
      else if (msg.type === "agent_created" || msg.type === "agent_updated") {
        api.sessions
          .transcripts(sessionId)
          .then((result) => {
            setTranscripts(result.transcripts);
          })
          .catch(() => {});
      }
    });
    return unsub;
  }, [sessionId, pinnedToBottom, selectedAgentId, scrollToTop]);

  const effectiveSessionId = sessionId;

  // Load transcript list for agent dropdown (with periodic refresh so
  // newly-spawned subagents appear in the dropdown without a page reload).
  useEffect(() => {
    if (!effectiveSessionId) return;
    let cancelled = false;
    async function loadTranscripts() {
      try {
        const result = await api.sessions.transcripts(effectiveSessionId);
        if (!cancelled) setTranscripts(result.transcripts);
      } catch {
        // Non-fatal
      }
    }
    loadTranscripts();
    const interval = window.setInterval(loadTranscripts, TRANSCRIPTS_REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [effectiveSessionId]);

  // Start file watching when component mounts, stop when unmounts
  // This enables real-time updates for external sessions (running in terminal)
  useEffect(() => {
    if (!effectiveSessionId) return;
    const clientId = clientIdRef.current;

    // Start watching
    api.sessions.watch(effectiveSessionId, { clientId }).catch(() => {
      // Non-fatal: file watching is optional
    });

    // Heartbeat to keep the watcher alive
    const heartbeatInterval = window.setInterval(() => {
      api.sessions.heartbeat(effectiveSessionId, { clientId }).catch(() => {});
    }, HEARTBEAT_INTERVAL_MS);

    return () => {
      // Stop watching when component unmounts
      window.clearInterval(heartbeatInterval);
      api.sessions.unwatch(effectiveSessionId, { clientId }).catch(() => {});
    };
  }, [effectiveSessionId]);

  // Load transcript messages for the current agent source.
  // Bound to sessionId + selectedAgentId: switching the agent dropdown / clicking
  // a task-flow node only reloads messages — it must NOT re-spawn claude.
  useEffect(() => {
    if (!effectiveSessionId) return;
    let cancelled = false;
    setLoading(true);
    lastLineRef.current = 0; // Reset cursor on agent switch
    firstLineRef.current = 0;
    setHasMore(false);
    hasMoreRef.current = false;
    // 切换会话源时重置 pinnedToBottom：有 scrollToUuid 时不自动滚底（交由定位逻辑处理），
    // 否则滚到底部以便用户看到最新消息
    setPinnedToBottom(!scrollToUuidRef.current);
    // System 消息（turn_duration/compaction/error）现在由 transcript API 直接
    // 按 JSONL 顺序返回，无需单独加载 system-events。
    api.sessions
      .transcript(effectiveSessionId, {
        agent_id: selectedAgentId || undefined,
        limit: 50,
      })
      .then((transcript) => {
        if (!cancelled) {
          setMessages(transcript.messages ?? []);
          setLoading(false);
          lastLineRef.current = transcript.last_line;
          firstLineRef.current = transcript.first_line;
          setHasMore(transcript.has_more);
          hasMoreRef.current = transcript.has_more;
          if (transcript.fileSize) fileSizeRef.current = transcript.fileSize;

          // 消息加载完成后，如果父组件要求跳转到特定 uuid，在此处理
          // 使用 ref 读取最新值（避免闭包捕获旧值）
          const targetUuid = scrollToUuidRef.current;
          if (targetUuid) {
            // 延迟到下一帧，确保 DOM 已更新
            requestAnimationFrame(() => {
              if (cancelled) return;
              const el = scrollRef.current?.querySelector(
                `[data-uuid="${CSS.escape(targetUuid)}"]`
              ) as HTMLElement | null;
              if (el) {
                // 找到目标 → 滚动 + 高亮 + 通知父组件
                el.scrollIntoView({ behavior: "smooth", block: "center" });
                el.style.transition = "background-color 0.3s";
                const isDark = document.documentElement.classList.contains("dark");
                el.style.backgroundColor = isDark ? "rgba(168, 162, 255, 0.15)" : "#fef3c7";
                el.style.boxShadow = isDark ? "inset 0 0 0 1px rgba(168, 162, 255, 0.25)" : "";
                window.setTimeout(() => {
                  el.style.backgroundColor = "";
                  el.style.boxShadow = "";
                }, 3000);
                onScrolled?.(targetUuid);
                return;
              }
              // 目标不在最新 50 条消息中 → 用 around_uuid 定向加载
              if (fallbackAttemptedForRef.current !== targetUuid) {
                fallbackAttemptedForRef.current = targetUuid;
                api.sessions
                  .transcript(effectiveSessionId, { around_uuid: targetUuid, limit: 50 })
                  .then((t) => {
                    if (!cancelled) {
                      setMessages(t.messages ?? []);
                      // around_uuid 加载后再尝试一次定位
                      requestAnimationFrame(() => {
                        if (cancelled) return;
                        const el2 = scrollRef.current?.querySelector(
                          `[data-uuid="${CSS.escape(targetUuid)}"]`
                        ) as HTMLElement | null;
                        if (el2) {
                          el2.scrollIntoView({ behavior: "smooth", block: "center" });
                          el2.style.transition = "background-color 0.3s";
                          const isDark2 = document.documentElement.classList.contains("dark");
                          el2.style.backgroundColor = isDark2
                            ? "rgba(168, 162, 255, 0.15)"
                            : "#fef3c7";
                          el2.style.boxShadow = isDark2
                            ? "inset 0 0 0 1px rgba(168, 162, 255, 0.25)"
                            : "";
                          window.setTimeout(() => {
                            el2.style.backgroundColor = "";
                            el2.style.boxShadow = "";
                          }, 3000);
                        }
                        onScrolled?.(targetUuid);
                      });
                    }
                  })
                  .catch(() => {
                    onScrolled?.(targetUuid);
                  });
              }
            });
          } else {
            // 无跳转目标时，滚到底部以便用户看到最新消息
            requestAnimationFrame(() => {
              if (cancelled) return;
              if (scrollRef.current) {
                scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
              }
            });
          }
        }
      })
      .catch(() => {
        if (!cancelled) {
          setMessages([]);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [effectiveSessionId, selectedAgentId]);

  // Visibility-gated message polling for the current agent's transcript.
  // The file watcher only tracks the main session JSONL file, so subagent
  // conversations rely on polling to receive new messages in real-time.
  // Pauses when the tab is hidden, fires a one-shot catch-up on re-focus.
  useEffect(() => {
    if (!effectiveSessionId) return;
    let interval: number | null = null;

    async function poll() {
      try {
        const wasBootstrap = lastLineRef.current === 0;
        const result = await api.sessions.transcript(effectiveSessionId, {
          agent_id: selectedAgentId || undefined,
          ...(wasBootstrap ? {} : { after: lastLineRef.current }),
          limit: 50,
          fileSize: fileSizeRef.current || undefined,
        });
        if (result.messages.length > 0) {
          lastLineRef.current = result.last_line;
          if (result.fileSize) fileSizeRef.current = result.fileSize;

          // Bootstrap: the initial load was empty, update firstLine/hasMore too
          if (wasBootstrap) {
            firstLineRef.current = result.first_line;
            setHasMore(result.has_more);
            hasMoreRef.current = result.has_more;
          }

          setMessages((prev) => {
            if (wasBootstrap) return result.messages;
            // Incremental: dedup by uuid and append
            const existingUuids = new Set(prev.map((m) => m.uuid).filter(Boolean));
            const newOnes = result.messages.filter((m) => !m.uuid || !existingUuids.has(m.uuid));
            if (newOnes.length === 0) return prev;
            const out = [...prev];
            for (const m of newOnes) {
              if (m.type === "user") {
                const text = m.content?.find((c: any) => c.type === "text")?.text;
                const dup = out.findIndex(
                  (x) =>
                    x.type === "user" &&
                    x.content.some((c) => c.type === "text" && (c as any).text === text)
                );
                if (dup >= 0) {
                  out[dup] = m;
                  continue;
                }
              }
              out.push(m);
            }
            return out;
          });

          // Auto-scroll if at bottom (skip when scrollToTop is active)
          if (pinnedToBottom && !scrollToTop) {
            requestAnimationFrame(() => {
              if (scrollRef.current) {
                scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
              }
            });
          }
        }
      } catch {
        // Non-fatal
      }
    }

    function start() {
      if (interval !== null) return;
      interval = window.setInterval(poll, MESSAGE_POLL_INTERVAL_MS);
    }
    function stop() {
      if (interval !== null) {
        window.clearInterval(interval);
        interval = null;
      }
    }
    function onVisibility() {
      if (document.visibilityState === "visible") {
        poll(); // One-shot catch-up immediately
        start();
      } else {
        stop();
      }
    }

    if (document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [effectiveSessionId, selectedAgentId, pinnedToBottom, scrollToTop]);

  // ── 任务流联动：按 uuid 定位会话消息 ──────────────────────────────
  // scrollToUuid 由父组件（TaskDetail）传入。会话源切换（selectedAgentId 变化）会
  // 异步重载 transcript，重载完成后 messages 变化 → 本 effect 重新触发定位。
  // 若目标 uuid 不在已加载范围（超长会话 > limit），兜底用 around_uuid 定向加载。
  useEffect(() => {
    if (!scrollToUuid) return;
    // 新的目标 uuid：重置兜底标记（允许每次新目标都尝试一次兜底加载）
    if (fallbackAttemptedForRef.current !== scrollToUuid) {
      fallbackAttemptedForRef.current = undefined;
    }

    let cancelled = false;
    let retry = 0;
    const MAX_RETRY = 8; // ~8 帧，覆盖切源异步重载延迟

    const highlight = (el: HTMLElement) => {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.style.transition = "background-color 0.3s";
      const isDark = document.documentElement.classList.contains("dark");
      el.style.backgroundColor = isDark ? "rgba(168, 162, 255, 0.15)" : "#fef3c7";
      el.style.boxShadow = isDark ? "inset 0 0 0 1px rgba(168, 162, 255, 0.25)" : "";
      window.setTimeout(() => {
        el.style.backgroundColor = "";
        el.style.boxShadow = "";
      }, 3000);
    };

    const attempt = () => {
      if (cancelled) return;
      const el = scrollRef.current?.querySelector(
        `[data-uuid="${CSS.escape(scrollToUuid)}"]`
      ) as HTMLElement | null;
      if (el) {
        highlight(el);
        onScrolled?.(scrollToUuid);
        return;
      }
      if (retry++ < MAX_RETRY) {
        requestAnimationFrame(attempt);
        return;
      }
      // 兜底：目标 uuid 不在已加载范围，按 uuid 定向加载（每个目标仅尝试一次）
      // 注意：不在这里调用 onScrolled，等 messages 更新后 effect 自然重跑并找到目标
      if (fallbackAttemptedForRef.current === scrollToUuid) return;
      fallbackAttemptedForRef.current = scrollToUuid;
      api.sessions
        .transcript(effectiveSessionId, { around_uuid: scrollToUuid, limit: 50 })
        .then((t) => {
          if (!cancelled) {
            setMessages(t.messages ?? []);
          }
        })
        .catch(() => {
          // 兜底加载失败：放弃定位，通知父组件清空 pending 以免一直等待
          onScrolled?.(scrollToUuid);
        });
    };
    requestAnimationFrame(attempt);
    return () => {
      cancelled = true;
    };
  }, [messages, scrollToUuid, effectiveSessionId, onScrolled]);

  // ── 任务流联动：点击 subagent 步骤时滚到该会话最开头 ──────────────────
  // scrollToTop 由父组件（TaskDetail）在切换 selectedAgentId 时设置 true。
  // 等消息加载完成后滚到顶部，然后回调通知父组件清空。
  useEffect(() => {
    if (!scrollToTop) return;
    let cancelled = false;
    let retry = 0;
    const MAX_RETRY = 8; // ~8 帧，覆盖切源异步重载延迟

    const attempt = () => {
      if (cancelled) return;
      const el = scrollRef.current;
      if (el && messages.length > 0) {
        el.scrollTop = 0;
        onScrolledToTop?.();
        return;
      }
      if (retry++ < MAX_RETRY) {
        requestAnimationFrame(attempt);
      } else {
        // 兜底：放弃滚动，避免父组件一直等待
        onScrolledToTop?.();
      }
    };
    requestAnimationFrame(attempt);

    return () => {
      cancelled = true;
    };
  }, [scrollToTop, messages.length, onScrolledToTop]);

  // 角色过滤：all / user / assistant / system。过滤只影响渲染，不改底层数据。
  // System 事件与 TranscriptMessage 分开存储，按所选角色各自筛选。
  const [roleFilter, setRoleFilter] = useState<"all" | "user" | "assistant" | "system">("all");
  // 切换会话或 agent 源时重置角色过滤：ChatPanel 组件实例会被复用（SessionDetail
  // 保持 visitedTabs 挂载），否则上个视图选中的 "system" 会残留，导致新会话
  // 只显示 System 事件而看不到 User/Assistant 消息。
  useEffect(() => {
    setRoleFilter("all");
  }, [effectiveSessionId, selectedAgentId]);
  // System 消息现在与 User/Assistant 一起由 transcript API 按顺序返回，
  // 过滤直接按消息 type 字段筛选即可，无需额外的 systemEvents 数组。
  const filteredMessages = useMemo(() => {
    if (roleFilter === "all") return messages;
    return messages.filter((m) => m.type === roleFilter);
  }, [messages, roleFilter]);

  return (
    <div className="flex flex-col h-full bg-surface-2 rounded-xl border border-border/50 overflow-hidden">
      {/* 工具栏 */}
      <div className="border-b border-border/40 px-4 py-2.5 flex items-center gap-2 flex-wrap shrink-0 bg-surface-1">
        {/* 状态指示 - 已屏蔽 */}
        {/* Agent 选择器 —— 始终显示，便于在主会话与 subagent 间切换 */}
        <div className="relative">
          <select
            value={selectedAgentId || ""}
            onChange={(e) => onAgentChange?.(e.target.value || undefined)}
            className="appearance-none bg-surface-3 border border-border/50 rounded-lg px-2 py-1 pr-6 text-xs text-muted focus:outline-none focus:border-blue-400 hover:border-blue-300 cursor-pointer"
          >
            <option value="">Main Agent</option>
            {transcripts
              .filter((t) => t.type !== "main")
              .map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
          </select>
          <ChevronDown className="w-3 h-3 text-faint absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
        </div>

        {/* 角色过滤 —— 右侧：User / Assistant / System / 全部 */}
        <div className="ml-auto flex items-center gap-1">
          {(
            [
              { value: "all", label: "All" },
              { value: "user", label: "User" },
              { value: "assistant", label: "Assistant" },
              { value: "system", label: "System" },
            ] as const
          ).map((r) => (
            <button
              key={r.value}
              type="button"
              onClick={() => setRoleFilter(r.value)}
              className={`text-[11px] px-2 py-1 rounded-md border transition-colors cursor-pointer ${
                roleFilter === r.value
                  ? "bg-blue-100 text-blue-700 border-blue-300 dark:bg-blue-500/20 dark:text-blue-300 dark:border-blue-500/40"
                  : "bg-surface-3 text-faint border-border/50 hover:text-muted hover:border-blue-300"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* 对话流区域 */}
      <div ref={scrollRef} className="flex-1 overflow-auto min-h-0">
        {/* History loading indicator */}
        {loadingHistory && (
          <div className="flex justify-center py-3">
            <div className="w-4 h-4 border-2 border-faint border-t-transparent rounded-full animate-spin" />
            <span className="text-xs text-muted ml-2">Loading history...</span>
          </div>
        )}

        {/* Scroll-up for history hint */}
        {hasMore && !loadingHistory && !loading && (
          <div className="flex justify-center py-2">
            <span className="text-[11px] text-faint">↑ Scroll up for older messages</span>
          </div>
        )}

        {loading && (
          <div className="text-center py-12 text-faint flex flex-col items-center gap-2">
            <div className="w-5 h-5 border-2 border-faint border-t-transparent rounded-full animate-spin" />
            <span className="text-xs">加载中...</span>
          </div>
        )}
        {!loading && filteredMessages.length === 0 && (
          <div className="text-center py-12 text-faint text-sm">
            {roleFilter !== "all"
              ? t("chat.noMessagesWithFilter")
              : t("chat.noMessagesSessionCleared")}
          </div>
        )}
        {!loading && filteredMessages.length > 0 && (
          <MessageList messages={filteredMessages} loading={false} />
        )}
      </div>
    </div>
  );
});

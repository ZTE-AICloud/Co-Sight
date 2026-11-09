// SPDX-License-Identifier: Apache-2.0
/**
 * @file AgentPickerDialog.tsx
 * @description 「召唤更多智能体」弹框 —— 本模块自己实现的选择器。
 *
 * 数据来自 **smart-factory** 的 `GET /agents`(裸 `{items,total}`,见 `api/harness-api.ts`)。
 * 选出来的 `agt_…` 会随首帧 `send` 的 `agentId` 直接进建会话,不需要任何映射。
 *
 * 与专家页的关系:**卡片构成同专家页**(头像、名称、描述、标签),但刻意**只有"选"** ——
 * 专家页卡片上那排「设计/评估/优化」在这里没有。
 *
 * 字段差异(相对早期的框架专家):没有作者 / 使用次数 / 预置,但有 `status`(草稿/就绪/归档)
 * 与 `icon`(封面图);筛选因此从「全部/最热/最新/预置」换成按**状态**筛。
 *
 * 弹框刻意**不要压黑背景**:它开在对话首页之上,用户该看得见后面那个页面。
 * 所以遮罩只留一点点(0.05),弹框也收着尺寸 —— 想再调就改这两个数。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { Loader2, Search, X } from "lucide-react";
import {
  fetchAgentPage,
  MAX_EXPERTS,
  type AgentSourceFilter,
  type HarnessAgent,
} from "../../api/harness-api";

/** 输入到发请求之间的等待。与专家页同一个 250ms。 */
const SEARCH_DEBOUNCE_MS = 250;

/** 卡片上平铺的标签数,超出折成 `+N`。 */
const MAX_VISIBLE_TAGS = 3;

/** 触底提前量:离底还有这么多像素就开始取下一页。 */
const LOAD_MORE_MARGIN_PX = 160;

/**
 * 来源筛选（服务端 `?source=user|builtin`；全部 = 不筛）。
 *
 * 状态由服务端过滤：每次请求都带 `status=completed`（已就绪）。
 * `null`（历史/读取失败行）不在服务端枚举里，因此不会被返回。
 */
const FILTERS: readonly AgentSourceFilter[] = ["all", "builtin", "user"];

/** 打字时不必每个字符都查一次;250ms 内的连续输入只算最后一次。 */
function useDebounced<T>(value: T, delayMs: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return settled;
}

/** `icon` 是图片地址还是 emoji/文本。 */
function isImageIcon(icon: string): boolean {
  return /^(https?:|data:|\/)/.test(icon);
}

export interface AgentPickerDialogProps {
  onClose: () => void;
  /** 用户点了「确认」。 */
  onPicked: (agentId: string) => void;
}

export function AgentPickerDialog({ onClose, onPicked }: AgentPickerDialogProps) {
  const { t } = useTranslation();
  const searchRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  /**
   * 换搜索词/筛选就 +1。
   *
   * 追加请求是在途的,回来时列表可能已经被换掉了 —— 对不上号的响应直接丢掉,
   * 否则旧关键字的那一页会被追加到新列表后面。
   */
  const generationRef = useRef(0);

  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<AgentSourceFilter>("all");
  const [items, setItems] = useState<HarnessAgent[]>([]);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const debouncedQuery = useDebounced(query, SEARCH_DEBOUNCE_MS);
  /** 攒到上限就不再加了。 */
  const capped = items.length >= MAX_EXPERTS;

  /** 第一页；搜索词或筛选一变就整个重来（不追加，免得混着两个条件的结果）。 */
  useEffect(() => {
    const generation = generationRef.current + 1;
    generationRef.current = generation;
    setStatus("loading");
    setItems([]);
    setPage(1);
    setHasMore(false);

    fetchAgentPage(
      { keyword: debouncedQuery, source: filter, status: "completed" },
      1
    )
      .then((result) => {
        if (generationRef.current !== generation) return;
        setItems(result.items);
        setHasMore(result.hasMore);
        setStatus("ready");
      })
      .catch(() => {
        if (generationRef.current !== generation) return;
        setItems([]);
        setHasMore(false);
        setStatus("error");
      });
  }, [debouncedQuery, filter]);

  /** 滚到底时追加下一页。 */
  const loadMore = useCallback(() => {
    if (status !== "ready" || loadingMore || !hasMore || capped) return;
    const generation = generationRef.current;
    setLoadingMore(true);

    fetchAgentPage(
      { keyword: debouncedQuery, source: filter, status: "completed" },
      page + 1
    )
      .then((result) => {
        if (generationRef.current !== generation) return;
        setItems((prev) => [...prev, ...result.items]);
        setPage((prev) => prev + 1);
        setHasMore(result.hasMore);
      })
      .catch(() => {
        // 追加失败就停在已加载的这段：不自动重试，否则滚动时会把后端打爆。
        if (generationRef.current === generation) setHasMore(false);
      })
      .finally(() => {
        if (generationRef.current === generation) setLoadingMore(false);
      });
  }, [capped, debouncedQuery, filter, hasMore, loadingMore, page, status]);

  /** 触底哨兵进了视口就取下一页。root 用列表自己的滚动容器,不是整个视口。 */
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (sentinel === null) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) loadMore();
      },
      { root: scrollRef.current, rootMargin: `${String(LOAD_MORE_MARGIN_PX)}px` },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [loadMore]);

  /** 打开就把焦点给搜索框 —— 这个弹框的第一动作是"找智能体"。 */
  useEffect(() => {
    searchRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const confirm = useCallback(() => {
    if (selectedId !== null) onPicked(selectedId);
  }, [onPicked, selectedId]);

  return createPortal(
    /*
     * 遮罩**几乎不压黑**:这个弹框开在对话首页之上,背景应当还是那个首页。
     * 弹簧靠下偏上、尺寸收着,让框外的标题/输入框仍可见。
     */
    <div
      className="fixed inset-0 z-[70] flex items-start justify-center px-6 pb-6 pt-[8vh]"
      style={{ backgroundColor: "rgba(0, 0, 0, 0.05)" }}
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("run.selectAgentToChat")}
        className="flex h-[min(620px,70vh)] w-[min(920px,90vw)] flex-col overflow-hidden rounded-2xl border border-border/40 bg-white shadow-2xl dark:bg-surface-2"
        onClick={(event) => event.stopPropagation()}
      >
        {/* 头部:标题 + 关闭 */}
        <div className="flex shrink-0 items-center justify-between border-b border-border/40 px-5 py-3">
          <h2 className="text-base font-semibold text-secondary">{t("run.selectAgentToChat")}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("common:close")}
            className="text-faint transition-colors hover:text-primary"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* 工具栏:搜索 + 按状态筛选 */}
        <div className="flex shrink-0 flex-wrap items-center gap-2 px-5 py-3">
          <div className="relative min-w-[200px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" />
            <input
              ref={searchRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("chat.picker.search")}
              aria-label={t("chat.picker.search")}
              className="w-full rounded-lg border border-border/60 bg-surface-1 py-1.5 pl-8 pr-3 text-sm text-primary placeholder:text-muted focus:border-accent focus:outline-none"
            />
          </div>
          <div className="flex items-center gap-1">
            {FILTERS.map((item) => (
              <button
                key={item}
                type="button"
                aria-pressed={filter === item}
                onClick={() => setFilter(item)}
                className={`rounded-lg px-3 py-1.5 text-xs transition-colors ${
                  filter === item
                    ? "bg-accent text-white"
                    : "text-secondary hover:bg-surface-4 hover:text-primary"
                }`}
              >
                {t(`chat.picker.${item}`)}
              </button>
            ))}
          </div>
        </div>

        {/* 卡片网格:滚到底自动追加下一页 */}
        <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-5 pb-4">
          {status !== "ready" ? (
            <p className="py-10 text-center text-sm text-muted">
              {status === "error" ? t("chat.picker.error") : t("common:loading")}
            </p>
          ) : items.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted">{t("chat.picker.empty")}</p>
          ) : (
            <>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {items.map((agent) => (
                  <AgentPickCard
                    key={agent.id}
                    agent={agent}
                    selected={selectedId === agent.id}
                    onSelect={() => setSelectedId(agent.id)}
                    sourceLabel={t(`chat.picker.${agent.source}`)}
                  />
                ))}
              </div>

              {/* 触底哨兵:它进视口就等于"该取下一页了" */}
              <div ref={sentinelRef} aria-hidden="true" className="h-px w-full" />

              {/* 列表末尾必须给个说法,否则用户分不清"就这些"还是"还能往下滚" */}
              {capped ? (
                <p className="py-3 text-center text-xs text-muted">
                  {t("chat.picker.truncated", { count: MAX_EXPERTS })}
                </p>
              ) : loadingMore ? (
                <p className="flex items-center justify-center gap-2 py-3 text-xs text-muted">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  {t("common:loading")}
                </p>
              ) : hasMore ? null : (
                <p className="py-3 text-center text-xs text-faint">{t("chat.picker.end")}</p>
              )}
            </>
          )}
        </div>

        {/* 底部:取消 / 确认 */}
        <div className="flex shrink-0 items-center justify-end gap-2 border-t border-border/40 px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-4 py-1.5 text-sm text-secondary transition-colors hover:bg-surface-4 hover:text-primary"
          >
            {t("common:cancel")}
          </button>
          <button
            type="button"
            onClick={confirm}
            disabled={selectedId === null}
            className="rounded-lg bg-accent px-4 py-1.5 text-sm text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
          >
            {t("chat.picker.confirm")}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

interface AgentPickCardProps {
  agent: HarnessAgent;
  selected: boolean;
  onSelect: () => void;
  /** 内置 / 自定义：由 `source` 判定，不要用 `status === null` 推断。 */
  sourceLabel: string;
}

/**
 * 一张智能体卡。构成:头像 / 名称 / 来源 / 描述 / 标签;
 * 区别是**整卡就是一个选择按钮**,没有专家页那排动作按钮。
 */
function AgentPickCard({ agent, selected, onSelect, sourceLabel }: AgentPickCardProps) {
  const visibleTags = agent.tags.slice(0, MAX_VISIBLE_TAGS);
  const hiddenCount = agent.tags.length - visibleTags.length;

  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      className={`flex flex-col gap-2 rounded-xl border p-3 text-left transition-colors ${
        selected
          ? "border-accent bg-accent/5"
          : "border-border/60 bg-surface-1 hover:border-border hover:bg-surface-2"
      }`}
    >
      <span className="flex items-center gap-2">
        <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center overflow-hidden rounded-full bg-surface-4 text-xs font-medium text-secondary">
          {agent.icon === "" ? (
            agent.name.slice(0, 1)
          ) : isImageIcon(agent.icon) ? (
            <img src={agent.icon} alt="" className="h-full w-full object-cover" />
          ) : (
            agent.icon
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-primary" title={agent.name}>
            {agent.name}
          </span>
          <span className="mt-0.5 flex items-center gap-1">
            {/* 来源：内置 / 自定义 —— 由 source 判定 */}
            <span className="inline-flex items-center rounded bg-surface-4 px-1.5 py-0.5 text-[11px] text-secondary">
              {sourceLabel}
            </span>
          </span>
        </span>
      </span>

      {agent.description === "" ? null : (
        <span className="line-clamp-2 text-xs leading-relaxed text-secondary">
          {agent.description}
        </span>
      )}

      {/* 标签行永远占位(`mt-auto`),让不同卡片的选择区高度一致 */}
      <span className="mt-auto flex flex-wrap gap-1">
        {visibleTags.map((tag) => (
          <span
            key={tag}
            className="rounded-md bg-surface-4 px-1.5 py-0.5 text-[11px] text-secondary"
            title={tag}
          >
            {tag}
          </span>
        ))}
        {hiddenCount <= 0 ? null : (
          <span
            className="rounded-md bg-surface-4 px-1.5 py-0.5 text-[11px] text-muted"
            title={agent.tags.join("、")}
          >
            {`+${String(hiddenCount)}`}
          </span>
        )}
      </span>
    </button>
  );
}

// SPDX-License-Identifier: Apache-2.0
/**
 * @file ComposerMenu.tsx
 * @description composer 左下角 `+` 弹出的两级菜单。
 *
 * 一级:**添加文件**（二级:本地文件）、**智能体**（二级:智能体列表）。
 * 开聊后智能体不可再改，一级只保留「添加文件」。
 *
 * 定位:必须 portal 到 `document.body` + `position: fixed`。因为 composer 位于
 * `Layout` 的裁切链里(`overflow-hidden` → `main` 的 `overflow-auto` →
 * `overflow-x-hidden`,外加 `.card{overflow-x:clip}`),常规绝对定位会被裁掉。
 * 二级浮层**不能**是一级的 DOM 子节点,否则点二级会被判成"落在菜单内部"而不关闭,
 * 因此两级各用一个 portal。
 */

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { Bot, Check, ChevronRight, ExternalLink, Paperclip, Search, Upload } from "lucide-react";
import { fetchAgentPickerPage, type Agent } from "../../api/agent-api";
import { AGENT_PICKER_LIMIT, type AgentChoice } from "../../pages/chat/useChatSession";
import { AgentAvatar } from "./AgentAvatar";

/** 二级浮层的类型。 */
type Section = "file" | "agent";

/** 一级菜单：添加文件在上，智能体在下（开聊后智能体不可再改）。 */
const FILE_ITEM = {
  key: "file" as const,
  labelKey: "run.addFile",
  icon: Paperclip,
};
const AGENT_ITEM = { key: "agent" as const, labelKey: "run.agent", icon: Bot };

/** 浮层宽度,用于判断子菜单会不会超出右边界。 */
const SUBMENU_WIDTH = 288;
/** 一级与二级之间的横向间隙:够开即可,再大就会和一级菜单"脱开"。 */
const SUBMENU_GAP = 4;
/** 二级面板自身的内边距(`p-1`)。对齐时要把这一层算进去,条目才会和一级同高同线。 */
const SUBMENU_PADDING = 4;

/**
 * 把浮层固定定位在锚点上方(composer 贴底,面板向上生长,无需先量高度)。
 * 监听 resize 与 scroll(capture,才能捕获到 `main` 的滚动)。
 *
 * 导出给 `ChatComposer` 的模型选择器复用 —— 同一套裁切规避策略。
 */
export function useFixedStyle(
  enabled: boolean,
  compute: () => React.CSSProperties,
  deps: React.DependencyList,
): React.CSSProperties | undefined {
  const [style, setStyle] = useState<React.CSSProperties | undefined>(undefined);

  useLayoutEffect(() => {
    if (!enabled) {
      setStyle(undefined);
      return;
    }
    const place = () => setStyle(compute());
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
    // compute 每次渲染都是新引用;真正的输入由 deps 携带
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, ...deps]);

  return style;
}

/** 搜索输入到发请求之间的等待：连续输入只查最后一次。 */
const AGENT_SEARCH_DEBOUNCE_MS = 250;
/** `+` 菜单一次搜索最多展示的结果数；更多结果交给「召唤更多智能体」。 */
export const AGENT_SEARCH_LIMIT = 20;

/** 输入防抖：`value` 停止变化 `delayMs` 后才返回新值。 */
function useDebounced<T>(value: T, delayMs: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return settled;
}

type SearchStatus = "idle" | "loading" | "ready" | "error";

interface AgentPickerPanelProps {
  agents: AgentChoice[];
  /** 当前选中的智能体；不在前 N 个里时置顶显示，避免重新打开菜单看不到勾选。 */
  selectedAgent?: AgentChoice | null;
  onSelect: (agent: AgentChoice) => void;
  onBrowseMore: () => void;
}

/** 智能体二级面板：前 N 个 + 服务端关键字搜索 + 召唤更多。 */
function AgentPickerPanel({
  agents,
  selectedAgent,
  onSelect,
  onBrowseMore,
}: AgentPickerPanelProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const keyword = query.trim();
  const debouncedKeyword = useDebounced(keyword, AGENT_SEARCH_DEBOUNCE_MS);

  const [search, setSearch] = useState<{
    status: SearchStatus;
    items: Agent[];
    total: number;
  }>({ status: "idle", items: [], total: 0 });
  /** 换关键字就 +1，丢弃对不上号的响应（后发先至时不能覆盖新结果）。 */
  const searchGenerationRef = useRef(0);

  useEffect(() => {
    const generation = ++searchGenerationRef.current;
    if (debouncedKeyword === "") {
      setSearch({ status: "idle", items: [], total: 0 });
      return;
    }

    setSearch((prev) => ({ ...prev, status: "loading" }));
    fetchAgentPickerPage(
      { keyword: debouncedKeyword, pageSize: AGENT_SEARCH_LIMIT, status: "completed" },
      1,
    )
      .then((result) => {
        if (generation !== searchGenerationRef.current) return;
        setSearch({ status: "ready", items: result.items, total: result.total });
      })
      .catch(() => {
        if (generation !== searchGenerationRef.current) return;
        setSearch({ status: "error", items: [], total: 0 });
      });

    // 卸载 / 换关键字时作废这次请求，避免回来时写进已卸载的组件
    return () => {
      searchGenerationRef.current += 1;
    };
  }, [debouncedKeyword]);

  /** 无搜索词：前 N 个；当前选中不在其中时置顶补一条。 */
  const defaultList = useMemo(() => {
    const first = agents.slice(0, AGENT_PICKER_LIMIT);
    if (selectedAgent === null || selectedAgent === undefined) return first;
    if (first.some((agent) => agent.id === selectedAgent.id)) return first;
    return [selectedAgent, ...first];
  }, [agents, selectedAgent]);

  const searching = keyword !== "";
  const pending = searching && (debouncedKeyword !== keyword || search.status === "loading");
  const visible: AgentChoice[] = searching ? search.items : defaultList;
  const showMoreHint =
    searching && search.status === "ready" && search.total > search.items.length;

  return (
    <div className="w-72">
      <div className="border-b border-border/50 p-2">
        <div className="flex items-center gap-2 rounded-lg bg-surface-3 px-2.5 py-1.5">
          <Search className="h-3.5 w-3.5 flex-shrink-0 text-muted" />
          <input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("run.searchAgent")}
            aria-label={t("run.searchAgent")}
            className="w-full bg-transparent text-sm text-primary placeholder:text-muted focus:outline-none"
          />
        </div>
      </div>

      <div
        role="listbox"
        aria-label={t("run.selectAgentToChat")}
        className="max-h-64 overflow-y-auto p-1"
      >
        {pending ? (
          <p className="px-2 py-3 text-center text-xs text-muted">{t("common:loading")}</p>
        ) : searching && search.status === "error" ? (
          <p className="px-2 py-3 text-center text-xs text-muted">{t("chat.picker.error")}</p>
        ) : visible.length === 0 ? (
          <p className="px-2 py-3 text-center text-xs text-muted">{t("agentUi.noMatch")}</p>
        ) : (
          visible.map((agent) => (
            <button
              key={agent.id}
              role="option"
              aria-selected={agent.id === selectedAgent?.id}
              onClick={() => onSelect(agent)}
              className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-surface-4"
            >
              <AgentAvatar icon={agent.icon} name={agent.name} />
              <span className="min-w-0 flex-1 truncate text-sm text-primary">{agent.name}</span>
              {agent.id === selectedAgent?.id && (
                <Check className="h-3.5 w-3.5 flex-shrink-0 text-accent" />
              )}
            </button>
          ))
        )}
      </div>

      {showMoreHint && (
        <p className="px-3 py-1 text-center text-[11px] text-muted">
          {t("chat.picker.showingFirst", {
            count: search.items.length,
            total: search.total,
          })}
        </p>
      )}

      <div className="border-t border-border/50 p-1">
        <button
          onClick={onBrowseMore}
          className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm text-muted transition-colors hover:bg-surface-4 hover:text-primary"
        >
          <ExternalLink className="h-3.5 w-3.5 flex-shrink-0" />
          <span>{t("run.moreAgents")}</span>
        </button>
      </div>
    </div>
  );
}

export interface ComposerMenuProps {
  open: boolean;
  /** `+` 按钮,作为一级浮层的锚点 */
  triggerRef: React.RefObject<HTMLElement | null>;
  agents: AgentChoice[];
  /** 当前选中的智能体（按对象传，搜索结果选中的也能直接拿来置顶/显示勾选） */
  selectedAgent?: AgentChoice | null;
  /** 开聊后智能体不可再改：只保留「添加文件」 */
  canSelectAgent?: boolean;
  /** 点击「添加文件 → 本地文件」 */
  onPickLocalFiles: () => void;
  onSelectAgent: (agent: AgentChoice) => void;
  onBrowseMoreAgents: () => void;
  /**
   * 展开「智能体」二级菜单时通知调用方。
   *
   * 智能体列表是在别的页面/窗口里增删的，而对话 iframe 不会因此重建；上层借这个
   * 时机重拉一次，避免「刚删掉的智能体还挂在菜单里」。菜单自己不负责数据，
   * 只负责说“用户要看智能体了”。
   */
  onOpenAgentSection?: () => void;
  onClose: () => void;
}

export function ComposerMenu({
  open,
  triggerRef,
  agents,
  selectedAgent,
  canSelectAgent = true,
  onPickLocalFiles,
  onSelectAgent,
  onBrowseMoreAgents,
  onOpenAgentSection,
  onClose,
}: ComposerMenuProps) {
  const { t } = useTranslation();
  const rootItems = canSelectAgent ? [FILE_ITEM, AGENT_ITEM] : [FILE_ITEM];
  const [section, setSection] = useState<Section | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const submenuRef = useRef<HTMLDivElement>(null);
  /** 一级每一项的 DOM,用于把二级浮层对齐到**当前这一行**而不是整个一级菜单。 */
  const itemRefs = useRef<Partial<Record<Section, HTMLButtonElement | null>>>({});

  // 重新打开时总从一级开始
  useEffect(() => {
    if (!open) setSection(null);
  }, [open]);

  /**
   * 展开二级菜单。`file` 与 `agent` 走同一个入口，后者顺手请上层刷新智能体列表。
   *
   * 放在用户动作里而不是 effect 里：父组件重渲染不会重复触发，只有真正切换
   * 菜单项时才通知；上层另有 1 秒节流兜底（来回悬停不会连发请求）。
   */
  function showSection(next: Section) {
    setSection(next);
    if (next === "agent") onOpenAgentSection?.();
  }

  // 外部点击 / Esc 关闭。注册的 ref 覆盖两个浮层与触发按钮。
  useEffect(() => {
    if (!open) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // 二级 → 一级 → 关闭
      if (section) setSection(null);
      else onClose();
    };

    const onMouseDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (triggerRef.current?.contains(target)) return;
      if (rootRef.current?.contains(target)) return;
      if (submenuRef.current?.contains(target)) return;
      onClose();
    };

    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("mousedown", onMouseDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("mousedown", onMouseDown, true);
    };
  }, [open, section, onClose, triggerRef]);

  const rootStyle = useFixedStyle(open, () => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return {};
    return {
      left: rect.left,
      bottom: Math.max(8, window.innerHeight - rect.top + 8),
    };
  }, [section]);

  const submenuStyle = useFixedStyle(
    open && section !== null,
    () => {
      const rect = rootRef.current?.getBoundingClientRect();
      if (!rect) return {};
      // 底边对齐**当前悬停的那一行**的底边:二级只有一行时正好与一级同一行;
      // 智能体面板较高,则从这里向上生长,和原来一样不会顶出视口。
      const itemRect = (section === null ? null : itemRefs.current[section])?.getBoundingClientRect();
      // 以二级条目(而不是面板外沿)对齐:补上它自己的内边距,视觉上就与一级那一行齐平。
      const anchorBottom = itemRect ? itemRect.bottom + SUBMENU_PADDING : rect.bottom;
      const bottom = Math.max(8, window.innerHeight - anchorBottom);
      // 右侧放不下就翻到左边
      return rect.right + SUBMENU_GAP + SUBMENU_WIDTH > window.innerWidth
        ? { right: window.innerWidth - rect.left + SUBMENU_GAP, bottom }
        : { left: rect.right + SUBMENU_GAP, bottom };
    },
    [section],
  );

  if (!open) return null;

  return createPortal(
    <>
      <div
        ref={rootRef}
        role="menu"
        aria-label={t("run.openMenu")}
        style={rootStyle}
        className="fixed z-[60] w-48 rounded-xl border border-border/60 bg-surface-2 p-1 shadow-xl animate-fade-in"
      >
        {rootItems.map((item) => {
          const ItemIcon = item.icon;
          return (
            <button
              key={item.key}
              ref={(element) => {
                itemRefs.current[item.key] = element;
              }}
              role="menuitem"
              aria-haspopup="menu"
              aria-expanded={section === item.key}
              onMouseEnter={() => showSection(item.key)}
              onClick={() => showSection(item.key)}
              className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm transition-colors ${
                section === item.key
                  ? "bg-surface-4 text-primary"
                  : "text-secondary hover:bg-surface-4"
              }`}
            >
              <ItemIcon className="h-4 w-4 flex-shrink-0 text-muted" />
              <span className="flex-1">{t(item.labelKey)}</span>
              <ChevronRight className="h-3.5 w-3.5 flex-shrink-0 text-muted" />
            </button>
          );
        })}
      </div>

      {section !== null && (
        <div
          ref={submenuRef}
          style={submenuStyle}
          className="fixed z-[60] overflow-hidden rounded-xl border border-border/60 bg-surface-2 shadow-xl animate-fade-in"
        >
          {section === "file" && (
            <div className="w-48 p-1" role="menu" aria-label={t("run.addFile")}>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  onClose();
                  onPickLocalFiles();
                }}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm text-secondary transition-colors hover:bg-surface-4 hover:text-primary"
              >
                <Upload className="h-4 w-4 flex-shrink-0 text-muted" />
                <span className="flex-1">{t("run.localFile")}</span>
              </button>
            </div>
          )}

          {section === "agent" && (
            <AgentPickerPanel
              agents={agents}
              selectedAgent={selectedAgent}
              onSelect={(agent) => {
                onSelectAgent(agent);
                onClose();
              }}
              onBrowseMore={onBrowseMoreAgents}
            />
          )}
        </div>
      )}
    </>,
    document.body,
  );
}

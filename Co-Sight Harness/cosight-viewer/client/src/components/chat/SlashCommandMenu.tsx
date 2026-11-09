// SPDX-License-Identifier: Apache-2.0
/**
 * @file SlashCommandMenu.tsx
 * @description `/` 候选浮层：命令与技能分两组，贴在输入框**上方**展开。
 *
 * 只负责画列表、上报“点了 / 悬停了第几条”；触发时机、过滤、键盘导航、
 * 插入 token 都在 `ChatComposer` / `slash-commands.ts` / `prompt-editor.ts`。
 *
 * 定位用 `position: fixed` + portal：发送框在不同页面里被不同容器包着，
 * absolute 需要逐层找定位祖先，fixed 与容器无关。
 */

import { Fragment, useEffect, useRef } from "react";
import type { CSSProperties } from "react";
import { Loader2, Sparkles, Terminal } from "lucide-react";

import type { SlashCommandItem } from "./slash-commands";

/** 输入框矩形（视口坐标）。菜单锚定在输入框上方/下方。 */
export interface SlashCommandAnchor {
  left: number;
  top: number;
  bottom: number;
  width: number;
}

export interface SlashCommandMenuProps {
  /** 已过滤、排好序的候选（命令在前、技能在后） */
  items: readonly SlashCommandItem[];
  /** 当前高亮第几条 */
  active: number;
  anchor: SlashCommandAnchor;
  /** 无障碍名称，如「技能与指令」 */
  label: string;
  /** 底部键盘提示 */
  hint: string;
  /** 首次冷启动、词表还没到时显示加载行 */
  loading?: boolean;
  /** 加载行文案 */
  loadingLabel?: string;
  /** 两个分组标题 */
  sectionLabels: { command: string; skill: string };
  onActive: (index: number) => void;
  onPick: (index: number) => void;
}

const MENU_MAX_HEIGHT = 360;
/** 浮层与输入框之间留一点缝 */
const MENU_GAP = 8;
/** 上方不足这么多时，才改到下方展开 */
const MIN_SPACE_ABOVE = 180;
/** 视口边缘留白 */
const VIEWPORT_MARGIN = 8;

function menuStyle(anchor: SlashCommandAnchor): CSSProperties {
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const width = Math.max(0, Math.min(anchor.width, viewportWidth - VIEWPORT_MARGIN * 2));
  const left = Math.max(
    VIEWPORT_MARGIN,
    Math.min(anchor.left, viewportWidth - width - VIEWPORT_MARGIN)
  );

  const spaceAbove = anchor.top - MENU_GAP - VIEWPORT_MARGIN;
  const spaceBelow = viewportHeight - anchor.bottom - MENU_GAP - VIEWPORT_MARGIN;
  const openAbove = spaceAbove >= MIN_SPACE_ABOVE || spaceAbove >= spaceBelow;

  if (openAbove) {
    return {
      left,
      width,
      bottom: viewportHeight - anchor.top + MENU_GAP,
      maxHeight: Math.max(0, Math.min(MENU_MAX_HEIGHT, spaceAbove)),
    };
  }
  return {
    left,
    width,
    top: anchor.bottom + MENU_GAP,
    maxHeight: Math.max(0, Math.min(MENU_MAX_HEIGHT, spaceBelow)),
  };
}

export function SlashCommandMenu({
  items,
  active,
  anchor,
  label,
  hint,
  loading = false,
  loadingLabel = "",
  sectionLabels,
  onActive,
  onPick,
}: SlashCommandMenuProps) {
  const listRef = useRef<HTMLDivElement>(null);

  // 键盘移动高亮时把它滚进可视区；只调整列表自己的 scrollTop，不带动整页
  useEffect(() => {
    const list = listRef.current;
    // 列表里还混着分组标题，不能直接用 children[active]
    const current = list?.querySelectorAll('[role="option"]')[active];
    if (!list || !(current instanceof HTMLElement)) return;

    const listRect = list.getBoundingClientRect();
    const itemRect = current.getBoundingClientRect();
    if (itemRect.top < listRect.top) {
      list.scrollTop -= listRect.top - itemRect.top;
    } else if (itemRect.bottom > listRect.bottom) {
      list.scrollTop += itemRect.bottom - listRect.bottom;
    }
  }, [active, items]);

  return (
    <div
      data-slash-menu=""
      style={menuStyle(anchor)}
      className="fixed z-[70] flex flex-col overflow-hidden rounded-2xl border border-border/60 bg-surface-2 shadow-2xl animate-fade-in"
    >
      <div ref={listRef} role="listbox" aria-label={label} className="min-h-0 flex-1 overflow-y-auto p-1.5">
        {loading && items.length === 0 ? (
          <div className="flex items-center gap-2 px-2.5 py-2 text-[11px] text-muted">
            <Loader2 className="h-3.5 w-3.5 flex-shrink-0 animate-spin" />
            <span>{loadingLabel}</span>
          </div>
        ) : null}
        {items.map((item, index) => {
          const header =
            index === 0 || items[index - 1]!.kind !== item.kind
              ? item.kind === "command"
                ? sectionLabels.command
                : sectionLabels.skill
              : null;

          return (
            <Fragment key={`${item.kind}-${item.name}`}>
              {header !== null && (
                <div className="px-2.5 pb-1 pt-2 text-[10px] font-medium uppercase tracking-wider text-faint">
                  {header}
                </div>
              )}
              <div
                role="option"
                aria-selected={index === active}
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => onActive(index)}
                onClick={() => onPick(index)}
                className={`flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 ${
                  index === active ? "bg-surface-4" : ""
                }`}
              >
                {item.kind === "command" ? (
                  <Terminal className="h-3.5 w-3.5 flex-shrink-0 text-muted" />
                ) : (
                  <Sparkles className="h-3.5 w-3.5 flex-shrink-0 text-accent" />
                )}
                <span className="flex-shrink-0 font-mono text-[12.5px] text-primary">
                  /{item.name}
                </span>
                {item.description !== "" && (
                  <span
                    className="min-w-0 flex-1 truncate text-right text-[11px] text-muted"
                    title={item.description}
                  >
                    {item.description}
                  </span>
                )}
              </div>
            </Fragment>
          );
        })}
      </div>
      <div className="border-t border-border/50 px-3 py-1 text-[10px] text-faint">{hint}</div>
    </div>
  );
}

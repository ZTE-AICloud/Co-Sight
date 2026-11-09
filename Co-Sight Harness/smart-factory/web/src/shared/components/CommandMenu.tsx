/**
 * `/` 命令候选浮层。
 *
 * **独立组件**：只负责「把这些条目画出来、告诉我点了 / 悬停了第几条」。
 * 它不碰正文，也不做过滤 —— 触发时机、光标锚点、键盘上下 / 回车、插入 token
 * 全在 Composer 里（原因见 Composer 文件末的分层说明）。
 *
 * 锚点是**视口坐标**（光标矩形），所以定位用 `position: fixed`：
 * 发送框在不同页面里被不同的容器包着（首页卡片 / 侧栏 / 对话区），
 * 用 absolute 得逐层找定位祖先，fixed 与那些容器无关。
 *
 * 键盘不在这里处理：焦点始终留在正文里，按键由 Composer 的 onKeyDown 转发成
 * `onActive` / `onPick`。浮层自己拿不到焦点，也就不会出现「点一下菜单、光标丢了」。
 */

import { useEffect, useRef } from 'react';
import type { CSSProperties } from 'react';
import './CommandMenu.css';

/** 光标矩形（视口坐标）。空行取不到真实矩形时由 Composer 退到编辑区顶部 */
export interface CommandAnchor {
  left: number;
  top: number;
  bottom: number;
}

export interface CommandMenuProps {
  /** 已经过滤、排好序的条目 */
  items: readonly { value: string; description?: string }[];
  /** 当前高亮第几条（键盘上下改它） */
  active: number;
  anchor: CommandAnchor;
  /** 无障碍名称，如「技能与指令」 */
  label: string;
  onActive: (index: number) => void;
  onPick: (index: number) => void;
}

/** 与 `.command-menu` 的 CSS 保持一致：定位要按实际宽度算右边界的夹取 */
const MENU_WIDTH = 340;
const MENU_MAX_HEIGHT = 280;
/** 浮层与光标之间留一点缝，别贴着字 */
const MENU_GAP = 6;
/** 下方留不足这么多且上方更宽敞时，翻到光标上方展开（创建页的发送框贴着底边） */
const MIN_SPACE_BELOW = 200;
/** 视口边缘留白 */
const VIEWPORT_MARGIN = 8;

/**
 * 算浮层的固定定位。
 *
 * - 横向：左对齐光标，但顶到右边界时往左夹，不把菜单挤出视口；
 * - 纵向：默认在光标下方；下方不够（发送框贴底）就翻到上方；
 *   两边都不够时挑宽敞的一侧，靠 max-height 让它自己滚。
 */
function menuStyle(anchor: CommandAnchor): CSSProperties {
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const width = Math.min(MENU_WIDTH, viewportWidth - VIEWPORT_MARGIN * 2);
  const left = Math.max(
    VIEWPORT_MARGIN,
    Math.min(anchor.left, viewportWidth - width - VIEWPORT_MARGIN),
  );

  const spaceBelow = viewportHeight - anchor.bottom - MENU_GAP - VIEWPORT_MARGIN;
  const spaceAbove = anchor.top - MENU_GAP - VIEWPORT_MARGIN;
  const openAbove = spaceBelow < MIN_SPACE_BELOW && spaceAbove > spaceBelow;

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

export function CommandMenu({
  items,
  active,
  anchor,
  label,
  onActive,
  onPick,
}: CommandMenuProps) {
  const listRef = useRef<HTMLDivElement>(null);

  /**
   * 键盘移动高亮时把它滚进可视区。
   *
   * 不用 scrollIntoView：那会把整页也带着滚（浮层是 fixed，页面的滚动条仍可能动），
   * 这里只调整列表自己的 scrollTop。
   */
  useEffect(() => {
    const list = listRef.current;
    const current = list?.children[active];
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
      ref={listRef}
      className="command-menu"
      role="listbox"
      aria-label={label}
      style={menuStyle(anchor)}
    >
      {items.map((item, index) => (
        <div
          key={item.value}
          role="option"
          aria-selected={index === active}
          className={
            index === active ? 'command-menu__item command-menu__item--active' : 'command-menu__item'
          }
          // 别抢走正文的焦点 / 光标：否则点一下命令，插入位置就跑到末尾去了
          onMouseDown={(event) => event.preventDefault()}
          onMouseEnter={() => onActive(index)}
          onClick={() => onPick(index)}
        >
          <span className="command-menu__value">{item.value}</span>
          {item.description !== undefined && (
            <span className="command-menu__desc">{item.description}</span>
          )}
        </div>
      ))}
    </div>
  );
}

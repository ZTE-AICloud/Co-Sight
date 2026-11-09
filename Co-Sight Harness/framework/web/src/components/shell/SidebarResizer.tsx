/**
 * 侧栏右缘的拖拽手柄（需求 UX-2）。
 *
 * 本文件现在只剩"侧栏这一侧的取值"：拖拽与键盘那套动作全在通用件
 * [`ColumnResizer`](../ui/ColumnResizer.tsx) 里，会话区右栏用的是同一个。
 */

import {
  SIDEBAR_MAX_WIDTH,
  SIDEBAR_MIN_WIDTH,
  SIDEBAR_RESIZE_STEP,
} from '../../lib/sidebarWidth';
import { ColumnResizer } from '../ui/ColumnResizer';

export interface SidebarResizerProps {
  /** 当前展开宽度（受控）。 */
  width: number;
  /** 调整后的新宽度。 */
  onResize: (width: number) => void;
  /** 拖拽开始/结束。侧栏据此关掉宽度过渡，否则拖起来像在追鼠标。 */
  onDraggingChange: (dragging: boolean) => void;
  /** 无障碍名（`app.resizeSidebar`）。 */
  label: string;
  /** 当前宽度的人话版本（如「280 像素」）。 */
  valueText: string;
}

/**
 * 被调整尺寸的那个面板的 id。手柄的 `aria-controls` 要指向它——否则读屏用户只知道自己
 * 在调一个数值，不知道调的是哪一块。
 *
 * 常量放在这里而不是 `Sidebar.tsx`：`Sidebar` 已经 import 了本模块，反向 import 会成环。
 */
export const SIDEBAR_PANEL_ID = 'app-sidebar';

export function SidebarResizer(props: SidebarResizerProps) {
  return (
    <ColumnResizer
      {...props}
      edge="end"
      panelId={SIDEBAR_PANEL_ID}
      min={SIDEBAR_MIN_WIDTH}
      max={SIDEBAR_MAX_WIDTH}
      step={SIDEBAR_RESIZE_STEP}
    />
  );
}

/**
 * 面板边缘的拖拽手柄（通用件）。
 *
 * 两个使用方：左侧栏的**右缘**（`edge="end"`）与会话区「工作区文件」面板的**左缘**
 * （`edge="start"`）。抽成一个零件不是为了少写几行——这里的指针收尾有一套**必须照做**
 * 的规矩（见 `endDrag` 的注释），抄第二遍就等于多一个把它写错的机会。
 *
 * 手柄渲染成被调整面板的绝对定位子元素，而不是外层的一个兄弟节点：视觉上那条分割线
 * 属于被调整面板自己的边框，手柄要做的就是"骑"在它上面。放在面板里还有个好处——
 * 它跟着面板一起被布局推动，不需要在两个组件之间传宽度变量。
 *
 * 宽度是**受控**的：本组件只报出"用户想要多宽"，夹取、持久化、渲染宽度都在调用方。
 */

import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';

import { cn } from '../../lib/cn';
import styles from './ColumnResizer.module.css';

export interface ColumnResizerProps {
  /** 当前宽度（受控）。 */
  width: number;
  /** 被调整面板的 id。`aria-controls` 要指向它——否则读屏用户只知道自己在一个数值，不知道调的是谁。 */
  panelId: string;
  /** 夹取区间。`min` 与 `max` 同时作为 `aria-valuemin` / `aria-valuemax` 报出去。 */
  min: number;
  max: number;
  /** 键盘调整一次的步长。 */
  step: number;
  /**
   * 手柄贴面板的哪条边。
   *
   * `end` = 右缘（左侧栏：向右拖变宽）；`start` = 左缘（会话区右栏：**向左**拖变宽）。
   * 只影响两件事：指针位移的符号，以及方向键哪一边是"变宽"。`Home` / `End` 不受影响
   * （都是"最窄 / 最宽"），与 `aria-valuenow` 报的是面板自己的宽度这一条保持一致。
   */
  edge: 'start' | 'end';
  /** 调整后的新宽度。 */
  onResize: (width: number) => void;
  /** 拖拽开始/结束。调用方据此关掉宽度过渡，否则拖起来像在追鼠标。 */
  onDraggingChange: (dragging: boolean) => void;
  /** 无障碍名。这个手柄没有任何可见文字，名字就是它的全部语义。 */
  label: string;
  /**
   * 当前宽度的**人话**版本（如「640 像素」）。范围控件默认只把 `aria-valuenow` 念成
   * 一个光秃秃的数字，没有单位、没有语境；读屏用户听到的会是「调整宽度 分隔条 640」。
   */
  valueText: string;
}

/**
 * 尽力释放指针捕获。失败是**预期内**的：`pointercancel` 时指针已经被浏览器收走，
 * 这时候释放会抛 `NotFoundError`。捕获没了本来就是我们要的结果，所以这里只吞掉异常，
 * 不改变任何状态——状态清理已经在调用方做完。
 */
function releaseCapture(element: HTMLElement, pointerId: number): void {
  try {
    element.releasePointerCapture?.(pointerId);
  } catch {
    // 已经不在捕获中（多半是 pointercancel 或元素已被移除），无需处理。
  }
}

export function ColumnResizer({
  width,
  panelId,
  min,
  max,
  step,
  edge,
  onResize,
  onDraggingChange,
  label,
  valueText,
}: ColumnResizerProps) {
  /*
   * 拖拽起点用 ref 而不是 state：它只在事件处理里读写，进 state 只会让每次
   * pointermove 多一次无意义的渲染（渲染出来的东西每次都一样）。
   */
  const origin = useRef({ x: 0, width });
  const [dragging, setDragging] = useState(false);

  /* 与 `dragging` 同步的 ref，只给卸载清理用：卸载时读 state 会读到旧闭包里的值。 */
  const draggingRef = useRef(false);

  function updateDragging(next: boolean): void {
    draggingRef.current = next;
    setDragging(next);
    onDraggingChange(next);
  }

  /*
   * 拖拽途中组件被卸载（最现实的一条：第二根手指去点折叠按钮，侧栏切到窄条态，
   * 手柄随之消失）时，必须把 `resizing` 还回去。少了这一段，面板会带着一个永远
   * 清不掉的 `.resizing` 回来，过渡仍然是关的。
   */
  useEffect(() => {
    return () => {
      if (draggingRef.current) {
        onDraggingChange(false);
      }
    };
  }, [onDraggingChange]);

  /**
   * 夹取 + 取整 + 挡住非有限数。
   *
   * 非有限数退回**当前宽度**（= 这一次不动）而不是默认值：这里出现 `NaN` 只可能是
   * 上游算错了，此时把面板跳到一个用户没要求的宽度比不动更莫名其妙。
   */
  function clamp(px: number): number {
    if (!Number.isFinite(px)) {
      return width;
    }
    return Math.min(max, Math.max(min, Math.round(px)));
  }

  function handlePointerDown(event: PointerEvent<HTMLDivElement>): void {
    if (event.button !== 0) {
      // 只认主键：右键拖拽在这里没有含义，跟着动反而会让人以为拖坏了。
      return;
    }
    origin.current = { x: event.clientX, width };
    /*
     * 指针捕获：拖到面板之外（包括主面板里那些模块 iframe 上方）时，事件仍然回到这里。
     * 少了它，光标一离开这 8px 命中区就"脱手"，拖拽变成断断续续的——而拖拽时
     * 光标必然是往面板外面去的。
     *
     * jsdom 没有实现这个方法，所以是可选调用：测试里直接把 pointermove 派发到本元素上
     * （见 tests/sidebar-resize.test.tsx 的说明）。
     */
    event.currentTarget.setPointerCapture?.(event.pointerId);
    updateDragging(true);
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>): void {
    if (!dragging) {
      return;
    }
    const delta = event.clientX - origin.current.x;
    // 贴左缘的手柄要往左拖才是变宽，所以位移取反。夹取在调用方的写入点上还会再做一次
    // （那里是唯一真相），这里做是为了让"拖到窗口外"时不会先把一个离谱的值传出去。
    onResize(clamp(edge === 'end' ? origin.current.width + delta : origin.current.width - delta));
  }

  function endDrag(event: PointerEvent<HTMLDivElement>): void {
    if (!dragging) {
      return;
    }
    /*
     * **先清状态，再做释放**，顺序不能反。
     *
     * `releasePointerCapture` 对一个"已经不再处于捕获中"的 pointerId 会抛
     * `NotFoundError`（规范如此，Chrome 实测确认）。而 `pointercancel` 恰恰是那种
     * 情形——浏览器接管手势时，指针已经被收走了，捕获也没了。于是这一行抛出的异常
     * 会让下面两行永远执行不到，后果不是"少清一个标记"：
     *
     *   - `dragging` 卡在 true → 之后**不按任何键**、只要鼠标划过这 8px 命中区就会
     *     触发 pointermove，宽度跟着鼠标乱变（幽灵拖拽）；
     *   - `onDraggingChange(false)` 没发出去 → 调用方的 `.resizing` 一直挂着，
     *     宽度过渡整场会话被关掉，折叠/展开/拖拽全部变成瞬移。
     *
     * 两者都不可自愈——用户没有办法把一个卡住的状态标记弄回来。所以状态清理放在
     * 前面，释放只当尽力而为。
     */
    updateDragging(false);
    releaseCapture(event.currentTarget, event.pointerId);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    /*
     * 键盘等价操作。纯拖拽的控件对只用键盘的人等于不存在——参考实现 dsh 的
     * DragHandle 就没有这一段，这里是补上的（WAI-ARIA 的窗口分隔条模式）。
     *
     * 方向键按"分隔条往哪边移动"来理解：贴右缘的手柄向右 = 面板变宽，贴左缘的
     * 向左 = 面板变宽。Home / End 与 aria-valuenow 报的是**面板自己的宽度**，
     * 所以它们恒为"最窄 / 最宽"，不跟着手柄贴哪条边翻。
     */
    const grow = edge === 'end' ? 'ArrowRight' : 'ArrowLeft';
    const shrink = edge === 'end' ? 'ArrowLeft' : 'ArrowRight';

    switch (event.key) {
      case grow:
        onResize(clamp(width + step));
        break;
      case shrink:
        onResize(clamp(width - step));
        break;
      case 'Home':
        onResize(min);
        break;
      case 'End':
        onResize(max);
        break;
      default:
        // 没处理的键不吞：尤其 Tab 还要能把焦点移走。
        return;
    }
    // 只有真的处理了才阻止默认行为，否则左右方向键会顺带把面板的滚动区也滚走。
    event.preventDefault();
  }

  /*
   * role="separator" + tabIndex 是可聚焦分隔条的标准写法；带上 aria-valuenow 之后
   * 它在无障碍树上同时是一个"滑块"，读屏软件会念出当前宽度（WAI-ARIA 的 Window Splitter）。
   */
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-controls={panelId}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={width}
      aria-valuetext={valueText}
      tabIndex={0}
      className={cn(styles.handle, edge === 'start' && styles.start, dragging && styles.dragging)}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      /*
       * 捕获丢了也要收尾：浏览器在 `pointercancel`、元素被移除、或指针被系统收走时
       * 都会发这个事件。`endDrag` 自带"不在拖拽中就早退"，所以与 pointerup 重复触发无害。
       */
      onLostPointerCapture={endDrag}
      onKeyDown={handleKeyDown}
    />
  );
}

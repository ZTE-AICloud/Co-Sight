/**
 * 可拖分栏：左对话 / 右工作区。
 *
 * 从 `AgentCreatePage` 抽出来，因为生产和评估两个阶段都要用，而预览阶段是单列、
 * 用不上它。**宽度状态留在页面级**（`useSplitWidth` 在页面上调用），所以切阶段
 * 不会把用户拖过的宽度复位；`SplitLayout` 只负责把三列排出来。
 *
 * `useSplitWidth` 的 ResizeObserver 跟着**元素本身**走（回调 ref）：预览阶段根本没有
 * `.ac-main`，预览 / 评估还要等产物门禁通过才挂出来 —— 元素是过一会儿才出现的，
 * 不能只在挂载时找一个 ref 然后永远观察 null。换阶段时节点也换，回调 ref 会再触发一次。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useI18n } from '../../../i18n/useI18n';
import type {
  CSSProperties,
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
  ReactNode,
} from 'react';

/**
 * 对话区默认宽度；中间那条分隔条占 SPLITTER_WIDTH，不在这里算。
 *
 * 480 是按「消息气泡里一行能放下十来个汉字 + 输入框不显局促」定的：380 时
 * 正文与工具条目都折得厉害，而右侧工作区在常见 1440 宽屏下仍有 950px 富余。
 * 用户拖过之后以拖出来的宽度为准（状态在页面级，见 useSplitWidth）。
 */
export const DEFAULT_CONV_WIDTH = 480;
/** 两边各自能压到的最小宽度 —— 再窄对话内容与文件预览都没法看 */
const MIN_CONV_WIDTH = 320;
const MIN_WORK_WIDTH = 420;
const SPLITTER_WIDTH = 8;

/** 容器宽度 → 对话区允许的最大宽度（给右侧工作区留够 MIN_WORK_WIDTH） */
function maxConvWidth(containerWidth: number): number {
  return Math.max(MIN_CONV_WIDTH, containerWidth - MIN_WORK_WIDTH - SPLITTER_WIDTH);
}

function clampConvWidth(width: number, containerWidth: number): number {
  return Math.min(
    Math.max(Math.round(width), MIN_CONV_WIDTH),
    maxConvWidth(containerWidth),
  );
}

/** `useSplitWidth` 的产物，原样交给 `SplitLayout` */
export interface SplitWidth {
  /**
   * 挂到 `.ac-main` 上的回调 ref。
   *
   * 用回调而不是 `RefObject`：预览 / 评估阶段在产物门禁通过前根本不渲染 `.ac-main`，
   * 元素是「挂载后过一会儿才出现」的。只按 `stageId` 跑一次的 effect 会在那时拿到
   * null，之后就再也不会观察 —— 窗口变窄（或右侧预览面板挤压）时宽度不收回。
   */
  attachMain: (node: HTMLDivElement | null) => void;
  convWidth: number;
  maxConv: number;
  resizing: boolean;
  style: CSSProperties;
  separatorProps: {
    onPointerDown: (event: ReactPointerEvent<HTMLDivElement>) => void;
    onPointerMove: (event: ReactPointerEvent<HTMLDivElement>) => void;
    onPointerUp: (event: ReactPointerEvent<HTMLDivElement>) => void;
    onPointerCancel: (event: ReactPointerEvent<HTMLDivElement>) => void;
    onKeyDown: (event: ReactKeyboardEvent<HTMLDivElement>) => void;
    onDoubleClick: () => void;
  };
}

/**
 * 分栏宽度的全部逻辑：拖拽、键盘、双击复位、窗口 / 容器变窄时收拢。
 *
 * @param activeKey 当前阶段的 key（传 `stageId` 即可）。它只用来「换了 `.ac-main`
 *                  就重新观察」—— 值本身不参与计算。
 */
export function useSplitWidth(_activeKey: string): SplitWidth {
  /** 命令式读取（拖拽起点）用；观察用的是下面那个元素状态 */
  const mainRef = useRef<HTMLDivElement | null>(null);
  const [mainElement, setMainElement] = useState<HTMLDivElement | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const [convWidth, setConvWidth] = useState(DEFAULT_CONV_WIDTH);
  const [resizing, setResizing] = useState(false);
  /** 拖拽起点：起始指针 x、起始宽度、这次拖拽允许的最大宽度 */
  const dragRef = useRef<{ startX: number; startWidth: number; max: number } | null>(null);

  const maxConv = containerWidth > 0 ? maxConvWidth(containerWidth) : DEFAULT_CONV_WIDTH;

  /**
   * 元素出现 / 换成另一个节点（切阶段）都会重新观察。
   * `activeKey` 只保留在签名里给调用方表达意图，实际不再参与依赖 —— 节点身份更准。
   */
  const attachMain = useCallback((node: HTMLDivElement | null) => {
    mainRef.current = node;
    setMainElement(node);
  }, []);

  useEffect(() => {
    if (mainElement === null) return;
    const observer = new ResizeObserver(() => setContainerWidth(mainElement.clientWidth));
    observer.observe(mainElement);
    setContainerWidth(mainElement.clientWidth);
    return () => observer.disconnect();
  }, [mainElement]);

  // 容器变窄时把已拖开的宽度收回到合法范围；不会主动放宽
  useEffect(() => {
    if (containerWidth <= 0) return;
    setConvWidth((current) =>
      Math.min(Math.max(current, MIN_CONV_WIDTH), maxConvWidth(containerWidth)),
    );
  }, [containerWidth]);

  // 拖拽期间锁住文本选择与光标，指针划过对话正文/文件预览时不会选出一片文字
  useEffect(() => {
    if (!resizing) return;
    const previousSelect = document.body.style.userSelect;
    const previousCursor = document.body.style.cursor;
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'col-resize';
    return () => {
      document.body.style.userSelect = previousSelect;
      document.body.style.cursor = previousCursor;
    };
  }, [resizing]);

  function handlePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    const container = mainElement?.clientWidth ?? mainRef.current?.clientWidth ?? 0;
    dragRef.current = {
      startX: event.clientX,
      startWidth: convWidth,
      max: container > 0 ? maxConvWidth(container) : Number.POSITIVE_INFINITY,
    };
    setResizing(true);
    // 捕获指针：拖出分隔条（甚至拖到 iframe 边缘）也能继续收到 move/up
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (drag === null) return;
    const next = drag.startWidth + (event.clientX - drag.startX);
    setConvWidth(Math.min(Math.max(Math.round(next), MIN_CONV_WIDTH), drag.max));
  }

  function handlePointerUp(event: ReactPointerEvent<HTMLDivElement>) {
    if (dragRef.current === null) return;
    dragRef.current = null;
    setResizing(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  /** 键盘也能调：左右 16px 一步，Home / End 到两头（分隔条有 tabIndex） */
  function handleKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    const step = 16;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      const delta = event.key === 'ArrowLeft' ? -step : step;
      setConvWidth((current) =>
        Math.min(Math.max(current + delta, MIN_CONV_WIDTH), maxConv),
      );
      return;
    }
    if (event.key === 'Home') {
      event.preventDefault();
      setConvWidth(MIN_CONV_WIDTH);
      return;
    }
    if (event.key === 'End') {
      event.preventDefault();
      setConvWidth(maxConv);
    }
  }

  function handleDoubleClick() {
    setConvWidth(clampConvWidth(DEFAULT_CONV_WIDTH, containerWidth || 1440));
  }

  return {
    attachMain,
    convWidth,
    maxConv,
    resizing,
    style: { '--ac-conv-width': `${convWidth}px` } as CSSProperties,
    separatorProps: {
      onPointerDown: handlePointerDown,
      onPointerMove: handlePointerMove,
      onPointerUp: handlePointerUp,
      onPointerCancel: handlePointerUp,
      onKeyDown: handleKeyDown,
      onDoubleClick: handleDoubleClick,
    },
  };
}

export function SplitLayout({
  split,
  left,
  right,
  workClassName = 'ac-work',
}: {
  split: SplitWidth;
  left: ReactNode;
  right: ReactNode;
  /** 右栏的类名：文件浏览阶段还要 `ac-work--files`（整块定高、内部各自滚动） */
  workClassName?: string;
}) {
  const { t } = useI18n();
  return (
    <div className="ac-main" ref={split.attachMain} style={split.style}>
      {left}

      <div
        className={`ac-split${split.resizing ? ' ac-split--active' : ''}`}
        role="separator"
        aria-orientation="vertical"
        aria-label={t('create.split.resize')}
        aria-valuenow={split.convWidth}
        aria-valuemin={MIN_CONV_WIDTH}
        aria-valuemax={split.maxConv}
        tabIndex={0}
        title={t('create.split.resizeHint')}
        {...split.separatorProps}
      />

      <main className={workClassName}>{right}</main>
    </div>
  );
}

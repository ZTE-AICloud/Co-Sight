import { useEffect, useRef, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react';

import { cn } from '../../lib/cn';
import { IconButton } from '../ui/Button';
import styles from './Dialog.module.css';

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * 真正能被 Tab 走到的元素。
 *
 * 不能直接拿 `querySelectorAll(FOCUSABLE)` 的结果当 Tab 序列用：
 *
 * - `button:not([disabled])` 会把 `tabIndex={-1}` 的按钮也算进来（未选中的语言
 *   单选、未激活的页签都是）。拿这样算出来的"末项"去判断"是否已到末尾"，
 *   那个分支永远不会成立，真实用户从最后一个可 Tab 到的元素再按 Tab，
 *   焦点就跑到遮罩背后的页面上了。
 * - 隐藏页签里的元素在真实浏览器里同样走不到，一并排除。
 */
function tabbable(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (element) => element.tabIndex >= 0 && element.closest('[hidden]') === null,
  );
}

export interface DialogProps {
  /** 标题栏文字。 */
  title: string;
  /**
   * 标题元素的 id，同时用于 `aria-labelledby`。
   *
   * 由调用方给而不是内部 `useId()`：同一个页面里可能先后打开两个不同的弹窗，
   * 而测试要能用 `getByRole('dialog', { name })` 与稳定的 id 断言"标题确实被
   * 关联上了"。id 写死在调用方也更便于人肉核对。
   */
  titleId: string;
  onClose: () => void;
  /** 关闭按钮的无障碍名称。 */
  closeLabel: string;
  /** `md`：设置类弹窗（720×560）；`sm`：确认类（420，高度自适应）。 */
  size?: 'md' | 'sm';
  children: ReactNode;
}

/**
 * 模态弹窗外壳：遮罩、标题栏、关闭按钮、焦点管理。
 *
 * 三件事自己接管，因为原生 `<dialog>` 在本项目的可测性前提下不可用
 * （jsdom 对 `showModal` 的支持不完整，用它会让所有弹窗测试要么跳过要么打桩）：
 *
 * 1. **Esc 关闭**；
 * 2. **焦点移到弹窗内、关闭后回到原来的元素**——不还回去的话键盘用户关掉弹窗后
 *    焦点会掉到 <body>，再按 Tab 要从页面最开始重新走一遍；
 * 3. **Tab 循环**，不让焦点跑到被遮罩挡住的身后页面上。
 *
 * 抽成组件是因为设置弹窗、工作区弹窗、确认弹窗三处都要这三件事。复制三份的代价
 * 不是这几十行，而是上面第 3 条那种"看不出来"的缺陷会在两份里修好、在第三份里留下。
 */
export function Dialog({
  title,
  titleId,
  onClose,
  closeLabel,
  size = 'md',
  children,
}: DialogProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    restoreRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    panelRef.current?.focus();
    return () => {
      restoreRef.current?.focus();
    };
  }, []);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key === 'Escape') {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== 'Tab') {
      return;
    }
    const panel = panelRef.current;
    if (panel === null) {
      return;
    }
    const focusables = tabbable(panel);
    const first = focusables[0];
    const last = focusables.at(-1);
    if (first === undefined || last === undefined) {
      return;
    }
    // 挂载时焦点落在面板容器（`tabIndex={-1}`）上而不是首元素上，所以反向环绕
    // 必须把容器也算作"最前面"。少了这一条，打开弹窗后直接 Shift+Tab 会退到
    // 遮罩背后的触发按钮上。
    const atStart = document.activeElement === first || document.activeElement === panel;
    if (event.shiftKey && atStart) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function onOverlayMouseDown(event: MouseEvent<HTMLDivElement>): void {
    // 只在点到遮罩本身时关闭；用 target === currentTarget 判断，
    // 否则在弹窗内部按住鼠标、拖到外面松手也会把弹窗关掉。
    if (event.target === event.currentTarget) {
      onClose();
    }
  }

  return (
    <div
      className={styles.overlay}
      role="presentation"
      onMouseDown={onOverlayMouseDown}
      onKeyDown={onKeyDown}
    >
      <div
        ref={panelRef}
        className={cn(styles.panel, size === 'sm' ? styles.panelSm : styles.panelMd)}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <header className={styles.header}>
          <h2 className={styles.title} id={titleId}>
            {title}
          </h2>
          <IconButton icon="close" label={closeLabel} onClick={onClose} />
        </header>
        {children}
      </div>
    </div>
  );
}

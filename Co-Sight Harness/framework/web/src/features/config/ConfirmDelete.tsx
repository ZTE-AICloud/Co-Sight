/**
 * 删除配置条目的二次确认。
 *
 * 与 `ConfirmDialog` 的唯一差别是**挂到 `document.body` 上**，而不是就地渲染。
 *
 * 原因只有一条，但足够致命：确认框是从设置弹窗内部触发的，就地渲染的话它会变成
 * 设置弹窗 DOM 的一部分，而外层 `Dialog` 的焦点陷阱是用 `panel.querySelectorAll(...)`
 * 算自己的 Tab 序列的——它会穿过嵌套的确认框，把「确认」按钮当成设置弹窗的**末项**。
 * 于是从「确认」再按一次 Tab，焦点会被环绕到被遮罩挡住的设置「关闭」按钮上：
 * 一个真实用户按出来的、看起来像"焦点丢了"的行为。移到 body 下，外层的查询看不到
 * 它，两层各自的陷阱就各管各的（确认框自己那一层的环绕由 `Dialog` 内部完成）。
 *
 * 层级不用担心：两个遮罩用的是同一个 `--z-modal`，谁在后面谁压在上面，而挂到 body
 * 的节点一定排在应用根节点之后。
 */

import { createPortal } from 'react-dom';

import { ConfirmDialog } from '../../components/shell/ConfirmDialog';

export interface ConfirmDeleteProps {
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel: string;
  closeLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  /** 提交中：两个按钮都禁用，避免连点两次删除。 */
  pending: boolean;
}

export function ConfirmDelete({
  title,
  message,
  confirmLabel,
  cancelLabel,
  closeLabel,
  onConfirm,
  onCancel,
  pending,
}: ConfirmDeleteProps) {
  return createPortal(
    <ConfirmDialog
      title={title}
      message={message}
      confirmLabel={confirmLabel}
      cancelLabel={cancelLabel}
      closeLabel={closeLabel}
      onConfirm={onConfirm}
      onCancel={onCancel}
      pending={pending}
      destructive
    />,
    document.body,
  );
}

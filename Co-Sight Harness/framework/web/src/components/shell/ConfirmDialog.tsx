import { useEffect, useRef } from 'react';

import { Button } from '../ui/Button';
import { Dialog } from './Dialog';
import styles from './ConfirmDialog.module.css';

export interface ConfirmDialogProps {
  title: string;
  /** 说清"按下确认之后会发生什么"，而不是重复标题。 */
  message: string;
  confirmLabel: string;
  cancelLabel: string;
  closeLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  /** 提交中：两个按钮都禁用，避免连点两次删除。 */
  pending?: boolean;
  /** 确认按钮用危险样式（删除类操作）。 */
  destructive?: boolean;
}

/**
 * 二次确认框。
 *
 * **初始焦点放在「取消」上**，不是「确认」。删除工作区、删除模型配置都是不可逆的，
 * 而弹窗一出现时用户的手还在键盘/触屏的"确定"位置附近——此时若确认按钮有焦点，
 * 一个空格就把东西删了。这一条不是风格偏好，是"危险操作的默认值必须是最安全的
 * 那个"，所以由组件内部锁死，调用方没有开关可关。
 *
 * 焦点是在挂载后自己抢的：Dialog 挂载时先把焦点放在面板容器上（那是给页签类弹窗
 * 用的默认），而**子组件的 effect 先于父组件执行**，所以这里的一次 `focus()`
 * 会覆盖掉它。顺序反过来的话，这一条会静默失效——用例里有断言钉住。
 */
export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  cancelLabel,
  closeLabel,
  onConfirm,
  onCancel,
  pending = false,
  destructive = false,
}: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    cancelRef.current?.focus();
  }, []);

  return (
    <Dialog
      title={title}
      titleId="confirm-dialog-title"
      onClose={onCancel}
      closeLabel={closeLabel}
      size="sm"
    >
      <div className={styles.body}>
        <p className={styles.message}>{message}</p>
        <div className={styles.actions}>
          <Button ref={cancelRef} onClick={onCancel} disabled={pending}>
            {cancelLabel}
          </Button>
          <Button
            variant={destructive ? 'danger' : 'primary'}
            onClick={onConfirm}
            disabled={pending}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

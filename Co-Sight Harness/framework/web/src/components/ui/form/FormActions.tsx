import type { ReactNode } from 'react';

import { cn } from '../../../lib/cn';
import styles from './form.module.css';

export interface FormActionsProps {
  /** 主操作与取消；破坏性操作请放进 `destructive` 槽。 */
  children: ReactNode;
  /** 靠左单独摆放的破坏性操作（删除）。 */
  destructive?: ReactNode;
  className?: string;
}

/**
 * 表单底部的操作栏。
 *
 * 存在的理由是那个"破坏性操作靠左"的约定：删除按钮一旦和保存挨着放，
 * 点错的代价是不可逆的。把位置规则收在一个组件里，后面新加的表单想违反
 * 这条约定就得先把这个组件改掉——比在每处靠自觉可靠。
 */
export function FormActions({ children, destructive, className }: FormActionsProps) {
  return (
    <div className={cn(styles.actions, className)}>
      {destructive === undefined ? null : (
        <div className={styles.actionsDestructive}>{destructive}</div>
      )}
      {children}
    </div>
  );
}

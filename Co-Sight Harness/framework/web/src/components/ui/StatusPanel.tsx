import type { ReactNode } from 'react';

import { cn } from '../../lib/cn';
import { Icon, type IconName } from './Icon';
import styles from './StatusPanel.module.css';

export interface StatusPanelProps {
  icon?: IconName;
  title: string;
  hint?: string;
  /** 可选操作，如「重试」。 */
  action?: ReactNode;
  /**
   * 出错时传 'alert'，让读屏软件立刻播报；空态用默认的普通容器。
   * 用 role 而不是 aria-live：这些面板是**替换**了内容区，不是追加一条通知。
   */
  role?: 'alert' | 'status' | undefined;
  className?: string;
}

/**
 * 一整块占位状态。
 *
 * 空列表 / 加载失败 / 模块未接入 / 设置项待实现这四种情况在本项目里都表现为
 * "本该有内容的地方现在没内容"，长得一样、语义不同。做成一个组件是为了保证
 * 它们的高度、留白、字号一致——否则这四处会各自漂移，肉眼看得出来但不值得单开评审。
 */
export function StatusPanel({
  icon = 'empty',
  title,
  hint,
  action,
  role,
  className,
}: StatusPanelProps) {
  return (
    <div className={cn(styles.panel, className)} {...(role === undefined ? {} : { role })}>
      <Icon name={icon} size={24} className={styles.icon} />
      <p className={styles.title}>{title}</p>
      {hint === undefined ? null : <p className={styles.hint}>{hint}</p>}
      {action === undefined ? null : <div className={styles.action}>{action}</div>}
    </div>
  );
}

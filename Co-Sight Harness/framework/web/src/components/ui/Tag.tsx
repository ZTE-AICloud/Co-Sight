import type { ReactNode } from 'react';

import { cn } from '../../lib/cn';
import styles from './Tag.module.css';

/**
 * 标签底色。
 *
 * `neutral` / `brand` 是稿里的两种（普通标签灰底、「预置」这类徽标浅蓝底）；
 * 其余六种是需求 UX-3.6 新增的彩色底，用 `tagTone()` 按标签文字稳定地分配——
 * 调用方**不要**手写这六个名字去表达别的意思，它们只表示"这是另一个标签"。
 */
export type TagTone = 'neutral' | 'brand' | 'blue' | 'teal' | 'green' | 'purple' | 'amber' | 'rose';

export interface TagProps {
  children: ReactNode;
  tone?: TagTone;
  /** 悬停提示。标签被截断时（`max-width` 生效）用它补全信息。 */
  title?: string;
  className?: string;
}

export function Tag({ children, tone = 'neutral', title, className }: TagProps) {
  return (
    <span className={cn(styles.tag, styles[tone], className)} title={title}>
      {children}
    </span>
  );
}

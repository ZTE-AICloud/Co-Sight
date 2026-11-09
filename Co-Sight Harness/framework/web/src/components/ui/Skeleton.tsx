import { cn } from '../../lib/cn';
import styles from './Skeleton.module.css';

export interface SkeletonProps {
  /** 宽度，数字按 px 处理。 */
  width?: number | string;
  height?: number | string;
  /** 圆形（头像占位）。 */
  circle?: boolean;
  className?: string;
}

export function Skeleton({ width, height, circle = false, className }: SkeletonProps) {
  return (
    <span
      className={cn(styles.skeleton, circle && styles.circle, className)}
      style={{ width, height }}
      // 骨架屏对读屏软件无意义，真正的加载语义由外层容器的 aria-busy 负责。
      aria-hidden="true"
    />
  );
}

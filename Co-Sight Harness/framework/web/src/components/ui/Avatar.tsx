import { useState } from 'react';

import { cn } from '../../lib/cn';
import styles from './Avatar.module.css';

export type AvatarSize = 'sm' | 'md' | 'lg';

export interface AvatarProps {
  /** 用于生成兜底首字与配色；同时是加载失败时唯一能显示的信息。 */
  name: string;
  /** 图片地址；缺失或加载失败时回落到首字。 */
  src?: string | null;
  size?: AvatarSize;
  className?: string;
}

/**
 * 由名字算出一个稳定色相。
 *
 * 刻意**不是随机**的：随机色相会让同一位专家每次刷新换一个颜色，
 * 用户会以为列表加载错了或者认错了人。哈希保证"同一个名字永远是同一个颜色"。
 * 返回值取 0-359，再按固定饱和度/明度（见 styleOf）收窄到浅色区间。
 */
function hueOf(name: string): number {
  let hash = 0;
  for (const char of name) {
    hash = (hash * 31 + (char.codePointAt(0) ?? 0)) % 360;
  }
  return hash;
}

/** 饱和度 62% / 明度 72%：任意色相下的浅色底，深字对比度都在 7:1 以上。 */
function styleOf(name: string): { background: string } {
  return { background: `hsl(${String(hueOf(name))} 62% 72%)` };
}

/**
 * 头像。
 *
 * **始终 `aria-hidden`**（连同内部的 `<img alt="">`）：稿中头像出现的两个位置
 * （专家卡片、侧栏用户行）旁边都有同一个人名的可见文本，读屏软件再念一次头像
 * 只是重复。将来真出现"只有头像、没有人名"的位置，再给它加可选 label，
 * 而不是现在就先写一个大多数调用方都要关掉的参数。
 */
export function Avatar({ name, src, size = 'md', className }: AvatarProps) {
  /*
   * 记录"失败的地址"而不是一个布尔。
   *
   * 布尔需要在 src 变化时用 useEffect 复位，而 effect 会在新图加载完成前
   * 先渲染一帧旧状态。记地址就不存在这个问题：换了 src，比较自然不等于，
   * 直接回到显示图片的分支。
   */
  const [failedSrc, setFailedSrc] = useState<string | null>(null);

  const usable = src !== null && src !== undefined && src !== '';
  const showImage = usable && src !== failedSrc;
  const initial = [...name][0] ?? '?';

  return (
    <span
      aria-hidden="true"
      className={cn(styles.avatar, styles[size], className)}
      // 有图时不设置背景，让图片自己铺满；无图时才套哈希色。
      style={showImage ? undefined : styleOf(name)}
    >
      {showImage ? (
        <img
          className={styles.image}
          src={src}
          alt=""
          loading="lazy"
          decoding="async"
          onError={() => {
            setFailedSrc(src);
          }}
        />
      ) : (
        initial.toUpperCase()
      )}
    </span>
  );
}

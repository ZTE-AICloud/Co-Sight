/**
 * 配置行骨架。模型配置与 Agent 代理配置的加载态共用一份。
 *
 * 直接复用 `ConfigRow` 而不是自己搭一个骨架行：骨架的全部价值在于和真行**逐像素**
 * 对齐（同样的行高、内边距、三段文字的相对位置），另写一份几何定义迟早会和真行漂开，
 * 而那种偏差只在数据到位的一瞬间闪一下，评审里几乎看不出来。
 *
 * `title=""` 是刻意的：那一行本来就没有文字，这里要的是它的**盒子**。`ConfigRow`
 * 的 `title` 是必填字符串（它对真行而言确实是必填的），为骨架把它改成可选会让
 * 真行的调用点少一层保护。
 */

import { ConfigRow } from '../../components/ui/ConfigList';
import { Skeleton } from '../../components/ui/Skeleton';

export function ConfigRowSkeleton() {
  return (
    <ConfigRow
      title=""
      badges={<Skeleton width={44} height={16} />}
      meta={<Skeleton width="55%" height={10} />}
      actions={<Skeleton width={104} height={24} />}
    />
  );
}

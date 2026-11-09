/**
 * 侧栏宽度（需求 UX-2：侧栏与主面板之间的分割线可以左右拖拽，且有最大/最小宽度）。
 *
 * 放在 lib 而不是组件里，是因为这三个数字被三处用到：侧栏自己（渲染宽度）、
 * 拖拽手柄（夹取 + 键盘步进）、测试（断言边界）。写死在 JSX 里会让"最大宽度到底是
 * 多少"变成只有读组件源码才知道的事。
 *
 * 数值来历：
 * - 280 = UX 稿的侧栏宽度（design-tokens.md 的布局一节），也是展开时拖拽的起点；
 * - 264 / 420 取自参考实现 deepseek-harness 的 SIDEBAR_MIN / SIDEBAR_MAX
 *   （`ui-layout/src/client/columns.ts`）。与它取同一组值不是抄数字：两个产品
 *   的侧栏在同样的区间里伸缩，同事在两边切换时手感是连续的；
 * - 56 = 折叠态的图标条宽度，等于"导航胶囊 40 + 左右各 8"（Sidebar.module.css）。
 */

/** 拖拽下限。再窄下去，导航项的文字就只剩一两个字了。 */
export const SIDEBAR_MIN_WIDTH = 264;

/** 展开时的初始宽度，等于 [稿] 值。 */
export const SIDEBAR_DEFAULT_WIDTH = 280;

/** 拖拽上限。再宽下去，主面板（框架的另一半）就没有意义了。 */
export const SIDEBAR_MAX_WIDTH = 420;

/** 折叠态宽度。折叠是"全有或全无"，不参与拖拽。 */
export const SIDEBAR_COLLAPSED_WIDTH = 56;

/** 键盘调整一次的步长。16 与常见的焦点/滚动步长一致，10 次能走完全程。 */
export const SIDEBAR_RESIZE_STEP = 16;

/**
 * 把任意数值夹到合法区间。
 *
 * 两件事都要做：夹取（指针拖到窗口外时位移差会变得很大，`clientX` 本身没有上界）
 * 与取整（小数宽度会一路传导到 `getBoundingClientRect`，让"宽度到底变了没变"的断言变得难读）。
 * 非有限数退回默认值而不是抛错：拖拽过程中的中途值不值得让整个界面挂掉。
 */
export function clampSidebarWidth(px: number): number {
  if (!Number.isFinite(px)) {
    return SIDEBAR_DEFAULT_WIDTH;
  }
  return Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, Math.round(px)));
}

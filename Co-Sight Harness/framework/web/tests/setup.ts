/**
 * vitest 全局准备（由 vite.config.ts 的 `test.setupFiles` 引入）。
 *
 * 这里只放"每一个测试文件都需要、且不依赖具体用例"的东西：
 * 断言扩展、DOM 清理、以及 jsdom 没有实现的浏览器 API。
 */

import '@testing-library/jest-dom/vitest';

import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';

import { resetUiStore } from './helpers/render';

/*
 * 手动清理。
 *
 * @testing-library/react 自带自动清理，但它的判断条件是"全局存在 afterEach"，
 * 而本项目的 vitest 显式设了 `globals: false`（不往全局挂 describe/it/expect，
 * 一切从 'vitest' 具名导入）。于是自动清理不会生效，不写这一句的后果是
 * **同一个文件里前一个用例渲染的 DOM 残留在 document 上**，后一个用例
 * `getByText` 会拿到两个节点并报 "found multiple elements"——一个和被测代码
 * 毫无关系的失败信息。
 *
 * 同一处顺带做另外两件"每个用例都要干净起点"的事：
 * - `unstubAllGlobals()`：`stubFetch` 系列改的是 `globalThis.fetch`。不复位的话，
 *   某个用例留下的打桩会跨文件生效，失败信息出现在一个根本没打桩的文件里；
 * - 复位 UI store：它走 persist，语言选择会落进 jsdom 的 localStorage，
 *   于是"用英文断言"的用例可能看到上一个用例留下的中文。
 */
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  resetUiStore();
});

/*
 * 用例**开始前**也复位一次，这一条不是冗余。
 *
 * store 的初始语言来自 `detectInitialLocale()`，它会读浏览器语言——而 jsdom 的
 * `navigator.language` 是 `en-US`。也就是说，不显式钉住的话，"第一个用例"看到的
 * 是英文界面，之后的用例（经过一次 afterEach 复位）看到的是中文：同一份断言
 * 在文件里的**位置**不同结果就不同，而失败信息只会说"文案不对"。
 * 另外 persist 还会在模块初始化时从 localStorage 回灌语言，同样得先清掉。
 */
beforeEach(() => {
  resetUiStore();
});

/*
 * jsdom 不实现 matchMedia。组件里凡是用 `@media (prefers-reduced-motion)`
 * 之外还需要在 JS 里判断的地方（或 CSS-in-JS 库的初始化）都会调它。
 * 默认返回"不匹配"，即按完整动效渲染。
 */
if (typeof window.matchMedia !== 'function') {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    // 可配置：测试要用自己的实现替换它（`vi.stubGlobal` 走 defineProperty，
    // 不可配置会直接报 "Cannot redefine property"）。
    configurable: true,
    value: (query: string): MediaQueryList =>
      ({
        matches: false,
        media: query,
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(() => false),
      }) as unknown as MediaQueryList,
  });
}

/*
 * jsdom 也不实现 `Element.prototype.scrollTo`（它没有布局，也就没有滚动）。
 *
 * 这一条不补的后果比"少测一个函数"严重得多：页面里"换筛选条件后回到顶部"
 * 是一段 effect，缺失时它**抛异常**，整个路由被交给 React Router 的错误边界，
 * 于是用例报的是"渲染出错"，看半天也和滚动没关系。
 * 空实现足够——没有布局可滚，但"确实调了 scrollTo、参数对不对"可以断言。
 */
if (typeof Element.prototype.scrollTo !== 'function') {
  Element.prototype.scrollTo = () => {
    /* 见上方说明：jsdom 没有布局，这里刻意什么都不做 */
  };
}

/*
 * jsdom 也不实现 IntersectionObserver，而"加载更多"的哨兵元素依赖它。
 * 这个桩**什么都不触发**：哨兵永远不会进入视口。于是列表测试断言的是
 * "第一页渲染出来了"，而不是"滚动触发了第二页"——后者在 jsdom 里没有布局，
 * 本来就测不出来，硬测只会得到一个永远绿或永远红的假信号。
 * 真实滚动行为交给 Playwright（e2e/）。
 */
if (typeof globalThis.IntersectionObserver !== 'function') {
  class NoopIntersectionObserver implements IntersectionObserver {
    readonly root: Element | Document | null = null;
    readonly rootMargin: string = '0px';
    readonly thresholds: readonly number[] = [0];
    readonly scrollMargin: string = '0px';
    observe(): void {
      /* 见上方说明：故意不回调 */
    }
    unobserve(): void {}
    disconnect(): void {}
    takeRecords(): IntersectionObserverEntry[] {
      return [];
    }
  }
  Object.defineProperty(globalThis, 'IntersectionObserver', {
    writable: true,
    // 同上：需要"能触发回调"的测试会把它换掉，不可配置就换不掉。
    configurable: true,
    value: NoopIntersectionObserver,
  });
}

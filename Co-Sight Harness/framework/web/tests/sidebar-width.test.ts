/**
 * `clampSidebarWidth()` 单元测试（需求 UX-2）。
 *
 * 这个函数是侧栏宽度的**唯一写入口**（store 的 `setSidebarWidth` 走它），所以它的
 * 边界就是整个功能的边界：拖拽、键盘、折叠三处都指望"传进来的任何数都能出来一个
 * 合法宽度"。
 *
 * 非有限数那一条不是为了好看：`Math.min(420, Math.max(264, NaN))` 还是 `NaN`，
 * 一路传到 `style.width = 'NaNpx'`，浏览器会**静默**忽略这条样式——侧栏回到
 * 自动宽度，看起来像"拖拽把侧栏搞坏了"，而错误信息里什么都没有。
 */

import { describe, expect, it } from 'vitest';

import {
  clampSidebarWidth,
  SIDEBAR_DEFAULT_WIDTH,
  SIDEBAR_MAX_WIDTH,
  SIDEBAR_MIN_WIDTH,
} from '../src/lib/sidebarWidth';

describe('clampSidebarWidth', () => {
  it('区间内的值原样通过', () => {
    expect(clampSidebarWidth(SIDEBAR_MIN_WIDTH)).toBe(SIDEBAR_MIN_WIDTH);
    expect(clampSidebarWidth(SIDEBAR_DEFAULT_WIDTH)).toBe(SIDEBAR_DEFAULT_WIDTH);
    expect(clampSidebarWidth(SIDEBAR_MAX_WIDTH)).toBe(SIDEBAR_MAX_WIDTH);
    expect(clampSidebarWidth(300)).toBe(300);
  });

  it('越界值夹到两端', () => {
    expect(clampSidebarWidth(SIDEBAR_MIN_WIDTH - 1)).toBe(SIDEBAR_MIN_WIDTH);
    expect(clampSidebarWidth(0)).toBe(SIDEBAR_MIN_WIDTH);
    expect(clampSidebarWidth(-2000)).toBe(SIDEBAR_MIN_WIDTH);
    expect(clampSidebarWidth(SIDEBAR_MAX_WIDTH + 1)).toBe(SIDEBAR_MAX_WIDTH);
    expect(clampSidebarWidth(99_999)).toBe(SIDEBAR_MAX_WIDTH);
  });

  it('小数四舍五入到整数', () => {
    // 小数宽度会一路传导到 getBoundingClientRect，让"宽度变没变"的断言变得难读。
    expect(clampSidebarWidth(300.4)).toBe(300);
    expect(clampSidebarWidth(300.5)).toBe(301);
  });

  it('非有限数退回默认值，而不是把 NaN 传下去', () => {
    expect(clampSidebarWidth(Number.NaN)).toBe(SIDEBAR_DEFAULT_WIDTH);
    expect(clampSidebarWidth(Number.POSITIVE_INFINITY)).toBe(SIDEBAR_DEFAULT_WIDTH);
    expect(clampSidebarWidth(Number.NEGATIVE_INFINITY)).toBe(SIDEBAR_DEFAULT_WIDTH);
  });

  it('常量本身是自洽的（默认值在区间内，且区间是个正常区间）', () => {
    expect(SIDEBAR_MIN_WIDTH).toBeLessThanOrEqual(SIDEBAR_DEFAULT_WIDTH);
    expect(SIDEBAR_DEFAULT_WIDTH).toBeLessThanOrEqual(SIDEBAR_MAX_WIDTH);
  });
});

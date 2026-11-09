/**
 * 相对时间换算（侧栏「最近」用）。
 *
 * 时间全部按固定 `now` 算，不依赖机器时钟。
 */

import { describe, expect, it } from 'vitest';

import { relativeTimeOf } from '../src/features/recent-sessions/relative-time';

const NOW = Date.parse('2026-10-26T12:00:00.000Z');

function isoBefore(ms: number): string {
  return new Date(NOW - ms).toISOString();
}

describe('relativeTimeOf', () => {
  it('一分钟以内是刚刚', () => {
    expect(relativeTimeOf(isoBefore(30_000), NOW)).toEqual({ unit: 'justNow', count: 0 });
  });

  it('一到六十分钟按分钟向下取整', () => {
    expect(relativeTimeOf(isoBefore(5 * 60_000 + 20_000), NOW)).toEqual({
      unit: 'minutes',
      count: 5,
    });
  });

  it('一到二十四小时按小时', () => {
    expect(relativeTimeOf(isoBefore(3 * 3_600_000 + 59_000), NOW)).toEqual({
      unit: 'hours',
      count: 3,
    });
  });

  it('一到三十天按天', () => {
    expect(relativeTimeOf(isoBefore(4 * 86_400_000), NOW)).toEqual({ unit: 'days', count: 4 });
  });

  it('超过三十天返回 null：交给调用方显示具体日期', () => {
    expect(relativeTimeOf(isoBefore(31 * 86_400_000), NOW)).toBeNull();
  });

  it('服务端时间在未来按刚刚处理，不出现负数', () => {
    expect(relativeTimeOf(isoBefore(-120_000), NOW)).toEqual({ unit: 'justNow', count: 0 });
  });

  it('解析不了的时间返回 null', () => {
    expect(relativeTimeOf('not-a-date', NOW)).toBeNull();
  });
});

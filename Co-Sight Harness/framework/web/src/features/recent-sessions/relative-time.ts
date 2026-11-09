/**
 * 「最近」列表里的相对时间。
 *
 * 只做区间判断，文案交给调用方翻译（`recent.justNow` 等）：这个文件不碰 i18n，
 * 才能在测试里用固定的 `now` 直接断言。
 *
 * 超过 30 天返回 `null` —— 那时"多少天前"已经不比一个日期更好读，由调用方
 * 用 `formatDateTime` 显示具体日期。
 */

export type RelativeTimeUnit = 'justNow' | 'minutes' | 'hours' | 'days';

export interface RelativeTime {
  unit: RelativeTimeUnit;
  /** `justNow` 恒为 0；其余是分钟 / 小时 / 天。 */
  count: number;
}

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
/** 超过它就显示具体日期，不再说"N 天前"。 */
const MAX_DAYS = 30;

/**
 * 把 ISO 时间换算成相对时间。
 *
 * 时钟偏差（服务端时间在未来）按"刚刚"处理，不返回负的分钟数——
 * 负值只会在界面显示成 `-3 分钟前`，比"刚刚"更难理解。
 * 解析失败返回 `null`。
 */
export function relativeTimeOf(iso: string, now: number = Date.now()): RelativeTime | null {
  const timestamp = Date.parse(iso);
  if (Number.isNaN(timestamp)) {
    return null;
  }
  const diff = Math.max(0, now - timestamp);
  if (diff < MINUTE_MS) {
    return { unit: 'justNow', count: 0 };
  }
  if (diff < HOUR_MS) {
    return { unit: 'minutes', count: Math.floor(diff / MINUTE_MS) };
  }
  if (diff < DAY_MS) {
    return { unit: 'hours', count: Math.floor(diff / HOUR_MS) };
  }
  const days = Math.floor(diff / DAY_MS);
  return days > MAX_DAYS ? null : { unit: 'days', count: days };
}

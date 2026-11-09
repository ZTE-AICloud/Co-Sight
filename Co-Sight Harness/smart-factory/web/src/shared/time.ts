/**
 * 时间展示的纯函数（不依赖 React）。
 *
 * 从 `features/agent-list/display.ts` 提到 shared：专家卡与技能卡都要显示
 * 「多久以前」，两处不能各写一套，否则同一个时间戳在两个 tab 上会说法不一致。
 */

import { translate } from '../i18n/translate';
import type { Locale } from '../i18n/locale';

/**
 * 详情里的绝对时间：本地时区、精确到分钟。
 *
 * 与 `timeAgo` 分工不同：卡片上要的是「多久以前」这种一眼可比的相对量；
 * 详情里要的是**能拿去和日志、和目录时间戳对得上**的绝对值，「3 小时前」对不上。
 */
export function formatTime(iso: string, locale: Locale = 'zh-CN'): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return iso;
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(then));
}

/** 相对时间。只做到「天」，更久就报日期 —— 卡片上不需要更细，也省掉一个日期库。 */
export function timeAgo(iso: string, locale: Locale = 'zh-CN'): string {
  const then = Date.parse(iso);
  // 解析不出来（如后端给了非 ISO 的串）就原样显示，别在卡片上写 NaN
  if (Number.isNaN(then)) return iso;

  const relative = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
  const minutes = Math.round((Date.now() - then) / 60_000);
  if (minutes < 1) return translate(locale, 'common.time.justNow');
  if (minutes < 60) return relative.format(-minutes, 'minute');

  const hours = Math.round(minutes / 60);
  if (hours < 24) return relative.format(-hours, 'hour');

  const days = Math.round(hours / 24);
  if (days <= 14) return relative.format(-days, 'day');

  return iso.slice(0, 10);
}

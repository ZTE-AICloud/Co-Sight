/**
 * 语言契约（对齐框架 D28 = B：中英双语）。
 *
 * 模块被宿主嵌入时，宿主会在 iframe 地址上带 `?locale=`（见 framework 的 ModuleHost），
 * 独立访问时退回浏览器语言。词典只有前端有，服务端只回 messageKey。
 */

export const SUPPORTED_LOCALES = ['zh-CN', 'en-US'] as const;

export type Locale = (typeof SUPPORTED_LOCALES)[number];

export const DEFAULT_LOCALE: Locale = 'zh-CN';

/** 语言切换器上的自称，一律用该语言本身书写（不自译）。 */
export const LOCALE_LABELS: Record<Locale, string> = {
  'zh-CN': '简体中文',
  'en-US': 'English',
};

/** BCP-47 基础标签，用于 `<html lang>`。 */
export const LOCALE_HTML_LANG: Record<Locale, string> = {
  'zh-CN': 'zh-CN',
  'en-US': 'en',
};

export function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (SUPPORTED_LOCALES as readonly string[]).includes(value);
}

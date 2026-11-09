/**
 * 国际化基础类型（D28 = B：v1 即中英双语）。
 *
 * 契约层只定义"有哪些语言"和"多语言文本长什么样"，
 * 具体词典只有前端有（framework/web/src/i18n/messages/）。
 * 服务端**不出词典**：它只把 `messageKey` 交给前端去翻，`message` 是渲染好的中文兜底。
 */

export const SUPPORTED_LOCALES = ['zh-CN', 'en-US'] as const;

export type Locale = (typeof SUPPORTED_LOCALES)[number];

export const DEFAULT_LOCALE: Locale = 'zh-CN';

/** 语言切换器上显示的语言自称，一律用该语言本身书写（不自译）。 */
export const LOCALE_LABELS: Record<Locale, string> = {
  'zh-CN': '简体中文',
  'en-US': 'English',
};

/** BCP-47 基础标签，用于 <html lang>。 */
export const LOCALE_HTML_LANG: Record<Locale, string> = {
  'zh-CN': 'zh-CN',
  'en-US': 'en',
};

export function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (SUPPORTED_LOCALES as readonly string[]).includes(value);
}

/**
 * 需要随语言切换的文本。模块清单（module.json）用它描述模块名与描述，
 * 保证模块清单本身语言无关、不需要为每种语言各发一份。
 */
export type LocalizedText = Record<Locale, string>;

export function pickLocalized(text: LocalizedText, locale: Locale): string {
  return text[locale];
}

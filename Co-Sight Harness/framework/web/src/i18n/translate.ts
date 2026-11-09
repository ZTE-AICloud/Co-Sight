/**
 * 翻译核心（纯函数，可单测，不依赖 React）。
 *
 * 与 React 解耦是刻意的：错误提示、日志、非组件代码（如 api 客户端的兜底文案）
 * 也要翻译，若翻译函数长在 hook 上，那些地方就只能硬编码中文。
 */

import { DEFAULT_LOCALE, LOCALE_HTML_LANG, SUPPORTED_LOCALES, isLocale } from 'harness-shared';
import type { Locale } from 'harness-shared';

import { enUS } from './messages/en-US';
import { zhCN } from './messages/zh-CN';
import type { MessageKey, MessageParams, Messages } from './types';

const DICTIONARIES: Record<Locale, Messages> = {
  'zh-CN': zhCN,
  'en-US': enUS,
};

/** 插值占位符，形如 `{count}`。 */
const PLACEHOLDER = /\{(\w+)\}/g;

/** 从点分键取值。取不到返回 undefined——**不抛错**，因为缺键要走兜底而不是崩页面。 */
function lookup(dictionary: Messages, key: string): string | undefined {
  let node: unknown = dictionary;
  for (const segment of key.split('.')) {
    if (typeof node !== 'object' || node === null) {
      return undefined;
    }
    node = (node as Record<string, unknown>)[segment];
  }
  return typeof node === 'string' ? node : undefined;
}

function interpolate(template: string, params: MessageParams | undefined): string {
  if (params === undefined) {
    return template;
  }
  return template.replace(PLACEHOLDER, (whole, name: string) => {
    const value = params[name];
    // 缺参时保留 `{name}` 而不是渲染 undefined：界面上出现 `{count}` 一眼能看出
    // 是漏传参数，出现 `undefined` 则容易被当成数据本身有问题。
    return value === undefined ? whole : String(value);
  });
}

export function translate(
  locale: Locale,
  key: MessageKey,
  params?: MessageParams,
): string {
  const fromLocale = lookup(DICTIONARIES[locale], key);
  if (fromLocale !== undefined) {
    return interpolate(fromLocale, params);
  }

  // 正常路径走不到这里（MessageKey 已在编译期保证存在）。留这条是因为
  // **服务端回的 messageKey 是运行期字符串**，类型系统管不住它（见 translateApiErrorKey）。
  const fromDefault = lookup(DICTIONARIES[DEFAULT_LOCALE], key);
  return fromDefault === undefined ? key : interpolate(fromDefault, params);
}

/**
 * 翻译服务端给的 messageKey。
 *
 * 与 `translate` 分开，是因为这里必须接受**任意字符串**：服务端的 messageKey
 * 来自契约（`error.not_found.workspace` 这类），前端并没有把服务端可能返回的
 * 键全收进词表。取不到时逐段降级，两条路并用：
 *
 * 1. **截短找字符串叶子**——`error.rate_limited.whatever` → `error.rate_limited`；
 * 2. **分组节点的 `default` 子键**——`error.not_found` 是对象节点，本身渲染不出来，
 *    但它声明的 `default` 正是这一组"新增了资源类型、词条还没跟上"时的兜底文案，
 *    于是 `error.not_found.something_new` → `error.not_found.default`。
 *
 * 第 2 条不是可有可无的润色。少了它，`error.not_found.something_new` 会返回 null，
 * 调用方退到 `error.internal`，于是**一个 404 被说成"服务内部错误"**——用户和排查
 * 的人都被带到错误方向。两条路都无果（如 `totally.unknown.key`）才返回 null。
 *
 * `default` 是分组约定而非魔法名：`error.not_implemented.default` 早就写在词表里，
 * 在接上这条路径之前它没有任何读取方。
 */
export function translateApiErrorKey(
  locale: Locale,
  messageKey: string,
  params?: MessageParams,
): string | null {
  const segments = messageKey.split('.');
  let groupDefault: string | undefined;
  for (let end = segments.length; end > 0; end -= 1) {
    const candidate = segments.slice(0, end).join('.');
    const value = lookup(DICTIONARIES[locale], candidate);
    if (value !== undefined) {
      return interpolate(value, params);
    }
    // 分组越短离根越近、兜底文案越泛；近的分组更贴题，所以只记第一个找到的。
    if (groupDefault === undefined) {
      groupDefault = lookup(DICTIONARIES[locale], `${candidate}.default`);
    }
  }
  return groupDefault === undefined ? null : interpolate(groupDefault, params);
}

export function isSupportedLocale(value: unknown): value is Locale {
  return isLocale(value);
}

export function htmlLangOf(locale: Locale): string {
  return LOCALE_HTML_LANG[locale];
}

export function detectInitialLocale(stored: string | null, navigatorLanguages: readonly string[]): Locale {
  if (isLocale(stored)) {
    return stored;
  }
  // 只做前缀匹配（`zh-Hans-CN` → `zh-CN` 的近似），不做完整的 BCP-47 协商：
  // 本平台只有两种语言，接受头再精确也不会得出第三种结果。
  for (const tag of navigatorLanguages) {
    const lower = tag.toLowerCase();
    if (lower.startsWith('zh')) {
      return 'zh-CN';
    }
    if (lower.startsWith('en')) {
      return 'en-US';
    }
  }
  return DEFAULT_LOCALE;
}

export { SUPPORTED_LOCALES };

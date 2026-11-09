/**
 * 翻译核心（纯函数，可单测，不依赖 React）。
 *
 * 与 React 解耦是刻意的：错误提示、日志、非组件代码（如 api 客户端的兜底文案）
 * 也要翻译，若翻译函数长在 hook 上，那些地方就只能硬编码中文。
 */

import { DEFAULT_LOCALE, isLocale } from './locale';
import type { Locale } from './locale';
import { enUS } from './messages/en-US';
import { zhCN } from './messages/zh-CN';
import type { MessageKey, MessageParams, Messages } from './types';

const DICTIONARIES: Record<Locale, Messages> = {
  'zh-CN': zhCN,
  'en-US': enUS,
};

/** 插值占位符，形如 `{count}`。 */
const PLACEHOLDER = /\{(\w+)\}/g;

/** 从点分键取值。取不到返回 undefined——**不抛错**，缺键走兜底而不是崩页面。 */
function lookup(dictionary: Messages, key: string): string | undefined {
  let node: unknown = dictionary;
  for (const segment of key.split('.')) {
    if (typeof node !== 'object' || node === null) return undefined;
    node = (node as Record<string, unknown>)[segment];
  }
  return typeof node === 'string' ? node : undefined;
}

function interpolate(template: string, params: MessageParams | undefined): string {
  if (params === undefined) return template;
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
  if (fromLocale !== undefined) return interpolate(fromLocale, params);

  // 正常路径走不到这里（MessageKey 已在编译期保证存在）。留这条是因为
  // **服务端回的 messageKey 是运行期字符串**，类型系统管不住它（见 translateApiErrorKey）。
  const fromDefault = lookup(DICTIONARIES[DEFAULT_LOCALE], key);
  return fromDefault === undefined ? key : interpolate(fromDefault, params);
}

/**
 * 翻译服务端给的 messageKey（运行期字符串，可能不在词表里）。
 *
 * 逐段降级，两条路并用：
 * 1. 截短找字符串叶子——`error.rate_limited.whatever` → `error.rate_limited`；
 * 2. 分组节点的 `default` 子键——`error.not_found.something_new` → `error.not_found.default`。
 *
 * 第 2 条不是润色：少了它，一个新资源类型的 404 会返回 null，调用方退到
 * `error.internal`，于是 404 被说成「服务内部错误」。
 *
 * `exact` 说明命中的是词表里真有的**具体**键（第 1 条），还是只落在分组兜底上
 * （第 2 条，或服务端直接给了 `error.bad_request.default` 这种 `default` 叶子）。
 * 兜底说明服务端带的是它自己的具体原因，见 `apiErrorText`。
 */
function resolveApiErrorKey(
  locale: Locale,
  messageKey: string,
  params?: MessageParams,
): { text: string; exact: boolean } | null {
  const segments = messageKey.split('.');
  let groupDefault: string | undefined;
  for (let end = segments.length; end > 0; end -= 1) {
    const candidate = segments.slice(0, end).join('.');
    const value = lookup(DICTIONARIES[locale], candidate);
    // `default` 叶子是分组的兜底文案（如「请求格式不正确」），不是这一条错误的说明：
    // 服务端给 `error.bad_request.default` 时指的是「没登记具体原因」，不是这个键本身。
    if (value !== undefined) {
      return { text: interpolate(value, params), exact: segments[end - 1] !== 'default' };
    }
    // 分组越短离根越近、兜底文案越泛；近的分组更贴题，所以只记第一个找到的。
    if (groupDefault === undefined) {
      groupDefault = lookup(DICTIONARIES[locale], `${candidate}.default`);
    }
  }
  return groupDefault === undefined ? null : { text: interpolate(groupDefault, params), exact: false };
}

export function translateApiErrorKey(
  locale: Locale,
  messageKey: string,
  params?: MessageParams,
): string | null {
  return resolveApiErrorKey(locale, messageKey, params)?.text ?? null;
}

/**
 * 服务端错误的最终展示文案。
 *
 * 词表里**精确**登记过这个键才用翻译；只退到分组 `default`（`error.bad_request.default`
 * →「请求格式不正确」）时改用服务端原话 —— 那种情况服务端给的是更具体的原因
 * （`模型 xxx 的协议是 openai，当前引擎只支持 anthropic`），翻译反而把能动手的信息吞掉了。
 *
 * 代价是这类未登记的键在英文界面下显示服务端的中文原话。**这是有意的**：一句看不太懂的
 * 具体原因，比一句读得通但没有信息的「Invalid request」有用。登记过的键不受影响。
 */
export function apiErrorText(
  locale: Locale,
  messageKey: string | undefined,
  message: string,
  params?: MessageParams,
): string {
  if (messageKey === undefined) return message;
  const resolved = resolveApiErrorKey(locale, messageKey, params);
  return resolved === null || !resolved.exact ? message : resolved.text;
}

export function isSupportedLocale(value: unknown): value is Locale {
  return isLocale(value);
}

/**
 * 首次语言：`?locale=`（宿主下发）→ localStorage → 浏览器语言 → 默认值。
 *
 * 只做前缀匹配（`zh-Hans-CN` → `zh-CN` 的近似），不做完整 BCP-47 协商：
 * 本平台只有两种语言。
 */
export function detectInitialLocale(
  queryLocale: string | null,
  stored: string | null,
  navigatorLanguages: readonly string[],
): Locale {
  if (isLocale(queryLocale)) return queryLocale;
  if (isLocale(stored)) return stored;
  for (const tag of navigatorLanguages) {
    const lower = tag.toLowerCase();
    if (lower.startsWith('zh')) return 'zh-CN';
    if (lower.startsWith('en')) return 'en-US';
  }
  return DEFAULT_LOCALE;
}

export { SUPPORTED_LOCALES } from './locale';

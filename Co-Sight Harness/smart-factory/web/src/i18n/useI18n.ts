/**
 * i18n 的 React 绑定。
 *
 * `t` 用 useCallback 固定引用：它会被大量组件用在依赖数组里（如 useMemo 拼 aria-label），
 * 若每次渲染换一个新函数，那些 memo 会全部失效。
 */

import { useCallback, useEffect, useSyncExternalStore } from 'react';

import type { Locale } from './locale';
import { applyHtmlLang, getLocale, setLocale, subscribeLocale } from './store';
import { translate, translateApiErrorKey } from './translate';
import type { MessageKey, MessageParams } from './types';

export interface I18n {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey, params?: MessageParams) => string;
  /** 翻译服务端返回的 messageKey（运行期字符串，可能不在词表里）。 */
  tApi: (messageKey: string, params?: MessageParams) => string | null;
}

export function useI18n(): I18n {
  const locale = useSyncExternalStore(subscribeLocale, getLocale, getLocale);

  const t = useCallback(
    (key: MessageKey, params?: MessageParams) => translate(locale, key, params),
    [locale],
  );

  const tApi = useCallback(
    (messageKey: string, params?: MessageParams) => translateApiErrorKey(locale, messageKey, params),
    [locale],
  );

  useEffect(() => {
    applyHtmlLang(locale);
  }, [locale]);

  return { locale, setLocale, t, tApi };
}

/**
 * 非组件环境取当前语言。
 *
 * 只给「必须知道语言但拿不到 hook」的地方用（如 api 客户端的兜底文案）。
 * 组件里不要用这个——它不会订阅变化，语言切换后组件不会重渲染。
 */
export function currentLocale(): Locale {
  return getLocale();
}

/** 非组件环境的即时翻译（不订阅变化）。 */
export function msg(key: MessageKey, params?: MessageParams): string {
  return translate(getLocale(), key, params);
}

/**
 * i18n 的 React 绑定。
 *
 * 语言存在 zustand（D6 = A）而不是 Context：语言是**全局单例的客户端状态**，
 * 用 Context 就得在根部套 Provider、再为"某个子树临时用别的语言"设计一层
 * 覆盖机制——而本项目不需要那种能力。少一层 Provider，组件树也少一层嵌套。
 *
 * `t` 用 useCallback 固定引用：它会被大量组件用在依赖数组里（如 useMemo 拼 aria-label），
 * 若每次渲染换一个新函数，那些 memo 会全部失效。
 */

import { useCallback } from 'react';

import type { Locale } from 'harness-shared';

import { useUiStore } from '../stores/ui';
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
  const locale = useUiStore((state) => state.locale);
  const setLocale = useUiStore((state) => state.setLocale);

  const t = useCallback(
    (key: MessageKey, params?: MessageParams) => translate(locale, key, params),
    [locale],
  );

  const tApi = useCallback(
    (messageKey: string, params?: MessageParams) => translateApiErrorKey(locale, messageKey, params),
    [locale],
  );

  return { locale, setLocale, t, tApi };
}

/**
 * 非组件环境取当前语言。
 *
 * 只给"必须知道语言但拿不到 hook"的地方用（例如 Query 的全局错误处理）。
 * 组件里不要用这个——它不会订阅变化，语言切换后组件不会重渲染。
 */
export function currentLocale(): Locale {
  return useUiStore.getState().locale;
}

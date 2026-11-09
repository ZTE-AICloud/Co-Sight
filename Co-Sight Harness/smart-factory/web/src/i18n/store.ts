/**
 * 语言状态：一个十几行的外部 store（`useSyncExternalStore` 直接消费）。
 *
 * smart-factory 没有引入 Zustand，也不值得为「一个枚举」引状态库。
 * 语言是**全局单例的客户端状态**，不需要子树覆盖，所以 Context 也不必；
 * 没有 Provider，组件树少一层嵌套。
 *
 * 语言只在启动时解析一次：宿主切语言会重建 iframe（src 里带 locale），
 * 独立态由切换器调用 `setLocale`。**不要每次路由都从 URL 读** ——
 * React Router 的 `NavLink to="/agents"` 会把 query string 丢掉。
 */

import { LOCALE_HTML_LANG } from './locale';
import type { Locale } from './locale';
import { detectInitialLocale } from './translate';

const STORAGE_KEY = 'smart-factory.locale';

let current: Locale | null = null;
const listeners = new Set<() => void>();

function queryLocale(): string | null {
  if (typeof window === 'undefined') return null;
  return new URLSearchParams(window.location.search).get('locale');
}

function storedLocale(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    // 隐私模式 / 禁用存储：读不到就当没有，不影响本次会话
    return null;
  }
}

function resolveInitial(): Locale {
  return detectInitialLocale(
    queryLocale(),
    storedLocale(),
    typeof navigator === 'undefined' ? [] : navigator.languages,
  );
}

export function getLocale(): Locale {
  current ??= resolveInitial();
  return current;
}

export function setLocale(next: Locale): void {
  if (next === getLocale()) return;
  current = next;
  // 宿主下发的语言不写回本地：它属于「这一次嵌入」，不该覆盖用户独立访问时的选择。
  // 用户主动切换才持久化。
  if (queryLocale() === null) {
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // 存储不可用：本次会话仍然生效
    }
  }
  applyHtmlLang(next);
  for (const listener of listeners) listener();
}

export function subscribeLocale(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** 把当前语言同步到 `<html lang>`（读屏语音、CJK 字体回退都依赖它）。 */
export function applyHtmlLang(locale: Locale = getLocale()): void {
  if (typeof document === 'undefined') return;
  document.documentElement.lang = LOCALE_HTML_LANG[locale];
}

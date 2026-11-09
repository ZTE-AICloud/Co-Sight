// SPDX-License-Identifier: Apache-2.0
/**
 * @file index.ts
 * @description Initializes the i18n internationalization framework, setting up
 * language resources for English and Chinese locales.
 */

import i18n from "i18next";
import { initReactI18next } from "react-i18next";
// import LanguageDetector from "i18next-browser-languagedetector";

/**
 * 从 URL 参数读取框架传递的语言设置
 *
 * 框架通过 iframe URL 的 `locale` 参数传递当前语言：
 * - `?locale=zh-CN` 或 `?locale=zh` → 中文
 * - `?locale=en-US` 或 `?locale=en` → 英文
 *
 * 如果没有 URL 参数（独立运行），则使用浏览器语言检测或回退到中文
 */
function getInitialLanguage(): string {
  // 尝试从 URL 读取 locale 参数
  const params = new URLSearchParams(window.location.search);
  const localeParam = params.get('locale');

  if (localeParam) {
    // 映射框架的 locale 代码到 i18next 的语言代码
    // zh-CN / zh → zh
    // en-US / en → en
    if (localeParam.startsWith('zh')) {
      return 'zh';
    }
    if (localeParam.startsWith('en')) {
      return 'en';
    }
  }

  // 独立运行时，尝试从 localStorage 读取
  const stored = localStorage.getItem('i18nextLng');
  if (stored) {
    if (stored.startsWith('zh')) return 'zh';
    if (stored.startsWith('en')) return 'en';
  }

  // 默认中文
  return 'zh';
}

const INITIAL_LANGUAGE = getInitialLanguage();

import common_en from "./locales/en/common.json";
import common_zh from "./locales/zh/common.json";
import sessions_en from "./locales/en/sessions.json";
import sessions_zh from "./locales/zh/sessions.json";
import settings_en from "./locales/en/settings.json";
import settings_zh from "./locales/zh/settings.json";
import errors_en from "./locales/en/errors.json";
import errors_zh from "./locales/zh/errors.json";
import updates_en from "./locales/en/updates.json";
import updates_zh from "./locales/zh/updates.json";

i18n.use(initReactI18next).init({
  lng: INITIAL_LANGUAGE,

  resources: {
    en: {
      common: common_en,
      sessions: sessions_en,
      settings: settings_en,
      errors: errors_en,
      updates: updates_en,
    },
    zh: {
      common: common_zh,
      sessions: sessions_zh,
      settings: settings_zh,
      errors: errors_zh,
      updates: updates_zh,
    },
  },
  supportedLngs: ["en", "zh"],
  nonExplicitSupportedLngs: true,
  fallbackLng: "en",
  ns: ["common", "nav", "sessions", "settings", "errors", "updates", "theme", "sidebar"],
  defaultNS: "common",
  interpolation: { escapeValue: false },
  // 恢复语言切换时解注：
  // detection: {
  //   order: ["localStorage", "navigator"],
  //   caches: ["localStorage"],
  //   lookupLocalStorage: "i18nextLng",
  // },
});

export default i18n;

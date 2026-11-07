import { createI18n } from 'vue-i18n';
import i18nConfig from '@/app/i18n';
import { isObject } from 'lodash';

// 界面语言：优先用户选择（localStorage），否则跟随浏览器；默认 zh-CN。
export const locale = JSON.parse(localStorage.getItem('language-option')) || navigator.language || navigator.userLanguage || 'zh-CN';
const i18n = createI18n({
  legacy: false,
  locale: locale.substring(0, 2),
  messages: i18nConfig
})


export default i18n;


export function translate (key, values) {
  const { t } = i18n.global;
  return t(key, values);
}

export const $t = translate;

let regString = '';

if (isObject(locale)) {
  regString = locale.value && locale.value.substring && locale.value.substring(0, 2);
} else {
  regString = locale.substring && locale.substring(0, 2);
}

export const isGlobalZh = /zh/i.test(regString);

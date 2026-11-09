import { useEffect } from 'react';

import type { Locale } from 'harness-shared';

import { htmlLangOf } from '../i18n/translate';

/**
 * 把当前语言同步到 `<html lang>`。
 *
 * 不是可有可无的一行：`lang` 决定读屏软件用哪种语音合成读页面，也决定浏览器
 * 对中日韩文本的字体回退与标点处理。index.html 里写死 `zh-CN` 的话，
 * 切到英文后整页仍会被按中文朗读。
 */
export function useHtmlLang(locale: Locale): void {
  useEffect(() => {
    document.documentElement.lang = htmlLangOf(locale);
  }, [locale]);
}

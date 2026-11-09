import { describe, expect, test } from 'vitest';

import {
  DEFAULT_LOCALE,
  LOCALE_HTML_LANG,
  LOCALE_LABELS,
  SUPPORTED_LOCALES,
  isLocale,
  pickLocalized,
} from './locale';

describe('isLocale', () => {
  test('接受支持的语言', () => {
    expect(isLocale('zh-CN')).toBe(true);
    expect(isLocale('en-US')).toBe(true);
  });

  test('拒绝未支持的语言与非法输入', () => {
    expect(isLocale('fr-FR')).toBe(false);
    expect(isLocale('zh')).toBe(false);
    expect(isLocale(null)).toBe(false);
    expect(isLocale(42)).toBe(false);
  });

  test('默认语言是中文', () => {
    expect(DEFAULT_LOCALE).toBe('zh-CN');
  });
});

describe('语言元信息', () => {
  test('每种语言都有自称与 html lang（D28 双语）', () => {
    for (const locale of SUPPORTED_LOCALES) {
      expect(LOCALE_LABELS[locale]).toBeTruthy();
      expect(LOCALE_HTML_LANG[locale]).toBeTruthy();
    }
  });

  test('语言自称用该语言本身书写，不做翻译', () => {
    expect(LOCALE_LABELS['zh-CN']).toBe('简体中文');
    expect(LOCALE_LABELS['en-US']).toBe('English');
  });
});

describe('pickLocalized', () => {
  const text = { 'zh-CN': '专家', 'en-US': 'Experts' };

  test('按语言取值', () => {
    expect(pickLocalized(text, 'zh-CN')).toBe('专家');
    expect(pickLocalized(text, 'en-US')).toBe('Experts');
  });
});

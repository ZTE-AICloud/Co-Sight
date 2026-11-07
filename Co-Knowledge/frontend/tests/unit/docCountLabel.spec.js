// @vitest-environment jsdom
// `@/app/i18n/i18n.js` 在导入期读 localStorage，先钉住语言再 import。
vi.hoisted(() => {
  window.localStorage.setItem('language-option', JSON.stringify('zh-CN'))
})

import { afterAll, describe, expect, it } from 'vitest'
import i18n from '@/app/i18n/i18n.js'
import { docCountLabel } from '@/shared/lib/utils'

describe('docCountLabel', () => {
  const originalLocale = i18n.global.locale.value

  afterAll(() => {
    i18n.global.locale.value = originalLocale
  })

  it('uses the singular form for one document in English', () => {
    i18n.global.locale.value = 'en'

    expect(docCountLabel(1)).toBe('1 document')
    expect(docCountLabel(8)).toBe('8 documents')
    expect(docCountLabel(0)).toBe('0 documents')
  })

  it('uses the same Chinese unit for every count', () => {
    i18n.global.locale.value = 'zh'

    expect(docCountLabel(1)).toBe('1 篇文档')
    expect(docCountLabel(8)).toBe('8 篇文档')
  })
})

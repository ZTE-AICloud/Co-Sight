// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'

import { flush, mountWithPlugins } from './helpers/mount'
import Text2SQLPage from '@/pages/text2sql/Text2SQLPage.vue'

describe('Text2SQLPage', () => {
  it('渲染工作台导航与默认查询面板', async () => {
    // arrange
    localStorage.clear()

    // act
    const wrapper = await mountWithPlugins(Text2SQLPage, { route: '/text2sql' })
    await flush()

    // assert
    expect(wrapper.find('.text2sql-page').exists()).toBe(true)
    expect(wrapper.find('.page-title h1').text()).toBe('Text2SQL')

    const nav = wrapper.find('.t2s-nav')
    expect(nav.text()).toContain('查询工作台')
    expect(nav.text()).toContain('验证与反馈')

    expect(wrapper.find('#text2sql-question').exists()).toBe(true)
    expect(wrapper.text()).toContain('选择问题，开始分析')
  })
})

// @vitest-environment jsdom
// 登录入口：外部 VUE_APP_UAC（或 qiankun 注入的 appState.loginUrl）优先；
// 没有外部地址时指向站内 /login，图标始终可见。
import { vi } from 'vitest'

const loginState = vi.hoisted(() => ({ url: '' }))

vi.mock('@/app/state', () => ({
  default: {
    get loginUrl () {
      return loginState.url
    }
  }
}))

import { flush, mountWithPlugins } from './helpers/mount'
import LeftNav from '@/app/layout/nav/LeftNav.vue'

describe('LeftNav 登录入口', () => {
  beforeEach(() => {
    loginState.url = ''
  })

  it('配置 appState.loginUrl 时保持外链行为', async () => {
    // Arrange
    loginState.url = 'https://uac.example/login'

    // Act
    const wrapper = await mountWithPlugins(LeftNav, { route: '/chat' })
    await flush()

    // Assert：与参考站相同的 .icon-button 位置/样式，href 指向配置的登录页
    const link = wrapper.find('.side-footer a[aria-label="登录入口"]')
    expect(link.exists()).toBe(true)
    expect(link.attributes('href')).toBe('https://uac.example/login')
    expect(link.classes()).toContain('icon-button')
    expect(link.find('svg').exists()).toBe(true)
  })

  it('没有外部 loginUrl 时渲染站内 /login 链接并可导航', async () => {
    // Act
    const wrapper = await mountWithPlugins(LeftNav, { route: '/chat' })
    await flush()

    // Assert：图标不再隐藏，指向站内登录页
    const link = wrapper.find('.side-footer a[aria-label="登录入口"]')
    expect(link.exists()).toBe(true)
    expect(link.attributes('href')).toBe('/login')
    expect(link.classes()).toContain('icon-button')
    expect(link.find('svg').exists()).toBe(true)

    // Act：点击后进入登录页
    await link.trigger('click')
    await flush()

    // Assert
    expect(wrapper.router.currentRoute.value.name).toBe('login')
  })
})

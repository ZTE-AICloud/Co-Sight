// @vitest-environment jsdom
/**
 * 主题读写的契约：
 * - 默认浅色（设计系统以 #f7f8fa / #1677ff 为产品默认外观，不是跟随系统）
 * - 存储值只在 dark / light 时被采纳，其他值一律回落默认
 * - 切换必须同时改 html.dark、data-theme、localStorage，并派发事件
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  DEFAULT_THEME,
  THEME_CHANGE_EVENT,
  THEME_STORAGE_KEY,
  applyTheme,
  initTheme,
  readStoredTheme,
  theme,
  toggleTheme
} from '@/shared/lib/theme'

describe('theme', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.className = ''
    document.documentElement.removeAttribute('data-theme')
  })

  it('没有存储值时默认浅色', () => {
    expect(DEFAULT_THEME).toBe('light')
    expect(readStoredTheme()).toBe('light')
  })

  it('读取已存储的 light', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'light')
    expect(readStoredTheme()).toBe('light')
  })

  it('非法存储值回落默认，而不是让页面挂掉', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'midnight')
    expect(readStoredTheme()).toBe('light')
  })

  it('applyTheme 同步 html class / data-theme / localStorage', () => {
    applyTheme('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('light')
    expect(theme.value).toBe('light')
  })

  it('toggleTheme 在两个主题之间往返且幂等', () => {
    applyTheme('dark')
    expect(toggleTheme()).toBe('light')
    expect(toggleTheme()).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('切换时派发 ragstudio:theme-change 事件', () => {
    const handler = vi.fn()
    window.addEventListener(THEME_CHANGE_EVENT, handler)
    applyTheme('dark')
    expect(handler).toHaveBeenCalledTimes(1)
    expect(handler.mock.calls[0][0].detail).toEqual({ theme: 'dark' })
    window.removeEventListener(THEME_CHANGE_EVENT, handler)
  })

  it('initTheme 读取存储值并应用', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'light')
    expect(initTheme()).toBe('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })
})

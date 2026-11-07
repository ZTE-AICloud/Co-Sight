// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { copyText } from '@/shared/lib/clipboard'

function setClipboard (value) {
  Object.defineProperty(navigator, 'clipboard', {
    value,
    configurable: true
  })
}

function setSecureContext (value) {
  Object.defineProperty(window, 'isSecureContext', {
    value,
    configurable: true
  })
}

afterEach(() => {
  setClipboard(undefined)
  setSecureContext(undefined)
  vi.restoreAllMocks()
})

describe('copyText', () => {
  it('安全上下文下优先使用 navigator.clipboard', async () => {
    setSecureContext(true)
    const writeText = vi.fn().mockResolvedValue(undefined)
    setClipboard({ writeText })

    await expect(copyText('hello')).resolves.toBe(true)
    expect(writeText).toHaveBeenCalledWith('hello')
  })

  it('clipboard 抛错时回落 execCommand，并移除临时 textarea', async () => {
    setSecureContext(true)
    setClipboard({ writeText: vi.fn().mockRejectedValue(new Error('denied')) })
    const execCommand = vi.fn().mockReturnValue(true)
    document.execCommand = execCommand

    await expect(copyText('hello')).resolves.toBe(true)
    expect(execCommand).toHaveBeenCalledWith('copy')
    expect(document.querySelectorAll('textarea')).toHaveLength(0)
  })

  it('非安全上下文（HTTP 部署）直接走 execCommand', async () => {
    setSecureContext(false)
    setClipboard({ writeText: vi.fn() })
    document.execCommand = vi.fn().mockReturnValue(true)

    await expect(copyText('hello')).resolves.toBe(true)
  })

  it('execCommand 返回 false 时报告失败，仍清理 DOM', async () => {
    setSecureContext(false)
    setClipboard(undefined)
    document.execCommand = vi.fn().mockReturnValue(false)

    await expect(copyText('hello')).resolves.toBe(false)
    expect(document.querySelectorAll('textarea')).toHaveLength(0)
  })
})

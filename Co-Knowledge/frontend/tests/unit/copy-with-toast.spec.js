// @vitest-environment jsdom
// 复制按钮的统一反馈：成功与失败都必须有 toast
// （只有失败提示、甚至完全没有提示，用户不知道复制是否成功）。
import { vi } from 'vitest'

const { copyText, success, error } = vi.hoisted(() => ({
  copyText: vi.fn(),
  success: vi.fn(),
  error: vi.fn()
}))

vi.mock('@/shared/lib/clipboard', () => ({ copyText }))
vi.mock('element-plus', () => ({ ElMessage: { success, error } }))

import { copyTextWithToast } from '@/shared/lib/copy-with-toast'

describe('copyTextWithToast', () => {
  beforeEach(() => {
    copyText.mockReset()
    success.mockReset()
    error.mockReset()
  })

  it('复制成功时弹成功提示，并把非字符串统一转成字符串', async () => {
    // Arrange
    copyText.mockResolvedValue(true)

    // Act
    const ok = await copyTextWithToast(123456)

    // Assert
    expect(ok).toBe(true)
    expect(copyText).toHaveBeenCalledWith('123456')
    expect(success).toHaveBeenCalledTimes(1)
    expect(error).not.toHaveBeenCalled()
  })

  it('复制失败时弹失败提示，不弹成功提示', async () => {
    // Arrange
    copyText.mockResolvedValue(false)

    // Act
    const ok = await copyTextWithToast(null)

    // Assert
    expect(ok).toBe(false)
    expect(copyText).toHaveBeenCalledWith('')
    expect(error).toHaveBeenCalledTimes(1)
    expect(success).not.toHaveBeenCalled()
  })
})

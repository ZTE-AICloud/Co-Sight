// @vitest-environment jsdom
import { vi } from 'vitest'

vi.mock('element-plus', () => ({
  ElMessage: {
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
    error: vi.fn(),
    closeAll: vi.fn()
  }
}))

vi.mock('@/app/i18n/i18n.js', () => ({
  $t: key => key,
  isGlobalZh: true,
  locale: 'zh'
}))

const { messageError } = vi.hoisted(() => ({ messageError: vi.fn() }))
vi.mock('@/shared/lib/message', () => ({
  default: { error: messageError, closeAll: vi.fn() }
}))

vi.mock('axios', () => {
  const instance = {
    defaults: {},
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() }
    }
  }
  return { default: { create: () => instance } }
})

import axiosInstance from '@/shared/api/client'
import { setUnauthorizedHandler } from '@/shared/api/unauthorized'

const responseErrorHandler = axiosInstance.interceptors.response.use.mock.calls[0][1]

function httpError (status, data = null, config = {}) {
  return {
    response: { status, data },
    config,
    message: `HTTP ${status}`
  }
}

function problem (status, code, detail = 'problem detail') {
  return { type: `urn:ragstudio:problem:${code}`, title: code, status, code, detail }
}

afterEach(() => {
  setUnauthorizedHandler(null)
  messageError.mockClear()
})

describe('axios 401 handling', () => {
  it('已注册处理器时：401 交给会话层，不再弹通用 toast', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)

    await expect(responseErrorHandler(httpError(401, problem(401, 'unauthorized'))))
      .rejects.toMatchObject({ status: 401, code: 'unauthorized' })

    expect(handler).toHaveBeenCalledTimes(1)
    expect(handler.mock.calls[0][0].status).toBe(401)
    expect(messageError).not.toHaveBeenCalled()
  })

  it('skipErrorHandler 的请求（登录/状态/登出）不触发全局处理器', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)

    await expect(responseErrorHandler(
      httpError(401, problem(401, 'invalid_credentials'), { skipErrorHandler: true })
    )).rejects.toMatchObject({ status: 401 })

    expect(handler).not.toHaveBeenCalled()
    expect(messageError).not.toHaveBeenCalled()
  })

  it('非 401 错误仍然走通用 toast', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)

    await expect(responseErrorHandler(httpError(500, problem(500, 'internal_error'))))
      .rejects.toMatchObject({ status: 500 })

    expect(handler).not.toHaveBeenCalled()
    expect(messageError).toHaveBeenCalledTimes(1)
  })

  it('没有处理器时 401 保留旧的 toast 行为', async () => {
    await expect(responseErrorHandler(httpError(401, problem(401, 'unauthorized'))))
      .rejects.toMatchObject({ status: 401 })

    expect(messageError).toHaveBeenCalledTimes(1)
  })

  it('skipErrorMessage 只抑制 toast，401 仍交给会话层', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)

    await expect(responseErrorHandler(
      httpError(401, problem(401, 'unauthorized'), { skipErrorMessage: true })
    )).rejects.toMatchObject({ status: 401 })

    expect(handler).toHaveBeenCalledTimes(1)
    expect(messageError).not.toHaveBeenCalled()
  })

  it('skipErrorMessage 的非 401 错误不弹通用 toast', async () => {
    await expect(responseErrorHandler(
      httpError(500, problem(500, 'internal_error'), { skipErrorMessage: true })
    )).rejects.toMatchObject({ status: 500 })

    expect(messageError).not.toHaveBeenCalled()
  })
})

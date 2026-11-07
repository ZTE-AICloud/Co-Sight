// @vitest-environment jsdom
//
// 测的是 `src/shared/api/client.js` 的响应拦截器（纯 REST + RFC 9457）。
// 这是全站唯一一处「HTTP/问题体 → 调用方」的翻译层，之前的单测都 mock 掉 api 模块，
// 拦截器本身没有覆盖 —— 这里直接换 axios adapter，走真实的拦截器链路。
import { beforeEach, describe, expect, it, vi } from 'vitest'

const errorToast = vi.fn(() => ({ close: vi.fn() }))
vi.mock('@/shared/lib/message', () => ({
  default: { error: (...args) => errorToast(...args) }
}))

import axiosInstance, { ApiError } from '@/shared/api/client'

/** 造一个只返回一次响应的 axios adapter。 */
function adapterFor ({ status = 200, data = null, headers = {} }) {
  return async config => {
    const response = { status, statusText: String(status), headers, data, config }
    if (status >= 400) {
      const error = new Error(`Request failed with status code ${status}`)
      error.response = response
      error.config = config
      error.isAxiosError = true
      error.toJSON = () => ({})
      throw error
    }
    return response
  }
}

function problemOf (status, code, detail = '服务器文案') {
  return {
    type: `urn:ragstudio:problem:${code}`,
    title: code,
    status,
    detail,
    code,
  }
}

async function call (options) {
  return axiosInstance.request({
    url: '/api/co-knowledge/v1/test',
    method: 'get',
    adapter: adapterFor(options),
    ...(options.config || {})
  })
}

beforeEach(() => {
  errorToast.mockClear()
  axiosInstance.defaults.headers = {}
})

describe('成功响应', () => {
  it('200 纯 JSON 直接返回 body', async () => {
    const body = { id: 'kb-1', name: 'demo' }
    await expect(call({ data: body })).resolves.toEqual(body)
  })

  it('分页体原样返回', async () => {
    const page = { items: [{ id: 1 }], total: 1, page: 1, pageSize: 10 }
    await expect(call({ data: page })).resolves.toEqual(page)
  })

  it('201 也按 2xx 成功返回 body', async () => {
    await expect(call({ status: 201, data: { id: 'new' } })).resolves.toEqual({ id: 'new' })
  })

  it('204 / 空 body 返回 null', async () => {
    await expect(call({ status: 204, data: '' })).resolves.toBeNull()
  })

  it('blob 成功直接返回 Blob', async () => {
    const blob = new Blob(['zip-bytes'], { type: 'application/octet-stream' })
    const result = await call({
      data: blob,
      headers: { 'content-type': 'application/octet-stream' },
      config: { responseType: 'blob' }
    })
    expect(result).toBe(blob)
  })
})

describe('problem+json 错误', () => {
  it('404 拒绝为 ApiError，并弹出服务端 detail', async () => {
    await expect(call({
      status: 404,
      data: problemOf(404, 'knowledge_base_not_found', '知识库不存在'),
      headers: { 'content-type': 'application/problem+json; charset=utf-8' }
    })).rejects.toMatchObject({
      name: 'ApiError',
      status: 404,
      code: 'knowledge_base_not_found',
      detail: '知识库不存在'
    })
    expect(errorToast).toHaveBeenCalledTimes(1)
    expect(errorToast.mock.calls[0][0].message).toBe('知识库不存在')
  })

  it('skipErrorHandler 时不弹 toast，仍返回 ApiError', async () => {
    const rejection = call({
      status: 422,
      data: problemOf(422, 'validation_failed', '参数不合法'),
      headers: { 'content-type': 'application/problem+json' },
      config: { skipErrorHandler: true }
    })
    await expect(rejection).rejects.toBeInstanceOf(ApiError)
    await expect(rejection).rejects.toMatchObject({ status: 422, detail: '参数不合法' })
    expect(errorToast).not.toHaveBeenCalled()
  })

  it('file_name_conflict 不弹全局 toast（页面自己弹覆盖确认）', async () => {
    await expect(call({
      status: 409,
      data: problemOf(409, 'file_name_conflict', '同名文件已存在'),
      headers: { 'content-type': 'application/problem+json' }
    })).rejects.toMatchObject({ code: 'file_name_conflict' })
    expect(errorToast).not.toHaveBeenCalled()
  })

  it('validateStatus:()=>true 的 4xx 也走同一条错误通道', async () => {
    await expect(call({
      status: 422,
      data: problemOf(422, 'validation_failed', '参数不合法'),
      headers: { 'content-type': 'application/problem+json' },
      config: { validateStatus: () => true }
    })).rejects.toMatchObject({ code: 'validation_failed' })
    expect(errorToast).toHaveBeenCalledTimes(1)
  })

  it('空 body 的 4xx 回落到 i18n 状态文案', async () => {
    await expect(call({ status: 500, data: '' })).rejects.toMatchObject({
      status: 500,
      code: 'http_error'
    })
    expect(errorToast).toHaveBeenCalledTimes(1)
  })
})

describe('取消与网络错误', () => {
  it('取消请求原样 reject ERR_CANCELED，不弹提示', async () => {
    const canceled = new Error('canceled')
    canceled.code = 'ERR_CANCELED'
    canceled.name = 'CanceledError'
    const promise = axiosInstance.request({
      url: '/api/co-knowledge/v1/test',
      adapter: async () => { throw canceled }
    })
    await expect(promise).rejects.toBe(canceled)
    expect(errorToast).not.toHaveBeenCalled()
  })

  it('网络错误归一成 network_error', async () => {
    const promise = axiosInstance.request({
      url: '/api/co-knowledge/v1/test',
      adapter: async () => { throw new Error('Network Error') }
    })
    await expect(promise).rejects.toMatchObject({ code: 'network_error', status: 0 })
    expect(errorToast).toHaveBeenCalledTimes(1)
  })
})

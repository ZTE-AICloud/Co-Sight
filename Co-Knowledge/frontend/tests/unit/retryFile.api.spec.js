// 重新解析接口的最小契约：方法/路径/无请求体。
// 后端只接受 status=2 的文档，这里只钉住前端拼的 URL，状态闸门由后端单测覆盖。
import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('@/shared/api/client', () => ({
  default: { post: vi.fn(() => Promise.resolve({ accepted: true })) }
}))

import client from '@/shared/api/client'
import { retryFile } from '@/features/knowledge-base/api/directory'

describe('retryFile（重新解析失败文档）', () => {
  beforeEach(() => client.post.mockClear())

  it('POST 到 /knowledge-bases/{kb}/documents/{id}/retry，不带请求体', async () => {
    await retryFile('kb-1', 'file-1')

    expect(client.post).toHaveBeenCalledTimes(1)
    const [url, body] = client.post.mock.calls[0]
    expect(url.endsWith('/knowledge-bases/kb-1/documents/file-1/retry')).toBe(true)
    expect(body).toBeUndefined()
  })
})

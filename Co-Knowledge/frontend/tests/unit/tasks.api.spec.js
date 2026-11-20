// 统一任务管理 API 的最小契约：方法/路径/参数。
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/shared/api/client', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({})),
    post: vi.fn(() => Promise.resolve({})),
    patch: vi.fn(() => Promise.resolve({}))
  }
}))

import client from '@/shared/api/client'
import {
  cancelTask, getTask, getTaskStats, listTaskGroups, listTasks, retryTask,
  updateTaskPriority
} from '@/features/tasks/api/tasks'

describe('tasks api', () => {
  beforeEach(() => {
    client.get.mockClear()
    client.post.mockClear()
    client.patch.mockClear()
  })

  it('listTasks 过滤空参数并按 page/size 取列表', async () => {
    await listTasks({
      task_type: 'FILE_IMPORT', status: '', keyword: '', page: 2, size: 20
    })

    const [url, config] = client.get.mock.calls[0]
    expect(url.endsWith('/tasks')).toBe(true)
    expect(config.params).toEqual({ task_type: 'FILE_IMPORT', page: 2, size: 20 })
  })

  it('detail / stats / groups 走 GET', async () => {
    await getTask('task-1')
    await getTaskStats()
    await listTaskGroups({ keyword: 'demo', page: 1, size: 20 })

    expect(client.get.mock.calls[0][0].endsWith('/tasks/task-1')).toBe(true)
    expect(client.get.mock.calls[1][0].endsWith('/tasks/stats')).toBe(true)
    expect(client.get.mock.calls[2][0].endsWith('/tasks/groups')).toBe(true)
    expect(client.get.mock.calls[2][1].params).toEqual({ keyword: 'demo', page: 1, size: 20 })
  })

  it('cancel 带可选 reason；retry 无请求体；priority 走 PATCH', async () => {
    await cancelTask('task-1', 'duplicate')
    await cancelTask('task-2')
    await retryTask('task-3')
    await updateTaskPriority('task-4', 50)

    expect(client.post.mock.calls[0][0].endsWith('/tasks/task-1/cancel')).toBe(true)
    expect(client.post.mock.calls[0][1]).toEqual({ reason: 'duplicate' })
    expect(client.post.mock.calls[1][1]).toEqual({})
    expect(client.post.mock.calls[2][0].endsWith('/tasks/task-3/retry')).toBe(true)
    expect(client.patch.mock.calls[0][0].endsWith('/tasks/task-4')).toBe(true)
    expect(client.patch.mock.calls[0][1]).toEqual({ priority: 50 })
  })
})

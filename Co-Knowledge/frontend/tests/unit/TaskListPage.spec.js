// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/features/tasks/api/tasks', () => ({
  listTasks: vi.fn(),
  listTaskGroups: vi.fn(),
  getTaskStats: vi.fn(),
  getTask: vi.fn(),
  cancelTask: vi.fn(),
  retryTask: vi.fn(),
  updateTaskPriority: vi.fn()
}))

import { flush, mountWithPlugins, expectNoI18nMisses } from './helpers/mount'
import { getTaskStats, listTaskGroups, listTasks } from '@/features/tasks/api/tasks'
import TaskListPage from '@/pages/tasks/TaskListPage.vue'

const TASK = {
  id: 'c93e84cb210b4aaa84f3fadb79e76e20',
  taskType: 'FILE_IMPORT',
  lane: 'file_import',
  status: 'COMPLETED',
  priority: 0,
  progress: 100,
  attempt: 1,
  maxAttempts: 4,
  kbaseId: '44ee4658c03665dd',
  kbaseName: 'Demo KB',
  fileName: 'report.md',
  cancelRequested: false,
  createdAt: '2026-11-10T15:51:04+08:00'
}

const GROUP = {
  kbaseId: '44ee4658c03665dd',
  kbaseName: 'Demo KB',
  total: 1,
  byStatus: { COMPLETED: 1 },
  latestCreatedAt: '2026-11-10T15:51:04+08:00'
}

describe('TaskListPage', () => {
  beforeEach(() => {
    localStorage.clear()
    listTasks.mockReset()
    listTaskGroups.mockReset()
    getTaskStats.mockReset()
    listTasks.mockResolvedValue({ items: [TASK], total: 1 })
    listTaskGroups.mockResolvedValue({ items: [GROUP], total: 1, taskTotal: 1 })
    getTaskStats.mockResolvedValue({
      total: 1,
      queueDepth: 0,
      oldestPendingAgeSeconds: 0,
      byStatus: { RUNNING: 0, FAILED: 0 }
    })
  })

  it('平铺模式渲染文件名称、知识库名称与状态', async () => {
    localStorage.setItem('tasks-view-mode', 'flat')
    const wrapper = await mountWithPlugins(TaskListPage, { route: '/tasks' })
    await flush()

    expect(wrapper.text()).toContain('任务管理')
    expect(wrapper.text()).toContain('report.md')
    expect(wrapper.text()).toContain('Demo KB')
    expect(wrapper.text()).toContain('已完成')
    expect(wrapper.text()).toContain('44ee4658c03665dd')
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
    expectNoI18nMisses(wrapper)
    wrapper.unmount()
  })

  it('树模式以知识库为根，展开后显示任务', async () => {
    const wrapper = await mountWithPlugins(TaskListPage, { route: '/tasks' })
    await flush()

    expect(wrapper.text()).toContain('Demo KB')
    expect(wrapper.text()).toContain('1 个任务')
    expect(wrapper.text()).not.toContain('report.md')

    const groupRow = wrapper.findAll('tbody tr').find(row => row.text().includes('Demo KB'))
    await groupRow.trigger('click')
    await flush()

    expect(wrapper.text()).toContain('report.md')
    expectNoI18nMisses(wrapper)
    wrapper.unmount()
  })
})

// @vitest-environment jsdom
// 检索编排列表页（#/flow）高度契约：
// 页面是「内容自然高度 + 整页滚动」，所以用原生 table.list-table，
// 不接 useTableFillHeight，也不设置任何固定 height。
import { vi } from 'vitest'
import { flush, mountWithPlugins } from './helpers/mount'

// 页面 onMounted 会取列表（本用例只关心高度契约，空列表即可）
vi.mock('@/features/workflow/api/workflow', () => ({
  getFlowList: vi.fn(() => Promise.resolve({ bo: [], recordsTotal: 0 })),
  deleteFlowApi: vi.fn(),
  exportWorkFlow: vi.fn(),
  publishWorkFlow: vi.fn()
}))

import WorkFlowIndex from '@/pages/workflow/WorkflowListPage.vue'

async function mountFlowIndex () {
  const wrapper = await mountWithPlugins(WorkFlowIndex, {
    route: '/flow',
    global: { mocks: { $globalZh: true } }
  })
  await flush()
  return wrapper
}

describe('检索编排列表页（#/flow）自然高度契约', () => {
  it('使用原生 table.list-table，不设置固定 height / max-height', async () => {
    const wrapper = await mountFlowIndex()
    const table = wrapper.find('table.list-table.flow-table')

    expect(table.exists()).toBe(true)
    expect(table.attributes('height')).toBeUndefined()
    expect(table.attributes('style') || '').not.toContain('height')
  })
})

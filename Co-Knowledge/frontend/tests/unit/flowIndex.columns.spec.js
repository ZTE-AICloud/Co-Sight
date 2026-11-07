// @vitest-environment jsdom
// ↑ 组件测试：要真渲染表格才看得到表头文案与列顺序
//
// 测的是 `views/Flow.vue`（检索编排 `/flow`）的表头结构。
//
// 原生 table.list-table。
//   - 保留勾选列（每行都有 checkbox），它不算业务列；
//   - 第一个业务列是「知识检索名称」，ID 收进名称单元格的第二行；
//   - 页面主操作只允许一个 Primary Button。
import { vi } from 'vitest'
import { flush, mountWithPlugins, textOf } from './helpers/mount'

// 页面 onMounted 会取列表：mock 成空列表（本用例只关心表头结构）
vi.mock('@/features/workflow/api/workflow', () => ({
  getFlowList: vi.fn(() => Promise.resolve({ bo: [], recordsTotal: 0 })),
  deleteFlowApi: vi.fn(),
  exportWorkFlow: vi.fn(),
  publishWorkFlow: vi.fn()
}))

import WorkFlowIndex from '@/pages/workflow/WorkflowListPage.vue'

async function mountFlowIndex ({ globalZh = true } = {}) {
  const wrapper = await mountWithPlugins(WorkFlowIndex, {
    route: '/flow',
    global: { mocks: { $globalZh: globalZh } }
  })
  await flush()
  return wrapper
}

describe('检索编排列表（#/flow）的表头结构', () => {
  it('首列是勾选列，第一个业务列是「知识检索名称」', async () => {
    // Arrange + Act
    const wrapper = await mountFlowIndex()

    // Assert
    const headers = wrapper.findAll('table.list-table thead th')
    expect(headers.length).toBeGreaterThan(1)
    expect(headers[0].find('input[type="checkbox"]').exists()).toBe(true)
    expect(textOf(headers[1])).toBe('知识检索名称')
  })

  it('表头不含「序号」，包含「知识检索名称」与「编排预览」', async () => {
    // Arrange + Act
    const wrapper = await mountFlowIndex()

    // Assert：脚手架用真词条，键名写错会渲染成裸键名
    const headers = wrapper.findAll('table.list-table thead th').map(textOf)
    expect(headers).toContain('知识检索名称')
    // 术语与页面/菜单统一：用「编排预览」
    expect(headers).toContain('编排预览')
    expect(headers).not.toContain('序号')
  })

  it('表格是参考站原生 table.list-table（不是 el-table）', async () => {
    // Arrange + Act
    const wrapper = await mountFlowIndex()

    // Assert
    expect(wrapper.find('table.list-table.flow-table').exists()).toBe(true)
    expect(wrapper.find('.el-table').exists()).toBe(false)
  })

  it('页面只有一个 Primary Button（新建知识检索）', async () => {
    // Arrange + Act
    const wrapper = await mountFlowIndex()

    // Assert：更多操作走 icon button / dropdown
    expect(wrapper.findAll('.el-button--primary')).toHaveLength(1)
  })
})

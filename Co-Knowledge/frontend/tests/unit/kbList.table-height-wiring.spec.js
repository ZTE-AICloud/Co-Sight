// @vitest-environment jsdom
// 列表页高度契约：
// 知识库/图谱列表是「内容自然高度 + 整页滚动」，不是表格撑满、分页贴底。
// 因此页面用原生 table.list-table，不传固定 `:height`。
import { vi } from 'vitest'
import { flush, mountWithPlugins } from './helpers/mount'

vi.mock('@/features/knowledge-base/api/knowledgeBase', () => ({
  deleteKnowledgeBase: vi.fn(),
  getKnowledgeGraphList: vi.fn()
}))

vi.mock('@/features/knowledge-base/api/kbaseApi.js', () => ({
  checkAISEnvironmentApi: vi.fn(() => Promise.resolve({ ais: false }))
}))

import { ElTable, ElTableColumn } from 'element-plus/es/components/table/index'
import Kbase from '@/pages/knowledge-base/KnowledgeBaseListPage.vue'
import KnowledgeGraphPage from '@/pages/graph/GraphListPage.vue'

const REAL_TABLE = { global: { components: { ElTable, ElTableColumn } } }

describe('列表页自然高度契约', () => {
  it('文档知识库 #/knowledge 使用原型原生 table.list-table（内容自然高度，整页滚动）', async () => {
    const wrapper = await mountWithPlugins(Kbase, { route: '/knowledge', ...REAL_TABLE })
    await flush()

    // 页面根是 .page；表格自然高度，分页是表格卡片后的兄弟节点。
    expect(wrapper.find('.page.management-page.knowledge-page').exists()).toBe(true)
    expect(wrapper.find('table.list-table.knowledge-table').exists()).toBe(true)
    expect(wrapper.find('.knowledge-main > .table-card + .table-pagination').exists()).toBe(true)
  })

  it('图谱知识库 #/graph 与模版列表都使用原生 table（内容自然高度）', async () => {
    // 没有页签头，两个列表二选一渲染：默认图谱列表；深链进模版列表。
    const graph = await mountWithPlugins(KnowledgeGraphPage, { route: '/graph', ...REAL_TABLE })
    await flush()
    expect(graph.find('table.list-table.knowledge-table').exists()).toBe(true)
    expect(graph.find('table.list-table.template-table').exists()).toBe(false)

    const template = await mountWithPlugins(KnowledgeGraphPage, {
      route: '/graph?subTab=knowledgeGraphTemplate',
      ...REAL_TABLE
    })
    // 组件内部的 subTab 同步有 50/100/300ms 的延迟兜底。
    await new Promise(resolve => setTimeout(resolve, 400))
    await flush()
    expect(template.find('table.list-table.template-table').exists()).toBe(true)
    expect(template.find('table.list-table.knowledge-table').exists()).toBe(false)
  })
})

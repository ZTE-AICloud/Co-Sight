// @vitest-environment jsdom
// 检索编排列表的「工作流预览」回归守卫：
// 顺序检索的画布只有一个检索器算子（`template_loader._fill_retriever` 把绑定的库
// 全写进它的 knowledge_info_list），预览跟着画**一个** Vector Search 步骤 ——
// 不能按库数逐个画：绑 5 个库会出 5 个重复 chip。
import { vi } from 'vitest'

const { ROWS } = vi.hoisted(() => ({
  ROWS: [{
    workFlowId: 'RAG_Workflow_808f',
    name: '顺序检索',
    template: 'Sequential',
    knowledgeType: 'knowledgeBase',
    publishType: 0,
    createdBy: 'admin',
    kbPkIds: [
      { name: 'kb-a' }, { name: 'kb-b' }, { name: 'kb-c' }, { name: 'kb-d' }, { name: 'kb-e' }
    ],
    graphKbPkIds: []
  }]
}))

vi.mock('@/features/workflow/api/workflow', () => ({
  getFlowList: vi.fn(() => Promise.resolve({ items: ROWS })),
  getAllKBList: vi.fn(() => Promise.resolve({})),
  createFlow: vi.fn(),
  deleteFlowApi: vi.fn(),
  exportWorkFlow: vi.fn(),
  publishWorkFlow: vi.fn(),
  unpublishWorkFlow: vi.fn()
}))

import { flush, mountWithPlugins } from './helpers/mount'
import WorkFlowIndex from '@/pages/workflow/WorkflowListPage.vue'

async function mountList () {
  const wrapper = await mountWithPlugins(WorkFlowIndex, { route: '/flow' })
  await flush()
  return wrapper
}

function previewChips (wrapper) {
  const flow = wrapper.findAll('.mini-flow').at(0)
  return flow ? flow.findAll('.flow-chip').map(chip => chip.text().trim()) : []
}

describe('检索编排列表：工作流预览', () => {
  it('顺序检索绑多个库时只画一个 Vector Search', async () => {
    // Arrange + Act
    const wrapper = await mountList()

    // Assert
    expect(previewChips(wrapper)).toEqual(['Query', 'Vector Search', 'Rerank'])
  })
})

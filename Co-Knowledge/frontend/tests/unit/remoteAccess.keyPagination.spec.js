// @vitest-environment jsdom
// ↑ 组件测试：要真挂 KeyManagement + 分页件，走一遍分页事件到取数的链路
//
// 测的是「密钥管理」列表的分页**接线**：
//   TablePagination 翻页 / 改每页条数 → 抛 `change`
//   → 页面必须接住并重新取数。
//
// 为什么单独钉：缺了 `@change` 不会报错，分页条自己也能高亮到第 2 页，
// 只是表格数据不换 —— 属于「看起来点了、其实没发请求」的那类失效，
// 只有走一遍事件才看得出来。
import { vi } from 'vitest'
import { flush, mountWithPlugins } from './helpers/mount'

const { queryAgentKeysApi } = vi.hoisted(() => ({
  queryAgentKeysApi: vi.fn()
}))

vi.mock('@/features/agent/api/remoteAccess', () => ({
  queryAgentKeysApi,
  getAgentKeyStatsApi: vi.fn(() => Promise.resolve({ totalCalls: 0, requests7d: 0 })),
  getAgentKeyStatusApi: vi.fn(),
  createAgentKeyApi: vi.fn(),
  updateAgentKeyApi: vi.fn(),
  deleteAgentKeyApi: vi.fn(),
  searchDocumentKbasesApi: vi.fn(() => Promise.resolve({ data: [] }))
}))

import TablePagination from '@/shared/ui/reference/TablePagination.vue'
import KeyManagement from '@/pages/agent/KeyManagementPage.vue'

async function mountKeys () {
  const wrapper = await mountWithPlugins(KeyManagement, {
    props: { status: null }
  })
  await flush()
  return wrapper
}

/**
 * 顶部概览计数走 `GET /agent-keys/stats` 的 keySummary，
 * 页面不为概览额外拉一次全量列表 —— 这里每次 queryAgentKeysApi 调用都是列表取数。
 */
function tableCalls () {
  return queryAgentKeysApi.mock.calls
}

/** 取第 n 次（从 0 起）列表请求的 query 参数。 */
function paramsOf (callIndex) {
  return tableCalls()[callIndex][0]
}

/**
 * 与后端同样的切片：空列表 + 非零总数会触发页面的空态，
 * 让用例看起来像卡死。
 */
function pageOf ({ currentPage = 1, pageSize = 10 } = {}) {
  // 120 条：第 2 页在默认 10 条/页下确实有数据
  const all = Array.from({ length: 120 }, (_, index) => ({
    keyPrefix: `ragk_${index}`,
    name: `key-${index}`
  }))
  const start = (currentPage - 1) * pageSize
  return { data: all.slice(start, start + pageSize), recordsTotal: all.length }
}

describe('密钥管理：分页/每页条数必须触发重新取数', () => {
  beforeEach(() => {
    queryAgentKeysApi.mockReset()
    queryAgentKeysApi.mockImplementation(params => Promise.resolve(pageOf(params)))
  })

  it('首次进入按默认分页取一次（currentPage=1，pageSize=10）', async () => {
    // Act
    await mountKeys()

    // Assert
    expect(tableCalls()).toHaveLength(1)
    expect(paramsOf(0)).toMatchObject({ currentPage: 1, pageSize: 10 })
  })

  it('点第 2 页：带着 currentPage=2 重新取数（而不是只把页码高亮过去）', async () => {
    // Arrange
    const wrapper = await mountKeys()

    // Act：分页件抛 change({ page, size })
    const pagination = wrapper.findComponent(TablePagination)
    expect(pagination.exists()).toBe(true)
    pagination.vm.$emit('change', { page: 2, size: 10 })
    await flush()

    // Assert
    expect(tableCalls()).toHaveLength(2)
    expect(paramsOf(1)).toMatchObject({ currentPage: 2, pageSize: 10 })
  }, 15000)

  it('改每页条数为 20：回到第 1 页并按 pageSize=20 重新取数', async () => {
    // Arrange
    const wrapper = await mountKeys()

    // Act
    wrapper.findComponent(TablePagination).vm.$emit('change', { page: 1, size: 20 })
    await flush()

    // Assert
    expect(tableCalls()).toHaveLength(2)
    expect(paramsOf(1)).toMatchObject({ currentPage: 1, pageSize: 20 })
  })
})

// @vitest-environment jsdom
// 密钥管理页顶部两个调用量卡片（总调用量 / 最近 7 天请求数）的接线。
//
// 这两张卡片不能写死 `'—'` +「接口未提供」；数据来自
// `GET /agent-keys/stats`，失败时仍回落「—」。这里钉住「取到就显示、失败不炸」。
import { vi } from 'vitest'
import { flush, mountWithPlugins } from './helpers/mount'

const { queryAgentKeysApi, getAgentKeyStatsApi } = vi.hoisted(() => ({
  queryAgentKeysApi: vi.fn(),
  getAgentKeyStatsApi: vi.fn()
}))

vi.mock('@/features/agent/api/remoteAccess', () => ({
  queryAgentKeysApi,
  getAgentKeyStatsApi,
  getAgentKeyStatusApi: vi.fn(),
  createAgentKeyApi: vi.fn(),
  updateAgentKeyApi: vi.fn(),
  deleteAgentKeyApi: vi.fn(),
  searchDocumentKbasesApi: vi.fn(() => Promise.resolve({ data: [] }))
}))

import KeyManagement from '@/pages/agent/KeyManagementPage.vue'

async function mountKeys () {
  const wrapper = await mountWithPlugins(KeyManagement, { props: { status: null } })
  await flush()
  return wrapper
}

function usageCards (wrapper) {
  const cards = wrapper.findAll('.metric-card')
  // 四张卡片顺序：已启用密钥 / 总调用量 / 可访问知识库 / 最近 7 天请求数
  return { calls: cards[1], requests: cards[3] }
}

describe('密钥管理：调用量卡片', () => {
  beforeEach(() => {
    queryAgentKeysApi.mockReset()
    getAgentKeyStatsApi.mockReset()
    queryAgentKeysApi.mockResolvedValue({ items: [], total: 0 })
  })

  it('取到统计后显示千分位数字与统计口径', async () => {
    // Arrange
    getAgentKeyStatsApi.mockResolvedValue({ totalCalls: 12430, requests7d: 3290 })

    // Act
    const wrapper = await mountKeys()

    // Assert
    const { calls, requests } = usageCards(wrapper)
    expect(calls.find('.metric-value').text()).toBe('12,430')
    expect(requests.find('.metric-value').text()).toBe('3,290')
    expect(calls.find('.metric-delta').attributes('title')).toContain('自统计启用以来累计调用')
    expect(requests.find('.metric-delta').attributes('title')).toContain('含今天')
    expect(calls.find('.metric-foot').text()).toBe('累计')
    expect(requests.find('.metric-foot').text()).toBe('近 7 天')
  })

  it('统计接口失败时回落占位符，不影响密钥列表', async () => {
    // Arrange
    getAgentKeyStatsApi.mockRejectedValue(new Error('503'))

    // Act
    const wrapper = await mountKeys()

    // Assert
    const { calls, requests } = usageCards(wrapper)
    expect(calls.find('.metric-value').text()).toBe('—')
    expect(requests.find('.metric-value').text()).toBe('—')
    expect(calls.find('.metric-delta').attributes('title')).toContain('接口未提供')
  })

  it('零调用量显示 0 而不是占位符', async () => {
    getAgentKeyStatsApi.mockResolvedValue({ totalCalls: 0, requests7d: 0 })

    const wrapper = await mountKeys()

    const { calls, requests } = usageCards(wrapper)
    expect(calls.find('.metric-value').text()).toBe('0')
    expect(requests.find('.metric-value').text()).toBe('0')
  })

  it('Key 概览计数取自 stats.keySummary，不再为概览拉 500 条列表', async () => {
    // Arrange：后端聚合返回全量口径（列表端点 pageSize 上限是 100）
    getAgentKeyStatsApi.mockResolvedValue({
      totalCalls: 0,
      requests7d: 0,
      keySummary: { total: 5, enabled: 3, rateLimited: 1, kbScoped: 2, kbCount: 4, allKbs: false }
    })

    // Act
    const wrapper = await mountKeys()

    // Assert：第一张卡 = 已启用密钥，第三张卡 = 可访问知识库数
    const cards = wrapper.findAll('.metric-card')
    expect(cards[0].find('.metric-value').text()).toBe('3')
    expect(cards[2].find('.metric-value').text()).toBe('4')
    expect(queryAgentKeysApi.mock.calls.some(([params]) => params && params.pageSize === 500)).toBe(false)
  })
})

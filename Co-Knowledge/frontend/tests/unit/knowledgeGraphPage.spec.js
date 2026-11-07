// @vitest-environment jsdom
// ↑ 组件测试：要 DOM + 真 router（onMounted 的 /kbase/ais 闸门会 router.replace）
import { vi } from 'vitest'
import { mountWithPlugins, DEFAULT_ROUTES, flush, textOf, expectNoI18nMisses } from './helpers/mount'

// 图谱知识库独立页。
// 这个 spec 钉三件「错了很安静」的事：
//   1) 页骨架（.aip-kbase 根 + 「知识库」页标题）—— `.aip-kbase` 是 sync/kb.less 的
//      样式作用域钥匙，少一行图谱列表就静默丢整套样式；
//   2) provide('kbaseActiveTab') 常量 —— 子列表靠它判断「图谱面可见」，喂错值
//      （或干脆不 provide）自动刷新会静默不跑；
//   3) AIS/V7 闸门 —— ais=true 或检查失败都要挪回文档知识库（fail-closed 语义）。
//
// 子组件 knowledgeGraphtab 换成探针桩（渲染函数，不用字符串模板 —— 本仓 vitest 没有
// 装运行时编译器）：它自己会拉起两张真列表（十几条接口调用），与本页的三条断言无关；
// 桩同时把 inject 到的外层页签状态渲染出来，供第 2 条断言。

vi.mock('@/features/knowledge-base/api/kbaseApi.js', () => ({ checkAISEnvironmentApi: vi.fn() }))
vi.mock('@/features/graph/GraphTabs.vue', async () => {
  const { h, inject } = await import('vue')
  return {
    default: {
      name: 'KnowledgeGraphtabProbe',
      setup () {
        const outerTab = inject('kbaseActiveTab', null)
        return () => h('div', { class: 'knowledge-graph-tab-container' }, [
          h('span', { class: 'probe-outer-tab' }, outerTab ? String(outerTab.value) : '')
        ])
      }
    }
  }
})

import { checkAISEnvironmentApi } from '@/features/knowledge-base/api/kbaseApi.js'
import KnowledgeGraphPage from '@/pages/graph/GraphListPage.vue'

const aisApi = vi.mocked(checkAISEnvironmentApi)

async function mountPage () {
  return mountWithPlugins(KnowledgeGraphPage, { route: '/graph', routes: DEFAULT_ROUTES })
}

describe('KnowledgeGraphPage（图谱知识库独立页）', () => {
  beforeEach(() => {
    // 默认给「非 AIS」：绝大多数用例只想验证页面本身
    aisApi.mockReset()
    aisApi.mockResolvedValue({ ais: false })
  })

  it('渲染页骨架：原型 .page 壳 + 「图谱知识库」页标题 + 图谱子页签容器', async () => {
    // Act
    const wrapper = await mountPage()
    await flush()

    // Assert：页面根是 .page；--rs-* 令牌由 body.prototype-ui 提供。
    expect(wrapper.find('.page.management-page.knowledge-page').exists()).toBe(true)
    expect(textOf(wrapper.find('.page-title h1'))).toBe('图谱知识库')
    expect(wrapper.find('.knowledge-graph-tab-container').exists()).toBe(true)
    expectNoI18nMisses(wrapper)
  })

  it('给子组件喂的外层页签是常量 knowledgeGraph（子列表的可见性闸门）', async () => {
    // Act
    const wrapper = await mountPage()
    await flush()

    // Assert：喂错值或不 provide，knowledgeGraph.vue 的 isSurfaceVisible 会让自动刷新静默不跑
    expect(textOf(wrapper.find('.probe-outer-tab'))).toBe('knowledgeGraph')
  })

  it('非 AIS 环境（ais:false）→ 留在本页', async () => {
    // Act
    const wrapper = await mountPage()
    await flush()

    // Assert
    expect(wrapper.router.currentRoute.value.path).toBe('/graph')
  })

  it('AIS/V7 环境（ais:true）→ 重定向回文档知识库', async () => {
    // Arrange：AIS/V7 环境必须隐藏图谱知识库（/kbase/ais 判定）
    aisApi.mockResolvedValue({ ais: true })

    // Act
    const wrapper = await mountPage()
    await flush()

    // Assert
    expect(wrapper.router.currentRoute.value.path).toBe('/knowledge')
  })

  it('环境检查失败 → 同样不放行（fail-closed：失败时图谱页签保持隐藏）', async () => {
    // Arrange
    aisApi.mockRejectedValue(new Error('network down'))

    // Act
    const wrapper = await mountPage()
    await flush()

    // Assert
    expect(wrapper.router.currentRoute.value.path).toBe('/knowledge')
  })
})

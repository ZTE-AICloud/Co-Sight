// @vitest-environment jsdom
import { vi } from 'vitest'
import { mountWithPlugins, flush, textOf, expectNoI18nMisses } from './helpers/mount'

// 图谱知识库页的容器（知识图谱 / 知识图谱模版）。
//
// **没有页签头**（不用 el-tabs + CSS 隐藏）。
// 两个列表二选一渲染：默认图谱列表；`?subTab=knowledgeGraphTemplate` 时渲染
// 模版列表并显示顶部返回链接。入口仍在工具条「更多操作 → 知识图谱模版」。
//
// 子列表换成探针桩：它们会拉起两张真列表（十几条接口调用），与本文件断言无关。

vi.mock('@/features/graph/GraphList.vue', async () => {
  const { h, inject } = await import('vue')
  return {
    default: {
      name: 'KnowledgeGraphProbe',
      setup () {
        const tab = inject('activeTabName', null)
        return () => h('div', { class: 'probe-graph-list' }, tab ? String(tab.value) : '')
      }
    }
  }
})
vi.mock('@/features/graph/GraphTemplateList.vue', async () => {
  const { h } = await import('vue')
  return {
    default: {
      name: 'KnowledgeGraphTemplateProbe',
      setup () {
        return () => h('div', { class: 'probe-template-list' }, 'template')
      }
    }
  }
})

import KnowledgeGraphtab from '@/features/graph/GraphTabs.vue'

async function mountTabs (route = '/graph') {
  return mountWithPlugins(KnowledgeGraphtab, { route })
}

/** 组件内部的 subTab 同步有 50/100/300ms 的三重延迟兜底，等它跑完。 */
async function settleRoute () {
  await new Promise(resolve => setTimeout(resolve, 400))
  await flush()
}

describe('knowledgeGraphtab（图谱知识库容器）', () => {
  it('不再渲染页签头，默认只挂图谱列表', async () => {
    // Act
    const wrapper = await mountTabs()
    await settleRoute()

    // Assert
    expect(wrapper.find('.el-tabs').exists()).toBe(false)
    expect(wrapper.find('.el-tabs__item').exists()).toBe(false)
    expect(wrapper.find('.probe-graph-list').exists()).toBe(true)
    expect(wrapper.find('.probe-template-list').exists()).toBe(false)
    expectNoI18nMisses(wrapper)
  })

  it('把当前页签名 provide 给子列表（初值 knowledgeGraph）', async () => {
    // Act
    const wrapper = await mountTabs()
    await settleRoute()

    // Assert：GraphList.vue 的 isSurfaceVisible 靠它判断「图谱面可见」，
    // 喂错值（或不 provide）自动刷新会静默不跑
    expect(textOf(wrapper.find('.probe-graph-list'))).toBe('knowledgeGraph')
  })

  it('subTab=knowledgeGraphTemplate：只挂模版列表并显示返回链接', async () => {
    // Act
    const wrapper = await mountTabs('/graph?subTab=knowledgeGraphTemplate')
    await settleRoute()

    // Assert
    expect(wrapper.find('.probe-graph-list').exists()).toBe(false)
    expect(wrapper.find('.probe-template-list').exists()).toBe(true)
    const back = wrapper.find('.kg-template-back')
    expect(back.exists()).toBe(true)
    expect(textOf(back)).toContain('知识图谱')
    expectNoI18nMisses(wrapper)
  })
})

// @vitest-environment jsdom
// 组件测试：el-dropdown 需要 DOM；静心历史面板的置顶 / 菜单命令 / 搜索都是可见契约。
import { mountWithPlugins, expectNoI18nMisses } from './helpers/mount'
import { ElDropdown, ElDropdownMenu, ElDropdownItem } from 'element-plus/es/components/dropdown/index'

import ChatHistoryPanel from '@/features/chat/components/ChatHistoryPanel.vue'

const REAL_EP = { components: { ElDropdown, ElDropdownMenu, ElDropdownItem } }

function historyOf (overrides = {}) {
  return {
    conversationId: 'conv-1',
    savedAt: new Date('2026-10-25T10:20:00+08:00').getTime(),
    title: '你好',
    messageCount: 2,
    pinned: false,
    ...overrides
  }
}

async function mountPanel (props = {}) {
  return mountWithPlugins(ChatHistoryPanel, {
    props: {
      histories: [historyOf()],
      total: 1,
      activeId: 'conv-1',
      ...props
    },
    global: REAL_EP
  })
}

async function openSessionMenu (wrapper) {
  await wrapper.find('.history-actions button').trigger('click')
  await wrapper.flush()
}

function renderedItems () {
  return Array.from(document.querySelectorAll('.el-dropdown-menu__item'))
}

describe('ChatHistoryPanel（0.1.7 历史会话）', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('渲染置顶标记与当前会话高亮，且没有缺词条', async () => {
    const wrapper = await mountPanel({
      histories: [
        historyOf({ conversationId: 'conv-pin', title: '置顶会话', pinned: true }),
        historyOf({ conversationId: 'conv-2', title: '普通会话' })
      ],
      total: 2,
      activeId: 'conv-2'
    })

    expect(wrapper.find('.history-pin').text()).toBe('置顶')
    expect(wrapper.findAll('.history-item')[1].classes()).toContain('active')
    expectNoI18nMisses(wrapper)
  })

  it('会话菜单抛出 action：命令与整条会话都带给父组件', async () => {
    const wrapper = await mountPanel({ histories: [historyOf({ pinned: true })] })

    await openSessionMenu(wrapper)
    // 页头「历史会话管理」菜单也渲染在 body 里；会话菜单是最后 4 项
    const items = renderedItems().slice(-4)
    expect(items.map(item => item.textContent.trim())).toEqual([
      '取消置顶', '重命名', '导出对话', '删除会话'
    ])

    items[0].dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await wrapper.flush()

    expect(wrapper.emitted('action')?.at(-1)?.[0]).toBe('pin')
    expect(wrapper.emitted('action')?.at(-1)?.[1]).toMatchObject({ conversationId: 'conv-1', pinned: true })
  })

  it('搜索框走 v-model:search，输入即回报给父级', async () => {
    const wrapper = await mountPanel()

    await wrapper.find('input').setValue('向量')

    expect(wrapper.emitted('update:search')?.at(-1)).toEqual(['向量'])
  })

  it('没有会话时区分「还没开始」和「搜索无匹配」', async () => {
    const empty = await mountPanel({ histories: [], total: 0 })
    expect(empty.text()).toContain('还没有历史会话')

    const noMatch = await mountPanel({ histories: [], total: 3, search: '不存在' })
    expect(noMatch.text()).toContain('暂无匹配的会话')
  })
})

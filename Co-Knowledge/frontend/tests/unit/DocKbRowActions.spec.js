// @vitest-environment jsdom
// ↑ 组件测试：必须 jsdom（el-dropdown 的触发器/popper 都要 DOM）
import { expectNoI18nMisses, mountWithPlugins, textOf } from './helpers/mount'
// el-dropdown 一族不在脚手架的 EP 最小集/占位表里，这里用**真组件**覆盖注册 ——
// 断言的既有「菜单项的 disabled 闸门」也有「真点击进不进得来」，占位件做不了。
import { ElDropdown, ElDropdownMenu, ElDropdownItem } from 'element-plus/es/components/dropdown/index'

import DocKbRowActions from '@/features/knowledge-base/components/DocKbRowActions.vue'

// 测的是 `views/kBase/components/DocKbRowActions.vue`（从 views/Kbase.vue 的
// #table-operation 插槽整块搬来）。
//
// 钉两件事：
// 1. **契约**：props 进（row）、events 出（detail / command）—— 载荷必须带整行，
//    命令字面量必须与父组件 `kbaseMoreDropdown` 的键一致（拼错会静默什么都不发生）。
// 2. **状态闸门**：哪些状态下「修改」可点。允许集合来自
//    `@/views/kBase/lib/list-status`（文档知识库与图谱页**有意不一致**的分叉点
//    在下面用例里：状态 6 文档页允许修改、图谱页不允许）。
//    菜单项点不动是 EP 对 disabled 的行为，所以这里直接对**渲染出来的菜单项**
//    派发真点击 —— 闸门写漏时事件会真的抛出来。
//
// 没有「发布」菜单项（无资产中心，发布接口恒 0005；发布闸门 isDocKbPublishEnabled 保留在 lib，
// 由 kbList.status.spec.js 钉住）。

/** 与组件同款写法：真 el-dropdown 一族。 */
const REAL_EP = { components: { ElDropdown, ElDropdownMenu, ElDropdownItem } }

/** 下拉项的模板顺序（查看详情 / 修改 / 删除）。 */
const DETAIL = 0
const MODIFY = 1
const DELETE = 2

/** 一条普通的已发布行（各用例按需覆盖字段）。`action: 'a'` = 没有行级鉴权标记 */
function rowOf (overrides = {}) {
  return { id: 'kb-1', name: '示例库', status: 7, action: 'a', failReason: '', ...overrides }
}

async function mountActions (row) {
  return mountWithPlugins(DocKbRowActions, {
    // 不传 row 的用例要走到组件的 default（空对象）
    props: row === undefined ? {} : { row },
    global: REAL_EP
  })
}

/** 打开下拉菜单：popper 内容挂在 document.body（wrapper.find 够不着）。 */
async function openMenu (wrapper) {
  await wrapper.find('.ux-icon-button').trigger('click')
  await wrapper.flush()
}

/** 已渲染的下拉项 DOM（顺序 = 模板顺序）。 */
function renderedItems () {
  return Array.from(document.querySelectorAll('.el-dropdown-menu__item'))
}

/** 对渲染出来的菜单项派发真点击（会经过 EP 的 disabled 闸门）。 */
function clickRenderedItem (index) {
  const items = renderedItems()
  expect(items.length, '下拉项没渲染出来，先确认 openMenu 是否生效').toBe(3)
  items[index].dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
}

/** 下拉项的组件实例（不用打开菜单即可读到已解析的 props）。 */
function itemComponents (wrapper) {
  return wrapper.findAllComponents(ElDropdownItem)
}

describe('DocKbRowActions（文档知识库列表操作列单元格）', () => {
  afterEach(() => {
    // popper 容器挂在 body 上，逐个用例清掉，免得跨用例串内容
    document.body.innerHTML = ''
  })

  describe('渲染（真 i18n 词条）', () => {
    it('「更多」入口用真文案，没有渲染出 i18n 键名', async () => {
      // Act
      const wrapper = await mountActions(rowOf())

      // Assert
      expect(wrapper.find('.ux-icon-button').attributes('aria-label')).toBe('更多')
      expectNoI18nMisses(wrapper)
    })

    it('下拉菜单按「查看详情 / 修改 / 删除」顺序渲染', async () => {
      // Arrange
      const wrapper = await mountActions(rowOf())

      // Act
      await openMenu(wrapper)

      // Assert
      expect(renderedItems().map(node => textOf(node))).toEqual(['查看详情', '修改', '删除'])
    })
  })

  describe('事件（props 进、events 出）', () => {
    it('点「查看详情」抛出 detail，载荷是整行', async () => {
      // Arrange
      const row = rowOf({ id: 'kb-42' })
      const wrapper = await mountActions(row)

      // Act
      await openMenu(wrapper)
      clickRenderedItem(DETAIL)
      await wrapper.flush()

      // Assert
      expect(wrapper.emitted('detail')).toEqual([[row]])
    })

    it('点菜单项抛出 command：命令名 + 整行（命令字面量与父组件分发表一致）', async () => {
      // Arrange
      const row = rowOf()
      const wrapper = await mountActions(row)

      // Act
      await openMenu(wrapper)
      clickRenderedItem(MODIFY)
      clickRenderedItem(DELETE)
      await wrapper.flush()

      // Assert
      expect(wrapper.emitted('command')).toEqual([
        ['modifyKbase', row],
        ['deleteKbase', row]
      ])
    })

    it('禁用项点不动：真点击不抛 command（闸门写漏时这条会红）', async () => {
      // Arrange：状态 1（解析中）时修改禁用
      const wrapper = await mountActions(rowOf({ status: 1 }))

      // Act
      await openMenu(wrapper)
      clickRenderedItem(MODIFY)
      await wrapper.flush()

      // Assert
      expect(wrapper.emitted('command')).toBeUndefined()
    })
  })

  describe('可用性闸门（行状态 → disabled）', () => {
    // [status, 修改是否禁用, 说明]
    const GATES = [
      [0, false, '待发布'],
      [5, false, '待发布'],
      [6, false, '发布中：文档页允许修改（图谱页不允许，继承来的分叉）'],
      [7, false, '已发布'],
      [8, false, '已发布但有改动'],
      [1, true, '解析中'],
      [2, true, '切分中'],
      [3, true, '生成中'],
      [4, true, '入库中'],
      [101, false, '解析失败'],
      [102, false, '切分失败'],
      [103, false, '生成失败'],
      [104, false, '入库失败'],
      [106, false, '发布失败'],
      [9, true, '认不出的状态：禁用'],
      [100, true, '认不出的状态：禁用'],
      ['12abc', true, '非数字字符串按 toNum → -1'],
      ['7', false, '字符串状态走 toNum 归一'],
      ['6', false, '字符串状态走 toNum 归一']
    ]

    it.each(GATES)('状态 %s → 修改%s禁用（%s）', async (status, modifyDisabled, _why) => {
      // Arrange
      const wrapper = await mountActions(rowOf({ status }))

      // Act
      const items = itemComponents(wrapper)

      // Assert
      expect(items[MODIFY].props('disabled')).toBe(modifyDisabled)
      // 删除只有行级鉴权（action === 'c'）一个闸门
      expect(items[DELETE].props('disabled')).toBe(false)
    })

    it('action === "c"（行级鉴权）时两项全禁用，哪怕状态是已发布', async () => {
      // Arrange
      const wrapper = await mountActions(rowOf({ status: 7, action: 'c' }))

      // Act
      const items = itemComponents(wrapper)

      // Assert
      expect([
        items[MODIFY].props('disabled'),
        items[DELETE].props('disabled')
      ]).toEqual([true, true])
    })

    it('action 是别的值时不锁行（删除可点）', async () => {
      // Arrange
      const wrapper = await mountActions(rowOf({ status: 7, action: 'a' }))

      // Act
      const items = itemComponents(wrapper)

      // Assert
      expect(items[DELETE].props('disabled')).toBe(false)
    })

    it('action 是空字符串时删除项仍被禁用 —— 既有行为，不是本次改造引入', async () => {
      // 原表达式 `kbAuth(row)` 在 action === '' 时返回**空串**，Vue 对「只声明
      // Boolean 类型」的 prop 会把空串转成 true（对齐原生 attribute 语义），于是删除
      // 也被禁用。子组件保留同一条表达式（没有简化成 `action === 'c'`），
      // 这条用例就是那个等价的证据：谁把它"顺手清理"成纯布尔比较，这里会红。
      // Arrange
      const wrapper = await mountActions(rowOf({ status: 7, action: '' }))

      // Act
      const items = itemComponents(wrapper)

      // Assert
      expect(items[DELETE].props('disabled')).toBe(true)
      // 修改经过 `||` 归一，不受这个空串转换影响
      expect(items[MODIFY].props('disabled')).toBe(false)
    })
  })

  describe('缺字段的行', () => {
    it('没传 row（走默认空对象）也能渲染，详情仍可用、删除不锁', async () => {
      // Act
      const wrapper = await mountActions(undefined)

      // Assert
      expect(wrapper.find('.ux-icon-button').attributes('aria-label')).toBe('更多')
      const items = itemComponents(wrapper)
      // ElDropdownItem 的 disabled 是「只声明 Boolean、无 default」：值缺省时读出来是
      // undefined（不是 false），EP 内部按 falsy 处理 —— 所以这里断 falsy 语义
      expect(items[DELETE].props('disabled')).toBeFalsy()
      expect(items[MODIFY].props('disabled')).toBe(true)
    })

    it('row 缺 id/name 不影响渲染（表格给的字段不齐时不炸）', async () => {
      // Act
      const wrapper = await mountActions({ status: 7, action: '' })

      // Assert
      expect(wrapper.find('.ux-icon-button').attributes('aria-label')).toBe('更多')
      expectNoI18nMisses(wrapper)
    })
  })
})

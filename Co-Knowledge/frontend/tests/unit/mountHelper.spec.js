// @vitest-environment jsdom
// ↑ 测的是脚手架本身，但它挂载组件、要用 document，所以同样走 jsdom
import { h, resolveComponent } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElTable } from 'element-plus/es/components/table/index'

import { findByText, mountWithPlugins, textOf, expectNoI18nMisses } from './helpers/mount'

// 这个 spec 测的是 `tests/unit/helpers/mount.js` **脚手架自身**，不是业务组件。
//
// 为什么需要它：`expectNoI18nMisses` / i18n 收集器这类便捷断言，坏起来最典型的形态
// 不是报错，而是**永远通过**（比如 missing 处理器再也没被调用）—— 那样所有依赖它的
// spec 都会静默失去这条保护，且没人会发现。所以这里用探针组件把脚手架的每条承诺
// 都反向验一遍：缺键必须被抓到、有键必须不被抓到、EP 占位件必须真的占位。

/** 造一个用真 i18n 渲染某个键的探针组件。 */
function i18nProbe (key) {
  return {
    name: 'I18nProbe',
    setup () {
      const { t } = useI18n()
      return () => h('span', t(key))
    }
  }
}

/** 造一个用到 EP 重型组件（默认应解析到占位件）的探针组件。 */
const tableProbe = {
  name: 'TableProbe',
  setup () {
    return () => h(resolveComponent('ElTable'), { data: [] }, { default: () => h('span', '表格槽位') })
  }
}

describe('mount.js 脚手架', () => {
  describe('i18n 用真词条', () => {
    it('能解析的键渲染出真文案，且不记缺失', async () => {
      // Act
      const wrapper = await mountWithPlugins(i18nProbe('nav.chat'))

      // Assert：zh 词条
      expect(textOf(wrapper)).toBe('对话测试')
      expect(wrapper.i18nMisses).toEqual([])
      // 不抛 = 这句在「有键」时是安全的（下面一条验证它在缺键时会抛）
      expectNoI18nMisses(wrapper)
    })

    it('拼错的键渲染成键名本身，并被 i18nMisses 记下来（expectNoI18nMisses 必须抛）', async () => {
      // Act
      const wrapper = await mountWithPlugins(i18nProbe('modules.kb.__no_such_key__'))

      // Assert：渲染出键名 —— 这就是「组件里键写错」在页面上的样子
      expect(textOf(wrapper)).toBe('modules.kb.__no_such_key__')
      expect(wrapper.i18nMisses).toEqual(['modules.kb.__no_such_key__'])
      // ⛔ 如果这条不抛，说明收集器坏了，所有 spec 的 expectNoI18nMisses 都是空断言
      expect(() => expectNoI18nMisses(wrapper)).toThrow()
    })

    it('locale: "en" 时渲染英文词条（语言是真实可切的）', async () => {
      // Act
      const wrapper = await mountWithPlugins(i18nProbe('nav.chat'), { locale: 'en' })

      // Assert
      expect(textOf(wrapper)).toBe('Chat Test')
    })
  })

  describe('Element Plus', () => {
    it('重型组件默认解析到占位件（渲染 data-ep-stub，不再往真组件里钻）', async () => {
      // Act
      const wrapper = await mountWithPlugins(tableProbe)

      // Assert
      expect(wrapper.find('[data-ep-stub="el-table"]').exists()).toBe(true)
      expect(textOf(wrapper)).toBe('表格槽位')
    })

    it('spec 可以用 global.components 覆盖成真组件', async () => {
      // Act
      const wrapper = await mountWithPlugins(tableProbe, { global: { components: { ElTable } } })

      // Assert：占位件不再出现，真 el-table 的根节点出现
      expect(wrapper.find('[data-ep-stub="el-table"]').exists()).toBe(false)
      expect(wrapper.find('.el-table').exists()).toBe(true)
    })
  })

  describe('查找/文本工具', () => {
    it('textOf 归一化空白，findByText 按归一化后的文案查找', async () => {
      // Arrange
      const probe = { setup: () => () => h('div', [h('span', '\n   对话\n   测试  ')]) }

      // Act
      const wrapper = await mountWithPlugins(probe)

      // Assert
      expect(textOf(wrapper.find('span'))).toBe('对话 测试')
      expect(findByText(wrapper, '对话 测试')).not.toBeNull()
      expect(findByText(wrapper, '不存在的文案')).toBeNull()
    })
  })
})

// @vitest-environment jsdom
// ↑ 组件测试：必须 jsdom（全局 environment 是 node，见 `vitest.config.mjs`）
import { h } from 'vue'
import { CircleCheck } from '@element-plus/icons-vue'
import { mountWithPlugins, textOf } from './helpers/mount'

import StatusText from '@/shared/ui/StatusText.vue'

// 测的是 `src/shared/ui/StatusText.vue`（替代原 vein-plus `<el-status>`）。
//
// 它自己的逻辑只有两件事，别的都是插槽：
//   ① `resolvedColor`：文字颜色 = 显式 color > 语义 type/status 对应色 > 不干预
//   ② `dotColor`：只有语义 type（info/warning/success/error）才画圆点，
//      带 icon 时不画（否则图标的后面还挂个点）
//
// 这两条一旦写反，页面上的表现是「未发布不再标红」「圆点/图标叠在一起」——
// 都是肉眼不一定当场能发现、但用户能看到的回归，所以这里逐条钉住。

const DOT_SELECTOR = '.status-text__dot'

describe('StatusText', () => {
  describe('语义 type：圆点 + 语义色 + 文案', () => {
    it('type="success" 画圆点、文字与圆点都用 success 色', async () => {
      // Arrange & Act
      const wrapper = await mountWithPlugins(StatusText, {
        props: { type: 'success', text: '已发布' }
      })

      // Assert
      const dot = wrapper.find(DOT_SELECTOR)
      expect(dot.exists()).toBe(true)
      expect(dot.attributes('style')).toContain('var(--el-color-success)')
      expect(wrapper.attributes('style')).toContain('var(--el-color-success)')
      expect(textOf(wrapper)).toBe('已发布')
    })

    it('四种语义 type 都能解析出颜色（info / warning / success / error）', async () => {
      // Arrange：文档注释里给出的调用形态表；漏掉一支就会有一类状态没颜色
      const expected = {
        info: 'var(--el-color-info)',
        warning: 'var(--el-color-warning)',
        success: 'var(--el-color-success)',
        error: 'var(--el-color-danger)'
      }

      for (const [type, color] of Object.entries(expected)) {
        // Act
        const wrapper = await mountWithPlugins(StatusText, { props: { type } })

        // Assert
        expect(wrapper.find(DOT_SELECTOR).attributes('style'), `type=${type}`).toContain(color)
      }
    })

    it('文本也可以走默认插槽（text prop 为空时）', async () => {
      // Act
      const wrapper = await mountWithPlugins(StatusText, {
        props: { type: 'warning' },
        slots: { default: () => '未发布' }
      })

      // Assert
      expect(textOf(wrapper)).toBe('未发布')
    })
  })

    it('type="custom" 只上色、不画圆点', async () => {
      // Arrange：custom 的调用点要么自带图标、要么只用颜色标文字，多一个点是多余的
      const wrapper = await mountWithPlugins(StatusText, {
        props: { type: 'custom', color: 'rgb(1, 2, 3)', text: '自定义' }
      })

      // Assert
      expect(wrapper.find(DOT_SELECTOR).exists()).toBe(false)
      expect(wrapper.attributes('style')).toContain('rgb(1, 2, 3)')
      expect(textOf(wrapper)).toBe('自定义')
    })

    it('显式 color 覆盖语义色（文字用 color，语义只看 type）', async () => {
      // Act
      const wrapper = await mountWithPlugins(StatusText, {
        props: { type: 'success', color: 'rgb(7, 8, 9)', text: '混合' }
      })

      // Assert：两处的优先级是文档写明的契约 —— color 优先于语义 type
      expect(wrapper.attributes('style')).toContain('rgb(7, 8, 9)')
      expect(wrapper.attributes('style')).not.toContain('var(--el-color-success)')
    })

    it('size="small" 加 small 类（列表里的小号形态）', async () => {
      // Act
      const wrapper = await mountWithPlugins(StatusText, { props: { size: 'small', text: 'x' } })

      // Assert
      expect(wrapper.classes()).toContain('status-text--small')
    })

  describe('图标形态', () => {
    it('给了 icon 就渲染 el-icon（<i class="el-icon">）且不再画圆点', async () => {
      // Act
      const wrapper = await mountWithPlugins(StatusText, {
        props: { icon: CircleCheck, type: 'success', text: '已完成' }
      })

      // Assert：tagName 是 'I' 才说明走的是注册进 Element Plus 的 el-icon；
      // 若脚手架没注册 ElIcon，这里会退化成未注册元素 `<el-icon>` 并带上同名 class
      const icon = wrapper.find('.status-text__icon')
      expect(icon.exists()).toBe(true)
      expect(icon.element.tagName).toBe('I')
      expect(wrapper.find(DOT_SELECTOR).exists()).toBe(false)
      expect(textOf(wrapper)).toBe('已完成')
    })

    it('图标 + 显式 color 时图标跟着 color 上色', async () => {
      // Act
      const wrapper = await mountWithPlugins(StatusText, {
        props: { icon: CircleCheck, color: 'rgb(4, 5, 6)' }
      })

      // Assert
      expect(wrapper.attributes('style')).toContain('rgb(4, 5, 6)')
    })
  })

  describe('prefix 插槽', () => {
    it('#prefix 插槽覆盖内置圆点（导入页用它塞主题图标）', async () => {
      // Act
      const wrapper = await mountWithPlugins(StatusText, {
        props: { type: 'success', text: '带前缀' },
        slots: { prefix: () => h('i', { class: 'plx-ico-ok' }) }
      })

      // Assert：插槽给了内容时，内置的圆点不能再渲染
      expect(wrapper.find('.plx-ico-ok').exists()).toBe(true)
      expect(wrapper.find(DOT_SELECTOR).exists()).toBe(false)
      expect(textOf(wrapper)).toBe('带前缀')
    })
  })
})

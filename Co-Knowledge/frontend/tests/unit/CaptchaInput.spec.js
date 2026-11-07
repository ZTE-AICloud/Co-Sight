// @vitest-environment jsdom
// ↑ 组件测试：正在被验证的还有「脚手架注册的 el-input 是真组件」，所以必须 jsdom
import { mountWithPlugins, textOf } from './helpers/mount'

import CaptchaInput from '@/shared/ui/CaptchaInput.vue'

// 测的是 `src/shared/ui/CaptchaInput.vue`（DangerConfirmDialog 的验证码输入格）。
//
// 挑它的原因：它是**真用到 Element Plus** 的小组件（`el-input` 的
// `:model-value` + `@update:model-value` 双向管道），又带 `defineExpose` 出来的
// `validate()` —— 正好把脚手架的两条主路径（注册 EP / 拿组件实例上的方法）都压到。
//
// 它管的事：显示码（`displayCode`）来自 `customRandomCaptcha`，输入经 el-input
// 原样转发成 `update:modelValue` + `input` 两个事件，`validate()` 比对两者。

const CAPTCHA = 'A1B2C3'

describe('CaptchaInput', () => {
  describe('渲染', () => {
    it('customRandomCaptcha 决定显示码，el-input 的 maxlength 跟着它走', async () => {
      // Act
      const wrapper = await mountWithPlugins(CaptchaInput, { props: { customRandomCaptcha: CAPTCHA } })

      // Assert
      expect(textOf(wrapper.find('.captcha-code'))).toBe(CAPTCHA)
      expect(wrapper.find('input').attributes('maxlength')).toBe(String(CAPTCHA.length))
    })

    it('没有验证码时 maxlength 兜底为 6', async () => {
      // Act
      const wrapper = await mountWithPlugins(CaptchaInput)

      // Assert
      expect(textOf(wrapper.find('.captcha-code'))).toBe('')
      expect(wrapper.find('input').attributes('maxlength')).toBe('6')
    })

    it('el-input 是真 Element Plus 组件（渲染出原生 <input> 而不是未注册元素）', async () => {
      // Act
      const wrapper = await mountWithPlugins(CaptchaInput, { props: { customRandomCaptcha: CAPTCHA } })

      // Assert：脚手架没注册 ElInput 时，`<el-input>` 会退化成未知元素
      // `<el-input>`，下面这条会红 —— 这条同时是脚手架的体检项
      const input = wrapper.find('input.el-input__inner')
      expect(input.exists()).toBe(true)
      expect(input.element.tagName).toBe('INPUT')
    })
  })

  describe('交互', () => {
    it('输入会同时发 update:modelValue 与 input（两个监听方都要拿到）', async () => {
      // Arrange
      const wrapper = await mountWithPlugins(CaptchaInput, { props: { customRandomCaptcha: CAPTCHA } })

      // Act：走真实 el-input 的输入管道，不直接调组件方法
      await wrapper.find('input').setValue('A1')

      // Assert：只发一个事件的话，父组件的 v-model 或 @input 里会有一边收不到
      expect(wrapper.emitted('update:modelValue')).toEqual([['A1']])
      expect(wrapper.emitted('input')).toEqual([['A1']])
    })
  })

  describe('displayCode 的更新规则', () => {
    it('customRandomCaptcha 变化时显示码跟着变', async () => {
      // Arrange
      const wrapper = await mountWithPlugins(CaptchaInput, { props: { customRandomCaptcha: 'AAA' } })

      // Act
      await wrapper.setProps({ customRandomCaptcha: 'BBB' })

      // Assert
      expect(textOf(wrapper.find('.captcha-code'))).toBe('BBB')
    })

    it('传空值**不**清掉已显示的验证码（watch 里的 if (value) 守卫）', async () => {
      // Arrange
      const wrapper = await mountWithPlugins(CaptchaInput, { props: { customRandomCaptcha: 'AAA' } })

      // Act
      await wrapper.setProps({ customRandomCaptcha: '' })

      // Assert：父组件重渲染时临时传空串不该把验证码清空
      expect(textOf(wrapper.find('.captcha-code'))).toBe('AAA')
    })
  })

  describe('defineExpose 的 validate()', () => {
    it('输入与显示码一致时通过，不一致时失败', async () => {
      // Arrange
      const wrapper = await mountWithPlugins(CaptchaInput, { props: { customRandomCaptcha: CAPTCHA } })

      // Act & Assert：不一致
      await wrapper.setProps({ modelValue: 'WRONG' })
      expect(wrapper.vm.validate()).toBe(false)

      // Act & Assert：一致
      await wrapper.setProps({ modelValue: CAPTCHA })
      expect(wrapper.vm.validate()).toBe(true)
    })

    it('modelValue 缺省时不算通过（空串不匹配任何验证码）', async () => {
      // Arrange
      const wrapper = await mountWithPlugins(CaptchaInput, { props: { customRandomCaptcha: CAPTCHA } })

      // Assert：属性声明里的 `modelValue` 默认值必须生效，否则 `undefined === 'A1B2C3'` 之外
      // 还有一条隐藏路径：真值判断写反时这里会变成 true
      expect(wrapper.vm.validate()).toBe(false)
    })
  })
})

import { splitReasoning } from '@/features/chat/lib/reasoning'

// 测的是 `chat/lib/reasoning.ts`（从 ChatTest.vue 拆出来的 `<think>` 拆分逻辑）。
// 三种情况都有真实用例：成对标记 / 只有开标记（流式中途）/ 没有标记，
// 另加「第二段被截断」这条现状钉死（见下）。
describe('splitReasoning', () => {
  describe('given_成对标记_when_拆分_then_思考与正文分开', () => {
    it('把 <think> 内容放 thinking，其余放 text', () => {
      // Arrange
      const raw = '<think>先查知识库</think>最终答案是 42'

      // Act
      const result = splitReasoning(raw)

      // Assert
      expect(result.thinking).toBe('先查知识库')
      expect(result.text).toBe('最终答案是 42')
    })

    it('标记前后的正文都保留在 text 里', () => {
      // Act
      const result = splitReasoning('前面<think>中间</think>后面')

      // Assert
      expect(result.thinking).toBe('中间')
      expect(result.text).toBe('前面后面')
    })

    it('标签大小写不敏感', () => {
      // Act
      const result = splitReasoning('<THINK>大写</Think>正文')

      // Assert
      expect(result.thinking).toBe('大写')
      expect(result.text).toBe('正文')
    })

    it('思考块首尾空白被 trim 掉', () => {
      // Act
      const result = splitReasoning('<think>\n  想了两步  \n</think>\n\n答案  ')

      // Assert
      expect(result.thinking).toBe('想了两步')
      expect(result.text).toBe('答案')
    })
  })

  describe('given_只有开标记（流式中途）_when_拆分_then_全算思考', () => {
    it('思考还没结束时不把半截思考当正文', () => {
      // Arrange：流式下每帧都会调用本函数，这一帧就是「才写了开头」的样子
      const raw = '<think>正在推理，还没写完'

      // Act
      const result = splitReasoning(raw)

      // Assert
      expect(result.thinking).toBe('正在推理，还没写完')
      expect(result.text).toBe('')
    })

    it('开标记后为空也算思考（不是正文）', () => {
      // Act
      const result = splitReasoning('<think>')

      // Assert
      expect(result.thinking).toBe('')
      expect(result.text).toBe('')
    })
  })

  describe('given_没有标记_when_拆分_then_全是正文', () => {
    it('普通答案原样留在 text，thinking 为空', () => {
      // Act
      const result = splitReasoning('这就是全部答案')

      // Assert
      expect(result.thinking).toBe('')
      expect(result.text).toBe('这就是全部答案')
    })

    it('空字符串不报错', () => {
      // Act & Assert
      expect(splitReasoning('')).toEqual({ thinking: '', text: '' })
    })

    it('非字符串入参（脏数据/非文本帧）当作空字符串，不抛异常', () => {
      // Act & Assert
      expect(splitReasoning(undefined)).toEqual({ thinking: '', text: '' })
      expect(splitReasoning(null)).toEqual({ thinking: '', text: '' })
      expect(splitReasoning({ output: 'text' })).toEqual({ thinking: '', text: '' })
    })
  })

  describe('given_第一对之后又被截断_when_拆分_then_只拆第一对（现状钉死）', () => {
    it('第二段未闭合的 <think> 留在正文里可见，不会吞掉后面的判断', () => {
      // Arrange：模型输出了两段思考，第二段没闭合（流式被中断 / 模型抽风）
      const raw = '<think>第一段</think>正文<think>第二段没闭合'

      // Act
      const result = splitReasoning(raw)

      // Assert：只处理第一对；第二对的字面量留在正文里（不是我们想要的排版，
      // 但这是**现状**，改动它需要单独评估，别让它在重构里悄悄变）
      expect(result.thinking).toBe('第一段')
      expect(result.text).toBe('正文<think>第二段没闭合')
    })
  })
})

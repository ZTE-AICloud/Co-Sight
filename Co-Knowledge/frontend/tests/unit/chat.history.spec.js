import {
  CHAT_HISTORY_LIMIT,
  buildChatHistory,
  sessionTitle
} from '@/features/chat/lib/chat-history'

function message (role, text, overrides = {}) {
  return {
    role,
    text,
    thinking: '',
    html: '',
    pending: false,
    stopped: false,
    error: false,
    ...overrides
  }
}

describe('chat-history', () => {
  describe('buildChatHistory', () => {
    it('把用户+助手整理成问答对', () => {
      // Arrange
      const messages = [
        message('user', '第一问'),
        message('assistant', '第一答'),
        message('user', '第二问'),
        message('assistant', '第二答')
      ]

      // Act
      const history = buildChatHistory(messages)

      // Assert
      expect(history).toEqual([
        { question: '第一问', answer: '第一答' },
        { question: '第二问', answer: '第二答' }
      ])
    })

    it('失败气泡不进历史（不把错误文案当上下文）', () => {
      // Arrange
      const messages = [
        message('user', '失败那问'),
        message('assistant', '工作流未发布', { error: true }),
        message('user', '成功那问'),
        message('assistant', '成功答案')
      ]

      // Act
      const history = buildChatHistory(messages)

      // Assert：失败的用户问也被跳过（error 标记在助手那条）
      expect(history).toEqual([
        { question: '成功那问', answer: '成功答案' }
      ])
    })

    it('用户消息自身带 error 时跳过', () => {
      const messages = [message('user', '坏的', { error: true }), message('assistant', '答')]

      expect(buildChatHistory(messages)).toEqual([])
    })

    it('答案缺失（流中断）时保留问句、答案置空', () => {
      // Arrange
      const messages = [
        message('user', '只有问没有答'),
        message('assistant', '', { pending: true })
      ]

      // Act & Assert
      expect(buildChatHistory(messages)).toEqual([
        { question: '只有问没有答', answer: '' }
      ])
    })

    it('只取最近 limit 对', () => {
      const messages = []
      for (let i = 0; i < 12; i++) {
        messages.push(message('user', `问${i}`), message('assistant', `答${i}`))
      }

      const history = buildChatHistory(messages, 3)

      expect(history).toEqual([
        { question: '问9', answer: '答9' },
        { question: '问10', answer: '答10' },
        { question: '问11', answer: '答11' }
      ])
    })

    it('默认上限与后端 default_max_multi_chat_limit 一致', () => {
      expect(CHAT_HISTORY_LIMIT).toBe(8)
    })

    it('limit <= 0 时不带历史', () => {
      const messages = [message('user', '问'), message('assistant', '答')]

      expect(buildChatHistory(messages, 0)).toEqual([])
      expect(buildChatHistory(messages, -1)).toEqual([])
    })
  })

  describe('sessionTitle', () => {
    it('取第一条用户消息', () => {
      expect(sessionTitle([
        message('assistant', '欢迎'),
        message('user', '这是第一个问题')
      ])).toBe('这是第一个问题')
    })

    it('压缩空白并截断', () => {
      const title = sessionTitle([message('user', '第一行\n\n第二行 内容很长很长很长很长很长很长')], 8)

      expect(title).toBe('第一行 第二行…')
    })

    it('没有用户消息时返回空串（视图用默认文案）', () => {
      expect(sessionTitle([message('assistant', '只有回答')])).toBe('')
      expect(sessionTitle([])).toBe('')
    })
  })
})

import { newConversationId } from '@/features/chat/lib/conversation'

// 测的是 `chat/lib/conversation.ts`。conversation_id 是服务端 chat memory 的键（必填），
// 生成得不对（或两次相同）会直接把多轮上下文串错。
describe('newConversationId', () => {
  afterEach(() => {
    // `window` 是本 spec 自己挂的桩，别漏给别的 spec
    delete globalThis.window
  })

  describe('given_有 crypto.getRandomValues_when_生成_then_dlg加32位十六进制', () => {
    it('格式固定为 conv- + 16 字节的 hex（32 个字符）', () => {
      // Arrange
      globalThis.window = { crypto: globalThis.crypto }

      // Act
      const id = newConversationId()

      // Assert
      expect(id).toMatch(/^conv-[0-9a-f]{32}$/)
    })

    it('连着生成 500 个都不重复', () => {
      // Arrange
      globalThis.window = { crypto: globalThis.crypto }
      const seen = new Set()

      // Act
      for (let i = 0; i < 500; i += 1) {
        seen.add(newConversationId())
      }

      // Assert
      expect(seen.size).toBe(500)
    })

    it('只用 getRandomValues，**不碰 randomUUID**（http 部署下它不存在）', () => {
      // Arrange：线上是 http://<ip>/ 部署，crypto.randomUUID 只在 secure context 有，
      // 真调它就会 `undefined is not a function`。这里把 randomUUID 换成会抛错的桩，
      // 一旦实现改回 randomUUID，这条会直接失败。
      const getRandomValues = globalThis.crypto.getRandomValues.bind(globalThis.crypto)
      let randomUuidCalled = false
      globalThis.window = {
        crypto: {
          getRandomValues,
          randomUUID: () => {
            randomUuidCalled = true
            return 'should-not-be-used'
          }
        }
      }

      // Act
      const id = newConversationId()

      // Assert
      expect(randomUuidCalled).toBe(false)
      expect(id).toMatch(/^conv-[0-9a-f]{32}$/)
    })
  })

  describe('given_crypto 不可用_when_生成_then_走时间戳兜底且仍然唯一', () => {
    it('crypto 整个缺失时走兜底分支，格式为 conv-<时间戳36进制>-<随机后缀>', () => {
      // Arrange
      globalThis.window = {}

      // Act
      const id = newConversationId()

      // Assert
      expect(id.startsWith('conv-')).toBe(true)
      const parts = id.split('-')
      expect(parts.length).toBe(3)
      // 时间戳：base36，换算回十进制后应当就是「现在」（允许几秒误差）
      const stamp = parseInt(parts[1], 36)
      expect(stamp).toBeGreaterThan(0)
      expect(Math.abs(Date.now() - stamp)).toBeLessThan(5000)
    })

    it('crypto 对象在但没有 getRandomValues 时也走兜底', () => {
      // Arrange：部分老浏览器只有 crypto 壳子
      globalThis.window = { crypto: {} }

      // Act
      const id = newConversationId()

      // Assert
      expect(id).toMatch(/^conv-[0-9a-z]+-[0-9a-z]{1,8}$/)
    })

    it('兜底分支连着生成 200 个也不重复（同一毫秒内靠随机后缀区分）', () => {
      // Arrange
      globalThis.window = {}
      const seen = new Set()

      // Act
      for (let i = 0; i < 200; i += 1) {
        seen.add(newConversationId())
      }

      // Assert
      expect(seen.size).toBe(200)
    })
  })
})

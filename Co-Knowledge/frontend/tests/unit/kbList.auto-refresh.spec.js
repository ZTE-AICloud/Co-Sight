// 测的是 `views/kBase/composables/useListAutoRefresh.ts`：文档知识库列表页与
// 知识图谱列表页合并出来的自动刷新（定时器 + 用户输入暂停）。
//
// 用假定时器跑，钉的是"生命周期"而不是"某一拍刷了什么"：
//   启动 → 停止 → 再启动 不残留定时器；重复 start 不叠出两个；
//   用户输入中那一拍不发请求、停手 1 秒恢复；dispose 把两个计时器一起清掉。
// 页面各自的闸门（页签可见性/有没有进行中的行）不属于这里，它们以 shouldRefresh 注入。
import {
  useListAutoRefresh,
  AUTO_REFRESH_INTERVAL,
  TYPING_IDLE_MS
} from '@/shared/composables/useListAutoRefresh'

describe('useListAutoRefresh', () => {
  let refreshes
  let shouldRefreshCalls
  let shouldRefreshResult
  let listAutoRefresh

  /** 建一个带默认 10 秒节拍的实例；用例想换节拍再自己覆盖 */
  function createInstance (overrides = {}) {
    return useListAutoRefresh({
      shouldRefresh: () => {
        shouldRefreshCalls.push(1)
        return shouldRefreshResult
      },
      onRefresh: () => {
        refreshes.push(1)
      },
      ...overrides
    })
  }

  beforeEach(() => {
    vi.useFakeTimers()
    refreshes = []
    shouldRefreshCalls = []
    shouldRefreshResult = true
    listAutoRefresh = createInstance()
  })

  afterEach(() => {
    listAutoRefresh.dispose()
    vi.useRealTimers()
  })

  describe('常量（两页同值，改这里等于同时改两页）', () => {
    it('轮询节拍 10 秒、停止输入宽限 1 秒', () => {
      // 钉住：合并前两页各自写着 10000 与 1000，值必须原样保留
      expect(AUTO_REFRESH_INTERVAL).toBe(10000)
      expect(TYPING_IDLE_MS).toBe(1000)
    })
  })

  describe('given_未启动_when_时间流逝_then_不刷新', () => {
    it('不调 start 就不该有任何请求', () => {
      // 钉住：定时器只在 start() 里创建（挂载前/卸载后不发请求）
      vi.advanceTimersByTime(AUTO_REFRESH_INTERVAL * 3)
      expect(refreshes).toHaveLength(0)
      expect(vi.getTimerCount()).toBe(0)
    })
  })

  describe('given_已启动_when_走到节拍_then_刷新一次', () => {
    it('默认节拍：差 1 毫秒不刷，满 10 秒刷一次', () => {
      // 钉住：节拍就是 AUTO_REFRESH_INTERVAL，且一次 tick 只刷新一次
      listAutoRefresh.start()
      vi.advanceTimersByTime(AUTO_REFRESH_INTERVAL - 1)
      expect(refreshes).toHaveLength(0)
      vi.advanceTimersByTime(1)
      expect(refreshes).toHaveLength(1)
    })

    it('闸门为假时跳过这一拍，闸门恢复后立即恢复刷新', () => {
      // 钉住：shouldRefresh 是每一拍的开关（例如列表里没有进行中的行）
      shouldRefreshResult = false
      listAutoRefresh.start()
      vi.advanceTimersByTime(AUTO_REFRESH_INTERVAL * 3)
      expect(refreshes).toHaveLength(0)
      expect(shouldRefreshCalls.length).toBeGreaterThanOrEqual(3)

      shouldRefreshResult = true
      vi.advanceTimersByTime(AUTO_REFRESH_INTERVAL)
      expect(refreshes).toHaveLength(1)
    })
  })

  describe('用户输入暂停', () => {
    it('输入中那一拍不发请求，停手满 1 秒后恢复', () => {
      // 钉住：用户正在输入时不打断（合并前两页 tick 里的 isUserTyping 判断）
      listAutoRefresh = createInstance({ interval: 500 })
      listAutoRefresh.start()

      vi.advanceTimersByTime(450)
      listAutoRefresh.noteTypingInput() // t=450 开始输入，t=1450 才算停手
      vi.advanceTimersByTime(50) // t=500：这一拍落在输入窗口里
      expect(refreshes).toHaveLength(0)
      vi.advanceTimersByTime(500) // t=1000：仍在窗口里
      expect(refreshes).toHaveLength(0)
      vi.advanceTimersByTime(500) // t=1500：t=1450 已恢复
      expect(refreshes).toHaveLength(1)
    })

    it('输入中连闸门都不查（先拦输入，再查闸门）', () => {
      // 钉住两道判断的顺序：输入中时不惊动 shouldRefresh（页面闸门里有读表格数据的开销）
      listAutoRefresh = createInstance({ interval: 500 })
      listAutoRefresh.start()
      listAutoRefresh.noteTypingInput()
      vi.advanceTimersByTime(500)
      expect(shouldRefreshCalls).toHaveLength(0)
      expect(refreshes).toHaveLength(0)
    })

    it('持续输入时计时器不断重置：最后一次输入后 1 秒才恢复', () => {
      // 钉住：noteTypingInput 每次都清掉上一个计时器重新起表（合并前两页 handleSearchInput 的行为）
      listAutoRefresh.noteTypingInput() // 若计时器不被重置，t=1000 就该恢复
      vi.advanceTimersByTime(800)
      listAutoRefresh.noteTypingInput() // t=800 又输入了一次 → t=1800 才恢复
      vi.advanceTimersByTime(200) // t=1000
      expect(listAutoRefresh.isUserTyping.value).toBe(true)
      vi.advanceTimersByTime(800) // t=1800
      expect(listAutoRefresh.isUserTyping.value).toBe(false)
    })
  })

  describe('生命周期：启动 → 停止 → 再启动', () => {
    it('停止后不再刷新，且定时器被释放', () => {
      // 钉住：stop() 清掉定时器（切到别的页签时不再空转）
      listAutoRefresh.start()
      vi.advanceTimersByTime(AUTO_REFRESH_INTERVAL)
      expect(refreshes).toHaveLength(1)
      expect(vi.getTimerCount()).toBe(1)

      listAutoRefresh.stop()
      expect(vi.getTimerCount()).toBe(0)
      vi.advanceTimersByTime(AUTO_REFRESH_INTERVAL * 3)
      expect(refreshes).toHaveLength(1)
    })

    it('停止 → 再启动后按新节拍继续刷新（不残留旧定时器）', () => {
      // 钉住：start → stop → start 的完整轮回，刷新次数严格等于"新定时器"的次数
      listAutoRefresh.start()
      vi.advanceTimersByTime(AUTO_REFRESH_INTERVAL)
      expect(refreshes).toHaveLength(1)

      listAutoRefresh.stop()
      vi.advanceTimersByTime(AUTO_REFRESH_INTERVAL * 2)
      expect(refreshes).toHaveLength(1)

      listAutoRefresh.start()
      vi.advanceTimersByTime(AUTO_REFRESH_INTERVAL)
      expect(refreshes).toHaveLength(2)
    })

    it('重复 start 不叠出第二个定时器（页签来回切、搜索重启都会重复 start）', () => {
      // 钉住：合并前两页的 start 都是"先 clearInterval 再 setInterval"；
      // 若少清一次，节拍会翻倍，这里用次数和定时器数一起钉
      listAutoRefresh.start()
      listAutoRefresh.start()
      listAutoRefresh.start()
      expect(vi.getTimerCount()).toBe(1)
      vi.advanceTimersByTime(AUTO_REFRESH_INTERVAL)
      expect(refreshes).toHaveLength(1)
    })

    it('stop 可以重复调用、也可以在启动前调用', () => {
      // 钉住：stop/dispose 幂等，不抛错
      expect(() => {
        listAutoRefresh.stop()
        listAutoRefresh.stop()
        listAutoRefresh.start()
        listAutoRefresh.stop()
        listAutoRefresh.stop()
      }).not.toThrow()
      expect(vi.getTimerCount()).toBe(0)
    })
  })

  describe('卸载清理', () => {
    it('dispose 把轮询定时器与输入计时器一起清掉', () => {
      // 钉住：合并前两页 onUnmounted 里是 stopAutoRefresh() + 清 typingTimer 两件事
      listAutoRefresh.start()
      listAutoRefresh.noteTypingInput()
      expect(vi.getTimerCount()).toBe(2)

      listAutoRefresh.dispose()
      expect(vi.getTimerCount()).toBe(0)
      vi.advanceTimersByTime(AUTO_REFRESH_INTERVAL * 3)
      expect(refreshes).toHaveLength(0)
    })

    it('dispose 可以重复调用', () => {
      listAutoRefresh.start()
      listAutoRefresh.dispose()
      expect(() => {
        listAutoRefresh.dispose()
      }).not.toThrow()
      expect(vi.getTimerCount()).toBe(0)
    })
  })
})

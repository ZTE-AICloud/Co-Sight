/**
 * 列表自动刷新（定时器 + 「用户输入中暂停」）：文档知识库列表页与知识图谱列表页
 * 共用的一份实现。
 *
 * 两页共用：同一个 `autoRefreshTimer` 变量、一个 10 秒节拍、
 * 同一个「启动先清旧的、停止要置 null」的生命周期，
 * 以及同一个「用户正在输入就跳过这一拍、停手 1 秒恢复」的输入闸门。
 *
 * 两页真正不同的只有两件事，都以参数注入：
 *   - `shouldRefresh`：这一拍该不该发请求。
 *       文档知识库页：页面在前台 + 列表里还有进行中的行
 *       知识图谱页：所在子页签可见（由页面喂常量）+ 窗口在前台
 *   - `onRefresh`：怎么刷（两页都是"静默"刷新：不挂转圈、不重置分页）
 *
 * 不注册 onUnmounted：清理仍由调用方在自己的 onUnmounted 里调 `dispose()`
 * （两页本来就是显式清理的），这样本模块不依赖组件实例，可直接在 node 环境的
 * vitest 里用假定时器单测（tests/unit/kbList.auto-refresh.spec.js）。
 */
import { ref, type Ref } from 'vue'

/** 轮询节拍（毫秒）：两页同值；文档知识库页的「切回前台补刷」也复用它对齐节拍 */
export const AUTO_REFRESH_INTERVAL = 10000

/** 用户停止输入多久后恢复轮询（毫秒） */
export const TYPING_IDLE_MS = 1000

export interface ListAutoRefreshOptions {
  /**
   * 这一拍是否该发请求：页面自己的可见性/待处理闸门。
   * 「用户正在输入」由本模块在调用它之前先拦掉，闸门里不用重复判断。
   */
  shouldRefresh: () => boolean
  /** 真正刷新时执行：各页自己的静默刷新（不挂转圈、不重置分页） */
  onRefresh: () => void
  /** 轮询节拍，默认 AUTO_REFRESH_INTERVAL */
  interval?: number
}

export interface ListAutoRefresh {
  /** 用户是否正在输入：输入中那一拍不刷新 */
  isUserTyping: Ref<boolean>
  /** 启动轮询；重复调用不会叠出第二个定时器（先清旧的再建新的） */
  start: () => void
  /** 停止轮询并释放定时器；可重复调用 */
  stop: () => void
  /** 用户敲了一下搜索框：标记输入中，并在 TYPING_IDLE_MS 后自动恢复 */
  noteTypingInput: () => void
  /** start + 「用户停止输入」计时器一起清掉（组件卸载时用） */
  dispose: () => void
}

export function useListAutoRefresh (options: ListAutoRefreshOptions): ListAutoRefresh {
  const interval = options.interval ?? AUTO_REFRESH_INTERVAL
  let timer: ReturnType<typeof setInterval> | null = null
  let typingTimer: ReturnType<typeof setTimeout> | null = null
  const isUserTyping = ref(false)

  function start (): void {
    // 重复 start（页签来回切、搜索重启）先清旧的，保证只剩一个定时器
    if (timer) {
      clearInterval(timer)
    }
    timer = setInterval(() => {
      // 用户正在输入：别打断
      if (isUserTyping.value) {
        return
      }
      // 这一拍没有可刷的东西（页面不可见 / 列表本来就是静止的）：不发请求
      if (!options.shouldRefresh()) {
        return
      }
      options.onRefresh()
    }, interval)
  }

  function stop (): void {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  function noteTypingInput (): void {
    isUserTyping.value = true
    // 每次输入都重新起表：停手满 TYPING_IDLE_MS 才恢复
    if (typingTimer) {
      clearTimeout(typingTimer)
    }
    typingTimer = setTimeout(() => {
      isUserTyping.value = false
    }, TYPING_IDLE_MS)
  }

  function dispose (): void {
    stop()
    if (typingTimer) {
      clearTimeout(typingTimer)
      typingTimer = null
    }
  }

  return { isUserTyping, start, stop, noteTypingInput, dispose }
}

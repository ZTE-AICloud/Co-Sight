/**
 * 全局路由加载指示。
 *
 * 为什么需要：路由组件是懒加载的，`beforeEach` 跑完之后浏览器才开始下载目标
 * chunk，下载期间**旧页面保持不动、新页面还没渲染**，界面上没有任何反馈。
 * 窄带链路上最典型的一幕就是「点了登录、提示成功、然后什么都不发生」——
 * 其实是在下 module.kb。这里把「导航进行中」暴露给 App.vue 的顶部进度条。
 *
 * 计数而不是布尔：重定向（`/` → `/login`）会先结束一次导航再开始下一次，
 * 用计数能避免中间那一下闪断。
 *
 * 短延迟 + 最小停留：本地/局域网导航只要几十毫秒，进度条一闪而过比不显示更
 * 让人以为出错，所以先等 SHOW_DELAY；已经开始显示的则至少停留 MIN_VISIBLE。
 */

import { readonly, ref } from 'vue'

const SHOW_DELAY = 120
const MIN_VISIBLE = 320

const pending = ref(false)

let depth = 0
let showTimer = null
let shownAt = 0
let hideTimer = null

function show () {
  if (pending.value) {
    return
  }
  pending.value = true
  shownAt = Date.now()
}

function hide () {
  if (!pending.value) {
    return
  }
  const elapsed = Date.now() - shownAt
  const wait = Math.max(0, MIN_VISIBLE - elapsed)
  hideTimer = setTimeout(() => {
    hideTimer = null
    pending.value = false
  }, wait)
}

function beginNavigation () {
  depth += 1
  if (hideTimer) {
    clearTimeout(hideTimer)
    hideTimer = null
  }
  if (depth === 1 && !pending.value) {
    showTimer = setTimeout(() => {
      showTimer = null
      if (depth > 0) {
        show()
      }
    }, SHOW_DELAY)
  }
}

function endNavigation () {
  if (depth === 0) {
    // onError 与 afterEach 可能对同一次失败各触发一次，这里吞掉多出来的那次。
    return
  }
  depth -= 1
  if (depth > 0) {
    return
  }
  if (showTimer) {
    clearTimeout(showTimer)
    showTimer = null
  }
  hide()
}

/** 导航进行中。只读：写入只发生在 installRouteProgress 注册的钩子里。 */
export const isRoutePending = readonly(pending)

export function installRouteProgress (router) {
  // 首次导航也走同一套计数：App 要到 `router.isReady()` 之后才挂载，所以那一次
  // 的进出在进度条渲染之前就已经配平，用户看不到任何闪烁。
  router.beforeEach(() => {
    beginNavigation()
  })

  router.afterEach(() => {
    endNavigation()
  })

  router.onError(() => {
    endNavigation()
  })
}

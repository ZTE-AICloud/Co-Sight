/**
 * 全局路由加载指示。
 *
 * 为什么需要：路由组件是懒加载的，`beforeEach` 跑完之后浏览器才开始下载目标
 * chunk，下载期间**旧页面保持不动、新页面还没渲染**，界面上没有任何反馈。
 * 窄带链路上最典型的一幕就是「点了登录、提示成功、然后什么都不发生」——
 * 其实是在下 module.kb。这里把「导航进行中」暴露给 App.vue 的顶部进度条。
 *
 * 以「导航目标」而不是计数判断进行中：守卫里返回一个新的位置（未登录访问业务页
 * 被送去 `/login`、登录后从 `/login` 回业务页）时，vue-router 会**换一个目标继续
 * 同一条导航链**重新跑 `beforeEach`，旧目标不会再触发 `afterEach`。按次数增减会
 * 在每次重定向后永久多算一次，进度条一旦显示就再也隐藏不了。
 *
 * 因此始终以「最后一次 `beforeEach` 收到的 to」为准，`afterEach` / `onError` 只有
 * 拿到同一个 to 才结算；被重定向、被新导航取消的旧链路随后触发的回调直接忽略。
 *
 * 短延迟 + 最小停留：本地/局域网导航只要几十毫秒，进度条一闪而过比不显示更
 * 让人以为出错，所以先等 SHOW_DELAY；已经开始显示的则至少停留 MIN_VISIBLE。
 */

import { readonly, ref } from 'vue'

const SHOW_DELAY = 120
const MIN_VISIBLE = 320

const pending = ref(false)

/** 当前导航链的目标位置对象；`null` 表示没有进行中的导航。 */
let activeTo = null
let showTimer = null
let shownAt = 0
let hideTimer = null

function show () {
  if (pending.value || !activeTo) {
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

function beginNavigation (to) {
  activeTo = to
  // 上一次导航刚结束、还在最小停留期内：保持显示，重新计时没有意义。
  if (hideTimer) {
    clearTimeout(hideTimer)
    hideTimer = null
  }
  if (!pending.value && !showTimer) {
    showTimer = setTimeout(() => {
      showTimer = null
      show()
    }, SHOW_DELAY)
  }
}

function endNavigation (to) {
  // 只有当前导航链能结算；`to` 缺省时（拿不到目标位置的错误回调）按当前链路处理。
  if (!activeTo || (to && to !== activeTo)) {
    return
  }
  activeTo = null
  if (showTimer) {
    clearTimeout(showTimer)
    showTimer = null
  }
  hide()
}

/** 导航进行中。只读：写入只发生在 installRouteProgress 注册的钩子里。 */
export const isRoutePending = readonly(pending)

export function installRouteProgress (router) {
  // 首次导航也走同一套流程：App 要到 `router.isReady()` 之后才挂载，所以那一次
  // 的进出在进度条渲染之前就已经结算，用户看不到任何闪烁。
  router.beforeEach(to => {
    beginNavigation(to)
  })

  router.afterEach(to => {
    endNavigation(to)
  })

  router.onError((error, to) => {
    endNavigation(to)
  })
}

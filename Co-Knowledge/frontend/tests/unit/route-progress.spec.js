// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

const Blank = { name: 'BlankView', render: () => null }
const ROUTES = [
  { path: '/knowledge', name: 'knowledge', component: Blank },
  { path: '/flow', name: 'flow', component: Blank },
  { path: '/login', name: 'login', component: Blank }
]

/** 进度条状态是模块级单例：每个用例重新载入一份。 */
async function loadRouteProgress () {
  vi.resetModules()
  return import('@/shared/lib/route-progress')
}

function createTestRouter () {
  return createRouter({ history: createMemoryHistory(), routes: ROUTES })
}

/** 让守卫挂起，用来制造「导航还没结束」的窗口。 */
function pendingGuard () {
  let release
  const guard = () => new Promise(resolve => {
    release = resolve
  })
  return { guard, release: () => release() }
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('route-progress', () => {
  it('导航超过 120ms 才显示，结束后按最小停留时间隐藏', async () => {
    const { installRouteProgress, isRoutePending } = await loadRouteProgress()
    const router = createTestRouter()
    installRouteProgress(router)
    const slow = pendingGuard()
    router.beforeEach(slow.guard)

    const navigation = router.push('/knowledge')
    await vi.advanceTimersByTimeAsync(120)
    expect(isRoutePending.value).toBe(true)

    slow.release()
    await navigation
    await vi.advanceTimersByTimeAsync(400)
    expect(isRoutePending.value).toBe(false)
  })

  it('守卫重定向之后进度条仍会消失', async () => {
    const { installRouteProgress, isRoutePending } = await loadRouteProgress()
    const router = createTestRouter()
    installRouteProgress(router)
    // 与 installAuthGuard 同形：未登录访问业务页，返回 /login 而不是放行。
    router.beforeEach(to => (to.name === 'flow' ? { name: 'login' } : true))

    await router.push('/flow')
    await vi.advanceTimersByTimeAsync(120 + 400)
    expect(isRoutePending.value).toBe(false)
  })

  it('重定向之后普通导航仍能正常显示和隐藏', async () => {
    const { installRouteProgress, isRoutePending } = await loadRouteProgress()
    const router = createTestRouter()
    installRouteProgress(router)
    router.beforeEach(to => (to.name === 'flow' ? { name: 'login' } : true))
    await router.push('/flow')

    const slow = pendingGuard()
    router.beforeEach(slow.guard)
    const navigation = router.push('/knowledge')
    await vi.advanceTimersByTimeAsync(120)
    expect(isRoutePending.value).toBe(true)

    slow.release()
    await navigation
    await vi.advanceTimersByTimeAsync(400)
    expect(isRoutePending.value).toBe(false)
  })

  it('被新导航取消的旧导航晚到 afterEach 不会留下卡住的进度条', async () => {
    const { installRouteProgress, isRoutePending } = await loadRouteProgress()
    const router = createTestRouter()
    installRouteProgress(router)
    const slow = pendingGuard()
    router.beforeEach(to => (to.name === 'knowledge' ? slow.guard() : true))

    const cancelled = router.push('/knowledge')
    await vi.advanceTimersByTimeAsync(120)
    expect(isRoutePending.value).toBe(true)

    await router.push('/flow')
    await vi.advanceTimersByTimeAsync(400)
    expect(isRoutePending.value).toBe(false)

    slow.release()
    await cancelled.catch(() => {})
    await vi.advanceTimersByTimeAsync(120 + 400)
    expect(isRoutePending.value).toBe(false)
  })

  it('守卫抛错时（onError 而非 afterEach）也会结算', async () => {
    const { installRouteProgress, isRoutePending } = await loadRouteProgress()
    const router = createTestRouter()
    installRouteProgress(router)
    const slow = pendingGuard()
    router.beforeEach(slow.guard)
    router.beforeEach(() => {
      throw new Error('guard exploded')
    })

    const navigation = router.push('/knowledge').catch(() => {})
    await vi.advanceTimersByTimeAsync(120)
    expect(isRoutePending.value).toBe(true)

    slow.release()
    await navigation
    await vi.advanceTimersByTimeAsync(400)
    expect(isRoutePending.value).toBe(false)
  })
})

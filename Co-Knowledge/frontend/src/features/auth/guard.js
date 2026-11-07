/**
 * 认证路由守卫。
 *
 * 规则（``AUTH_MODE=local`` 时才生效；none/gateway 完全放行）：
 * - 未登录访问业务页 → ``/login?redirect=<原地址>``；
 * - 已登录访问 ``/login`` → 回 ``redirect`` 或 ``/kb``；
 * - ``mustChangePassword`` → 强制去 ``/change-password``（改完再回原地址）；
 * - ``/auth/status`` 失败 → fail-closed：送到登录页并带 ``unavailable=1``，
 *   由页面显示“认证服务不可用 / 重试”，绝不当作 ``none`` 放行。
 */
import { currentUser, ensureStatus, isAuthEnabled, isAuthenticated } from './session'

/**
 * 只接受站内绝对路径；``//evil.com``、``http://…``、``/login``、``/change-password``
 * 都拒绝，避免开放重定向与登录/改密页自环。
 */
export function safeRedirect (value) {
  if (typeof value !== 'string') {
    return null
  }
  if (!value.startsWith('/') || value.startsWith('//')) {
    return null
  }
  const path = value.split('?')[0].split('#')[0]
  if (path === '/login' || path.startsWith('/login/')) {
    return null
  }
  if (path === '/change-password') {
    return null
  }
  return value
}

function loginLocation (to, extra = {}) {
  return {
    name: 'login',
    query: { redirect: to.fullPath, ...extra }
  }
}

export function installAuthGuard (router) {
  router.beforeEach(async to => {
    try {
      await ensureStatus()
    } catch (error) {
      if (to.name === 'login') {
        return true
      }
      return loginLocation(to, { unavailable: '1' })
    }

    if (!isAuthEnabled.value) {
      return true
    }

    const mustChange = Boolean(currentUser.value?.mustChangePassword)

    if (to.name === 'login') {
      if (!isAuthenticated.value) {
        return true
      }
      const target = safeRedirect(to.query.redirect)
      if (mustChange) {
        return target
          ? { name: 'changePassword', query: { redirect: target } }
          : { name: 'changePassword' }
      }
      return target || { name: 'knowledge' }
    }

    if (to.name === 'changePassword') {
      if (!isAuthenticated.value) {
        return loginLocation(to)
      }
      return true
    }

    if (!isAuthenticated.value) {
      return loginLocation(to)
    }

    if (mustChange) {
      const target = safeRedirect(to.fullPath)
      return target
        ? { name: 'changePassword', query: { redirect: target } }
        : { name: 'changePassword' }
    }

    return true
  })
}

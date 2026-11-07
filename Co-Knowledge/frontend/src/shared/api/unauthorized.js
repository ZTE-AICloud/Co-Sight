/**
 * 401 处理器的注册点。
 *
 * 为什么单独一个模块：``client.js`` 与 ``stream.js`` 都在 ``shared/`` 里，
 * 不能反向 import ``features/auth``。由 ``app/main.js`` 在启动时把
 * ``features/auth/session.js`` 的处理器注册进来。
 *
 * 没有注册处理器时（例如单测、登录前的极早期请求），调用方保留兜底的 toast 行为。
 */

let handler = null

export function setUnauthorizedHandler (fn) {
  handler = typeof fn === 'function' ? fn : null
}

export function hasUnauthorizedHandler () {
  return typeof handler === 'function'
}

export function notifyUnauthorized (error) {
  if (typeof handler === 'function') {
    handler(error)
  }
}

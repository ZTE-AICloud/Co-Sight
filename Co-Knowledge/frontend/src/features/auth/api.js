/**
 * 本地账号接口（对应后端 ``/api/co-knowledge/v1/auth``）。
 *
 * 所有请求都带 ``skipErrorHandler``：登录失败/未登录由页面与会话层自行处理，
 * 不能让 axios 拦截器先弹一条通用 toast，更不能触发 401 重定向循环。
 */
import axiosInstance from '@/shared/api/client'
import { AUTH_BASE } from '@/shared/api/endpoints'

const AUTH_REQUEST = { skipErrorHandler: true }

// `/auth/status` 是每次进入应用都要跑的探针，且**挡在首次渲染之前**（见
// `src/app/main.js` 的 mount 时机）。axios 实例的默认超时是 1 小时（给检索/
// 问答那类长请求用的），探针沿用这个值会让「后端不可达」表现为界面一直停在
// 启动占位上。这里单独压到 15s，让路由守卫按 fail-closed 走到登录页的
// 「认证服务不可用」提示。
const AUTH_STATUS_TIMEOUT = 15000

export function fetchAuthStatus () {
  return axiosInstance.get(`${AUTH_BASE}/status`, { ...AUTH_REQUEST, timeout: AUTH_STATUS_TIMEOUT })
}

export function login (username, password) {
  return axiosInstance.post(`${AUTH_BASE}/login`, { username, password }, AUTH_REQUEST)
}

export function logout () {
  return axiosInstance.post(`${AUTH_BASE}/logout`, null, AUTH_REQUEST)
}

export function fetchMe () {
  return axiosInstance.get(`${AUTH_BASE}/me`, AUTH_REQUEST)
}

export function changePassword (currentPassword, newPassword) {
  return axiosInstance.post(
    `${AUTH_BASE}/password`,
    { currentPassword, newPassword },
    AUTH_REQUEST
  )
}

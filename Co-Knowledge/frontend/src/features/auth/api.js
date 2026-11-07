/**
 * 本地账号接口（对应后端 ``/api/co-knowledge/v1/auth``）。
 *
 * 所有请求都带 ``skipErrorHandler``：登录失败/未登录由页面与会话层自行处理，
 * 不能让 axios 拦截器先弹一条通用 toast，更不能触发 401 重定向循环。
 */
import axiosInstance from '@/shared/api/client'
import { AUTH_BASE } from '@/shared/api/endpoints'

const AUTH_REQUEST = { skipErrorHandler: true }

export function fetchAuthStatus () {
  return axiosInstance.get(`${AUTH_BASE}/status`, AUTH_REQUEST)
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

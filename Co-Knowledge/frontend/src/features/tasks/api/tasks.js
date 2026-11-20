import axios from '@/shared/api/client'
import { KBASE_BASE } from '@/shared/api/endpoints'

const TASKS_BASE = `${KBASE_BASE}/tasks`

/** 分页列表；空字符串不发给后端。 */
export function listTasks (params = {}) {
  const query = {}
  Object.entries(params).forEach(([key, value]) => {
    if (value !== '' && value !== null && value !== undefined) {
      query[key] = value
    }
  })
  return axios.get(TASKS_BASE, { params: query })
}

export function getTask (taskId) {
  return axios.get(`${TASKS_BASE}/${encodeURIComponent(taskId)}`)
}

export function getTaskStats () {
  return axios.get(`${TASKS_BASE}/stats`)
}

/** 按知识库聚合的任务组（树表根行）。 */
export function listTaskGroups (params = {}) {
  const query = {}
  Object.entries(params).forEach(([key, value]) => {
    if (value !== '' && value !== null && value !== undefined) {
      query[key] = value
    }
  })
  return axios.get(`${TASKS_BASE}/groups`, { params: query })
}

/** 取消排队任务；RUNNING 任务只打标记，由 worker 协作中止。 */
export function cancelTask (taskId, reason = '') {
  const body = reason ? { reason } : {}
  return axios.post(`${TASKS_BASE}/${encodeURIComponent(taskId)}/cancel`, body)
}

export function retryTask (taskId) {
  return axios.post(`${TASKS_BASE}/${encodeURIComponent(taskId)}/retry`)
}

export function updateTaskPriority (taskId, priority) {
  return axios.patch(`${TASKS_BASE}/${encodeURIComponent(taskId)}`, { priority })
}

/** 任务管理页的展示映射与格式化（纯函数，便于单测）。 */

export const TASK_TYPES = ['FILE_IMPORT', 'GRAPH_EXTRACT', 'GRAPH_IMPORT']

export const TYPE_KEYS = {
  FILE_IMPORT: 'typeFileImport',
  GRAPH_EXTRACT: 'typeGraphExtract',
  GRAPH_IMPORT: 'typeGraphImport'
}

export const STATUSES = [
  'PENDING', 'RUNNING', 'RETRY', 'COMPLETED',
  'COMPLETED_WITH_ERRORS', 'FAILED', 'CANCELLED'
]

export const STATUS_KEYS = {
  PENDING: 'statusPending',
  RUNNING: 'statusRunning',
  RETRY: 'statusRetry',
  COMPLETED: 'statusCompleted',
  COMPLETED_WITH_ERRORS: 'statusCompletedWithErrors',
  FAILED: 'statusFailed',
  CANCELLED: 'statusCancelled'
}

export const STATUS_TONES = {
  PENDING: 'info',
  RUNNING: 'success',
  RETRY: 'warning',
  COMPLETED: 'success',
  COMPLETED_WITH_ERRORS: 'warning',
  FAILED: 'error',
  CANCELLED: 'info'
}

export const ATTEMPT_KEYS = {
  RUNNING: 'statusRunning',
  COMPLETED: 'statusCompleted',
  COMPLETED_WITH_ERRORS: 'statusCompletedWithErrors',
  FAILED: 'statusFailed',
  CANCELLED: 'statusCancelled',
  LOST: 'statusRetry'
}

export const ATTEMPT_TONES = {
  RUNNING: 'success',
  COMPLETED: 'success',
  COMPLETED_WITH_ERRORS: 'warning',
  FAILED: 'error',
  CANCELLED: 'info',
  LOST: 'warning'
}

export function shortId (id) {
  return String(id || '').slice(0, 12)
}

export function typeLabel (type, t) {
  const key = TYPE_KEYS[type]
  return key ? t(`modules.taskManagement.${key}`) : (type || '—')
}

export function statusLabel (status, t) {
  const key = STATUS_KEYS[status]
  return key ? t(`modules.taskManagement.${key}`) : (status || '—')
}

export function statusTone (status) {
  return STATUS_TONES[status] || 'info'
}

export function attemptLabel (status, t) {
  const key = ATTEMPT_KEYS[status]
  return key ? t(`modules.taskManagement.${key}`) : (status || '—')
}

export function attemptTone (status) {
  return ATTEMPT_TONES[status] || 'info'
}

export function canCancel (row) {
  return ['PENDING', 'RETRY', 'RUNNING'].includes(row?.status)
}

export function canRetry (row) {
  return ['FAILED', 'CANCELLED'].includes(row?.status)
}

export function canPrioritize (row) {
  return ['PENDING', 'RETRY'].includes(row?.status)
}

export function formatDateTime (value) {
  if (!value) {
    return ''
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return String(value)
  }
  const pad = number => String(number).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function formatAge (seconds, emptyLabel) {
  const value = Number(seconds) || 0
  if (value <= 0) {
    return emptyLabel
  }
  if (value < 60) {
    return `${value}s`
  }
  if (value < 3600) {
    return `${Math.floor(value / 60)}m`
  }
  if (value < 86400) {
    return `${Math.floor(value / 3600)}h`
  }
  return `${Math.floor(value / 86400)}d`
}

export function formatDuration (milliseconds) {
  const value = Number(milliseconds)
  if (!Number.isFinite(value) || value < 0) {
    return '—'
  }
  if (value < 1000) {
    return `${value}ms`
  }
  if (value < 60000) {
    return `${(value / 1000).toFixed(1)}s`
  }
  return `${(value / 60000).toFixed(1)}m`
}

export function prettyJson (value) {
  if (value === null || value === undefined || value === '') {
    return '—'
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch (error) {
    return String(value)
  }
}

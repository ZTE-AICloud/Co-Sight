/** 任务管理页的展示映射与格式化（纯函数，便于单测）。 */

export const TASK_TYPES = ['FILE_IMPORT', 'GRAPH_EXTRACT', 'GRAPH_IMPORT', 'T2S_INDEX']

export const TYPE_KEYS = {
  FILE_IMPORT: 'typeFileImport',
  GRAPH_EXTRACT: 'typeGraphExtract',
  GRAPH_IMPORT: 'typeGraphImport',
  T2S_INDEX: 'typeText2sqlIndex'
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

export function formatBytes (value) {
  const size = Number(value)
  if (!Number.isFinite(size) || size < 0) {
    return ''
  }
  if (size < 1024) {
    return `${size} B`
  }
  const units = ['KB', 'MB', 'GB']
  let scaled = size
  let index = -1
  do {
    scaled /= 1024
    index += 1
  } while (scaled >= 1024 && index < units.length - 1)
  return `${scaled.toFixed(1)} ${units[index]}`
}

const STAGE_KEYS = {
  parse: 'stageParse',
  split: 'stageSplit',
  embed: 'stageEmbed'
}

//: 链路顺序。JSONB 会按「短键优先」重排对象键，不能依赖后端写入顺序。
const STAGE_ORDER = ['parse', 'split', 'embed']

export function formatStageTimings (timings, t) {
  if (!timings || typeof timings !== 'object') {
    return ''
  }
  const stages = STAGE_ORDER
    .filter(stage => stage in timings)
    .concat(Object.keys(timings).filter(stage => !STAGE_ORDER.includes(stage)))
  return stages
    .filter(stage => Number.isFinite(Number(timings[stage])))
    .map(stage => {
      const key = STAGE_KEYS[stage]
      const label = key ? t(`modules.taskManagement.${key}`) : stage
      return `${label} ${formatDuration(timings[stage])}`
    })
    .join(' · ')
}

function formatRatio (success, total) {
  if (success === null || success === undefined ||
      total === null || total === undefined) {
    return ''
  }
  return `${Number(success)} / ${Number(total)}`
}

/**
 * 「产出 extra」的结构化摘要。只读已知字段，未知键留给原始 JSON。
 * 返回空数组时不渲染摘要区，避免老任务出现一排空标签。
 */
export function resultFacts (task, t) {
  const extra = task?.extra || {}
  const type = task?.taskType
  const facts = []
  const add = (labelKey, value) => {
    if (value === null || value === undefined || value === '') {
      return
    }
    facts.push({
      label: t(`modules.taskManagement.${labelKey}`),
      value: String(value)
    })
  }

  if (type === 'FILE_IMPORT') {
    add('resultFileName', extra.fileName)
    add('resultFileSize',
      extra.fileSize === undefined ? '' : formatBytes(extra.fileSize))
    add('resultChunks', extra.chunkCount)
    add('resultVectors', extra.vectorCount)
    add('resultIndexDocs', extra.indexDocCount)
    add('resultStageTimings', formatStageTimings(extra.stageTimingsMs, t))
    return facts
  }

  if (type === 'GRAPH_EXTRACT') {
    add('resultFiles', extra.fileCount)
    add('resultEntities', formatRatio(extra.entity_success, extra.entity_total))
    add('resultEdges', formatRatio(extra.edge_success, extra.edge_total))
    add('resultSchema', extra.schemaId)
    add('resultOperator', extra.operatorId)
    add('resultModel', extra.llm)
    add('resultVectorEntities', extra.vector_entities)
    add('resultVectorEdges', extra.vector_edges)
    add('resultVectorChunks', extra.vector_chunks)
    add('resultImportTask', extra.importTaskId)
    add('resultFailedRecords', extra.failedRecordCount)
    return facts
  }

  if (type === 'GRAPH_IMPORT') {
    add('resultEntities', formatRatio(extra.entity_success, extra.entity_total))
    add('resultEdges', formatRatio(extra.edge_success, extra.edge_total))
    add('resultVectorEntities', extra.vector_entities)
    add('resultVectorEdges', extra.vector_edges)
    add('resultVectorChunks', extra.vector_chunks)
    add('resultSkipped', extra.vector_skipped)
    add('resultFailedRecords',
      Array.isArray(extra.failed_records) ? extra.failed_records.length : '')
    add('resultIndexError', extra.index_error)
    return facts
  }

  return facts
}

export const fileLimits = [
  { extensions: ['txt'], maxMB: 5 },
  { extensions: ['xlsx', 'csv', 'html'], maxMB: 10 },
  { extensions: ['pptx'], maxMB: 20 },
  { extensions: ['json'], maxMB: 50 },
  { extensions: ['docx', 'md'], maxMB: 100 },
  { extensions: ['pdf'], maxMB: 150 },
  { extensions: ['zedx'], maxMB: 650 }
]
export const acceptedExtensions = fileLimits.flatMap(group => group.extensions.map(ext => `.${ext}`)).join(',')
export const fileKey = file => `${file.name}:${file.size}:${file.lastModified}`
export function formatFileSize(bytes) {
  if (bytes === 0) {
    return '0 B'
  }
  if (bytes < 1024) {
    return `${bytes} B`
  }
  if (bytes < 1024 ** 2) {
    return `${(bytes / 1024).toFixed(1)} KB`
  }
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}
/**
 * 收集待上传文件并做格式/大小校验。
 *
 * 后三个参数可覆盖：
 * - `limits`：文件大小上限来自 `GET /file/size_limit`，不是写死的 5–650MB；
 * - `maxFiles` / `maxTotalBytes`：同上（后端 `number` 与 nginx 总大小）。
 * - `messages`：英文界面用的文案。缺省为中文，行为不变。
 */
export function collectKnowledgeFiles(existing, incoming, options = {}) {
  const limits = options.limits || fileLimits
  const maxFiles = options.maxFiles ?? 50
  const maxTotalBytes = options.maxTotalBytes ?? 650 * 1024 ** 2
  const messages = {
    format: '不支持此文件格式',
    empty: '文件为空',
    tooLarge: max => `单个文件不能超过 ${max} MB`,
    duplicate: '已在文件列表中',
    tooMany: max => `最多添加 ${max} 个文件`,
    totalTooLarge: max => `文件总大小不能超过 ${max} MB`,
    // 「整批」原因（数量 / 总量超限）合并成一条，不再每个文件刷一行
    batchRejected: (reason, count) => `${reason}（${count} 个文件未添加）`,
    ...options.messages
  }
  const files = [...existing], errors = []
  // 数量 / 总量是整批共用的限制：超过以后每个文件都会失败，逐个列出来
  // 只会得到一屏重复文案。按原因聚合成一条。
  const batchRejected = new Map()
  let total = files.reduce((sum, file) => sum + file.size, 0)
  for (const file of incoming) {
    const extension = file.name.split('.').pop().toLowerCase()
    const rule = limits.find(group => group.extensions.includes(extension))
    let reason = '', batch = false
    if (!file.name.includes('.') || !rule) {
      reason = messages.format
    } else if (file.size === 0) {
      reason = messages.empty
    } else if (file.size > rule.maxMB * 1024 ** 2) {
      reason = messages.tooLarge(rule.maxMB)
    } else if (files.some(item => fileKey(item) === fileKey(file))) {
      reason = messages.duplicate
    } else if (files.length >= maxFiles) {
      reason = messages.tooMany(maxFiles); batch = true
    } else if (total + file.size > maxTotalBytes) {
      reason = messages.totalTooLarge(Math.round(maxTotalBytes / 1024 ** 2)); batch = true
    }
    if (!reason) {
      files.push(file); total += file.size
    } else if (batch) {
      batchRejected.set(reason, (batchRejected.get(reason) || 0) + 1)
    } else {
      errors.push(`${file.name}：${reason}`)
    }
  }
  for (const [reason, count] of batchRejected) {
    errors.push(messages.batchRejected(reason, count))
  }
  return { files, errors }
}

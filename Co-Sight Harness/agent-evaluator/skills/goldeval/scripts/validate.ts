import { readFileSync } from 'fs'

const args = process.argv.slice(2)

let dataset = ''
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--dataset') {
    dataset = args[i + 1] ?? ''
    i++
  }
}

if (!dataset) {
  console.error('ERROR: --dataset <path> is required')
  process.exit(1)
}

let content: string
try {
  content = readFileSync(dataset, 'utf-8')
} catch {
  console.error(`ERROR: 无法读取数据集文件: ${dataset}`)
  process.exit(1)
}

const lines = content.split('\n').filter((line) => line.trim().length > 0)
const errors: string[] = []
const seenIds = new Set<string>()
const duplicateIds: string[] = []

lines.forEach((line, index) => {
  let parsed: unknown
  try {
    parsed = JSON.parse(line)
  } catch {
    errors.push(`第 ${index + 1} 行: 非法 JSON`)
    return
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    errors.push(`第 ${index + 1} 行: 必须是 JSON 对象`)
    return
  }
  const record = parsed as Record<string, unknown>
  const dataId = record.data_id
  if (dataId === undefined || dataId === null || String(dataId).trim() === '') {
    errors.push(`第 ${index + 1} 行: 缺少 data_id`)
  } else if (seenIds.has(String(dataId))) {
    duplicateIds.push(String(dataId))
  } else {
    seenIds.add(String(dataId))
  }
  for (const field of ['input', 'output', 'expected_output']) {
    const value = record[field]
    if (value === undefined || value === null || String(value).trim() === '') {
      errors.push(`第 ${index + 1} 行: 缺少 ${field}`)
    }
  }
})

if (duplicateIds.length > 0) {
  errors.push(`data_id 重复: ${[...new Set(duplicateIds)].join(', ')}`)
}

if (errors.length > 0) {
  console.log(`校验失败: ${dataset}`)
  for (const err of errors) console.log(`- ${err}`)
  process.exit(1)
}

console.log(`校验通过: ${dataset} (${lines.length} 行, data_id 唯一)`)

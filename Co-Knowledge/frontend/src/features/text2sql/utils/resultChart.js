/**
 * 由查询结果推断柱状图（不绑定具体列名）。
 *
 * 规则：
 * - 至少两列、两行；
 * - 找第一个「全为数字」的列作为度量（至少有一个非空数字）；
 * - 找第一个非度量的「非数字」列作为维度；
 * - 时间类维度（month/date/time 等）保持原顺序，其余按度量倒序；
 * - 最多画 50 条，避免大结果把图表撑爆。
 *
 * 标签与单位来自列名映射（指标业务名 / 单位）或列名本身，标题按「维度+度量」
 * 拼接（如「城市支付金额」），与工作区的视觉一致。
 */
const TIME_LIKE = /(month|date|day|time|_at|created|week|year|月份|日期|时间)/i

function isMeasureColumn (rows, index) {
  let hasNumber = false
  for (const row of rows) {
    const value = row[index]
    if (value === null || value === undefined) {
      continue
    }
    if (typeof value !== 'number') {
      return false
    }
    hasNumber = true
  }
  return hasNumber
}

export function buildChart (columns, rows, labels = {}) {
  if (!Array.isArray(columns) || columns.length < 2) {
    return null
  }
  if (!Array.isArray(rows) || rows.length < 2) {
    return null
  }

  const numericIndexes = columns
    .map((_, index) => index)
    .filter(index => isMeasureColumn(rows, index))
  if (!numericIndexes.length) {
    return null
  }
  // 优先选「看起来像度量」的数值列（金额/数量/占比…或指标注册名），
  // 避免把 user_id / 行号这类数值维度当成度量。
  const measure = numericIndexes.find(index =>
    /(amount|pay|gmv|count|users|total|sum|avg|rate|price|revenue|sales|占比|金额|人数|数量)/i
      .test(columns[index]) || labels[columns[index]])
    ?? numericIndexes[0]
  const dimension = columns.findIndex((_, index) => index !== measure
    && rows.some(row => row[index] !== null && row[index] !== undefined
      && typeof row[index] !== 'number'))
  if (dimension < 0) {
    return null
  }

  const points = rows
    .map(row => ({ label: String(row[dimension] ?? ''), value: Number(row[measure]) }))
    .filter(point => Number.isFinite(point.value))
  if (points.length < 2) {
    return null
  }

  const timeLike = TIME_LIKE.test(columns[dimension])
  if (!timeLike) {
    points.sort((a, b) => b.value - a.value)
  }

  const measureLabel = labels[columns[measure]] || columns[measure]
  const dimensionLabel = labels[columns[dimension]] || columns[dimension]
  const unit = measureLabel.includes('/')
    ? measureLabel.split('/').slice(1).join('/').trim()
    : ''
  const measureName = measureLabel.replace(/\s*\/\s*.*$/, '').trim() || measureLabel
  return {
    dimension,
    measure,
    rows: points.slice(0, 50),
    total: points.length,
    title: `${dimensionLabel}${measureName}`,
    subtitle: unit ? `单位：${unit}` : `按${dimensionLabel}展示`,
    sorted: !timeLike
  }
}

/**
 * 准备弹窗「字段与说明」的纯逻辑。
 *
 * 字段的启用状态与业务说明保存在目录表里，准备时通过
 * PATCH /datasources/{id}/columns/{columnId} 落库；这里只负责把表目录
 * 转成可编辑状态、收集相对打开时快照的变化，避免把整库字段都提交一遍。
 */

export function buildColumnState (tables = []) {
  const state = {}
  for (const table of tables) {
    const columns = {}
    for (const column of table.columns || []) {
      columns[column.id] = {
        enabled: column.enabled !== false,
        businessDescription: column.businessDescription || ''
      }
    }
    state[table.name] = columns
  }
  return state
}

export function collectColumnChanges (state = {}, initial = {}, tables = []) {
  const changes = []
  for (const table of tables) {
    const current = state[table.name] || {}
    const before = initial[table.name] || {}
    for (const column of table.columns || []) {
      const next = current[column.id]
      const previous = before[column.id]
      if (!next || !previous) {
        continue
      }
      const enabled = next.enabled !== false
      const description = String(next.businessDescription || '')
      const enabledChanged = enabled !== (previous.enabled !== false)
      const descriptionChanged = description !== String(previous.businessDescription || '')
      if (!enabledChanged && !descriptionChanged) {
        continue
      }
      changes.push({
        id: column.id,
        tableName: table.name,
        columnName: column.name,
        enabled,
        businessDescription: description
      })
    }
  }
  return changes
}

export function countEnabledColumns (state = {}, tables = []) {
  return tables.reduce((total, table) => total + (table.columns || [])
    .filter(column => (state[table.name] || {})[column.id]?.enabled !== false).length, 0)
}

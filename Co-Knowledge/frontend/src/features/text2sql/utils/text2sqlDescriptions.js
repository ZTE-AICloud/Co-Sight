// CSV accepts quoted commas, newlines, escaped quotes and UTF-8 BOM. Validate everything before applying changes.
export function parseDescriptionCSV (text, allowedNames) {
  const rows = []; const row = []; let cell = ''; let quoted = false; let endedQuote = false
  const input = text.replace(/^\uFEFF/, '')
  const pushCell = () => {
    row.push(cell); cell = ''; endedQuote = false
  }
  for (let i = 0; i < input.length; i++) {
    const char = input[i]
    if (quoted) {
      if (char === '"' && input[i + 1] === '"') {
        cell += '"'; i++
      } else if (char === '"') {
        quoted = false; endedQuote = true
      } else {
        cell += char
      }
    } else if (char === '"') {
      if (cell || endedQuote) {
        throw new Error('CSV 引号格式不正确。')
      }
      quoted = true
    } else if (char === ',') {
      pushCell()
    } else if (char === '\r' || char === '\n') {
      if (char === '\r' && input[i + 1] === '\n') {
        i++
      }
      pushCell(); if (row.some(value => value.trim())) {
        rows.push([...row]);
      } row.length = 0
    } else {
      if (endedQuote) {
        throw new Error('CSV 引号后只能有逗号或换行。')
      }
      cell += char
    }
  }
  if (quoted) {
    throw new Error('CSV 中存在未闭合的引号。')
  }
  pushCell(); if (row.some(value => value.trim())) {
    rows.push([...row])
  }
  if (rows[0]?.length !== 2 || rows[0][0].trim() !== 'table_name' || rows[0][1].trim() !== 'description') {
    throw new Error('请使用导出的模板，表头须为 table_name,description。')
  }
  const allowed = new Set(allowedNames); const seen = new Set(); const updates = new Map()
  if (rows.length > 501) {
    throw new Error('一次最多导入 500 张表的说明。')
  }
  for (const values of rows.slice(1)) {
    if (values.length !== 2) {
      throw new Error('每行必须包含表名和说明两列。')
    }
    const name = values[0].trim(); let description = values[1].trim()
    if (!allowed.has(name)) {
      throw new Error(`表 ${name} 不在本次所选范围内，未导入任何修改。`)
    }
    if (seen.has(name)) {
      throw new Error(`表 ${name} 重复，请检查模板。`)
    }
    seen.add(name)
    if (/^'[\s]*[=+\-@]/.test(description)) {
      description = description.slice(1)
    }
    if (description.length > 200) {
      throw new Error(`表 ${name} 的说明超过 200 字。`)
    }
    if (description) {
      updates.set(name, description)
    }
  }
  return Object.fromEntries(updates)
}

export function descriptionCSV (tables, descriptions) {
  const cell = value => {
    let text = String(value || '')
    if (/^[\s]*[=+\-@\t\r]/.test(text)) {
      text = `'${text}`
    }
    return `"${text.replaceAll('"', '""')}"`
  }
  return `\uFEFF${[['table_name', 'description'], ...tables.map(table => [table.name, Object.hasOwn(descriptions, table.name) ? descriptions[table.name] : table.description || ''])].map(row => row.map(cell).join(',')).join('\r\n')}`
}

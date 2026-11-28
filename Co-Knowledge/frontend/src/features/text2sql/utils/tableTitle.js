/**
 * 数据结构列表的行标题：`<表全名> · <业务名称> · N 个字段[ · 视图]`。
 *
 * 扫描来的表（尤其是 `kb_index` 里按文档切分的 `doc_*_chunk` / `doc_*_vector`）
 * 没有业务名称与数据库注释，如果这时把表名再塞进中段，就会渲染成
 * `kb_index.doc_x_chunk · doc_x_chunk · 8 个字段`。中段只在业务名称/注释
 * 确实提供额外信息时出现。
 */
export function tableTitle (table) {
  const name = table?.fullName || table?.name || ''
  const label = table?.businessName || table?.dbComment || ''
  const fields = `${(table?.columns || []).length} 个字段${table?.type && table.type !== 'BASE_TABLE' ? ' · 视图' : ''}`
  const segments = [name]

  if (label && label !== table?.name && label !== name) {
    segments.push(label)
  }
  segments.push(fields)

  return segments.join(' · ')
}

import { demoDate, demoTables, demoRelations, demoValues, demoOrders, demoUsers, demoRegions, exampleQuestions, pipelineStages } from '../demo-data/text2sql.js'

const clone = value => JSON.parse(JSON.stringify(value))
const normalize = text => text.replace(/[\s。？?！!，,；;]/g, '').toLowerCase()
const identifier = text => `"${text.replaceAll('"', '""')}"`

export function resolveExample (question) {
  const value = normalize(question)
  return exampleQuestions.find(item => normalize(item.question) === value)
}

export function demoQueryResult (id) {
  const cutoff = new Date(`${demoDate}T00:00:00Z`)
  cutoff.setUTCDate(cutoff.getUTCDate() - 30)
  const orders = demoOrders.filter(o => o.status === 2 && o.create_time >= cutoff.toISOString().slice(0, 10))
  const city = o => demoUsers.find(u => u.user_id === o.user_id)?.city_id
  const sum = rows => rows.reduce((total, row) => total + row.pay_amount, 0)
  const results = {
    total: { columns: ['gmv'], rows: [[sum(orders)]] },
    xian: { columns: ['gmv'], rows: [[sum(orders.filter(o => city(o) === 1))]] },
    cities: { columns: ['city', 'gmv'], rows: demoRegions.map(r => [r.city_name, sum(orders.filter(o => city(o) === r.city_id))]).sort((a, b) => b[1] - a[1]) },
    users: { columns: ['paid_users'], rows: [[new Set(orders.map(o => o.user_id)).size]] }
  }
  if (id === 'top') {
    return { ...results.cities, rows: results.cities.rows.slice(0, 1), row_count: 1 }
  }
  if (id === 'monthly') {
    const months = new Map()
    demoOrders.filter(o => o.status === 2 && city(o) === 1).forEach(o => {
      const month = `${o.create_time.slice(0, 7)}-01`
      if (!months.has(month)) {
        months.set(month, new Set())
      }
      months.get(month).add(o.user_id)
    })
    const rows = [...months].sort(([a], [b]) => a.localeCompare(b)).map(([month, users]) => [month, users.size])
    return { columns: ['month', 'paid_users'], rows, row_count: rows.length }
  }
  const result = results[id]
  return result ? { ...result, row_count: result.rows.length } : null
}

export function expandDemoRelations (names, depth = 1) {
  const tables = new Set(names)
  for (let hop = 0; hop < depth; hop++) {
    const frontier = new Set(tables)
    demoRelations.forEach(r => {
      if (frontier.has(r.from_table) || frontier.has(r.to_table)) {
        tables.add(r.from_table); tables.add(r.to_table)
      }
    })
  }
  return { tables: [...tables], relations: clone(demoRelations.filter(r => tables.has(r.from_table) && tables.has(r.to_table))) }
}

export function demoSQL (id, schema = 'public') {
  const prefix = `${identifier(schema)}.`
  const from = `${prefix}order_info o`
  const join = `\nJOIN ${prefix}user_info u\n    ON o.user_id = u.user_id\nJOIN ${prefix}region_info r\n    ON u.city_id = r.city_id`
  const where = '\nWHERE o.status = 2\n    AND o.create_time >= CURRENT_DATE - INTERVAL \'30 days\''
  switch (id) {
  case 'total': return `SELECT SUM(o.pay_amount) AS gmv\nFROM ${from}${where};`
  case 'xian': return `SELECT SUM(o.pay_amount) AS gmv\nFROM ${from}${join}${where}\n    AND r.city_name = '西安市';`
  case 'cities': case 'top': return `SELECT\n    r.city_name AS city,\n    SUM(o.pay_amount) AS gmv\nFROM ${from}${join}${where}\nGROUP BY r.city_name\nORDER BY gmv DESC${id === 'top' ? '\nLIMIT 1' : ''};`
  case 'users': return `SELECT COUNT(DISTINCT o.user_id) AS paid_users\nFROM ${from}${where};`
  case 'monthly': return `SELECT\n    DATE_TRUNC('month', o.create_time)::date AS month,\n    COUNT(DISTINCT o.user_id) AS paid_users\nFROM ${from}${join}\nWHERE o.status = 2\n    AND r.city_name = '西安市'\nGROUP BY DATE_TRUNC('month', o.create_time)::date\nORDER BY month;`
  default: return ''
  }
}

const scenarioFailure = {
  unsafe: { code: 'SQL_UNSAFE', stage: 'validation', message: '检测到 DELETE 写入语句。演示规则仅允许 SELECT，已模拟阻止执行。', category: 'SQL Validation Error' },
  multiple: { code: 'SQL_UNSAFE', stage: 'validation', message: '检测到多个 SQL Statement，已模拟阻止执行。', category: 'SQL Validation Error' },
  column: { code: 'SQL_UNKNOWN_COLUMN', stage: 'validation', message: 'unknown column order_info.salary：字段不在本次 Schema Context 中。', category: 'Schema Linking Error' },
  cost: { code: 'SQL_COST_TOO_HIGH', stage: 'explain', message: 'SQL 执行计划成本过高，已模拟阻止执行。', category: 'SQL Validation Error' },
  empty: { code: 'SCHEMA_RETRIEVAL_EMPTY', stage: 'tables', message: '未召回相关 Schema，请尝试使用订单、支付金额或城市等业务词。', category: 'Retrieval Error' },
  model: { code: 'LLM_GENERATE_FAILED', stage: 'llm', message: '模拟模型调用失败。可切换回「跟随问题」重新运行。', category: 'SQL Generation Error' }
}

// A fixture presenter, not a SQL parser or security boundary. All checks/plans are mock data.
export function createDemoResponse (question, source, scenario = 'auto') {
  const example = resolveExample(question)
  if (scenario === 'auto' && /删除|清空|\b(delete|drop|truncate)\b/i.test(question)) {
    scenario = 'unsafe'
  }
  const failure = source.status !== 'indexed'
    ? { code: 'SCHEMA_NOT_INDEXED', stage: 'tables', message: '当前数据源尚未建立索引，请先扫描 Schema 并构建索引。', category: 'Retrieval Error' }
    : scenarioFailure[scenario] || (!example && scenario === 'auto' ? { code: 'DEMO_QUESTION_UNSUPPORTED', stage: 'tables', message: '此原型支持「示例问题」中的六个业务问题。请选择示例体验完整链路。', category: 'Demo Limitation' } : null)
  const id = example?.id || 'cities'
  const multiTable = ['xian', 'cities', 'top', 'monthly'].includes(id)
  const initial = multiTable ? ['order_info', 'region_info'] : ['order_info']
  const expanded = multiTable ? expandDemoRelations(initial) : { tables: initial, relations: [] }
  const tables = expanded.tables.map(name => ({ name, description: demoTables.find(t => t.name === name).description,
    score: initial.includes(name) ? (name === 'order_info' ? 0.96 : 0.91) : null, source: initial.includes(name) ? 'retrieval' : 'relation' }))
  const needed = new Set(['order_info.status', 'order_info.create_time', ...(id === 'users' || id === 'monthly' ? ['order_info.user_id'] : ['order_info.pay_amount']),
    ...(multiTable ? ['order_info.user_id', 'user_info.user_id', 'user_info.city_id', 'region_info.city_id', 'region_info.city_name'] : [])])
  const columns = demoTables.flatMap(t => t.columns.filter(c => needed.has(`${t.name}.${c.name}`)).map(c => ({ table: t.name, ...clone(c), score: c.foreignKey || c.primaryKey ? 0.87 : 0.94 })))
  const values = demoValues.filter(v => v.value === 2 || (['xian', 'monthly'].includes(id) && v.value === '西安市'))
  const generated = scenario === 'unsafe' ? `DELETE FROM ${identifier(source.schema)}.order_info;`
    : scenario === 'multiple' ? `SELECT * FROM ${identifier(source.schema)}.order_info;\nDROP TABLE ${identifier(source.schema)}.order_info;`
      : scenario === 'column' ? `SELECT salary\nFROM ${identifier(source.schema)}.order_info;` : demoSQL(id, source.schema)
  const stopsAt = failure ? pipelineStages.findIndex(s => s.id === failure.stage) : pipelineStages.length - 1
  const reached = stage => pipelineStages.findIndex(s => s.id === stage) <= stopsAt
  const passed = stage => !failure || pipelineStages.findIndex(s => s.id === stage) < stopsAt
  const checks = [
    { label: '单条 SELECT', detail: '拒绝写入、DDL 与多语句', valid: !['unsafe', 'multiple'].includes(scenario) },
    { label: 'Schema 白名单', detail: '表与字段来自本次检索上下文', valid: scenario !== 'column' },
    { label: 'LIMIT Guard', detail: '聚合保留语义，普通查询上限 1,000 行', valid: true },
    { label: '只读连接', detail: `演示账号 ${source.username}`, valid: true }
  ]
  const explain = reached('explain') ? {
    total_cost: scenario === 'cost' ? 186450.5 : multiTable ? 128.64 : 42.18,
    plan_rows: scenario === 'cost' ? 2500000 : demoQueryResult(id).row_count,
    plan_width: 40, node_type: multiTable ? 'Sort' : 'Aggregate',
    max_total_cost: 100000, max_plan_rows: 1000000,
    nodes: multiTable ? [
      { node: 'Sort', detail: 'gmv DESC', rows: 3, cost: 128.64, depth: 0 },
      { node: 'HashAggregate', detail: 'Group Key: r.city_name', rows: 3, cost: 128.61, depth: 1 },
      { node: 'Hash Join', detail: 'u.city_id = r.city_id', rows: 7, cost: 112.4, depth: 2 },
      { node: 'Hash Join', detail: 'o.user_id = u.user_id', rows: 7, cost: 76.2, depth: 3 },
      { node: 'Seq Scan', detail: 'order_info · status = 2 · 最近30天', rows: 7, cost: 28.3, depth: 4 },
      { node: 'Seq Scan', detail: 'user_info', rows: 6, cost: 12.8, depth: 4 },
      { node: 'Seq Scan', detail: 'region_info', rows: 3, cost: 10.3, depth: 3 }
    ] : [
      { node: 'Aggregate', detail: id === 'users' ? 'COUNT(DISTINCT user_id)' : 'SUM(pay_amount)', rows: 1, cost: 42.18, depth: 0 },
      { node: 'Seq Scan', detail: 'order_info · status = 2 · 最近30天', rows: 7, cost: 28.3, depth: 1 }
    ]
  } : null
  if (explain && id === 'xian') {
    explain.nodes = explain.nodes.filter(n => n.node !== 'Sort')
    explain.nodes[0] = { node: 'Aggregate', detail: 'SUM(o.pay_amount) · city_name = 西安市', rows: 1, cost: explain.total_cost, depth: 0 }
  }
  if (explain && id === 'monthly') {
    explain.nodes[0].detail = 'DATE_TRUNC(\'month\', o.create_time)::date'
    explain.nodes[1].detail = 'Group Key: month · COUNT(DISTINCT o.user_id)'
    explain.nodes[4].detail = 'order_info · status = 2 · 不限制最近30天'
    explain.nodes[4].rows = 9
  }
  if (explain && id === 'top') {
    explain.nodes.unshift({ node: 'Limit', detail: 'LIMIT 1', rows: 1, cost: explain.total_cost, depth: 0 })
  }
  // Keep the cost-failure plan internally consistent.
  if (scenario === 'cost' && explain) {
    explain.nodes[0] = { ...explain.nodes[0], rows: explain.plan_rows, cost: explain.total_cost }
  }
  const durations = Object.fromEntries(pipelineStages.map((s, i) => [`${s.id}_ms`, i <= stopsAt ? s.ms : 0]))
  return {
    demo: true, reference_date: demoDate,
    request_id: `demo-${window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36)
      .slice(2)}`}`,
    datasource_id: source.id, datasource_name: source.name, question, scenario,
    retrieval: { tables: reached('columns') ? tables : [], columns: reached('values') ? columns : [], values: reached('relations') ? clone(values) : [], relations: reached('llm') ? expanded.relations : [] },
    sql: { generated: reached('llm') && passed('llm') ? generated : '', final: reached('validation') && passed('validation') ? generated : '' },
    validation: { valid: reached('validation') ? passed('validation') : null, checks: reached('validation') ? checks : [], warnings: [] },
    explain, result: failure ? null : demoQueryResult(id), error: failure ? clone(failure) : null,
    timing: { ...durations, retrieval_ms: durations.tables_ms + durations.columns_ms + durations.values_ms + durations.relations_ms,
      llm_ms: durations.llm_ms, validation_ms: durations.validation_ms, explain_ms: durations.explain_ms, execute_ms: durations.execute_ms,
      total_ms: Object.values(durations).reduce((sum, ms) => sum + ms, 0) },
    usage: reached('llm') && passed('llm') ? { prompt_tokens: multiTable ? 1186 : 642, completion_tokens: multiTable ? 154 : 68, total_tokens: multiTable ? 1340 : 710 } : null,
    stages: pipelineStages.map((s, i) => ({ ...s, status: i > stopsAt ? 'skipped' : failure && i === stopsAt ? 'error' : 'success', ms: i <= stopsAt ? s.ms : 0 }))
  }
}

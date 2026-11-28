import { demoDate, demoTables, demoOrders, demoUsers, exampleQuestions } from '../demo-data/text2sql.js'
import { createDemoResponse, resolveExample } from './text2sql.js'
import { sourceTableNames, sourceTables, tableDescription } from '../demo-data/text2sqlScale.js'

export const tableNames = demoTables.map(table => table.name)
export const defaultSemantics = { amountName: '已支付订单金额', userName: '付费用户数', notes: '', tableDescriptions: {} }
export const columnLabels = { city: '城市', city_name: '城市', gmv: '支付金额 / 元', total_pay_amount: '支付金额 / 元', pay_amount: '支付金额 / 元', paid_amount: '支付金额 / 元', amount: '支付金额 / 元', total_amount: '支付金额 / 元', paid_users: '付费用户数', user_count: '付费用户数', paid_user_count: '付费用户数', month: '月份' }
export const clone = value => JSON.parse(JSON.stringify(value))
const normalized = value => String(value || '').replace(/[\s。？?！!，,；;]/g, '')
  .toLowerCase()
export const requiredTables = id => (['total', 'users'].includes(id) ? ['order_info'] : tableNames)
export const enabledTables = source => source.selectedTables || sourceTableNames(source)
export const sourceStatus = source => (source.enabled === false ? '已停用' : source.status === 'indexed' ? '索引就绪' : source.status === 'scanned' ? '待构建索引' : '待准备')
export const exampleById = id => exampleQuestions.find(item => item.id === id)

export function sourceChanges (previous, values) {
  const connection = ['host', 'port', 'database', 'schema', 'username'].some(key => previous[key] !== values[key]) || !!values.credentialChanged
  return { connection, renamed: previous.name !== values.name, changed: connection || previous.name !== values.name }
}

export function effectiveSemantics (source) {
  return { amountName: source.semantics?.amountName || defaultSemantics.amountName,
    userName: source.semantics?.userName || defaultSemantics.userName, notes: source.semantics?.notes || '',
    tableDescriptions: Object.fromEntries(sourceTables(source).map(table => [table.name, tableDescription(table, source.semantics?.tableDescriptions) || ''])) }
}

export function preparationChanged (source, values) {
  const next = { ...source, ...values }
  const tables = value => JSON.stringify([...enabledTables(value)].sort())
  return tables(source) !== tables(next) || JSON.stringify(effectiveSemantics(source)) !== JSON.stringify(effectiveSemantics(next))
}

export function resolveQuestion (question, previous = null) {
  const q = normalized(question)
  const exact = resolveExample(question)
  if (exact) {
    return { id: exact.id, period: exact.id === 'monthly' ? 'all' : 'recent30', original: question }
  }
  if (/删除|清空|\b(delete|drop|truncate|insert|update)\b/i.test(question)) {
    return { unsafe: true, original: question }
  }
  const dayWindow = q.match(/(?:最近|过去|近)(\d+)天/)
  if ((dayWindow && Number(dayWindow[1]) !== 30) || /利润|毛利|客单价|转化|同比|环比|预测|咸阳|宝鸡|今年|去年|昨天|今天|本周|本月|上月|季度|20\d{2}[-年]|订单数|订单量|多少单|几笔|多少笔|订单最多|订单最少/.test(q)) {
    return { unsupported: true, reason: '此演示暂不支持该指标、城市或时间范围，请选择已有业务问题。' }
  }
  const context = previous?.intent
  const contextual = !!context && /^(只看|仅看|那|再|改为|改成|按月|每月|按城市|按城|各城)/.test(q)
  const xian = /西安/.test(q) || (contextual && ['xian', 'monthly'].includes(context.id))
  const monthly = /每月|按月|每个月|月度/.test(q)
  const amount = /金额|总额|实付|支付额/.test(q)
  const users = /用户|人数|多少人/.test(q)
  const inheritedUsers = contextual && !amount && !users && ['users', 'monthly'].includes(context.id)
  if (/销售额|营收|收入/.test(q) && !/已支付|实付/.test(q)) {
    return { clarify: true, reason: '“销售额”有多种口径，此演示只提供已支付订单金额，是否采用该口径？', choices: [{ label: '按已支付金额查询（不含退款）', id: /城市|各城|每城/.test(q) ? 'cities' : xian ? 'xian' : 'total', period: 'recent30' }] }
  }
  if (monthly && xian && (users || inheritedUsers)) {
    return { id: 'monthly', period: /近30|最近30|近三十|最近三十/.test(q) || (contextual && context.period === 'recent30') ? 'recent30' : 'all', original: question, parentId: contextual ? previous.request_id : null }
  }
  if (monthly && contextual) {
    return { clarify: true, parentId: previous.request_id, reason: inheritedUsers ? '月度演示仅提供西安付费用户数，是否将城市范围缩小到西安？' : '当前月度示例统计“西安付费用户数”，不是支付金额。请选择要继续分析的指标。', choices: inheritedUsers ? [{ label: '西安每月付费用户（最近30天）', id: 'monthly', period: context.period || 'recent30' }, { label: '继续查看全部城市付费用户', id: 'users', period: 'recent30' }] : [{ label: '西安每月付费用户（最近30天）', id: 'monthly', period: context.period || 'recent30' }, { label: '继续查看西安支付金额', id: 'xian', period: 'recent30' }] }
  }
  if (monthly) {
    return { unsupported: true, reason: '月度演示支持西安付费用户数，请选择“西安每月付费用户”。' }
  }
  if (xian && inheritedUsers) {
    if (context.id === 'monthly') {
      return { id: 'monthly', period: context.period, original: question, parentId: previous.request_id }
    }
    return { clarify: true, parentId: previous.request_id, reason: '当前统计的是付费用户数。西安用户示例仅支持每月去重，请确认是否按月展示；月度人数不能直接相加为总人数。', choices: [{ label: '西安每月付费用户（最近30天）', id: 'monthly', period: 'recent30' }, { label: '继续查看全部城市付费用户', id: 'users', period: 'recent30' }] }
  }
  if ((users || inheritedUsers) && /最高|最多|排名第一|排行第一|top1|城市|各城/.test(q)) {
    return { unsupported: true, reason: '城市用户数分组和排行尚未提供，请选择已支付金额排行或整体付费用户数。' }
  }
  if (/最高|最多|排名第一|排行第一|top1/.test(q) && !amount && !contextual) {
    return { clarify: true, reason: '请确认城市排行使用哪个指标。当前演示提供已支付订单金额排行。', choices: [{ label: '按城市已支付金额排行', id: 'top', period: 'recent30' }] }
  }
  if (/最高|最多|排名第一|排行第一|top1/.test(q) && (amount || contextual)) {
    return { id: 'top', period: 'recent30', original: question, parentId: contextual ? previous.request_id : null }
  }
  if (users && /付费|支付|去重/.test(q) && !xian) {
    return { id: 'users', period: 'recent30', original: question }
  }
  if (xian && (amount || contextual)) {
    return { id: 'xian', period: 'recent30', original: question, parentId: contextual ? previous.request_id : null }
  }
  if ((amount && /各城市|每个城市|按城市|城市分别|各城|每城/.test(q)) || (contextual && /城市|各城/.test(q))) {
    return { id: 'cities', period: 'recent30', original: question, parentId: contextual ? previous.request_id : null }
  }
  if (amount && /支付|订单|实付/.test(q) && !/城市|用户/.test(q)) {
    return { id: 'total', period: 'recent30', original: question }
  }
  return { unsupported: true, reason: '此原型支持支付金额、城市分组与排行、付费用户及西安月度用户，尚未接入自由问答模型。' }
}

export function queryExplanation (intent, source) {
  const recent = intent.period !== 'all'
  return {
    metric: ['users', 'monthly'].includes(intent.id) ? (source.semantics?.userName || defaultSemantics.userName) : (source.semantics?.amountName || defaultSemantics.amountName),
    dateRange: recent ? '2026-10-04 至 2026-11-03（含首尾日期）' : '全部演示月份（2026-09 至 2026-11）',
    datePolicy: !recent ? '全部演示月份' : intent.datePolicy === 'fixed' ? '固定本次日期范围' : '每次相对数据基准取最近30天（演示基准固定）',
    timeField: 'order_info.create_time（订单创建时间，演示时区 UTC）',
    filters: `订单状态 = 已支付（status = 2），不含未支付及已退款订单${['xian', 'monthly'].includes(intent.id) ? '；城市 = 西安市' : ''}`,
    calculation: ['users', 'monthly'].includes(intent.id) ? 'COUNT(DISTINCT order_info.user_id)，按用户去重；月度查询每月独立去重。' : 'SUM(order_info.pay_amount)，单位元。',
    attribution: '城市按 user_info.city_id 关联的用户归属地区统计，不代表订单发生地。',
    notes: source.semantics?.notes || '', schemaSyncedAt: source.scannedAt || '', dataAsOf: demoDate,
    version: source.revision || 1
  }
}

export function createWorkspaceResponse (question, source, scenario = 'auto', intent = resolveQuestion(question)) {
  const canonical = exampleById(intent.id)?.question || question
  const result = createDemoResponse(intent.unsafe ? question : canonical, source, scenario)
  result.question = question
  result.createdAt = new Date().toISOString()
  result.source = clone(source)
  result.intent = { id: intent.id || 'cities', period: intent.period || 'recent30', parentId: intent.parentId || null, datePolicy: intent.period === 'all' ? 'all' : intent.datePolicy === 'fixed' ? 'fixed' : 'relative' }
  result.explanation = queryExplanation(result.intent, source)
  if (source.enabled === false) {
    return failResponse(result, 'DATASOURCE_DISABLED', '该数据源已停用，请启用后再查询。', '数据源状态', 'tables')
  }
  const missing = requiredTables(result.intent.id).filter(name => !enabledTables(source).includes(name))
  if (missing.length && !result.error) {
    return failResponse(result, 'SCHEMA_SCOPE_MISSING', `查询需要 ${missing.join('、')}，请在“准备数据”中调整可查询表范围。`, '数据范围', 'tables')
  }
  if (intent.unsupported && scenario === 'auto') {
    return failResponse(result, 'DEMO_QUESTION_UNSUPPORTED', intent.reason, '演示范围', 'tables')
  }
  if (intent.id === 'monthly' && intent.period === 'recent30' && !result.error) {
    const months = new Map()
    for (const order of demoOrders.filter(order => order.status === 2 && order.create_time >= '2026-10-04' && order.create_time <= demoDate && demoUsers.find(user => user.user_id === order.user_id)?.city_id === 1)) {
      const month = `${order.create_time.slice(0, 7)}-01`
      if (!months.has(month)) {
        months.set(month, new Set())
      }
      months.get(month).add(order.user_id)
    }
    result.result = { columns: ['month', 'paid_users'], rows: [...months].sort().map(([month, users]) => [month, users.size]), row_count: months.size }
    result.sql.generated = result.sql.generated.replace('AND r.city_name = \'西安市\'', 'AND r.city_name = \'西安市\'\n    AND o.create_time >= DATE \'2026-10-04\'\n    AND o.create_time < DATE \'2026-11-04\'')
    result.sql.final = result.sql.generated
    if (result.explain) {
      result.explain.plan_rows = months.size
      result.explain.nodes[4].detail = 'order_info · status = 2 · 2026-10-04 至 2026-11-03'
      result.explain.nodes[4].rows = 3
      result.explain.nodes[0].rows = months.size
      result.explain.nodes[1].rows = months.size
    }
  }
  for (const key of ['generated', 'final']) {
    result.sql[key] = result.sql[key].replace('o.create_time >= CURRENT_DATE - INTERVAL \'30 days\'', 'o.create_time >= DATE \'2026-10-04\'\n    AND o.create_time < DATE \'2026-11-04\'')
  }
  for (const table of result.retrieval.tables) {
    table.description = source.semantics?.tableDescriptions?.[table.name] || table.description
  }
  return result
}

export function failResponse (response, code, message, category, stage = 'tables') {
  const index = response.stages.findIndex(item => item.id === stage)
  response.error = { code, message, category, stage }
  response.result = null; response.sql = { generated: '', final: '' }; response.explain = null; response.usage = null
  response.validation = { valid: null, checks: [], warnings: [] }
  response.retrieval = { tables: [], columns: [], relations: [], values: [] }
  response.stages = response.stages.map((item, i) => ({ ...item, status: i > index ? 'skipped' : i === index ? 'error' : 'success', ms: i > index ? 0 : item.ms }))
  response.timing = Object.fromEntries(Object.keys(response.timing).map(key => [key, key === 'total_ms' ? response.stages.reduce((sum, item) => sum + item.ms, 0) : 0]))
  return response
}

export function errorPresentation (error) {
  if (!error) {
    return null
  }
  const options = {
    QUERY_CANCELLED: ['查询已取消', '上一次完成的结果仍可查看。', 'retry', '重新运行', 'info'],
    DEMO_QUESTION_UNSUPPORTED: ['换个问题试试', '当前是限定范围的演示，选择示例即可继续。', 'examples', '选择可运行的问题', 'info'],
    SCHEMA_SCOPE_MISSING: ['需要补充数据表', '调整表范围并重新准备数据后，再运行此问题。', 'prepare', '调整数据范围', 'warning'],
    SCHEMA_NOT_INDEXED: ['数据尚未就绪', '先准备数据，再开始查询。', 'prepare', '准备数据', 'warning'],
    DATASOURCE_DISABLED: ['数据源已停用', '启用数据源后可重新查询，历史结果仍可查看。', 'sources', '管理数据源', 'warning'],
    LLM_GENERATE_FAILED: ['SQL 生成失败', '演示模型未返回结果，可以重试正常场景。', 'retry', '重新生成', 'error'],
    SQL_UNSAFE: ['查询被安全规则拒绝', '演示仅提供只读分析，请改用查询问题。', 'examples', '改用只读问题', 'error'],
    SQL_COST_TOO_HIGH: ['查询成本超过演示阈值', '建议缩小查询范围；可先运行正常示例。', 'examples', '选择较小范围的问题', 'warning'],
    SQL_UNKNOWN_COLUMN: ['字段未匹配', '检查可查询表及业务说明后，重新提问。', 'prepare', '查看数据结构', 'warning'],
    VALUE_NOT_FOUND: ['没有匹配到数据值', '确认名称后重新提问，或在「枚举与指标」中补充别名。', 'quality', '维护枚举与指标', 'warning'],
    VALUE_AMBIGUOUS: ['数据值存在多个匹配', '使用更精确的名称重新提问（运行详情里列出了候选值）。', 'question', '修改问题', 'warning'],
    SCHEMA_RETRIEVAL_EMPTY: ['没有找到相关数据结构', '查看当前表范围，或改用订单、金额、城市等业务词。', 'prepare', '检查数据范围', 'warning']
  }
  const [title, hint, action, label, tone] = options[error.code] || ['查询未完成', '保留当前问题后重试，或查看运行详情。', 'retry', '重试', 'error']
  return { title, hint, action, label, tone }
}

export function resultSummary (response) {
  if (!response?.result) {
    return ''
  }
  const { rows, columns } = response.result
  if (!rows.length) {
    return '当前条件下没有匹配的数据，可以调整条件后再查询。'
  }
  const format = value => Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
  const display = value => {
    if (value === null || value === undefined || value === '') {
      return '—'
    }
    return typeof value === 'number' ? format(value) : String(value)
  }
  if (columns.length === 1 && rows.length === 1) {
    return `${columnLabels[columns[0]] || columns[0]}：${display(rows[0][0])}`
  }
  if (columns.length >= 2 && rows.every(row => typeof row[1] === 'number')) {
    const label = columnLabels[columns[1]] || columns[1]
    const best = rows.reduce((current, row) => (row[1] > current[1] ? row : current), rows[0])
    return `${best[0]} 的 ${label} 最高，为 ${format(best[1])}${rows.length > 1 ? `；共返回 ${rows.length} 行。` : '。'}`
  }
  return `查询返回 ${rows.length} 行 × ${columns.length} 列结果。`
}

// Spreadsheet formula prefixes are neutralized for user-defined labels as well as values.
export function resultCSV (result) {
  const cell = value => {
    let text = String(value ?? '')
    if (typeof value !== 'number' && /^[\s]*[=+\-@\t\r]/.test(text)) {
      text = `'${text}`
    }
    return `"${text.replaceAll('"', '""')}"`
  }
  return `\ufeff${[result.columns.map(column => columnLabels[column] || column), ...result.rows].map(row => row.map(cell).join(',')).join('\r\n')}`
}

import { demoDate, exampleQuestions } from '../demo-data/text2sql.js'
import { enabledTables, effectiveSemantics, requiredTables, resolveQuestion, createWorkspaceResponse } from './text2sqlWorkspace.js'

export const topicDetails = source => ({
  name: source.topic?.name || (source.id === 'text2sql-demo' ? '电商经营分析' : source.name),
  description: source.topic?.description || '分析已支付金额、付费用户与城市分布，核对日期和统计口径。',
  owner: source.topic?.owner || (source.id === 'text2sql-demo' ? '演示维护组（示例）' : '未指定维护人')
})
export const configurationBinding = source => JSON.stringify({
  id: source.id, revision: source.revision || 1,
  connection: [source.host, source.port, source.database, source.schema, source.username],
  tables: [...enabledTables(source)].sort(), semantics: effectiveSemantics(source)
})
export const publicationCurrent = source => source.publication?.binding === configurationBinding(source)
export const queryAvailable = source => source.status === 'indexed' && source.enabled !== false &&
  (!source.requiresPublication || (publicationCurrent(source) && canPublish(source)))
export const qualityCurrent = source => source.qualityReport?.binding === configurationBinding(source)
const validationIds = new Set(['total', 'xian', 'cities', 'top', 'users', 'monthly', 'profit', 'seven-days', 'write', 'ambiguous', 'amount-paraphrase', 'users-paraphrase'])
export const canPublish = source => source.status === 'indexed' && source.enabled !== false && qualityCurrent(source) &&
  Array.isArray(source.qualityReport.cases) && source.qualityReport.cases.length === validationIds.size &&
  new Set(source.qualityReport.cases.map(item => item.id)).size === validationIds.size &&
  source.qualityReport.cases.every(item => item.passed && validationIds.has(item.id)) &&
  source.qualityReport.cases.some(item => item.kind === 'answer' && item.available)
export function publishConfiguration (source, now = new Date().toISOString()) {
  if (!canPublish(source)) {
    throw new Error('请先完成当前配置的演示验证，并至少准备一个可回答的问题。')
  }
  return { revision: source.revision || 1, binding: configurationBinding(source), checkedAt: source.qualityReport.checkedAt, publishedAt: now }
}

// Fixed, independent result expectations for this demo. These are regression checks,
// not a real-model evaluation set or a statement about arbitrary SQL accuracy.
const expectedRows = {
  total: [[299940]], xian: [[153220]], cities: [['西安市', 153220], ['咸阳市', 82320], ['宝鸡市', 64400]],
  top: [['西安市', 153220]], users: [[6]], monthly: [['2026-09-01', 2], ['2026-10-01', 1], ['2026-11-01', 1]]
}
export function evaluateConfiguration (source, now = new Date().toISOString()) {
  const cases = exampleQuestions.map(example => {
    const missing = requiredTables(example.id).filter(name => !enabledTables(source).includes(name))
    const result = createWorkspaceResponse(example.question, source)
    const available = !missing.length && source.enabled !== false && source.status === 'indexed'
    const passed = available ? !result.error && JSON.stringify(result.result?.rows) === JSON.stringify(expectedRows[example.id])
      : !result.result && !!result.error
    return { id: example.id, question: example.question, kind: 'answer', passed, available,
      detail: available ? passed ? '结果与固定样例基准一致' : '结果未匹配样例基准' : missing.length ? `已阻止越过表范围：缺少 ${missing.join('、')}` : '当前数据未准备或已停用' }
  })
  for (const [id, question, expected] of [['profit', '利润是多少？', 'unsupported'], ['seven-days', '最近7天支付金额是多少？', 'unsupported'],
    ['write', '删除所有订单', 'unsafe'], ['ambiguous', '销售额是多少？', 'clarify']]) {
    const intent = resolveQuestion(question)
    cases.push({ id, question, kind: 'boundary', passed: intent[expected] === true, available: false,
      detail: expected === 'clarify' ? '歧义口径先澄清' : expected === 'unsafe' ? '拒绝写入类请求' : '超出演示范围明确拒绝' })
  }
  for (const [id, question, expected] of [['amount-paraphrase', '最近30天实付总额是多少？', 'total'], ['users-paraphrase', '最近30天付费用户有多少人？', 'users']]) {
    const intent = resolveQuestion(question)
    cases.push({ id, question, kind: 'paraphrase', passed: intent.id === expected, available: false, detail: '同义问法保持指标含义' })
  }
  return { binding: configurationBinding(source), revision: source.revision || 1, checkedAt: now, referenceDate: demoDate,
    answerable: cases.filter(item => item.kind === 'answer' && item.available && item.passed).length, cases }
}

export function suggestedFollowups (response) {
  if (!response?.intent) {
    return []
  }
  const { id, period, datePolicy } = response.intent
  const suggestion = (label, nextId, nextPeriod = period) => ({ label,
    question: nextId === 'monthly' && nextPeriod === 'recent30' ? '查询西安最近30天每个月的付费用户数。' : exampleQuestions.find(item => item.id === nextId).question,
    intent: { id: nextId, period: nextPeriod, datePolicy: nextPeriod === 'all' ? 'all' : datePolicy === 'fixed' ? 'fixed' : 'relative', parentId: response.request_id } })
  if (id === 'users') {
    return [suggestion('西安付费用户 · 按月查看', 'monthly', 'recent30')]
  }
  if (id === 'monthly') {
    return [suggestion(period === 'all' ? '只看最近30天' : '查看全部演示月份', 'monthly', period === 'all' ? 'recent30' : 'all')]
  }
  return [id !== 'xian' && suggestion('只看西安支付金额', 'xian'),
    id !== 'cities' && suggestion('比较各城市支付金额', 'cities'),
    id !== 'top' && id !== 'xian' && suggestion('查看金额最高的城市', 'top'),
    id === 'xian' && suggestion('查看全部城市总金额', 'total')].filter(Boolean)
}

export const feedbackStatus = item => ({ open: '待处理', reviewing: '处理中', resolved: '已验证解决' })[item.status] || '待处理'
export const feedbackCategory = category => ({ helpful: '答案有帮助', meaning: '业务口径', sql: 'SQL 问题', data: '数据问题' })[category] || category
export function transitionFeedback (item, status, resolution, source, now = new Date().toISOString()) {
  if (!['open', 'reviewing', 'resolved'].includes(status)) {
    throw new Error('未知反馈状态')
  }
  if (status !== 'open' && !resolution?.trim()) {
    throw new Error('请填写处理说明，告诉提问者问题如何处理。')
  }
  if (status === 'resolved' && (!source || !canPublish(source) || !publicationCurrent(source))) {
    throw new Error('请先验证并发布当前演示配置，再标记为已验证解决。')
  }
  if (status === 'resolved' && source.qualityReport.checkedAt < item.createdAt) {
    throw new Error('这条反馈提交后尚未重新验证，请先核对并运行演示验证。')
  }
  if (status === 'resolved' && item.datasource_id && item.datasource_id !== source.id) {
    throw new Error('反馈必须使用所属数据源的验证记录。')
  }
  if (status === 'resolved' && item.question) {
    const intentId = item.intentId || resolveQuestion(item.question).id
    if (!intentId) {
      throw new Error('这条问题超出可验证的演示范围，请保留处理中并记录处理说明。')
    }
    if (!source.qualityReport.cases.some(entry => entry.id === intentId && entry.available && entry.passed)) {
      throw new Error('当前配置仍不能回答这条问题，请补齐数据范围后再验证。')
    }
  }
  return { ...item, status, resolution: resolution?.trim() || '', updatedAt: now,
    resolvedRevision: status === 'resolved' ? source.revision || 1 : null }
}

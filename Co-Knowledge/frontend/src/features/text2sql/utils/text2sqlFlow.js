import { demoDate, exampleQuestions } from '../demo-data/text2sql.js'
import { createWorkspaceResponse, enabledTables, effectiveSemantics } from './text2sqlWorkspace.js'
import { sourceTables } from '../demo-data/text2sqlScale.js'

export const normalizeDatePolicy = (period, policy) => (period === 'all' ? 'all' : policy === 'fixed' ? 'fixed' : 'relative')
export function queryBinding (question, source, context, datePolicy = 'relative') {
  return JSON.stringify({ question: question.trim(), source: source.id, revision: source.revision || 1, status: source.status, enabled: source.enabled !== false,
    tables: [...enabledTables(source)].sort(), context: context?.request_id || null, datePolicy })
}
export function clarifiedIntent (clarification, choice, binding) {
  if (!clarification || clarification.binding !== binding) {
    return null
  }
  const confirmed = clarification.choices.find(item => item.id === choice.id && item.period === choice.period && item.label === choice.label)
  return confirmed ? { id: confirmed.id, period: confirmed.period, parentId: clarification.parentId || null } : null
}
export function parametersFromIntent (intent = {}) {
  return { metric: ['users', 'monthly'].includes(intent.id) ? 'users' : 'amount', breakdown: ({ cities: 'cities', top: 'top', monthly: 'monthly' })[intent.id] || 'total',
    city: ['xian', 'monthly'].includes(intent.id) ? 'xian' : 'all', period: intent.period === 'all' && intent.id === 'monthly' ? 'all' : 'recent30', datePolicy: normalizeDatePolicy(intent.period, intent.datePolicy) }
}
export function intentFromParameters (values) {
  let id
  if (values.metric === 'amount' && values.period === 'recent30') {
    if (values.breakdown === 'total' && ['all', 'xian'].includes(values.city)) {
      id = values.city === 'xian' ? 'xian' : 'total'
    }
    if (values.city === 'all' && ['cities', 'top'].includes(values.breakdown)) {
      id = values.breakdown
    }
  }
  if (values.metric === 'users' && values.breakdown === 'total' && values.city === 'all' && values.period === 'recent30') {
    id = 'users'
  }
  if (values.metric === 'users' && values.breakdown === 'monthly' && values.city === 'xian' && ['all', 'recent30'].includes(values.period)) {
    id = 'monthly'
  }
  return id ? { id, period: values.period, datePolicy: normalizeDatePolicy(values.period, values.datePolicy) } : null
}
export function questionForIntent (intent) {
  if (intent.id === 'monthly' && intent.period === 'recent30') {
    return '查询西安最近30天每个月的付费用户数。'
  }
  return exampleQuestions.find(item => item.id === intent.id)?.question || ''
}
export function conditionSummary (intent) {
  if (!intent?.id) {
    return null
  }
  return { metric: ['users', 'monthly'].includes(intent.id) ? '付费用户数 · 人 · 去重' : '已支付订单金额 · 元',
    city: ['xian', 'monthly'].includes(intent.id) ? '西安市' : '全部城市',
    breakdown: ({ cities: '按城市分组', top: '城市金额排行', monthly: '按月统计' })[intent.id] || '汇总',
    dates: intent.period === 'all' ? '全部演示月份' : '2026-10-04 至 2026-11-03',
    policy: intent.period === 'all' ? '全部演示月份' : intent.datePolicy === 'fixed' ? '固定本次日期范围' : `随数据基准取最近30天（${demoDate}）` }
}
export function preparationDifference (source, values) {
  const before = new Set(enabledTables(source)); const after = new Set(values.selectedTables)
  const previous = effectiveSemantics(source); const next = effectiveSemantics({ ...source, ...values })
  return { added: [...after].filter(name => !before.has(name)), removed: [...before].filter(name => !after.has(name)),
    settings: ['amountName', 'userName', 'notes'].filter(key => previous[key] !== next[key]),
    descriptions: sourceTables(source).filter(table => previous.tableDescriptions[table.name] !== next.tableDescriptions[table.name])
      .map(table => table.name) }
}
export function exampleCoverage (source) {
  return exampleQuestions.map(example => {
    const response = createWorkspaceResponse(example.question, source)
    return { question: example.question, supported: !!response.result, status: response.result ? '范围支持' : '暂不可用', detail: response.error?.message || `演示返回 ${response.result.row_count} 行` }
  })
}

// This recognizes existing demo templates only. It is not a SQL parser or a security boundary.
function sqlTokens (sql) {
  const tokens = []; let i = 0
  while (i < sql.length) {
    if (/\s/.test(sql[i])) {
      i++; continue
    }
    if (sql.startsWith('--', i)) {
      i = sql.indexOf('\n', i); if (i < 0) {
        break;
      } continue
    }
    if (sql.startsWith('/*', i)) {
      const end = sql.indexOf('*/', i + 2); if (end < 0) {
        return null;
      } i = end + 2; continue
    }
    if (sql[i] === '\'' || sql[i] === '"') {
      const quote = sql[i]; const start = i++; let closed = false
      while (i < sql.length) {
        if (sql[i++] === quote) {
          if (sql[i] === quote) {
            i++;
          } else {
            closed = true; break
          }
        }
      }
      if (!closed) {
        return null
      }
      tokens.push(sql.slice(start, i)); continue
    }
    const word = sql.slice(i).match(/^[a-zA-Z_][a-zA-Z0-9_$]*|^\d+(?:\.\d+)?/)
    if (word) {
      tokens.push(word[0].toLowerCase()); i += word[0].length
    } else {
      tokens.push(sql[i++])
    }
  }
  if (tokens.at(-1) === ';') {
    tokens.pop()
  }
  return tokens.join('\u0001')
}
export function validateDemoSQL (sql, source) {
  if (source.enabled === false || source.status !== 'indexed') {
    return { valid: false, message: '请先启用并准备数据源。' }
  }
  const tokens = sqlTokens(sql)
  if (!tokens) {
    return { valid: false, message: '草稿为空或引号、注释未闭合。' }
  }
  const intents = [...exampleQuestions.map(item => ({ id: item.id, period: item.id === 'monthly' ? 'all' : 'recent30' })), { id: 'monthly', period: 'recent30' }]
  for (const intent of intents) {
    const candidate = createWorkspaceResponse(questionForIntent(intent), source, 'auto', intent)
    if (!candidate.error && sqlTokens(candidate.sql.final) === tokens) {
      return { valid: true, intent, question: questionForIntent(intent), message: '已匹配内置查询模板，可运行对应的演示查询。' }
    }
  }
  return { valid: false, message: '草稿不匹配当前数据范围内的演示模板。请用“调整条件”生成支持的 SQL；任意 SQL 的解析与执行尚未接入。' }
}

/**
 * 知识来源类型：文档知识库 / 图谱知识库 / 数据库。
 *
 * 「知识来源类型」在建流弹窗的第一层：先选类型，模板只展示该类型
 * 能用的那几种（文档 3 种、图谱只有「图谱检索」）。列表页与画布也按同一套
 * 类型给出来源标签，避免「图谱库混在文档库里、直到建完才发现是图谱画布」。
 *
 * 这里只放纯函数与常量：文案走 i18n key，图标由组件按 id 取。
 */
import { KB_OPTION_KEY_HYPHEN } from '@/features/knowledge-base/constants.js'
import { collectOperatorSources } from './flowGeometry'

export const SOURCE_KIND_IDS = ['knowledge', 'graph', 'database']

/**
 * `templates` 是**建流模板**的内部值（与后端 Sequential/Blended/Conditional 一致），
 * 不是显示名。图谱检索复用 Blended：后端按绑定库类型自动选 `Blended_graph` 变体。
 */
const SOURCE_KIND_META = {
  knowledge: {
    id: 'knowledge',
    labelKey: 'modules.kb.dockb',
    shortKey: 'modules.workflow.sourceKindShortKnowledge',
    tone: 'blue',
    templates: ['Blended', 'Sequential', 'Conditional']
  },
  graph: {
    id: 'graph',
    labelKey: 'modules.kb.graphKnowledgeBase',
    shortKey: 'modules.workflow.sourceKindShortGraph',
    tone: 'purple',
    templates: ['Blended']
  },
  database: {
    id: 'database',
    labelKey: 'modules.workflow.sourceKindDatabase',
    shortKey: 'modules.workflow.sourceKindShortDatabase',
    tone: 'cyan',
    templates: ['Conditional']
  }
}

export function sourceKindMeta (id) {
  return SOURCE_KIND_META[id] || SOURCE_KIND_META.knowledge
}

/** 下拉选项的 value 形如 `graph_xxx|#|1`：取 `|#|` 前的表名判断库类型。 */
function kbTableName (name) {
  const value = String(name || '')
  const index = value.indexOf(KB_OPTION_KEY_HYPHEN)
  return index >= 0 ? value.slice(0, index) : value
}

export function isGraphKbName (name) {
  return /^graph_/.test(kbTableName(name))
}

export function isDocumentKbName (name) {
  return /^doc_/.test(kbTableName(name))
}

/**
 * 算子 → 知识来源类型。没有来源概念的算子（融合检索、自定义算子）返回 ''。
 * 归并检索器（FusionRetriever）只是合并上游结果，不直接绑库。
 */
export function sourceKindOfOperator (operator) {
  const id = typeof operator === 'string' ? operator : operator?.operator
  if (!id) {
    return ''
  }
  if (id === 'KnowledgeGraphRetriever' || /GraphRetriever$/.test(id)) {
    return 'graph'
  }
  if (id === 'VectorRetriever' || id === 'KeywordRetriever') {
    return 'knowledge'
  }
  if (/Sql/.test(id)) {
    return 'database'
  }
  return ''
}

/**
 * 选中库与算子类型不符时返回**不匹配的库名**（空数组表示没问题）。
 * 只对能识别的表名（`doc_*` / `graph_*`）下结论；纯库名放行给后端。
 */
export function operatorSourceMismatch (operator, names = collectOperatorSources(operator)) {
  const kind = sourceKindOfOperator(operator)
  if (kind === 'graph') {
    return names.filter(isDocumentKbName)
  }
  if (kind === 'knowledge') {
    return names.filter(isGraphKbName)
  }
  return []
}

/** 列表行 → 来源类型 id 数组；没有绑定信息时按文档知识库处理。 */
export function workflowSourceKinds (row = {}) {
  const kinds = []
  if (row.knowledgeType === 'database') {
    kinds.push('database')
  }
  if (Array.isArray(row.kbPkIds) && row.kbPkIds.length) {
    kinds.push('knowledge')
  }
  if (Array.isArray(row.graphKbPkIds) && row.graphKbPkIds.length) {
    kinds.push('graph')
  }
  if (!kinds.length) {
    kinds.push('knowledge')
  }
  return SOURCE_KIND_IDS.filter(id => kinds.includes(id))
}

/**
 * 列表/详情展示用的「检索类型」：只绑图谱库的工作流显示为「图谱检索」，
 * 其余仍是建流时选的模板（Blended/Sequential/Conditional）。
 */
export function workflowDisplayType (row = {}) {
  if (row.knowledgeType === 'database') {
    return 'database'
  }
  const kinds = workflowSourceKinds(row)
  if (kinds.length === 1 && kinds[0] === 'graph') {
    return 'graph'
  }
  return row.template || ''
}

/**
 * 列表页「检索类型」下拉的判定：按**展示出来的类型**筛，而不是 `row.template`。
 *
 * 只绑图谱库的 Blended 工作流在列表上显示为「图谱检索」，如果按 template 筛，
 * 它会在「混合检索」与「图谱检索」两个选项下同时出现。
 */
export function matchesWorkflowType (row, type) {
  return !type || type === 'all' || workflowDisplayType(row) === type
}

/** 画布上的检索器算子 → 去重后的来源类型（按固定顺序，避免标签抖动）。 */
export function sourceKindsFromOperators (operators = []) {
  const kinds = operators.map(sourceKindOfOperator).filter(Boolean)
  return SOURCE_KIND_IDS.filter(id => kinds.includes(id))
}

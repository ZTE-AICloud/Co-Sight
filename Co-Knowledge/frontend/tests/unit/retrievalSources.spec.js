// 知识来源类型（0.1.10）：类型归属、列表展示类型与「库/算子不匹配」判定。
import {
  isDocumentKbName,
  isGraphKbName,
  matchesWorkflowType,
  operatorSourceMismatch,
  sourceKindOfOperator,
  sourceKindsFromOperators,
  workflowDisplayType,
  workflowSourceKinds
} from '@/features/workflow/lib/retrievalSources'

const GRAPH_KB = `graph_f223eecf514a41658dd3f3367012d818|#|1`
const DOC_KB = `doc_9a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d|#|1`

describe('知识来源类型：算子归属', () => {
  it('图谱检索器归为图谱知识库', () => {
    expect(sourceKindOfOperator('KnowledgeGraphRetriever')).toBe('graph')
  })

  it('向量/关键词检索器归为文档知识库', () => {
    expect(sourceKindOfOperator('VectorRetriever')).toBe('knowledge')
    expect(sourceKindOfOperator('KeywordRetriever')).toBe('knowledge')
  })

  it('融合检索与自定义算子没有来源类型', () => {
    expect(sourceKindOfOperator('FusionRetriever')).toBe('')
    expect(sourceKindOfOperator({ operator: 'MyCustomRetriever' })).toBe('')
  })
})

describe('知识来源类型：库名归属', () => {
  it('按 |#| 前的表名判断图谱库（发布状态后缀不干扰）', () => {
    expect(isGraphKbName(GRAPH_KB)).toBe(true)
    expect(isGraphKbName(DOC_KB)).toBe(false)
    expect(isDocumentKbName(DOC_KB)).toBe(true)
  })

  it('历史配置里的纯库名不做判断', () => {
    expect(isGraphKbName('企业知识图谱')).toBe(false)
    expect(isDocumentKbName('企业知识图谱')).toBe(false)
  })
})

describe('知识来源类型：算子与库不匹配', () => {
  it('图谱检索器选中文档库时报不匹配', () => {
    const operator = { operator: 'KnowledgeGraphRetriever', kwargs: { knowledge_base_name: [DOC_KB] } }
    expect(operatorSourceMismatch(operator)).toEqual([DOC_KB])
  })

  it('文档检索器选中图谱库时报不匹配', () => {
    const operator = { operator: 'KeywordRetriever', kwargs: { knowledge_base_name: [GRAPH_KB] } }
    expect(operatorSourceMismatch(operator)).toEqual([GRAPH_KB])
  })

  it('类型一致或无法判定时不报错', () => {
    const graph = { operator: 'KnowledgeGraphRetriever', kwargs: { knowledge_base_name: [GRAPH_KB] } }
    const legacy = { operator: 'VectorRetriever', kwargs: { knowledge_info_list: [{ knowledge_base_name: ['企业知识图谱'] }] } }
    expect(operatorSourceMismatch(graph)).toEqual([])
    expect(operatorSourceMismatch(legacy)).toEqual([])
  })
})

describe('知识来源类型：列表展示', () => {
  it('只绑图谱库的工作流展示为图谱检索', () => {
    const row = { template: 'Blended', knowledgeType: 'knowledgeBase', kbPkIds: [], graphKbPkIds: [{ name: 'g' }] }
    expect(workflowSourceKinds(row)).toEqual(['graph'])
    expect(workflowDisplayType(row)).toBe('graph')
  })

  it('文档 + 图谱混合绑定时仍按建流模板展示', () => {
    const row = { template: 'Blended', knowledgeType: 'knowledgeBase', kbPkIds: [{ name: 'd' }], graphKbPkIds: [{ name: 'g' }] }
    expect(workflowSourceKinds(row)).toEqual(['knowledge', 'graph'])
    expect(workflowDisplayType(row)).toBe('Blended')
  })

  it('老数据没有绑定信息时按文档知识库处理', () => {
    expect(workflowSourceKinds({ template: 'Sequential' })).toEqual(['knowledge'])
    expect(workflowDisplayType({ template: 'Sequential' })).toBe('Sequential')
  })

  it('结构化库展示为数据库类型', () => {
    const row = { template: 'Conditional', knowledgeType: 'database' }
    expect(workflowSourceKinds(row)).toEqual(['database'])
    expect(workflowDisplayType(row)).toBe('database')
  })
})

describe('检索类型下拉：按展示类型筛', () => {
  const graphOnly = { template: 'Blended', knowledgeType: 'knowledgeBase', kbPkIds: [], graphKbPkIds: [{ name: 'g' }] }
  const docsBlended = { template: 'Blended', knowledgeType: 'knowledgeBase', kbPkIds: [{ name: 'd' }], graphKbPkIds: [] }

  it('只绑图谱库的 Blended 工作流不会出现在「混合检索」下', () => {
    expect(matchesWorkflowType(graphOnly, 'Blended')).toBe(false)
    expect(matchesWorkflowType(graphOnly, 'graph')).toBe(true)
  })

  it('文档混合检索仍按模板归到「混合检索」', () => {
    expect(matchesWorkflowType(docsBlended, 'Blended')).toBe(true)
    expect(matchesWorkflowType(docsBlended, 'graph')).toBe(false)
  })

  it('all / 空值不过滤', () => {
    expect(matchesWorkflowType(graphOnly, 'all')).toBe(true)
    expect(matchesWorkflowType(docsBlended, '')).toBe(true)
  })
})

describe('知识来源类型：画布算子汇总', () => {
  it('按固定顺序去重，混合画布同时给出文档与图谱', () => {
    expect(sourceKindsFromOperators([
      { operator: 'KnowledgeGraphRetriever' },
      { operator: 'VectorRetriever' },
      { operator: 'KeywordRetriever' }
    ])).toEqual(['knowledge', 'graph'])
  })

  it('没有来源类型时不返回标签', () => {
    expect(sourceKindsFromOperators([{ operator: 'FusionRetriever' }])).toEqual([])
  })
})

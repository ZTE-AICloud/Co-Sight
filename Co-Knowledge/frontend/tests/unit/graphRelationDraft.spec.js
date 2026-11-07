import {
  isDuplicateRelation,
  parseRelationDraft,
  relationEdgeOptions,
  relationPropertyDefs,
  relationPropertyKind
} from '@/features/graph/lib/relation-draft'

// 测的是「添加关系」抽屉（e496779 原型 GraphRelationDrawer）的纯逻辑层：
// 原型允许自由关系名 + 自定义属性；真实后端只认模板声明的边类型与属性，
// 这里钉住的就是「原型表单 → createEdge payload」的这层收口。

const nodes = [
  {
    entity_id: 'Device_001',
    entity_type: 'Device',
    entity_name: '备用电源',
    properties: { name: '备用电源' }
  },
  {
    entity_id: 'Scene_001',
    entity_type: 'Scene',
    entity_name: '机房巡检',
    properties: { name: '机房巡检' }
  }
]

const edges = [
  { edge_id: 'BelongsTo_1', edge_type: 'BelongsTo', source_id: 'Device_001', target_id: 'Scene_001' }
]

// adjacency_map：Device → Scene 有 AddedTo（out），Scene → Device 只有反向条目（in）。
const edgeTypesFor = (sourceType) => {
  if (sourceType === 'Device') {
    return [
      {
        edge_type: 'AddedTo',
        direction: 'out',
        properties: [
          { name: 'weight', type: 'INTEGER' },
          { name: 'note', type: 'STRING' },
          { name: 'enabled', type: 'BOOLEAN' },
          { name: 'meta', type: 'EMBEDDEDMAP' }
        ]
      },
      { edge_type: 'AddedTo', direction: 'in' }
    ]
  }
  return [{ edge_type: 'AddedTo', direction: 'in' }]
}

function parse (draft, overrides = {}) {
  return parseRelationDraft(draft, {
    nodes,
    edges,
    edgeTypesFor,
    suffix: 'fixed',
    ...overrides
  })
}

test('只保留当前方向的 out 边类型', () => {
  expect(relationEdgeOptions('Device', 'Scene', edgeTypesFor).map(item => item.edge_type)).toEqual(['AddedTo'])
  // 反方向在 adjacency_map 里只有 in 条目，不能当成可创建的关系
  expect(relationEdgeOptions('Scene', 'Device', edgeTypesFor)).toEqual([])
})

test('边类型缺失或不在模板里时报 edgeTypeRequired', () => {
  const missing = parse({ source: 'Device_001', target: 'Scene_001', edgeType: '', properties: {} })
  expect(missing.valid).toBe(false)
  expect(missing.errors.edgeType).toBe('edgeTypeRequired')

  const wrong = parse({ source: 'Device_001', target: 'Scene_001', edgeType: 'BelongsTo', properties: {} })
  expect(wrong.valid).toBe(false)
  expect(wrong.errors.edgeType).toBe('edgeTypeRequired')
})

test('起点、终点必填且不能是同一个实体', () => {
  const noSource = parse({ source: '', target: 'Scene_001', edgeType: 'AddedTo', properties: {} })
  expect(noSource.errors.source).toBe('sourceRequired')

  const noTarget = parse({ source: 'Device_001', target: '', edgeType: 'AddedTo', properties: {} })
  expect(noTarget.errors.target).toBe('targetRequired')

  const selfLoop = parse({ source: 'Device_001', target: 'Device_001', edgeType: 'AddedTo', properties: {} })
  expect(selfLoop.errors.target).toBe('selfLoop')
})

test('同起点同终点同类型的关系判为重复', () => {
  expect(isDuplicateRelation(
    { source: 'Device_001', target: 'Scene_001', edgeType: 'BelongsTo' },
    edges
  )).toBe(true)
  const duplicated = parse({
    source: 'Device_001',
    target: 'Scene_001',
    edgeType: 'AddedTo',
    properties: {}
  }, {
    edges: [{ edge_id: 'AddedTo_1', edge_type: 'AddedTo', source_id: 'Device_001', target_id: 'Scene_001' }]
  })
  expect(duplicated.errors.duplicate).toBe('duplicate')
})

test('属性只下发模板声明的键，并按模板类型解析', () => {
  const parsed = parse({
    source: 'Device_001',
    target: 'Scene_001',
    edgeType: 'AddedTo',
    properties: {
      weight: '12',
      note: '备注',
      enabled: 'true',
      meta: '{"a":1}',
      undeclared: '会被丢弃'
    }
  })
  expect(parsed.valid).toBe(true)
  expect(parsed.value.properties).toEqual({
    weight: 12,
    note: '备注',
    enabled: true,
    meta: { a: 1 }
  })
  expect(parsed.value.edgeId).toBe('AddedTo_fixed')
})

test('属性值格式错误时返回对应错误码', () => {
  const number = parse({
    source: 'Device_001', target: 'Scene_001', edgeType: 'AddedTo', properties: { weight: '1.5' }
  })
  expect(number.errors.properties.weight).toBe('integer')

  const json = parse({
    source: 'Device_001', target: 'Scene_001', edgeType: 'AddedTo', properties: { meta: '{bad' }
  })
  expect(json.errors.properties.meta).toBe('json')
})

test('模板属性的名称取 name，控件类型取 type', () => {
  expect(relationPropertyDefs({ properties: [{ name: 'a' }, { name: 'b' }, {}] }).map(item => (
    item.name
  ))).toEqual(['a', 'b'])
  expect(relationPropertyKind({ type: 'BOOLEAN' })).toBe('boolean')
  expect(relationPropertyKind({ type: 'DOUBLE' })).toBe('number')
  expect(relationPropertyKind({ type: 'EMBEDDED' })).toBe('json')
  expect(relationPropertyKind({})).toBe('string')
})

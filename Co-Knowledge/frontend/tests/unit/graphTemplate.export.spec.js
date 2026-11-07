import JSZip from 'jszip'
import {
  extractSchemaDataFromResponse,
  transformEntityProperties,
  transformEntities,
  transformEdgeProperties,
  transformEdges,
  transformSchemaDataToExportFormat,
  createZipFromExportData
} from '@/features/graph/lib/graph-template-export'

// 测的是 `views/knowledgeGraphTab/lib/graph-template-export.ts`——从
// `knowledgeGraphTemplate.vue` 抽出的导出/转换纯函数。
// 这里钉的是抽取之后行为不变，特别是各处的 `|| 默认值` 回退、
// 响应形状判定的优先级、以及 jszip 真的产出的 zip 结构。
// （`transformEdges` 不在最初的盘点清单里，但它在同一调用链上，一并搬出/一并测。）

/** 与 `src/assets/template/import_graph_schema_template_ZH.zip` 里的可再导入格式同构（缩样） */
function createImportTemplateFixture () {
  return {
    schema_id: 'schema-001',
    schema_name: '用户关系图谱',
    schema_desc: '用于描述用户之间的社交关系和工作关系',
    entities: [
      {
        entity_type: 'Person',
        entity_desc: '人物实体',
        properties: [
          { name: 'name', type: 'STRING', desc: '姓名', is_primary: true, is_embedding: false, is_index: true },
          { name: 'age', type: 'INTEGER', desc: '年龄', is_primary: false, is_embedding: false, is_index: false }
        ]
      }
    ],
    edges: [
      {
        edge_type: 'Knows',
        edge_desc: '认识关系',
        direction: 'two-way',
        source_entity: 'Person',
        target_entity: 'Person',
        properties: [
          { name: 'since', type: 'DATE', desc: '认识日期', is_embedding: false, is_index: false }
        ]
      }
    ]
  }
}

describe('extractSchemaDataFromResponse', () => {
  it('null / undefined / 空对象都返回 null（调用方靠 null 走「导出失败」分支）', () => {
    expect(extractSchemaDataFromResponse(null)).toBeNull()
    expect(extractSchemaDataFromResponse(undefined)).toBeNull()
    expect(extractSchemaDataFromResponse({})).toBeNull()
  })

  it('顶层直接是数据（带 schema_id）时返回 response 自身', () => {
    const resp = { schema_id: 'top', entities: [], edges: [] }
    expect(extractSchemaDataFromResponse(resp)).toBe(resp)
  })

  it('顶层没有 schema_id 时读 data（兼容仓内旧调用形态）', () => {
    const data = { schema_id: 'flat' }
    expect(extractSchemaDataFromResponse({ data })).toBe(data)
  })

  it('旧的 bo 信封已不再读取', () => {
    expect(extractSchemaDataFromResponse({ bo: { schema_id: 'from-bo' } })).toBeNull()
    expect(extractSchemaDataFromResponse({ data: { bo: { schema_id: 'from-data-bo' } } })).toBeNull()
  })
})

describe('transformEntityProperties', () => {
  it('缺省 / null / 空数组都返回空数组', () => {
    expect(transformEntityProperties(undefined)).toEqual([])
    expect(transformEntityProperties(null)).toEqual([])
    expect(transformEntityProperties([])).toEqual([])
  })

  it('六个字段忠实映射，输入里的其他字段被丢弃', () => {
    const [out] = transformEntityProperties([
      {
        name: 'name',
        type: 'STRING',
        desc: '姓名',
        is_primary: true,
        is_embedding: false,
        is_index: true,
        id: 42,
        nested: { a: 1 }
      }
    ])
    expect(out).toStrictEqual({
      name: 'name',
      type: 'STRING',
      desc: '姓名',
      is_primary: true,
      is_embedding: false,
      is_index: true
    })
  })

  it('缺字段的默认值：desc 补 ""、三个布尔补 false；name/type 原样透传（缺失即 undefined）', () => {
    expect(transformEntityProperties([{}])).toStrictEqual([
      { name: undefined, type: undefined, desc: '', is_primary: false, is_embedding: false, is_index: false }
    ])
  })

  it('desc 为 null 时也走默认值（`||` 是回退，不会把 null 原样带出去）', () => {
    expect(transformEntityProperties([{ desc: null }])[0].desc).toBe('')
  })

  it('钉住现状：`|| false` 只是回退不是类型归一——传 1 / 字符串出来还是原值（TS 签名写的 boolean 比运行时窄）', () => {
    const [out] = transformEntityProperties([{ is_primary: 1, is_index: 'yes' }])
    expect(out.is_primary).toBe(1)
    expect(out.is_index).toBe('yes')
  })

  it('把字符串当数组用会抛 TypeError，不会被静默兜成 []', () => {
    expect(() => transformEntityProperties('name,type')).toThrow(TypeError)
  })
})

describe('transformEntities', () => {
  it('缺省 / null / 空数组都返回空数组', () => {
    expect(transformEntities(undefined)).toEqual([])
    expect(transformEntities(null)).toEqual([])
    expect(transformEntities([])).toEqual([])
  })

  it('entity_desc 缺失/null 补 ""，properties 缺失/null 补 []；entity_type 原样透传', () => {
    expect(transformEntities([{}])).toStrictEqual([
      { entity_type: undefined, entity_desc: '', properties: [] }
    ])
    expect(transformEntities([{ entity_type: 'Person', entity_desc: null, properties: null }])).toStrictEqual([
      { entity_type: 'Person', entity_desc: '', properties: [] }
    ])
  })

  it('嵌套 properties 走实体属性映射（保留 is_primary，丢弃多余字段）', () => {
    const [out] = transformEntities([
      { entity_type: 'Person', properties: [{ name: 'name', type: 'STRING', is_primary: true, junk: 1 }] }
    ])
    expect(out.properties).toStrictEqual([
      { name: 'name', type: 'STRING', desc: '', is_primary: true, is_embedding: false, is_index: false }
    ])
  })
})

describe('transformEdgeProperties', () => {
  it('缺省 / null / 空数组都返回空数组', () => {
    expect(transformEdgeProperties(undefined)).toEqual([])
    expect(transformEdgeProperties(null)).toEqual([])
    expect(transformEdgeProperties([])).toEqual([])
  })

  it('映射五个字段且不含 is_primary（这是与实体属性的差别），多余字段丢弃', () => {
    expect(transformEdgeProperties([
      { name: 'since', type: 'DATE', desc: '认识日期', is_embedding: false, is_index: false, is_primary: true }
    ])).toStrictEqual([
      { name: 'since', type: 'DATE', desc: '认识日期', is_embedding: false, is_index: false }
    ])
  })

  it('缺字段的默认值：desc 补 ""、两个布尔补 false', () => {
    expect(transformEdgeProperties([{}])).toStrictEqual([
      { name: undefined, type: undefined, desc: '', is_embedding: false, is_index: false }
    ])
  })
})

describe('transformEdges', () => {
  it('缺省 / null / 空数组都返回空数组', () => {
    expect(transformEdges(undefined)).toEqual([])
    expect(transformEdges(null)).toEqual([])
    expect(transformEdges([])).toEqual([])
  })

  it('direction 缺失或空串回退 "one-way"，显式的 two-way / self-loop 原样保留', () => {
    const base = { edge_type: 'Knows', source_entity: 'Person', target_entity: 'Person' }
    expect(transformEdges([base])).toStrictEqual([
      {
        edge_type: 'Knows',
        edge_desc: '',
        direction: 'one-way',
        source_entity: 'Person',
        target_entity: 'Person',
        properties: []
      }
    ])
    expect(transformEdges([{ ...base, direction: '' }])[0].direction).toBe('one-way')
    expect(transformEdges([{ ...base, direction: 'two-way' }])[0].direction).toBe('two-way')
    expect(transformEdges([{ ...base, direction: 'self-loop' }])[0].direction).toBe('self-loop')
  })

  it('source_entity / target_entity 原样透传（不解析实体类型名）', () => {
    const [out] = transformEdges([{ source_entity: 'Person', target_entity: 'Company' }])
    expect(out.source_entity).toBe('Person')
    expect(out.target_entity).toBe('Company')
  })
})

describe('transformSchemaDataToExportFormat', () => {
  it('空对象：只补 schema_desc "" 与空数组；schema_id / schema_name 保持 undefined（没有兜底默认名）', () => {
    expect(transformSchemaDataToExportFormat({})).toStrictEqual({
      schema_id: undefined,
      schema_name: undefined,
      schema_desc: '',
      entities: [],
      edges: []
    })
  })

  it('输出只含导出格式的 5 个字段，输入里的其他字段（如 createTime）被丢弃', () => {
    const out = transformSchemaDataToExportFormat({
      schema_id: 's',
      schema_name: 'n',
      createTime: 123,
      entities: [],
      edges: []
    })
    expect(Object.keys(out).sort()).toEqual(['edges', 'entities', 'schema_desc', 'schema_id', 'schema_name'])
  })

  it('与静态导入模板同构的完整数据往返后逐字段相等（导出格式即可再导入格式）', () => {
    const fixture = createImportTemplateFixture()
    expect(transformSchemaDataToExportFormat(fixture)).toStrictEqual(fixture)
  })
})

describe('createZipFromExportData', () => {
  it('真的过一遍 jszip：1 个条目、名为 schema.json、内容为 2 空格缩进的 JSON', async () => {
    const exportData = transformSchemaDataToExportFormat(createImportTemplateFixture())

    const blob = await createZipFromExportData(exportData)
    expect(blob).toBeInstanceOf(Blob)
    expect(blob.size).toBeGreaterThan(0)

    const zip = await JSZip.loadAsync(blob)
    expect(Object.keys(zip.files)).toEqual(['schema.json'])

    const content = await zip.file('schema.json').async('string')
    expect(content).toBe(JSON.stringify(exportData, null, 2))
    expect(JSON.parse(content)).toStrictEqual(exportData)
  })

  it('两次调用互不影响：第二次的 zip 里也只有自己的 schema.json 内容', async () => {
    const first = await createZipFromExportData({ schema_id: 'a', schema_desc: '', entities: [], edges: [] })
    const second = await createZipFromExportData({ schema_id: 'b', schema_desc: '', entities: [], edges: [] })

    const zipA = await JSZip.loadAsync(first)
    const zipB = await JSZip.loadAsync(second)
    expect(Object.keys(zipA.files)).toEqual(['schema.json'])
    expect(JSON.parse(await zipA.file('schema.json').async('string')).schema_id).toBe('a')
    expect(JSON.parse(await zipB.file('schema.json').async('string')).schema_id).toBe('b')
  })
})

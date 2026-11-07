import {
  createEntityDraft,
  parseEntityDraft,
  kindFromSchemaType,
  kindFromValue
} from '@/features/graph/lib/entity-draft'

// 测的是实体编辑抽屉（0.1.5 原型 GraphEntityDrawer）的纯逻辑层：
// 属性按模板类型（优先）/运行时值展开成四类控件，保存时再解析回带类型的值。
// 关键约束：模板声明为 STRING 的 JSON 文本不能被写成对象（后端会类型不匹配）。

describe('kindFromSchemaType', () => {
  it('模板属性类型映射到四类控件', () => {
    expect(kindFromSchemaType('STRING')).toBe('string')
    expect(kindFromSchemaType('BOOLEAN')).toBe('boolean')
    expect(kindFromSchemaType('INTEGER')).toBe('number')
    expect(kindFromSchemaType('FLOAT')).toBe('number')
    expect(kindFromSchemaType('EMBEDDEDMAP')).toBe('json')
    expect(kindFromSchemaType('LINKLIST')).toBe('json')
  })

  it('缺省类型交给运行时推断；未知类型按文本处理', () => {
    expect(kindFromSchemaType(undefined)).toBeNull()
    expect(kindFromSchemaType('SOMETHING_NEW')).toBe('string')
  })
})

describe('kindFromValue', () => {
  it('只把真正的对象/数组当 JSON，字符串永远当文本', () => {
    expect(kindFromValue({ a: 1 })).toBe('json')
    expect(kindFromValue([1, 2])).toBe('json')
    expect(kindFromValue(null)).toBe('json')
    expect(kindFromValue('{"a":1}')).toBe('string')
    expect(kindFromValue(true)).toBe('boolean')
    expect(kindFromValue(12)).toBe('number')
  })
})

describe('createEntityDraft', () => {
  it('name/description 单独编辑，其余属性按模板类型展开', () => {
    const entity = {
      entity_id: 'Entity_1',
      entity_name: 'ent_site_001',
      properties: {
        name: 'West Lake No.1 Site',
        description: '核心站点',
        capacity_ah: 200,
        enabled: true,
        condition: { metric: 'battery_level', operator: 'lt', value: 20 }
      }
    }
    const defs = {
      capacity_ah: { type: 'INTEGER' },
      enabled: { type: 'BOOLEAN' },
      condition: { type: 'EMBEDDEDMAP' }
    }

    const draft = createEntityDraft(entity, defs)

    expect(draft.name).toBe('West Lake No.1 Site')
    expect(draft.description).toBe('核心站点')
    expect(draft.hasName).toBe(true)
    expect(draft.hasDescription).toBe(true)
    expect(draft.properties.map((field) => field.key)).toEqual(['capacity_ah', 'enabled', 'condition'])
    expect(draft.properties.find((field) => field.key === 'capacity_ah'))
      .toMatchObject({ kind: 'number', value: 200 })
    expect(draft.properties.find((field) => field.key === 'enabled'))
      .toMatchObject({ kind: 'boolean', value: true })
    expect(draft.properties.find((field) => field.key === 'condition').kind).toBe('json')
    expect(draft.properties.find((field) => field.key === 'condition').value)
      .toContain('"metric": "battery_level"')
  })

  it('模板声明为 STRING 的 JSON 文本保持文本控件', () => {
    const draft = createEntityDraft(
      { entity_id: 'E', properties: { name: 'n', attributes: '{"vendor":"Acme"}' } },
      { attributes: { type: 'STRING' } }
    )
    expect(draft.properties[0]).toMatchObject({ key: 'attributes', kind: 'string' })
  })

  it('模板没有 name/description 时用 entity_name 兜底，并标记不持久化', () => {
    const draft = createEntityDraft(
      { entity_id: 'Entity_9', entity_name: 'ent_x', properties: { id: 'ent_x' } },
      { id: { type: 'STRING' } }
    )
    expect(draft.name).toBe('ent_x')
    expect(draft.hasName).toBe(false)
    expect(draft.hasDescription).toBe(false)
  })
})

describe('parseEntityDraft', () => {
  const baseDraft = {
    name: ' West Lake ',
    description: 'desc',
    hasName: true,
    hasDescription: true,
    properties: [
      { key: 'capacity_ah', kind: 'number', value: '200' },
      { key: 'enabled', kind: 'boolean', value: true },
      { key: 'condition', kind: 'json', value: '{"metric":"battery_level"}' },
      { key: 'attributes', kind: 'string', value: '{"vendor":"Acme"}' }
    ]
  }

  it('解析出带类型的属性，并合并 name/description', () => {
    const parsed = parseEntityDraft(baseDraft, { capacity_ah: { type: 'INTEGER' } })

    expect(parsed.nameError).toBe('')
    expect(parsed.errors).toEqual({})
    expect(parsed.value.name).toBe('West Lake')
    expect(parsed.value.properties).toMatchObject({
      name: 'West Lake',
      description: 'desc',
      capacity_ah: 200,
      enabled: true,
      condition: { metric: 'battery_level' },
      attributes: '{"vendor":"Acme"}'
    })
  })

  it('名称为空返回 nameRequired', () => {
    const parsed = parseEntityDraft({ ...baseDraft, name: '   ' })
    expect(parsed.nameError).toBe('nameRequired')
  })

  it('非法 JSON / JSON 原始值 / 非数字 / 非整数分别给出错误码', () => {
    const parsed = parseEntityDraft({
      ...baseDraft,
      properties: [
        { key: 'bad_json', kind: 'json', value: '{oops' },
        { key: 'json_primitive', kind: 'json', value: '"text"' },
        { key: 'bad_number', kind: 'number', value: 'NaN' },
        { key: 'bad_integer', kind: 'number', value: '1.5' }
      ]
    }, { bad_integer: { type: 'INTEGER' } })

    expect(parsed.errors).toEqual({
      bad_json: 'json',
      json_primitive: 'jsonType',
      bad_number: 'number',
      bad_integer: 'integer'
    })
  })

  it('模板没有 name/description 时不写这两个键', () => {
    const parsed = parseEntityDraft({
      name: 'fallback',
      description: '',
      hasName: false,
      hasDescription: false,
      properties: [{ key: 'id', kind: 'string', value: 'ent_x' }]
    })
    expect(parsed.value.properties).toEqual({ id: 'ent_x' })
  })
})

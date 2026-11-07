import {
  compatibleEdgeOptions,
  entityNameOf,
  entityTypeOf,
  kindForProperty,
  parseCreateEntityDraft,
  propertiesForType,
  resolveDescriptionProperty,
  resolveDisplayProperty
} from '@/features/graph/lib/entity-create-draft'

// 测的是「新增实体」抽屉（0.1.9 原型 GraphEntityCreateDrawer）的纯逻辑层。
// 真实后端会校验模板属性名 / 类型，以及边类型与两端实体类型的配对；
// 这里钉住的就是「原型表单 → 后端 createEntity payload」的这层翻译。

const entityDefs = {
  Scene: [
    { name: 'id', type: 'STRING', is_primary: true },
    { name: 'name', type: 'STRING' },
    { name: 'scene_level', type: 'INTEGER' },
    { name: 'description', type: 'STRING' },
    { name: 'enabled', type: 'BOOLEAN' },
    { name: 'aliases', type: 'EMBEDDEDLIST' }
  ],
  Entity: [
    { name: 'id', type: 'STRING', is_primary: true },
    { name: 'name', type: 'STRING' },
    { name: 'description', type: 'STRING' }
  ],
  CodeOnly: [
    { name: 'code', type: 'STRING', is_primary: true },
    { name: 'label', type: 'STRING' }
  ],
  Free: []
}

const entities = [
  {
    entity_id: 'site_001',
    entity_type: 'Entity',
    entity_name: '中心站点',
    properties: { name: '中心站点', description: '站点' }
  },
  {
    entity_id: 'site_002',
    entity_type: 'Entity',
    properties: { name: '小区 001' }
  }
]

// adjacency_map 里 A=新实体、B=已有实体：'out' = 新→旧，'in' = 旧→新。
const edgeTypesFor = () => [
  { edge_type: 'RequiresEntity', direction: 'out' },
  { edge_type: 'RequiresEntity', direction: 'in' }
]

function context (overrides = {}) {
  return {
    entityTypes: ['Scene', 'Entity', 'CodeOnly', 'Free'],
    propertyDefs: entityDefs,
    entities,
    edgeTypesFor,
    suffix: '123',
    ...overrides
  }
}

function draft (overrides = {}) {
  return {
    name: '',
    type: '',
    description: '',
    properties: [],
    relation: { enabled: false, peer: '', edgeType: '', direction: 'newToPeer' },
    ...overrides
  }
}

function row (key, value, kind = 'string') {
  return { uid: `${key}-${kind}`, key, kind, value }
}

describe('template property lookups', () => {
  it('reads the entity_meta property array', () => {
    expect(propertiesForType('Scene', entityDefs).map((item) => item.name)).toContain('scene_level')
    expect(propertiesForType('scene', entityDefs)).toHaveLength(6)
    expect(propertiesForType('Missing', entityDefs)).toEqual([])
  })

  it('writes the entity name to name, then the primary key, then the first property', () => {
    expect(resolveDisplayProperty('Scene', entityDefs)?.name).toBe('name')
    expect(resolveDisplayProperty('CodeOnly', entityDefs)?.name).toBe('code')
    expect(resolveDisplayProperty('Free', entityDefs)).toBeNull()
    expect(resolveDescriptionProperty('Scene', entityDefs)?.name).toBe('description')
    expect(resolveDescriptionProperty('CodeOnly', entityDefs)).toBeNull()
  })

  it('derives the value editor kind from the template type', () => {
    expect(kindForProperty('Scene', 'scene_level', entityDefs)).toBe('number')
    expect(kindForProperty('Scene', 'enabled', entityDefs)).toBe('boolean')
    expect(kindForProperty('Scene', 'aliases', entityDefs)).toBe('json')
    expect(kindForProperty('Scene', 'name', entityDefs)).toBe('string')
    expect(kindForProperty('Free', 'anything', entityDefs)).toBe('string')
  })
})

describe('parseCreateEntityDraft: validation', () => {
  it('requires a name and a declared entity type', () => {
    const parsed = parseCreateEntityDraft(draft(), context())

    expect(parsed.valid).toBe(false)
    expect(parsed.errors.name).toBe('nameRequired')
    expect(parsed.errors.type).toBe('typeRequired')
  })

  it('rejects properties the template does not declare and duplicate keys', () => {
    const parsed = parseCreateEntityDraft(draft({
      name: '电池',
      type: 'Scene',
      properties: [
        row('scene_level', '3'),
        row('unknown_prop', 'x'),
        row('scene_level', '4')
      ]
    }), context())

    expect(parsed.valid).toBe(false)
    expect(parsed.errors.properties[0].key).toBe('duplicate')
    expect(parsed.errors.properties[1].key).toBe('notDefined')
    expect(parsed.errors.properties[2].key).toBe('duplicate')
  })

  it('does not allow name / description to be repeated as extra property rows', () => {
    const parsed = parseCreateEntityDraft(draft({
      name: '电池',
      type: 'Scene',
      description: '说明',
      properties: [row('name', '另一个名字'), row('description', '另一段描述')]
    }), context())

    expect(parsed.errors.properties[0].key).toBe('duplicate')
    expect(parsed.errors.properties[1].key).toBe('duplicate')
  })

  it('reports typed value errors with codes, not silent coercion', () => {
    const parsed = parseCreateEntityDraft(draft({
      name: '电池',
      type: 'Scene',
      properties: [
        row('scene_level', '3.5'),
        row('aliases', '{invalid')
      ]
    }), context())

    expect(parsed.errors.properties[0].value).toBe('integer')
    expect(parsed.errors.properties[1].value).toBe('json')
  })

  it('skips empty optional values instead of sending empty strings', () => {
    const parsed = parseCreateEntityDraft(draft({
      name: '电池',
      type: 'Scene',
      properties: [row('scene_level', ''), row('aliases', '')]
    }), context())

    expect(parsed.valid).toBe(true)
    expect(parsed.value.properties).toEqual({ name: '电池' })
  })
})

describe('parseCreateEntityDraft: payload', () => {
  it('maps the display name / description and parses template-typed properties', () => {
    const parsed = parseCreateEntityDraft(draft({
      name: ' 备用电池 ',
      type: 'Scene',
      description: ' 手动补充的站点备用电源 ',
      properties: [
        row('scene_level', '200', 'number'),
        row('enabled', false, 'boolean'),
        row('aliases', '["备用电源"]', 'json')
      ]
    }), context())

    expect(parsed.valid).toBe(true)
    expect(parsed.value.entityId).toBe('Scene_123')
    expect(parsed.value.entityType).toBe('Scene')
    expect(parsed.value.entityName).toBe('备用电池')
    expect(parsed.value.properties).toEqual({
      name: '备用电池',
      description: '手动补充的站点备用电源',
      scene_level: 200,
      enabled: false,
      aliases: ['备用电源']
    })
  })

  it('falls back to the primary property when the template has no name field', () => {
    const parsed = parseCreateEntityDraft(draft({
      name: 'S-01',
      type: 'CodeOnly'
    }), context())

    expect(parsed.valid).toBe(true)
    expect(parsed.value.nameProperty).toBe('code')
    expect(parsed.value.properties).toEqual({ code: 'S-01' })
  })

  it('lets templates without declared properties accept free-form keys', () => {
    const parsed = parseCreateEntityDraft(draft({
      name: '自由实体',
      type: 'Free',
      description: '自由描述',
      properties: [row('capacity_ah', '200', 'number'), row('aliases', '["a"]', 'json')]
    }), context())

    expect(parsed.valid).toBe(true)
    expect(parsed.value.properties).toEqual({
      name: '自由实体',
      description: '自由描述',
      capacity_ah: 200,
      aliases: ['a']
    })
  })
})

describe('parseCreateEntityDraft: relations', () => {
  it('creates an outgoing relation with backend direction "out"', () => {
    const parsed = parseCreateEntityDraft(draft({
      name: '备用电池',
      type: 'Scene',
      relation: { enabled: true, peer: 'site_001', edgeType: 'RequiresEntity', direction: 'newToPeer' }
    }), context())

    expect(parsed.valid).toBe(true)
    expect(parsed.value.relation).toEqual({
      peerId: 'site_001',
      peerType: 'Entity',
      edgeType: 'RequiresEntity',
      edgeId: 'RequiresEntity_123',
      direction: 'out',
      sourceId: 'Scene_123',
      targetId: 'site_001',
      properties: {}
    })
  })

  it('creates an incoming relation with backend direction "in"', () => {
    const parsed = parseCreateEntityDraft(draft({
      name: '备用电池',
      type: 'Scene',
      relation: { enabled: true, peer: 'site_001', edgeType: 'RequiresEntity', direction: 'peerToNew' }
    }), context())

    expect(parsed.value.relation).toMatchObject({
      direction: 'in',
      sourceId: 'site_001',
      targetId: 'Scene_123'
    })
  })

  it('requires an existing peer and a relation type that exists in that direction', () => {
    const missingPeer = parseCreateEntityDraft(draft({
      name: '备用电池',
      type: 'Scene',
      relation: { enabled: true, peer: 'missing', edgeType: 'RequiresEntity', direction: 'newToPeer' }
    }), context())
    expect(missingPeer.errors.peer).toBe('peerRequired')

    const missingEdge = parseCreateEntityDraft(draft({
      name: '备用电池',
      type: 'Scene',
      relation: { enabled: true, peer: 'site_001', edgeType: 'UnknownEdge', direction: 'newToPeer' }
    }), context())
    expect(missingEdge.errors.edgeType).toBe('edgeTypeRequired')
  })

  it('ignores stale peer / edge fields when the relation switch is off', () => {
    const parsed = parseCreateEntityDraft(draft({
      name: '备用电池',
      type: 'Scene',
      relation: { enabled: false, peer: 'gone', edgeType: 'Gone', direction: 'newToPeer' }
    }), context())

    expect(parsed.valid).toBe(true)
    expect(parsed.value.relation).toBeNull()
  })
})

describe('compatibleEdgeOptions', () => {
  it('filters adjacency entries by the requested direction', () => {
    expect(compatibleEdgeOptions('Scene', 'Entity', 'newToPeer', edgeTypesFor).map((edge) => edge.direction))
      .toEqual(['out'])
    expect(compatibleEdgeOptions('Scene', 'Entity', 'peerToNew', edgeTypesFor).map((edge) => edge.direction))
      .toEqual(['in'])
  })

  it('returns nothing when a type or peer type is missing', () => {
    expect(compatibleEdgeOptions('', 'Entity', 'newToPeer', edgeTypesFor)).toEqual([])
    expect(compatibleEdgeOptions('Scene', '', 'newToPeer', edgeTypesFor)).toEqual([])
  })

  it('accepts both directions for self relations even though adjacency only records "out"', () => {
    const selfEdgeTypes = (newType, peerType) => (
      newType === 'Scene' && peerType === 'Scene'
        ? [{ edge_type: 'HasSceneParent', direction: 'out' }]
        : []
    )
    expect(compatibleEdgeOptions('Scene', 'Scene', 'newToPeer', selfEdgeTypes)).toHaveLength(1)
    expect(compatibleEdgeOptions('Scene', 'Scene', 'peerToNew', selfEdgeTypes)).toHaveLength(1)
  })
})

describe('entity helpers', () => {
  it('prefers properties.name, then entity_name, then the id', () => {
    expect(entityNameOf(entities[0])).toBe('中心站点')
    expect(entityNameOf({ entity_id: 'x', properties: {} })).toBe('x')
    expect(entityTypeOf({ id: 'x', class: 'Scene' })).toBe('Scene')
  })
})

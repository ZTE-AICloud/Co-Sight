/**
 * 「新增实体」抽屉的草稿构造 / 校验（纯函数）。
 *
 * 图谱模板会校验属性名和值类型，未声明的属性会被后端以
 * ``entity.property.not.defined`` 拒绝。因此这里按模板属性表收口：
 * 属性名从模板里选，值类型由模板决定；模板没有声明任何属性时
 * 才退化成自由填写（此时后端也放行任意属性）。
 *
 * 实体名称写入模板的展示属性（优先 ``name``，否则主键，最后取第一个属性）——
 * 与画布的显示名口径一致。模板没有 ``description`` 属性时不写这个键。
 *
 * 关联关系同样受模板约束：后端要求边类型在模板中声明、且两端实体类型与
 * ``source_entity`` / ``target_entity`` 对得上。这里用 adjacency_map 的
 * 「新实体类型 → 已有实体类型」条目按方向过滤，并把方向翻译成后端 edgeInfo 口径
 * （后端 direction 相对已有实体：``'in'`` = 已有实体是起点，``'out'`` = 新实体是起点）。
 *
 * 零 Vue 依赖，可在 Node 里直接单测。
 */

import { kindFromSchemaType, type EntityPropertyKind } from './entity-draft'

export type CreateRelationDirection = 'newToPeer' | 'peerToNew'

export interface CreateEntityPropertyDef {
  name?: string
  type?: string
  is_primary?: boolean
  desc?: string
}

/** schemaMapping.entity_meta 的原始形状：type → { properties: [...] } */
export type CreateEntityPropertyDefs = Record<
  string,
  CreateEntityPropertyDef[] | undefined
>

export interface CreateEntityPropertyRow {
  uid: string
  key: string
  kind: EntityPropertyKind
  value: string | number | boolean
}

export interface CreateEntityRelationDraft {
  enabled: boolean
  peer: string
  edgeType: string
  direction: CreateRelationDirection
}

export interface CreateEntityDraft {
  name: string
  type: string
  description: string
  properties: CreateEntityPropertyRow[]
  relation: CreateEntityRelationDraft
}

export interface CreateEntityOptionEntity {
  entity_id?: string
  id?: string
  entity_type?: string
  class?: string
  entity_name?: string
  properties?: Record<string, unknown>
}

export interface CreateEntityEdgeOption {
  edge_type?: string
  direction?: string
}

export type CreateEntityErrorCode =
  | ''
  | 'nameRequired'
  | 'typeRequired'
  | 'peerRequired'
  | 'edgeTypeRequired'
  | 'keyRequired'
  | 'duplicate'
  | 'notDefined'
  | 'json'
  | 'jsonType'
  | 'number'
  | 'integer'

export interface CreateEntityPropertyErrors {
  key?: CreateEntityErrorCode
  value?: CreateEntityErrorCode
}

export interface CreateEntityErrors {
  name?: CreateEntityErrorCode
  type?: CreateEntityErrorCode
  properties: CreateEntityPropertyErrors[]
  peer?: CreateEntityErrorCode
  edgeType?: CreateEntityErrorCode
}

export interface ParsedCreateEntityRelation {
  peerId: string
  peerType: string
  edgeType: string
  edgeId: string
  direction: 'in' | 'out'
  sourceId: string
  targetId: string
  properties: Record<string, unknown>
}

export interface ParsedCreateEntity {
  valid: boolean
  errors: CreateEntityErrors
  value: {
    entityId: string
    entityType: string
    entityName: string
    nameProperty: string
    descriptionProperty: string
    properties: Record<string, unknown>
    relation: ParsedCreateEntityRelation | null
  }
}

export interface CreateEntityContext {
  entityTypes: string[]
  propertyDefs: CreateEntityPropertyDefs
  entities: CreateEntityOptionEntity[]
  // no-unused-vars 会把类型签名里的参数名当成运行时变量，显式登记豁免
  // （与 entity-create.ts 同因）。
  // eslint-disable-next-line no-unused-vars
  edgeTypesFor: (newType: string, peerType: string) => CreateEntityEdgeOption[]
  now?: number
  suffix?: string
}

const JSON_TYPES = new Set([
  'EMBEDDED',
  'EMBEDDEDMAP',
  'LINKMAP',
  'EMBEDDEDLIST',
  'LINKLIST',
  'EMBEDDEDSET',
  'LINKSET'
])

const INTEGER_TYPES = new Set(['BYTE', 'SHORT', 'INTEGER', 'LONG'])

const NUMBER_TYPES = new Set(['BYTE', 'SHORT', 'INTEGER', 'LONG', 'FLOAT', 'DOUBLE'])

const DEFAULT_NAME_PROPERTY = 'name'

const DEFAULT_DESCRIPTION_PROPERTY = 'description'

function sameName (a: string, b: string): boolean {
  return a === b || a.toLowerCase() === b.toLowerCase()
}

/** 模板里某个实体类型的属性表。 */
export function propertiesForType (
  type: string,
  defs: CreateEntityPropertyDefs = {}
): CreateEntityPropertyDef[] {
  if (!type) {
    return []
  }
  const key = Object.keys(defs).find((item) => sameName(item, type))
  const entry = key ? defs[key] : undefined
  return Array.isArray(entry)
    ? entry.filter((item): item is CreateEntityPropertyDef => Boolean(item?.name))
    : []
}

/**
 * 实体名称写到哪里：``name`` → 主键 → 第一个属性。
 * 与 backend `_extract_display_field` / 画布显示名保持同一顺序。
 */
export function resolveDisplayProperty (
  type: string,
  defs: CreateEntityPropertyDefs = {}
): CreateEntityPropertyDef | null {
  const properties = propertiesForType(type, defs)
  if (!properties.length) {
    return null
  }
  const named = properties.find((item) => sameName(String(item.name), DEFAULT_NAME_PROPERTY))
  if (named) {
    return named
  }
  const primary = properties.find((item) => item.is_primary === true)
  return primary || properties[0]
}

/** 模板声明了 description 才写这个键（否则后端 property.not.defined）。 */
export function resolveDescriptionProperty (
  type: string,
  defs: CreateEntityPropertyDefs = {}
): CreateEntityPropertyDef | null {
  return propertiesForType(type, defs)
    .find((item) => sameName(String(item.name), DEFAULT_DESCRIPTION_PROPERTY)) || null
}

/** 模板属性类型 → 控件类型；模板没声明时按文本。 */
export function kindForProperty (
  type: string,
  key: string,
  defs: CreateEntityPropertyDefs = {}
): EntityPropertyKind {
  const def = propertiesForType(type, defs).find((item) => sameName(String(item.name), key))
  return kindFromSchemaType(def?.type) || 'string'
}

export function entityIdOf (entity: CreateEntityOptionEntity | null | undefined): string {
  return String(entity?.entity_id ?? entity?.id ?? '')
}

export function entityTypeOf (entity: CreateEntityOptionEntity | null | undefined): string {
  return String(entity?.entity_type ?? entity?.class ?? '')
}

export function entityNameOf (entity: CreateEntityOptionEntity | null | undefined): string {
  const properties = entity?.properties && typeof entity.properties === 'object'
    ? entity.properties as Record<string, unknown>
    : {}
  return String(properties.name ?? entity?.entity_name ?? entityIdOf(entity))
}

function resolveEntityType (type: string, types: string[]): string {
  if (!type) {
    return ''
  }
  return types.find((item) => item === type) ||
    types.find((item) => sameName(item, type)) ||
    ''
}

function typeFromEntityId (id: string, types: string[]): string {
  const matched = types
    .filter((type) => id.startsWith(`${type}_`))
    .sort((a, b) => b.length - a.length)
  return matched[0] || ''
}

/** 用户选择的方向（新→旧 / 旧→新）对应 adjacency_map 里的哪个 direction。 */
function adjacencyDirectionFor (direction: CreateRelationDirection): 'in' | 'out' {
  return direction === 'newToPeer' ? 'out' : 'in'
}

/** 后端 edgeInfo.direction 相对“已有实体”：新→旧 = 'out'，旧→新 = 'in'。 */
function backendDirectionFor (direction: CreateRelationDirection): 'in' | 'out' {
  return direction === 'newToPeer' ? 'out' : 'in'
}

/** 当前方向下与新实体类型、已有实体类型都匹配的边类型。 */
export function compatibleEdgeOptions (
  newType: string,
  peerType: string,
  direction: CreateRelationDirection,
  // eslint-disable-next-line no-unused-vars
  edgeTypesFor: (newType: string, peerType: string) => CreateEntityEdgeOption[]
): CreateEntityEdgeOption[] {
  if (!newType || !peerType) {
    return []
  }
  const wanted = adjacencyDirectionFor(direction)
  try {
    const options = (edgeTypesFor(newType, peerType) || [])
      .filter((edge) => Boolean(edge?.edge_type))
    const matched = options.filter((edge) => edge.direction === wanted)
    if (matched.length || !sameName(newType, peerType)) {
      return matched
    }
    // 自环关系（source_entity === target_entity）在 adjacency_map 里只会生成一条
    // direction='out'，但后端两端类型相同，反方向同样合法。
    return options
  } catch {
    return []
  }
}

function emptyErrors (rows: CreateEntityPropertyRow[]): CreateEntityErrors {
  return {
    name: '',
    type: '',
    properties: rows.map(() => ({})),
    peer: '',
    edgeType: ''
  }
}

function parsePropertyValue (
  raw: string | number | boolean,
  kind: EntityPropertyKind,
  declaredType: string,
  errors: CreateEntityPropertyErrors
): { value?: unknown, skip?: boolean } {
  const type = String(declaredType || '').toUpperCase()

  if (kind === 'boolean') {
    return { value: raw === true || raw === 'true' }
  }

  const text = raw === null || raw === undefined ? '' : String(raw)
  if (text === '') {
    return { skip: true }
  }

  if (kind === 'number') {
    const value = Number(text)
    if (!Number.isFinite(value)) {
      errors.value = 'number'
      return {}
    }
    if (INTEGER_TYPES.has(type) && !Number.isInteger(value)) {
      errors.value = 'integer'
      return {}
    }
    return { value }
  }

  if (kind === 'json') {
    try {
      const parsed = JSON.parse(text)
      if (parsed !== null && typeof parsed !== 'object') {
        errors.value = 'jsonType'
        return {}
      }
      return { value: parsed }
    } catch {
      errors.value = 'json'
      return {}
    }
  }

  return { value: text }
}

function kindForDeclaredValue (declaredType: string): EntityPropertyKind {
  const type = String(declaredType || '').toUpperCase()
  if (type === 'BOOLEAN') {
    return 'boolean'
  }
  if (NUMBER_TYPES.has(type)) {
    return 'number'
  }
  if (JSON_TYPES.has(type)) {
    return 'json'
  }
  return 'string'
}

/**
 * 校验并解析新增实体草稿。
 *
 * - 模板声明了属性：属性名必须来自模板，值按模板类型解析；
 * - 模板未声明属性：属性名/值类型自由填写，名称和描述按 ``name`` / ``description`` 落库；
 * - 关联关系：已有实体、关系类型、方向必须同时成立；
 * - ID：``{类型}_{后缀}`` / ``{关系类型}_{后缀}``，后缀默认由时间戳 + 随机串组成，
 *   单测可传入固定 ``suffix``。
 */
export function parseCreateEntityDraft (
  draft: CreateEntityDraft,
  context: CreateEntityContext
): ParsedCreateEntity {
  const rows = Array.isArray(draft.properties) ? draft.properties : []
  const errors = emptyErrors(rows)
  const type = resolveEntityType(String(draft.type || '').trim(), context.entityTypes || [])
  const properties = propertiesForType(type, context.propertyDefs)
  const schemaDeclared = properties.length > 0
  const nameProperty = resolveDisplayProperty(type, context.propertyDefs)
  const descriptionProperty = resolveDescriptionProperty(type, context.propertyDefs)
  const name = String(draft.name || '').trim()
  const description = String(draft.description || '').trim()

  if (!name) {
    errors.name = 'nameRequired'
  }
  if (!type) {
    errors.type = 'typeRequired'
  }

  const values: Record<string, unknown> = {}
  const nameKey = nameProperty?.name || DEFAULT_NAME_PROPERTY
  const descriptionKey = descriptionProperty?.name || DEFAULT_DESCRIPTION_PROPERTY

  if (name && (nameProperty || !schemaDeclared)) {
    values[nameKey] = name
  }
  if (description && (descriptionProperty || !schemaDeclared)) {
    values[descriptionKey] = description
  }

  const usedKeys = new Set<string>(
    [nameProperty?.name, descriptionProperty?.name].filter((key): key is string => Boolean(key))
  )

  rows.forEach((row, index) => {
    const rowErrors = errors.properties[index]
    const rawKey = String(row.key || '').trim()
    const duplicate = rawKey
      ? Array.from(usedKeys).some((key) => sameName(key, rawKey)) ||
        rows.some((other, otherIndex) => (
          otherIndex !== index &&
          String(other.key || '').trim() !== '' &&
          sameName(String(other.key || '').trim(), rawKey)
        ))
      : false
    const declared = properties.find((item) => sameName(String(item.name), rawKey))
    const kind = declared ? kindForDeclaredValue(String(declared.type)) : row.kind

    if (!rawKey) {
      rowErrors.key = 'keyRequired'
      return
    }
    if (schemaDeclared && !declared) {
      rowErrors.key = 'notDefined'
      return
    }
    if (duplicate) {
      rowErrors.key = 'duplicate'
      return
    }

    const parsed = parsePropertyValue(row.value, kind, String(declared?.type || ''), rowErrors)
    if (parsed.skip || rowErrors.value) {
      return
    }
    values[rawKey] = parsed.value
    usedKeys.add(rawKey)
  })

  const suffix = context.suffix ?? `${context.now ?? Date.now()}-${Math.random().toString(36).slice(2, 7)}`
  const entityId = type ? `${type}_${suffix}` : ''

  let relation: ParsedCreateEntityRelation | null = null
  if (draft.relation?.enabled) {
    const peerId = String(draft.relation.peer || '')
    const peer = (context.entities || []).find((entity) => entityIdOf(entity) === peerId)
    const peerType = entityTypeOf(peer) || typeFromEntityId(peerId, context.entityTypes || [])
    if (!peerId || !peer) {
      errors.peer = 'peerRequired'
    } else if (type) {
      const options = compatibleEdgeOptions(
        type,
        peerType,
        draft.relation.direction,
        context.edgeTypesFor
      )
      const edgeType = String(draft.relation.edgeType || '')
      const matched = options.find((edge) => edge.edge_type === edgeType)
      if (!edgeType || !matched) {
        errors.edgeType = 'edgeTypeRequired'
      } else {
        const direction = backendDirectionFor(draft.relation.direction)
        relation = {
          peerId,
          peerType,
          edgeType,
          edgeId: `${edgeType}_${suffix}`,
          direction,
          sourceId: direction === 'out' ? entityId : peerId,
          targetId: direction === 'out' ? peerId : entityId,
          properties: {}
        }
      }
    }
  }

  const valid = !errors.name &&
    !errors.type &&
    !errors.peer &&
    !errors.edgeType &&
    errors.properties.every((item) => !item.key && !item.value)

  return {
    valid,
    errors,
    value: {
      entityId,
      entityType: type,
      entityName: name,
      nameProperty: nameProperty?.name || DEFAULT_NAME_PROPERTY,
      descriptionProperty: descriptionProperty?.name || DEFAULT_DESCRIPTION_PROPERTY,
      properties: values,
      relation
    }
  }
}

/**
 * 「添加关系」抽屉的草稿构造 / 校验（纯函数）。
 *
 * 抽屉允许任意「关系名 + 自定义属性」，但后端**只认模板声明**：
 *
 * * 边类型必须出现在 schema 的 `edges` 里（`RetCode.graph.edge.type.not.defined`）；
 * * 两端实体类型要与该边定义的 `source_entity` / `target_entity` 对上
 *   （`_validate_edge_node_types`）；
 * * 属性名必须在该边定义里声明（`RetCode.graph.edge.property.not.defined`）。
 *
 * 所以这里把「自由属性」收口成「模板属性」：边类型只列当前方向可用的，
 * 属性按模板类型解析；未声明属性的边类型不带属性。「关系描述」也只在
 * 模板声明了 `description` 属性时才出现（否则后端会拒绝未知键）。
 *
 * 边 ID 按后端 `_validate_id_format` 生成：`{edge_type}_{字母数字与中划线}`。
 *
 * 零 Vue 依赖，可在 Node 里直接单测。
 */

import { kindFromSchemaType, type EntityPropertyKind } from './entity-draft'
import { entityIdOf, entityTypeOf } from './entity-create-draft'

/** adjacency_map 里的一条边定义（`direction: 'out'` 表示从当前行实体类型出发）。 */
export interface RelationEdgeOption {
  edge_type?: string
  edge_desc?: string
  direction?: string
  properties?: RelationPropertyDef[]
}

export interface RelationPropertyDef {
  property_name?: string
  name?: string
  code?: string
  prop?: string
  type?: string
  desc?: string
}

export interface RelationOptionEntity {
  entity_id?: string
  id?: string
  entity_type?: string
  class?: string
  entity_name?: string
  properties?: Record<string, unknown>
}

export interface RelationExistingEdge {
  edge_id?: string
  edge_type?: string
  source_id?: string
  target_id?: string
  source?: string
  target?: string
}

export interface RelationDraft {
  source: string
  target: string
  edgeType: string
  /** 模板声明的属性 → 原始输入值（未填的键不会下发） */
  properties: Record<string, string | number | boolean>
}

export type RelationErrorCode =
  | ''
  | 'sourceRequired'
  | 'targetRequired'
  | 'selfLoop'
  | 'edgeTypeRequired'
  | 'duplicate'
  | 'json'
  | 'jsonType'
  | 'number'
  | 'integer'

export interface RelationErrors {
  source?: RelationErrorCode
  target?: RelationErrorCode
  edgeType?: RelationErrorCode
  duplicate?: RelationErrorCode
  /** 属性名 → 错误码（属性名来自模板，无需翻译键） */
  properties?: Record<string, RelationErrorCode>
}

export interface ParsedRelation {
  valid: boolean
  errors: RelationErrors
  value: {
    edgeId: string
    edgeType: string
    sourceId: string
    targetId: string
    properties: Record<string, unknown>
  }
}

export interface RelationContext {
  nodes: RelationOptionEntity[]
  edges: RelationExistingEdge[]
  // eslint-disable-next-line no-unused-vars
  edgeTypesFor: (sourceType: string, targetType: string) => RelationEdgeOption[]
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

/** 模板属性名。 */
export function relationPropertyName (def: RelationPropertyDef | null | undefined): string {
  return String(def?.name ?? '')
}

/** 某条边定义声明的属性列表（去掉没有名字的项）。 */
export function relationPropertyDefs (option: RelationEdgeOption | null | undefined): RelationPropertyDef[] {
  return (Array.isArray(option?.properties) ? option?.properties || [] : [])
    .filter((def) => Boolean(relationPropertyName(def)))
}

/** 属性值控件类型：模板没声明时按文本。 */
export function relationPropertyKind (def: RelationPropertyDef | null | undefined): EntityPropertyKind {
  return kindFromSchemaType(def?.type) || 'string'
}

/**
 * 当前「起点 → 终点」方向下可用的边类型。
 *
 * `schemaMapper` 会把一条边同时写进 `adjacency[source][target]`（`direction: 'out'`）
 * 与 `adjacency[target][source]`（`direction: 'in'`）；只有 `out` 表示方向正确。
 * 起点与终点同类型时（自环）只生成 `out` 一条，两种方向都合法。
 */
export function relationEdgeOptions (
  sourceType: string,
  targetType: string,
  // eslint-disable-next-line no-unused-vars
  edgeTypesFor: (sourceType: string, targetType: string) => RelationEdgeOption[]
): RelationEdgeOption[] {
  if (!sourceType || !targetType) {
    return []
  }
  try {
    return (edgeTypesFor(sourceType, targetType) || [])
      .filter((edge) => Boolean(edge?.edge_type) && edge.direction === 'out')
  } catch {
    return []
  }
}

/** 起点实体 → 终点实体；两端都不存在时返回 undefined。 */
export function relationEndpointTypes (
  source: RelationOptionEntity | null | undefined,
  target: RelationOptionEntity | null | undefined
): { sourceType: string, targetType: string } {
  return {
    sourceType: entityTypeOf(source),
    targetType: entityTypeOf(target)
  }
}

function edgeSourceId (edge: RelationExistingEdge): string {
  return String(edge.source_id ?? edge.source ?? '')
}

function edgeTargetId (edge: RelationExistingEdge): string {
  return String(edge.target_id ?? edge.target ?? '')
}

/** 同起点、同终点、同类型的关系已存在 → 视为重复（后端会分配不同 id，仍允许，但 UI 提示重复）。 */
export function isDuplicateRelation (
  draft: Pick<RelationDraft, 'source' | 'target' | 'edgeType'>,
  edges: RelationExistingEdge[]
): boolean {
  return (edges || []).some((edge) => (
    String(edge.edge_type || '') === String(draft.edgeType || '') &&
    edgeSourceId(edge) === String(draft.source || '') &&
    edgeTargetId(edge) === String(draft.target || '')
  ))
}

function parsePropertyValue (
  raw: string | number | boolean,
  declaredType: string,
  errors: Record<string, RelationErrorCode>,
  key: string
): { value?: unknown, skip?: boolean } {
  const type = String(declaredType || '').toUpperCase()
  const kind = kindFromSchemaType(declaredType) || 'string'
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
      errors[key] = 'number'
      return {}
    }
    if (INTEGER_TYPES.has(type) && !Number.isInteger(value)) {
      errors[key] = 'integer'
      return {}
    }
    return { value }
  }
  if (JSON_TYPES.has(type)) {
    try {
      const parsed = JSON.parse(text)
      if (parsed !== null && typeof parsed !== 'object') {
        errors[key] = 'jsonType'
        return {}
      }
      return { value: parsed }
    } catch {
      errors[key] = 'json'
      return {}
    }
  }
  return { value: text }
}

/**
 * 校验并解析关系草稿。
 *
 * - 起点 / 终点必须是画布上已有的实体，且不能是同一个；
 * - 边类型必须是当前方向下模板声明的关系；
 * - 属性只下发模板声明的键，并按模板类型解析；
 * - ID：`{edge_type}_{后缀}`，后缀默认 `时间戳-随机串`（单测可传固定值）。
 */
export function parseRelationDraft (draft: RelationDraft, context: RelationContext): ParsedRelation {
  const nodes = context.nodes || []
  const edges = context.edges || []
  const sourceId = String(draft.source || '')
  const targetId = String(draft.target || '')
  const source = nodes.find((node) => entityIdOf(node) === sourceId)
  const target = nodes.find((node) => entityIdOf(node) === targetId)
  const errors: RelationErrors = { properties: {} }

  if (!sourceId || !source) {
    errors.source = 'sourceRequired'
  }
  if (!targetId || !target) {
    errors.target = 'targetRequired'
  } else if (sourceId && sourceId === targetId) {
    errors.target = 'selfLoop'
  }

  const sourceType = entityTypeOf(source)
  const targetType = entityTypeOf(target)
  const options = relationEdgeOptions(sourceType, targetType, context.edgeTypesFor)
  const edgeType = String(draft.edgeType || '')
  const option = options.find((edge) => edge.edge_type === edgeType)
  if (!edgeType || !option) {
    errors.edgeType = 'edgeTypeRequired'
  }

  const properties: Record<string, unknown> = {}
  if (option) {
    const draftProps = draft.properties && typeof draft.properties === 'object' ? draft.properties : {}
    relationPropertyDefs(option).forEach((def) => {
      const name = relationPropertyName(def)
      const parsed = parsePropertyValue(draftProps[name], String(def.type || ''), errors.properties!, name)
      if (parsed.skip || errors.properties![name]) {
        return
      }
      properties[name] = parsed.value
    })
  }

  if (!errors.source && !errors.target && !errors.edgeType && isDuplicateRelation(draft, edges)) {
    errors.duplicate = 'duplicate'
  }

  const suffix = context.suffix ?? `${context.now ?? Date.now()}-${Math.random().toString(36).slice(2, 7)}`
  const valid = !errors.source &&
    !errors.target &&
    !errors.edgeType &&
    !errors.duplicate &&
    Object.keys(errors.properties || {}).length === 0

  return {
    valid,
    errors,
    value: {
      edgeId: edgeType ? `${edgeType}_${suffix}` : '',
      edgeType,
      sourceId,
      targetId,
      properties
    }
  }
}

/**
 * 实体编辑抽屉的草稿构造 / 校验（纯函数）。
 *
 * 把实体的属性按「文本 / 数字 / 布尔值 / JSON」四类展开成可编辑字段，
 * 保存时再解析回带类型的值。
 *
 * 真实工程的属性类型来自图谱模板（STRING / BOOLEAN / INTEGER / FLOAT / EMBEDDED…），
 * 所以这里优先按模板声明判定类型，模板缺声明时才按运行时值推断；错误只返回**错误码**，
 * 由组件层做 i18n，保证中英文界面都有正确文案。
 *
 * 零 Vue 依赖，可在 Node 里直接单测。
 */

export type EntityPropertyKind = 'string' | 'number' | 'boolean' | 'json'

export type EntityFieldError = 'json' | 'jsonType' | 'number' | 'integer'

export interface EntityPropertyDef {
  type?: string
}

export type EntityPropertyDefs = Record<string, EntityPropertyDef | undefined>

export interface EntityPropertyField {
  key: string
  kind: EntityPropertyKind
  value: string | number | boolean
}

export interface EntityDraft {
  name: string
  description: string
  properties: EntityPropertyField[]
  /** 模板是否声明了 name / description（未声明时保存不写这两个键，避免后端 property.not.defined） */
  hasName: boolean
  hasDescription: boolean
}

export interface ParsedEntityDraft {
  nameError: 'nameRequired' | ''
  errors: Record<string, EntityFieldError>
  value: {
    name: string
    description: string
    properties: Record<string, unknown>
  }
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

function isPlainRecord (value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

/** 模板属性类型 → 编辑控件类型；未知/缺省返回 null，交给运行时值推断 */
export function kindFromSchemaType (declared?: string): EntityPropertyKind | null {
  if (!declared) {
    return null
  }
  const type = String(declared).toUpperCase()
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

/** 运行时值 → 编辑控件类型（字符串永不当 JSON，避免把模板声明为 STRING 的 JSON 文本写回对象） */
export function kindFromValue (value: unknown): EntityPropertyKind {
  if (typeof value === 'boolean') {
    return 'boolean'
  }
  if (typeof value === 'number') {
    return 'number'
  }
  if (value === null || typeof value === 'object') {
    return 'json'
  }
  return 'string'
}

function formatJsonValue (value: unknown): string {
  if (typeof value === 'string') {
    try {
      return JSON.stringify(JSON.parse(value), null, 2)
    } catch {
      return value
    }
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value ?? '')
  }
}

function toDraftValue (kind: EntityPropertyKind, raw: unknown): string | number | boolean {
  if (kind === 'boolean') {
    return raw === true || raw === 'true'
  }
  if (kind === 'number') {
    return typeof raw === 'number' ? raw : (raw === null || raw === undefined ? '' : String(raw))
  }
  if (kind === 'json') {
    return formatJsonValue(raw)
  }
  return raw === null || raw === undefined ? '' : String(raw)
}

/**
 * 构造抽屉草稿。
 * `name` / `description` 从属性里取出单独编辑；其余属性按模板类型（优先）展开。
 */
export function createEntityDraft (
  entity: Record<string, unknown> | null | undefined,
  propertyDefs: EntityPropertyDefs = {}
): EntityDraft {
  const props = isPlainRecord(entity?.properties) ? entity?.properties as Record<string, unknown> : {}
  const hasName = Object.prototype.hasOwnProperty.call(props, 'name') ||
    Object.prototype.hasOwnProperty.call(propertyDefs, 'name')
  const hasDescription = Object.prototype.hasOwnProperty.call(props, 'description') ||
    Object.prototype.hasOwnProperty.call(propertyDefs, 'description')
  const fallbackName = String(entity?.entity_name ?? entity?.entity_id ?? entity?.id ?? '')

  const properties: EntityPropertyField[] = Object.keys(props)
    .filter((key) => key !== 'name' && key !== 'description')
    .map((key) => {
      const raw = props[key]
      const kind = kindFromSchemaType(propertyDefs[key]?.type) || kindFromValue(raw)
      return { key, kind, value: toDraftValue(kind, raw) }
    })

  return {
    name: hasName ? String(props.name ?? fallbackName) : fallbackName,
    description: hasDescription ? String(props.description ?? '') : '',
    properties,
    hasName,
    hasDescription
  }
}

function parseField (
  field: EntityPropertyField,
  declared: string | undefined,
  errors: Record<string, EntityFieldError>
): unknown {
  if (field.kind === 'json') {
    try {
      const parsed = JSON.parse(String(field.value))
      if (parsed !== null && typeof parsed !== 'object') {
        errors[field.key] = 'jsonType'
      }
      return parsed
    } catch {
      errors[field.key] = 'json'
      return null
    }
  }
  if (field.kind === 'number') {
    const text = String(field.value).trim()
    const value = Number(field.value)
    if (text === '' || !Number.isFinite(value)) {
      errors[field.key] = 'number'
      return null
    }
    if (declared && INTEGER_TYPES.has(String(declared).toUpperCase()) && !Number.isInteger(value)) {
      errors[field.key] = 'integer'
      return null
    }
    return value
  }
  if (field.kind === 'boolean') {
    return field.value === true || field.value === 'true'
  }
  return String(field.value ?? '')
}

/**
 * 校验并解析草稿。
 * 返回的错误是错误码（`json` / `jsonType` / `number` / `integer` / `nameRequired`），
 * 组件层负责翻译。
 */
export function parseEntityDraft (
  draft: EntityDraft,
  propertyDefs: EntityPropertyDefs = {}
): ParsedEntityDraft {
  const errors: Record<string, EntityFieldError> = {}
  const properties: Record<string, unknown> = {}

  draft.properties.forEach((field) => {
    properties[field.key] = parseField(field, propertyDefs[field.key]?.type, errors)
  })

  const name = draft.name.trim()
  if (draft.hasName) {
    properties.name = name
  }
  if (draft.hasDescription) {
    properties.description = draft.description
  }

  return {
    nameError: name ? '' : 'nameRequired',
    errors,
    value: {
      name,
      description: draft.description,
      properties
    }
  }
}

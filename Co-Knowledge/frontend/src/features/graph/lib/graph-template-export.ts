/**
 * 图谱模板「导出/转换」纯函数。
 *
 * 非纯函数留在组件里：downloadZipFile（URL.createObjectURL / document 副作用）、
 * getExportErrorMessage（依赖组件实例 proxy.$t）。
 *
 * 函数体里保留了 `(prop: any)` / `(entity: any)` 回调标注；
 * 对外的参数与返回值都给了明确类型，导出数据结构与
 * `src/assets/template/import_graph_schema_template*.zip` 里的可再导入格式一致。
 */
import JSZip from 'jszip'

/** 实体属性输入（后端 JSON 直通；运行时不做类型校验，只做字段映射） */
export interface EntityPropertyInput {
  name?: string
  type?: string
  desc?: string
  is_primary?: boolean
  is_embedding?: boolean
  is_index?: boolean
}

/** 关系属性输入（与实体属性不同：没有 is_primary） */
export interface EdgePropertyInput {
  name?: string
  type?: string
  desc?: string
  is_embedding?: boolean
  is_index?: boolean
}

/** 实体属性导出项（desc 与三个布尔字段会被补上默认值） */
export interface EntityPropertyExport {
  name?: string
  type?: string
  desc: string
  is_primary: boolean
  is_embedding: boolean
  is_index: boolean
}

/** 关系属性导出项（无 is_primary） */
export interface EdgePropertyExport {
  name?: string
  type?: string
  desc: string
  is_embedding: boolean
  is_index: boolean
}

/** 实体输入 */
export interface SchemaEntityInput {
  entity_type?: string
  entity_desc?: string
  properties?: EntityPropertyInput[] | null
}

/** 关系输入（source/target 是实体类型名，direction 取值如 one-way / two-way / self-loop） */
export interface SchemaEdgeInput {
  edge_type?: string
  edge_desc?: string
  direction?: string
  source_entity?: string
  target_entity?: string
  properties?: EdgePropertyInput[] | null
}

export interface EntityExport {
  entity_type?: string
  entity_desc: string
  properties: EntityPropertyExport[]
}

export interface EdgeExport {
  edge_type?: string
  edge_desc: string
  direction: string
  source_entity?: string
  target_entity?: string
  properties: EdgePropertyExport[]
}

/** 接口返回的模板数据；导出只读取下列字段 */
export interface GraphSchemaData {
  schema_id?: string
  schema_name?: string
  schema_desc?: string
  entities?: SchemaEntityInput[] | null
  edges?: SchemaEdgeInput[] | null
}

/** 模板详情响应（纯 JSON）。 */
export interface GraphSchemaResponse extends GraphSchemaData {
  data?: GraphSchemaData | null
}

/** 导出结果 = 可再导入的 GraphSchema 结构（schema.json 的顶层） */
export interface SchemaExportData {
  schema_id?: string
  schema_name?: string
  schema_desc: string
  entities: EntityExport[]
  edges: EdgeExport[]
}

// 从响应中提取模板数据
export function extractSchemaDataFromResponse (response: GraphSchemaResponse | null | undefined): GraphSchemaData | null {
  if (!response) {
    return null
  }
  if (response.schema_id) {
    return response
  }
  return response.data?.schema_id ? response.data : null
}

// 转换实体属性格式
export function transformEntityProperties (properties: EntityPropertyInput[] | null | undefined): EntityPropertyExport[] {
  return (properties || []).map((prop: any) => ({
    name: prop.name,
    type: prop.type,
    desc: prop.desc || '',
    is_primary: prop.is_primary || false,
    is_embedding: prop.is_embedding || false,
    is_index: prop.is_index || false
  }))
}

// 转换实体格式
export function transformEntities (entities: SchemaEntityInput[] | null | undefined): EntityExport[] {
  return (entities || []).map((entity: any) => ({
    entity_type: entity.entity_type,
    entity_desc: entity.entity_desc || '',
    properties: transformEntityProperties(entity.properties)
  }))
}

// 转换关系属性格式
export function transformEdgeProperties (properties: EdgePropertyInput[] | null | undefined): EdgePropertyExport[] {
  return (properties || []).map((prop: any) => ({
    name: prop.name,
    type: prop.type,
    desc: prop.desc || '',
    is_embedding: prop.is_embedding || false,
    is_index: prop.is_index || false
  }))
}

// 转换关系格式
export function transformEdges (edges: SchemaEdgeInput[] | null | undefined): EdgeExport[] {
  return (edges || []).map((edge: any) => ({
    edge_type: edge.edge_type,
    edge_desc: edge.edge_desc || '',
    direction: edge.direction || 'one-way',
    source_entity: edge.source_entity,
    target_entity: edge.target_entity,
    properties: transformEdgeProperties(edge.properties)
  }))
}

// 将模板数据转换为导出格式
export function transformSchemaDataToExportFormat (schemaData: GraphSchemaData): SchemaExportData {
  return {
    schema_id: schemaData.schema_id,
    schema_name: schemaData.schema_name,
    schema_desc: schemaData.schema_desc || '',
    entities: transformEntities(schemaData.entities),
    edges: transformEdges(schemaData.edges)
  }
}

// 创建ZIP文件
export async function createZipFromExportData (exportData: SchemaExportData): Promise<Blob> {
  const zip = new JSZip()
  const jsonContent = JSON.stringify(exportData, null, 2)
  zip.file('schema.json', jsonContent)
  return await zip.generateAsync({ type: 'blob' })
}

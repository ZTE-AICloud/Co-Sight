/**
 * 图谱域造数/清理。
 *
 * 两条完全不同的建库链路：
 * - `seedGraphByImport`：`/graph/import`（zip 导入），异步落图且**不更新**
 *   `kb_kbase.status`，只能等查询有数据；
 * - `seedGraphByExtract`：`/graph/extract`（文件 + 算子），任务完成后库状态=5。
 *
 * 抽取用官方 `graph_extract` 模板，但 fixture 会给 config 补一个 `schemaId` 参数：
 * 后端只给「声明了 schemaId 的专业算子」传 `schema`，官方模板没声明，原样导入会报
 * `graph_extract() missing 1 required positional argument: 'schema'`。
 */
import JSZip from 'jszip'
import { expect } from '@playwright/test'
import type { ApiClient } from '../api/api-client'
import type { GraphKbRow } from '../api/graph-api'
import { resourceName } from '../env'
import {
  GRAPH_SCHEMA,
  graphExtractOperatorZip,
  graphImportZip
} from './files'

export interface SeededGraph {
  kbId: string
  name: string
}

export interface SeededGraphExtract extends SeededGraph {
  schemaId: string
  operatorId: string | number
}

function sanitize (value: string): string {
  return value.replace(/[^A-Za-z0-9_一-龥]/g, '_')
}

export function uniqueGraphSchema (caseId: string): Record<string, unknown> {
  const token = sanitize(resourceName(caseId).replace(/^E2E-/, ''))
  return {
    ...GRAPH_SCHEMA,
    schema_id: `schema_${token}`.toLowerCase(),
    schema_name: `E2E${token}`,
    schema_desc: `E2E schema for ${caseId}`
  }
}

async function findKbByName (api: ApiClient, name: string): Promise<GraphKbRow> {
  const page = await api.graph.listKbs(name)
  const row = (page?.items || []).find(item => item.name === name)
  if (!row) throw new Error(`图谱知识库未创建：${name}`)
  return row
}

export async function findGraphKbByName (
  api: ApiClient,
  name: string
): Promise<GraphKbRow> {
  return findKbByName(api, name)
}

export async function seedGraphByImport (
  api: ApiClient,
  caseId: string
): Promise<SeededGraph> {
  const name = resourceName(caseId)
  await api.graph.importGraph(await graphImportZip(name))
  const row = await findKbByName(api, name)
  await api.graph.waitForGraphData(row.id)
  // 导入完成后引擎会回写 kb_kbase.status=5；这条断言钉住“列表状态不再恒为 0”。
  await api.graph.waitForReady(row.id)
  return { kbId: row.id, name }
}

/** 空图谱导入：schema 落库、实体/边都是空，用来测空态。 */
export async function seedEmptyGraph (
  api: ApiClient,
  caseId: string
): Promise<SeededGraph> {
  const name = resourceName(caseId)
  const zip = new JSZip()
  zip.file('desc.json', JSON.stringify({
    name,
    desc: 'E2E empty graph',
    embedding: 'e2e-embedding'
  }))
  zip.file('schema.json', JSON.stringify(uniqueGraphSchema(caseId)))
  zip.file('entities.jsonl', '')
  zip.file('edges.jsonl', '')
  await api.graph.importGraph(await zip.generateAsync({ type: 'nodebuffer' }))
  const row = await findKbByName(api, name)
  // schema 是同步写入的；等详情能拿到 schemaInfo 即可打开详情页。
  let detail: Record<string, unknown> | undefined
  for (let attempt = 0; attempt < 30; attempt += 1) {
    detail = await api.graph.detail(row.id)
    if (detail?.schemaInfo) break
    await new Promise(resolve => setTimeout(resolve, 500))
  }
  expect(detail?.schemaInfo, `空图谱 ${name} 未写入 schemaInfo`).toBeTruthy()
  await api.graph.waitForReady(row.id)
  return { kbId: row.id, name }
}

export async function seedGraphSchema (
  api: ApiClient,
  caseId: string
): Promise<Record<string, unknown>> {
  const schema = uniqueGraphSchema(caseId)
  await api.graph.createSchema(schema)
  return schema
}

export interface SeededOperator {
  id: string | number
  name: string
}

export async function seedGraphOperator (
  api: ApiClient,
  caseId: string
): Promise<SeededOperator> {
  const imported = await api.operator.import({
    name: 'graph_extract.zip',
    mimeType: 'application/zip',
    buffer: await graphExtractOperatorZip(caseId)
  }) as { id?: string | number; name?: string } | undefined
  if (!imported?.id) throw new Error('graph_extract 算子导入失败：响应里没有 id')
  return { id: imported.id, name: imported.name || '' }
}

export async function seedGraphByExtract (
  api: ApiClient,
  caseId: string,
  options: {
    schema?: Record<string, unknown>
    operatorId?: string | number
    content?: string
    fileName?: string
  } = {}
): Promise<SeededGraphExtract> {
  const schema = options.schema || await seedGraphSchema(api, caseId)
  const operatorId = options.operatorId
    ?? (await seedGraphOperator(api, caseId)).id
  const name = resourceName(caseId)
  const models = await api.listEmbeddingModels()
  const embeddingModel = models[0] || 'e2e-embedding'
  const content = options.content ?? [
    '# E2E 图谱抽取语料',
    '',
    'Alice 在 Acme 公司担任工程师，Bob 是 Alice 的同事。',
    ''
  ].join('\n')

  const created = await api.graph.extract(
    [{
      name: options.fileName || 'extract.md',
      mimeType: 'text/markdown',
      buffer: Buffer.from(content, 'utf8')
    }],
    {
      name,
      description: `E2E graph extract ${caseId}`,
      category: 10,
      props: { embeddingModel },
      operatorId,
      coverFlag: true,
      schemaId: schema.schema_id,
      kwargs: { llm: 'e2e-llm' }
    }
  )
  const kbId = String(created?.id || '')
  if (!kbId) throw new Error(`图谱抽取未返回库 ID：${JSON.stringify(created)}`)
  await api.graph.waitForExtract(kbId)
  return { kbId, name, schemaId: String(schema.schema_id), operatorId }
}

export async function cleanupGraphExtract (
  api: ApiClient,
  seeded: SeededGraphExtract
): Promise<void> {
  await api.graph.cleanup(seeded.kbId)
  try { await api.operator.delete(seeded.operatorId) } catch { /* best effort */ }
  try { await api.graph.deleteSchema(seeded.schemaId) } catch { /* best effort */ }
}

/** 导出包换个名字、去掉旧 id 后重新打包，供“导出→再导入”使用。 */
export async function renameGraphZip (
  buffer: Buffer,
  name: string
): Promise<Buffer> {
  const source = await JSZip.loadAsync(buffer)
  const zip = new JSZip()
  for (const entry of Object.keys(source.files)) {
    if (entry.endsWith('/')) continue
    zip.file(entry, await source.file(entry)!.async('nodebuffer'))
  }
  const descEntry = source.file('desc.json')
  if (!descEntry) throw new Error('导出的图谱 zip 缺少 desc.json')
  const desc = JSON.parse(await descEntry.async('string'))
  desc.name = name
  delete desc.id
  zip.file('desc.json', JSON.stringify(desc, null, 2))
  return zip.generateAsync({ type: 'nodebuffer' })
}

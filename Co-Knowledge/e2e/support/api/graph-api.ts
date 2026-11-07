import type { ApiClient } from './api-client'
import type { FileInput } from './kb-api'

export interface GraphKbRow {
  id: string
  name: string
  status?: number | string
  description?: string
  [key: string]: unknown
}

export interface GraphQueryResult {
  entities?: Array<Record<string, unknown>>
  edges?: Array<Record<string, unknown>>
  [key: string]: unknown
}

export class GraphApi {
  constructor (private readonly api: ApiClient) {}

  listKbs (keyword = ''): Promise<{ items?: GraphKbRow[]; total?: number }> {
    const query = new URLSearchParams({
      categories: '10', page: '1', size: '100', keyword
    })
    return this.api.get(`/knowledge-bases?${query.toString()}`)
  }

  async findKbByName (name: string): Promise<GraphKbRow | undefined> {
    const page = await this.listKbs(name)
    return (page?.items || []).find(row => row.name === name)
  }

  getKb (id: string): Promise<GraphKbRow> {
    return this.api.get<GraphKbRow>(`/knowledge-bases/${encodeURIComponent(id)}/graph`)
  }

  /** 详情：`{ data, schemaInfo, fileInfo }`（详情页三段内容的原始载荷）。 */
  detail (id: string): Promise<Record<string, unknown>> {
    return this.api.get<Record<string, unknown>>(`/knowledge-bases/${encodeURIComponent(id)}/graph`)
  }

  createKb (payload: {
    name: string
    description?: string
    embeddingModel: string
  }): Promise<GraphKbRow> {
    return this.api.post<GraphKbRow>('/knowledge-bases?type=graph', {
      name: payload.name,
      description: payload.description || 'E2E graph',
      category: 10,
      props: { embeddingModel: payload.embeddingModel }
    })
  }

  deleteKb (id: string): Promise<void> {
    return this.api.del(`/knowledge-bases/${encodeURIComponent(id)}`)
  }

  listFiles (kbId: string): Promise<Array<Record<string, unknown>>> {
    return this.api.get(
      `/knowledge-bases/${encodeURIComponent(kbId)}/documents?page=1&size=100`
    ).then(page => (page as { items?: Array<Record<string, unknown>> })?.items || [])
  }

  importGraph (zip: Buffer): Promise<unknown> {
    return this.api.upload('/graph-imports', 'file', {
      name: 'graph-import.zip',
      mimeType: 'application/zip',
      buffer: zip
    })
  }

  async waitForKbReady (
    kbId: string,
    timeoutMs = 120_000
  ): Promise<GraphKbRow> {
    const deadline = Date.now() + timeoutMs
    let last: GraphKbRow | undefined
    while (Date.now() < deadline) {
      const page = await this.listKbs()
      last = (page?.items || []).find(row => row.id === kbId)
      if (last) {
        const status = Number(last.status)
        if (status === 1) return last
        if (status === 2) throw new Error(`图谱库 ${kbId} 生成失败: ${JSON.stringify(last)}`)
      }
      await new Promise(resolve => setTimeout(resolve, 1_000))
    }
    throw new Error(`图谱库 ${kbId} 未在 ${timeoutMs / 1000}s 内就绪：${JSON.stringify(last)}`)
  }

  query (
    kbId: string,
    options: {
      queryType?: 'entity' | 'relation' | 'subgraph' | 'edge' | 'sub_graph' | ''
      filters?: Array<Record<string, unknown>>
      limit?: number
      depth?: number
      direction?: string
    } = {}
  ): Promise<GraphQueryResult> {
    const mapped = options.queryType === 'relation'
      ? 'edge'
      : options.queryType === 'subgraph'
        ? 'sub_graph'
        : options.queryType || ''
    return this.api.post<GraphQueryResult>(
      `/knowledge-bases/${encodeURIComponent(kbId)}/graph/query`,
      {
        limit: options.limit ?? 100,
        depth: options.depth ?? 10,
        direction: options.direction || 'both',
        query_type: mapped,
        filters: options.filters || []
      }
    )
  }

  createEntity (
    kbId: string,
    entityId: string,
    entityType: string,
    properties: Record<string, unknown>
  ): Promise<unknown> {
    return this.api.post(
      `/knowledge-bases/${encodeURIComponent(kbId)}/graph/entities`,
      { entityId, entityType, properties }
    )
  }

  updateEntity (
    kbId: string,
    entityId: string,
    entityType: string,
    properties: Record<string, unknown>
  ): Promise<unknown> {
    return this.api.patch(
      `/knowledge-bases/${encodeURIComponent(kbId)}/graph/entities/${encodeURIComponent(entityId)}`,
      { entityType, properties }
    )
  }

  deleteEntity (kbId: string, entityId: string, entityType: string): Promise<unknown> {
    return this.api.request('DELETE',
      `/knowledge-bases/${encodeURIComponent(kbId)}/graph/entities/${encodeURIComponent(entityId)}`,
      { params: { entityType } })
  }

  createEdge (
    kbId: string,
    edgeId: string,
    edgeType: string,
    sourceId: string,
    targetId: string,
    properties: Record<string, unknown> = {}
  ): Promise<unknown> {
    return this.api.post(
      `/knowledge-bases/${encodeURIComponent(kbId)}/graph/edges`,
      { edgeId, edgeType, sourceId, targetId, properties }
    )
  }

  updateEdge (
    kbId: string,
    edgeId: string,
    edgeType: string,
    properties: Record<string, unknown>
  ): Promise<unknown> {
    return this.api.patch(
      `/knowledge-bases/${encodeURIComponent(kbId)}/graph/edges/${encodeURIComponent(edgeId)}`,
      { edgeType, properties }
    )
  }

  deleteEdge (kbId: string, edgeId: string, edgeType: string): Promise<unknown> {
    return this.api.request('DELETE',
      `/knowledge-bases/${encodeURIComponent(kbId)}/graph/edges/${encodeURIComponent(edgeId)}`,
      { params: { edgeType } })
  }

  listSchemas (): Promise<Array<Record<string, unknown>>> {
    return this.api.get<Array<Record<string, unknown>>>('/graph-schemas')
      .then(rows => rows || [])
  }

  createSchema (schema: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.api.post('/graph-schemas', schema)
  }

  deleteSchema (schemaId: string): Promise<unknown> {
    return this.api.del(`/graph-schemas/${encodeURIComponent(schemaId)}`)
  }

  exportStatus (kbId: string): Promise<{ status: number; contentType: string }> {
    return this.api.fetchRaw(
      `/knowledge-bases/${encodeURIComponent(kbId)}/graph/export`,
      { method: 'GET' }
    ).then(response => ({
      status: response.status(),
      contentType: response.headers()['content-type'] || ''
    }))
  }

  extract (
    files: FileInput[],
    data: Record<string, unknown>
  ): Promise<Record<string, unknown>> {
    return this.api.uploadMany('/graph-extractions', 'file', files, {
      data: JSON.stringify(data)
    }).then(result => (result || {}) as Record<string, unknown>)
  }

  /**
   * 等导入真正落图。
   *
   * ⚠️ `/graph/import` 是异步的，且**不会**把 `kb_kbase.status` 推到就绪：
   * 它只更新 `graph_import_tasks`（实测导入完成后库状态仍为 0=已创建）。所以这里
   * 以「查询能返回实体」为判据，不能等 status。
   */
  async waitForGraphData (
    kbId: string,
    timeoutMs = 120_000
  ): Promise<GraphQueryResult> {
    const deadline = Date.now() + timeoutMs
    let last: unknown
    while (Date.now() < deadline) {
      try {
        const result = await this.query(kbId, { queryType: 'entity' })
        last = result
        if ((result?.entities || []).length > 0) return result
      } catch (error) {
        last = error
      }
      await new Promise(resolve => setTimeout(resolve, 1_000))
    }
    throw new Error(`图谱库 ${kbId} 未在 ${timeoutMs / 1000}s 内导入出数据：${JSON.stringify(last)}`)
  }

  /** 等导入/抽取把库推到指定状态（默认 5=已就绪）。 */
  async waitForReady (
    kbId: string,
    expected = 5,
    timeoutMs = 120_000
  ): Promise<GraphKbRow> {
    const deadline = Date.now() + timeoutMs
    let last: GraphKbRow | undefined
    while (Date.now() < deadline) {
      const page = await this.listKbs()
      last = (page?.items || []).find(row => row.id === kbId)
      if (last && Number(last.status) === expected) return last
      await new Promise(resolve => setTimeout(resolve, 500))
    }
    throw new Error(`图谱库 ${kbId} 未在 ${timeoutMs / 1000}s 内到达状态 ${expected}：${JSON.stringify(last)}`)
  }

  /** 等抽取任务把库推到终态（5=就绪；101/102/103/104=失败）。 */
  async waitForExtract (
    kbId: string,
    timeoutMs = 300_000
  ): Promise<GraphKbRow> {
    const deadline = Date.now() + timeoutMs
    let last: GraphKbRow | undefined
    while (Date.now() < deadline) {
      const page = await this.listKbs()
      last = (page?.items || []).find(row => row.id === kbId)
      if (last) {
        const status = Number(last.status)
        if (status === 5) return last
        if ([101, 102, 103, 104].includes(status)) {
          throw new Error(
            `图谱抽取失败（status=${status}）：${last.failReason || '无失败原因'}`
          )
        }
      }
      await new Promise(resolve => setTimeout(resolve, 1_000))
    }
    throw new Error(`图谱库 ${kbId} 未在 ${timeoutMs / 1000}s 内完成抽取：${JSON.stringify(last)}`)
  }

  /** 导出 zip（`POST /graph/export`，响应是 octet-stream）。 */
  async exportZip (kbId: string): Promise<Buffer> {
    const response = await this.api.fetchRaw(
      `/knowledge-bases/${encodeURIComponent(kbId)}/graph/export`,
      { method: 'GET' }
    )
    if (!response.ok()) {
      throw new Error(`图谱导出失败：HTTP ${response.status()}`)
    }
    const contentType = response.headers()['content-type'] || ''
    if (!contentType.includes('octet-stream') && !contentType.includes('zip')) {
      throw new Error(`图谱导出返回了非 zip 内容：${contentType}`)
    }
    return response.body()
  }

  async cleanup (kbId: string): Promise<void> {
    try { await this.deleteKb(kbId) } catch { /* best effort */ }
  }
}

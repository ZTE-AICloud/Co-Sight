import type { ApiClient } from './api-client'

export type ModelKind = 'llm' | 'embedding' | 'rerank'

export interface ModelRecord {
  modelId: string
  modelKind: ModelKind
  modelName: string
  displayName?: string
  apiModel?: string
  baseUrl?: string
  apiKeyMasked?: string
  hasApiKey?: boolean
  chatPath?: string
  embeddingsPath?: string
  modelsPath?: string
  rerankPath?: string
  dimension?: number | null
  enabled?: boolean
  [key: string]: unknown
}

export interface ModelPayload {
  modelKind: ModelKind
  modelName: string
  displayName?: string
  apiModel?: string
  baseUrl: string
  apiKey?: string
  chatPath?: string
  embeddingsPath?: string
  modelsPath?: string
  rerankPath?: string
  dimension?: number
  maxTokens?: number
  temperature?: number
  timeout?: number
  remark?: string
  enabled?: boolean
  isDefault?: boolean
}

export class ModelApi {
  constructor (private readonly api: ApiClient) {}

  async list (kind?: ModelKind): Promise<ModelRecord[]> {
    const query = kind ? `?kind=${kind}&currentPage=1&pageSize=100` : '?currentPage=1&pageSize=100'
    const page = await this.api.get<{ items?: ModelRecord[]; total?: number }>(`/models${query}`)
    return page?.items || []
  }

  get (modelId: string): Promise<ModelRecord> {
    return this.api.get<ModelRecord>(`/models/${encodeURIComponent(modelId)}`)
  }

  create (payload: ModelPayload): Promise<ModelRecord> {
    return this.api.post<ModelRecord>('/models', payload)
  }

  update (modelId: string, payload: Partial<ModelPayload>): Promise<ModelRecord> {
    return this.api.put<ModelRecord>(`/models/${encodeURIComponent(modelId)}`, payload)
  }

  delete (modelId: string): Promise<unknown> {
    return this.api.del(`/models/${encodeURIComponent(modelId)}`)
  }

  test (modelId: string, payload: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    return this.api.post(`/models/${encodeURIComponent(modelId)}/test`, payload)
  }

  testConfig (payload: ModelPayload): Promise<Record<string, unknown>> {
    return this.api.post('/models/test', payload)
  }

  async findByName (kind: ModelKind, modelName: string): Promise<ModelRecord | undefined> {
    return (await this.list(kind)).find(row => row.modelName === modelName)
  }
}

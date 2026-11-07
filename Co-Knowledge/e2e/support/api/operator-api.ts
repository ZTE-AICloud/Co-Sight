import type { ApiClient } from './api-client'

export interface OperatorRow {
  id: string | number
  name?: string
  nameEn?: string
  module?: string
  visibleRange?: string
  isPublished?: boolean | number
  [key: string]: unknown
}

export class OperatorApi {
  constructor (private readonly api: ApiClient) {}

  list (params: {
    currentPage?: number
    pageSize?: number
    keyword?: string
    visibleRange?: string
    module?: string
  } = {}): Promise<{ items?: OperatorRow[]; total?: number }> {
    const query = new URLSearchParams({
      page: String(params.currentPage ?? 1),
      size: String(params.pageSize ?? 100),
      keyword: params.keyword || ''
    })
    if (params.visibleRange) query.set('visibility', params.visibleRange)
    if (params.module) query.set('module', params.module)
    return this.api.get(`/operators?${query.toString()}`)
  }

  async findAll (): Promise<OperatorRow[]> {
    const page = await this.list({ currentPage: 1, pageSize: 100 })
    return page?.items || []
  }

  async findByName (name: string): Promise<OperatorRow | undefined> {
    return (await this.findAll()).find(row => row.name === name || row.nameEn === name)
  }

  import (file: { name: string; mimeType: string; buffer: Buffer }): Promise<unknown> {
    return this.api.upload('/operators', 'file', file)
  }

  delete (id: string | number): Promise<unknown> {
    return this.api.del(`/operators/${id}`)
  }

  publish (id: string | number): Promise<unknown> {
    return this.api.post(`/operators/${id}/publish`)
  }

  unpublish (id: string | number): Promise<unknown> {
    return this.api.del(`/operators/${id}/publish`)
  }

  makePublic (id: string | number): Promise<unknown> {
    return this.api.put(`/operators/${id}/visibility`, { public: true })
  }

  makePrivate (id: string | number): Promise<unknown> {
    return this.api.put(`/operators/${id}/visibility`, { public: false })
  }

  types (): Promise<Array<Record<string, unknown>>> {
    return this.api.get<Array<Record<string, unknown>>>('/operators/types')
  }

  async exportStatus (id: string | number): Promise<{ status: number; contentType: string }> {
    const response = await this.api.fetchRaw(`/operators/${id}/export`, { method: 'GET' })
    return {
      status: response.status(),
      contentType: response.headers()['content-type'] || ''
    }
  }
}

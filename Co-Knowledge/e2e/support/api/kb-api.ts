/**
 * 知识库/目录/文件/切片 API。
 *
 * 只封装 E2E 需要的造数与清理路径；业务断言留在 spec。
 */
import type { ApiClient } from './api-client'

export interface FileInput {
  name: string
  mimeType: string
  buffer: Buffer
}

export interface KbRecord {
  id: string
  name: string
  tableName?: string
  embeddingModel?: string
  category?: number
  status?: number | string
  [key: string]: unknown
}

export interface DirectoryRow {
  id: string
  title?: string
  type?: string
  [key: string]: unknown
}

export interface FileRow {
  id: string
  title?: string
  name?: string
  status: number
  kType?: string
  failReason?: string
  errorMsg?: string
  [key: string]: unknown
}

export interface ChunkRow {
  id?: string
  chunkId?: string
  content?: string
  text?: string
  source?: string
  [key: string]: unknown
}

const SYSTEM_ARGS = [
  { argName: 'maxWordCount', argType: 'int', defaultValue: 512 },
  { argName: 'overlap', argType: 'int', defaultValue: 128 }
]

const MIME_BY_FORMAT: Record<string, string> = {
  md: 'text/markdown',
  txt: 'text/plain',
  pdf: 'application/pdf',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
}

export class KbApi {
  constructor (private readonly api: ApiClient) {}

  async list (): Promise<KbRecord[]> {
    const page = await this.api.get<{ items?: KbRecord[] }>(
      '/knowledge-bases?page=1&size=500&keyword=&categories=1,10'
    )
    return page?.items || []
  }

  search (params: Record<string, unknown>): Promise<Record<string, unknown>> {
    const query = new URLSearchParams({
      page: String(params.currentPage ?? params.page ?? 1),
      size: String(params.pageSize ?? params.size ?? 10),
      keyword: String(params.keyword ?? '')
    })
    const categories = params.categories
    if (Array.isArray(categories)) query.set('categories', categories.join(','))
    return this.api.get(`/knowledge-bases?${query.toString()}`)
  }

  async findByName (name: string): Promise<KbRecord | undefined> {
    const rows = await this.list()
    return rows.find(row => row.name === name)
  }

  get (id: string): Promise<KbRecord> {
    return this.api.get<KbRecord>(`/knowledge-bases/${encodeURIComponent(id)}`)
  }

  create (payload: Record<string, unknown>): Promise<KbRecord> {
    return this.api.post<KbRecord>('/knowledge-bases', payload)
  }

  createV2 (payload: Record<string, unknown>): Promise<KbRecord> {
    return this.api.post<KbRecord>('/knowledge-bases?type=graph', payload)
  }

  updateV2 (id: string, payload: Record<string, unknown>): Promise<unknown> {
    return this.api.patch(`/knowledge-bases/${encodeURIComponent(id)}`, payload)
  }

  delete (id: string): Promise<void> {
    return this.api.del(`/knowledge-bases/${encodeURIComponent(id)}`)
  }

  deleteV2 (id: string): Promise<void> {
    return this.api.del(`/knowledge-bases/${encodeURIComponent(id)}`)
  }

  async judgeEmpty (id: string): Promise<boolean> {
    const rows = await this.list()
    const row = rows.find(item => item.id === id)
    return Number(row?.currentFileCount ?? 0) === 0
  }

  directoryChildren (kbId: string): Promise<DirectoryRow[]> {
    return this.api.get<DirectoryRow[]>(
      `/knowledge-bases/${encodeURIComponent(kbId)}/directories?type=folder&sort=true`
    ).then(rows => rows || [])
  }

  async defaultDirectoryId (kbId: string): Promise<string> {
    const rows = await this.directoryChildren(kbId)
    const folder = rows.find(row => row.id)
    if (!folder) throw new Error(`知识库 ${kbId} 没有默认目录`)
    return folder.id
  }

  createDirectory (kbId: string, title: string, parentId?: string): Promise<DirectoryRow> {
    return this.api.post<DirectoryRow>(
      `/knowledge-bases/${encodeURIComponent(kbId)}/directories`,
      { title, parentId }
    )
  }

  async listAllFiles (kbId: string): Promise<FileRow[]> {
    const page = await this.api.get<{ items?: FileRow[] }>(
      `/knowledge-bases/${encodeURIComponent(kbId)}/documents?page=1&size=100`
    )
    return page?.items || []
  }

  /** 上传文件；系统算子 -1 的 args 必须逐项给全（README 的硬约束）。 */
  async uploadFile (
    kbId: string,
    directoryId: string,
    file: FileInput,
    format: string,
    coverFlag = false
  ): Promise<string> {
    const metadata = {
      kType: 'document',
      directoryId,
      coverFlag,
      splitType: 'system',
      parseOperator: {},
      splitOperator: {
        [format]: {
          operatorId: -1,
          fileFormat: format,
          args: SYSTEM_ARGS
        }
      }
    }
    return this.uploadWithMetadata(kbId, file, metadata)
  }

  async uploadWithCustomOperator (
    kbId: string,
    directoryId: string,
    file: FileInput,
    format: string,
    operatorId: number,
    args: Array<Record<string, unknown>> = [],
    coverFlag = false
  ): Promise<string> {
    const metadata = {
      kType: 'document',
      directoryId,
      coverFlag,
      splitType: 'custom',
      parseOperator: {},
      splitOperator: {
        [format]: { operatorId, fileFormat: format, args }
      }
    }
    return this.uploadWithMetadata(kbId, file, metadata)
  }

  /** 直接传 metadata，用于验证参数缺失/非法等负向路径。 */
  async uploadRaw (
    kbId: string,
    file: FileInput,
    metadata: Record<string, unknown>
  ): Promise<string> {
    return this.uploadWithMetadata(kbId, file, metadata)
  }

  async deleteFile (kbId: string, fileId: string): Promise<void> {
    await this.api.del(
      `/knowledge-bases/${encodeURIComponent(kbId)}/documents/${encodeURIComponent(fileId)}`
    )
  }

  private async uploadWithMetadata (
    kbId: string,
    file: FileInput,
    metadata: Record<string, unknown>
  ): Promise<string> {
    const result = await this.api.upload(
      `/knowledge-bases/${encodeURIComponent(kbId)}/documents`,
      'files',
      file,
      { metadata: JSON.stringify(metadata) }
    ) as Record<string, string>
    const fileId = result?.[file.name]
    if (!fileId) {
      throw new Error(`上传响应里没有 ${file.name} 的 fileId: ${JSON.stringify(result)}`)
    }
    return fileId
  }

  async waitForFile (
    kbId: string,
    fileName: string,
    timeoutMs = 180_000
  ): Promise<FileRow> {
    const deadline = Date.now() + timeoutMs
    let last: FileRow | undefined
    while (Date.now() < deadline) {
      const files = await this.listAllFiles(kbId)
      last = files.find(row => (row.title || row.name) === fileName)
      if (last) {
        if (last.status === 1) return last
        if (last.status === 2) {
          throw new Error(
            `文件导入失败: ${fileName} (${last.failReason || last.errorMsg || '无原因'})`
          )
        }
      }
      await new Promise(resolve => setTimeout(resolve, 1_000))
    }
    throw new Error(
      `文件 ${fileName} 在 ${timeoutMs / 1000}s 内未导入成功；最后状态: ${JSON.stringify(last)}`
    )
  }

  async createWithFile (options: {
    name: string
    embeddingModel: string
    description?: string
    fileName: string
    content: string | Buffer
    format: string
    operatorId?: number
    operatorArgs?: Array<Record<string, unknown>>
  }): Promise<{ kbId: string; directoryId: string; fileId: string; fileName: string }> {
    const kb = await this.create({
      name: options.name,
      description: options.description || 'E2E',
      props: { embeddingModel: options.embeddingModel }
    })
    const directoryId = await this.defaultDirectoryId(kb.id)
    const format = options.format.toLowerCase()
    const file: FileInput = {
      name: options.fileName,
      mimeType: MIME_BY_FORMAT[format] || 'application/octet-stream',
      buffer: Buffer.isBuffer(options.content) ? options.content : Buffer.from(options.content, 'utf8')
    }
    const fileId = options.operatorId
      ? await this.uploadWithCustomOperator(
        kb.id, directoryId, file, format, options.operatorId, options.operatorArgs || []
      )
      : await this.uploadFile(kb.id, directoryId, file, format)
    await this.waitForFile(kb.id, options.fileName)
    return { kbId: kb.id, directoryId, fileId, fileName: options.fileName }
  }

  async chunks (
    kbId: string,
    fileId?: string,
    pageSize = 100
  ): Promise<{ items?: ChunkRow[]; total?: number }> {
    if (fileId) {
      return this.api.get(
        `/knowledge-bases/${encodeURIComponent(kbId)}/documents/` +
        `${encodeURIComponent(fileId)}/chunks?page=1&size=${pageSize}`
      )
    }
    return this.api.get(
      `/knowledge-bases/${encodeURIComponent(kbId)}/chunks?page=1&size=${pageSize}`
    )
  }

  /** 尽力清理：先删文件再删库；失败不掩盖原始测试失败。 */
  async cleanup (kbId: string): Promise<void> {
    try {
      const files = await this.listAllFiles(kbId)
      for (const file of files) {
        try { await this.api.del(`/knowledge-bases/${kbId}/documents/${file.id}`) } catch { /* best effort */ }
      }
    } catch { /* best effort */ }
    try { await this.delete(kbId) } catch { /* best effort */ }
  }
}

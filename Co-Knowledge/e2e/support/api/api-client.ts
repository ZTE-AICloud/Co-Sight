/**
 * RKB HTTP API 客户端。
 *
 * 用途：E2E 的**造数/清理**走这里，UI 只走被测算子。
 * RKB API 是纯 JSON + RFC 9457 problem 错误：
 *   - 2xx：body 就是资源 / 数组 / `{items,total,page,pageSize}`；
 *   - 4xx/5xx：`application/problem+json`，读取 `code` 与 `detail`。
 *
 * 所有方法失败时抛 `ApiError`，消息里带 method + path + 响应体片段，避免只看到
 * "expect(received).toBe..."。
 */
import type { APIRequestContext, APIResponse } from '@playwright/test'
import { env } from '../env'
import { KbApi, type FileInput } from './kb-api'
import { FlowApi } from './flow-api'
import { OperatorApi } from './operator-api'
import { GraphApi } from './graph-api'
import { ModelApi } from './model-api'

const PREFIX = '/api/co-knowledge/v1'

export interface KbRow {
  id: string
  name: string
  tableName?: string
  embeddingModel?: string
  status?: number | string
  [key: string]: unknown
}

export interface FileRow {
  id: string
  /** 列表接口返回的是 `title`；`name` 仅用于部分旧响应。 */
  title?: string
  name?: string
  status: number
  failReason?: string
  errorMsg?: string
  [key: string]: unknown
}

export interface SearchHit {
  content?: string
  score?: number
  source?: string
  metadata?: Record<string, unknown>
  [key: string]: unknown
}

export interface SearchGroup {
  baseName?: string
  docs: SearchHit[]
  [key: string]: unknown
}

export interface ModelRow {
  modelId: string
  modelKind: string
  modelName: string
  displayName?: string
  baseUrl?: string
  [key: string]: unknown
}

export interface UploadResult {
  kbId: string
  directoryId: string
  fileId: string
  fileName: string
}

export class ApiError extends Error {
  constructor (
    message: string,
    readonly method: string,
    readonly path: string,
    readonly status: number,
    readonly body: string,
    readonly code: string = 'http_error',
    readonly detail: string = ''
  ) {
    super(`${message} [${method} ${path} -> ${status}] ${body.slice(0, 500)}`)
    this.name = 'ApiError'
  }
}

export class ApiClient {
  readonly kb: KbApi
  readonly flow: FlowApi
  readonly operator: OperatorApi
  readonly graph: GraphApi
  readonly model: ModelApi

  constructor (
    private readonly context: APIRequestContext,
    readonly baseURL: string
  ) {
    this.kb = new KbApi(this)
    this.flow = new FlowApi(this)
    this.operator = new OperatorApi(this)
    this.graph = new GraphApi(this)
    this.model = new ModelApi(this)
  }

  private url (path: string): string {
    if (/^https?:\/\//.test(path)) return path
    return path.startsWith(PREFIX) ? path : `${PREFIX}${path}`
  }

  private async send (
    method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
    path: string,
    options: Parameters<APIRequestContext['fetch']>[1] = {}
  ): Promise<unknown> {
    // AUTH_MODE=local 的 CSRF 纵深要求 unsafe 请求带匹配的 Origin；
    // 浏览器会自动带，Playwright 的 APIRequestContext 不会。
    const headers = env.authMode === 'local' && !['GET', 'HEAD'].includes(method)
      ? { Origin: env.baseURL, ...(options.headers as Record<string, string> | undefined) }
      : options.headers
    const response: APIResponse = await this.context.fetch(this.url(path), {
      // 后端是单进程：批量/抽取任务在跑时，偶发把简单 GET 拖过 15s（ISSUE-OPS-002）。
      // 造数请求给足 60s；调用方仍可用 options.timeout 覆盖。
      timeout: 60_000,
      method,
      ...options,
      headers
    })
    const text = await response.text()
    let body: unknown = text
    try {
      body = text ? JSON.parse(text) : null
    } catch {
      // 非 JSON（健康检查纯文本、文件流）保留原文
    }
    if (!response.ok()) {
      const problem = (body && typeof body === 'object')
        ? body as Record<string, unknown>
        : {}
      const code = String(problem.code || 'http_error')
      const detail = String(problem.detail || '')
      throw new ApiError(
        `HTTP ${response.status()} ${code}${detail ? `: ${detail}` : ''}`,
        method, path, response.status(), text, code, detail
      )
    }
    if (response.status() === 204) {
      return null
    }
    return body
  }

  get<T> (path: string): Promise<T> {
    return this.send('GET', path) as Promise<T>
  }

  post<T> (path: string, data?: unknown): Promise<T> {
    return this.send('POST', path, { data }) as Promise<T>
  }

  put<T> (path: string, data?: unknown): Promise<T> {
    return this.send('PUT', path, { data }) as Promise<T>
  }

  patch<T> (path: string, data?: unknown): Promise<T> {
    return this.send('PATCH', path, { data }) as Promise<T>
  }

  del<T> (path: string): Promise<T> {
    return this.send('DELETE', path) as Promise<T>
  }

  /** 子 API 用：返回解包后的载荷；失败抛 ApiError。 */
  request<T> (
    method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
    path: string,
    options: Parameters<APIRequestContext['fetch']>[1] = {}
  ): Promise<T> {
    return this.send(method, path, options) as Promise<T>
  }

  /** 需要状态码/响应头/二进制时用；调用方自己处理错误。 */
  fetchRaw (
    path: string,
    options: Parameters<APIRequestContext['fetch']>[1] = {}
  ): Promise<APIResponse> {
    return this.context.fetch(this.url(path), options)
  }

  /** 单文件 multipart。字段名由端点决定（`file` / `files`）。 */
  upload (
    path: string,
    fieldName: string,
    file: FileInput,
    fields: Record<string, string> = {}
  ): Promise<unknown> {
    return this.send('POST', path, {
      multipart: { [fieldName]: file, ...fields }
    })
  }

  /**
   * 多文件 multipart。
   *
   * Playwright 的 `multipart` 类型只接受单文件；同名多文件需要 FormData，
   * 而 APIRequestContext 不直接吃 FormData。E2E 的图谱抽取只传一篇语料即可，
   * 多文件导入走 `/file/upload` 的逐个上传。
   */
  uploadMany (
    path: string,
    fieldName: string,
    files: FileInput[],
    fields: Record<string, string> = {}
  ): Promise<unknown> {
    if (files.length !== 1) {
      throw new Error('uploadMany 目前只支持单文件（Playwright multipart 限制）')
    }
    return this.upload(path, fieldName, files[0], fields)
  }

  // ------------------------------------------------------------------
  // 健康检查
  // ------------------------------------------------------------------

  async health (): Promise<string> {
    return this.get<string>('/health')
  }

  // ------------------------------------------------------------------
  // 知识库 / 目录 / 文件
  // ------------------------------------------------------------------

  async listKbs (): Promise<KbRow[]> {
    const page = await this.get<{ items?: KbRow[] }>(
      '/knowledge-bases?page=1&size=500&keyword=&categories=1,10'
    )
    return page?.items || []
  }

  async listEmbeddingModels (): Promise<string[]> {
    const rows = await this.get<string[]>('/system/embedding-models')
    return Array.isArray(rows) ? rows : []
  }

  async findKbByName (name: string): Promise<KbRow | undefined> {
    return (await this.listKbs()).find(row => row.name === name)
  }

  async createKb (name: string, embeddingModel: string, description = 'E2E'): Promise<KbRow> {
    // ⚠️ 不要传 kbtype：让服务端使用默认值（新库统一写 type='document'）。
    return this.post<KbRow>('/knowledge-bases', {
      name,
      description,
      props: { embeddingModel }
    })
  }

  async deleteKb (kbId: string): Promise<void> {
    await this.del(`/knowledge-bases/${encodeURIComponent(kbId)}`)
  }

  async defaultDirectoryId (kbId: string): Promise<string> {
    const rows = await this.get<Array<{ id: string; title?: string }>>(
      `/knowledge-bases/${encodeURIComponent(kbId)}/directories?type=folder&sort=true`
    )
    const folder = (rows || []).find(row => row.id)
    if (!folder) throw new Error(`知识库 ${kbId} 没有默认目录`)
    return folder.id
  }

  async listAllFiles (kbId: string): Promise<FileRow[]> {
    // MAX_PAGE_SIZE = 100；传 500 会被 _page_params 判成 0004（request.invalid）。
    const page = await this.get<{ items?: FileRow[] }>(
      `/knowledge-bases/${encodeURIComponent(kbId)}/documents?page=1&size=100`
    )
    return page?.items || []
  }

  async deleteFile (kbId: string, fileId: string): Promise<void> {
    await this.del(
      `/knowledge-bases/${encodeURIComponent(kbId)}/documents/${encodeURIComponent(fileId)}`
    )
  }

  async listChunks (
    kbId: string,
    pageSize = 100
  ): Promise<{ items?: Array<Record<string, unknown>>; total?: number }> {
    return this.get(
      `/knowledge-bases/${encodeURIComponent(kbId)}/chunks?page=1&size=${pageSize}`
    )
  }

  async uploadMarkdown (
    kbId: string,
    directoryId: string,
    fileName: string,
    content: string
  ): Promise<string> {
    const metadata = {
      kType: 'document',
      directoryId,
      splitType: 'system',
      parseOperator: {},
      splitOperator: {
        md: {
          operatorId: -1,
          fileFormat: 'md',
          args: [
            { argName: 'maxWordCount', argType: 'int', defaultValue: 512 },
            { argName: 'overlap', argType: 'int', defaultValue: 128 }
          ]
        }
      }
    }
    const result = await this.send('POST', `/knowledge-bases/${encodeURIComponent(kbId)}/documents`, {
      multipart: {
        files: {
          name: fileName,
          mimeType: 'text/markdown',
          buffer: Buffer.from(content, 'utf8')
        },
        metadata: JSON.stringify(metadata)
      }
    }) as Record<string, string>
    const fileId = result?.[fileName]
    if (!fileId) {
      throw new Error(`上传响应里没有 ${fileName} 的 fileId: ${JSON.stringify(result)}`)
    }
    return fileId
  }

  /**
   * 轮询文件状态直到成功/失败。
   *
   * 状态口径（见 directory_service.py）：0=进行中，1=成功，2=失败。
   * 超时时间留给异步解析/切分/向量化/ES 索引。
   */
  async waitForFile (
    kbId: string,
    fileName: string,
    timeoutMs = 180_000
  ): Promise<FileRow> {
    const deadline = Date.now() + timeoutMs
    let last: FileRow | undefined
    while (Date.now() < deadline) {
      const files = await this.listAllFiles(kbId)
      // 目录列表接口把文件名放在 `title`，不是 `name`。按 name 匹配会导致
      // 导入早已成功、轮询却永远找不到文件（表现为整条用例超时）。
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

  /** 建库 + 上传一篇带唯一标记的 md，等待导入完成。 */
  async createKbWithMarkdown (
    name: string,
    embeddingModel: string,
    fileName: string,
    content: string
  ): Promise<UploadResult> {
    const kb = await this.createKb(name, embeddingModel)
    const directoryId = await this.defaultDirectoryId(kb.id)
    const fileId = await this.uploadMarkdown(kb.id, directoryId, fileName, content)
    await this.waitForFile(kb.id, fileName)
    return { kbId: kb.id, directoryId, fileId, fileName }
  }

  /** 尽力清理：先删文件再删库；任何一步失败都不掩盖原始测试失败。 */
  async cleanupKb (kbId: string): Promise<void> {
    try {
      const files = await this.listAllFiles(kbId)
      for (const file of files) {
        try { await this.deleteFile(kbId, file.id) } catch { /* best effort */ }
      }
    } catch { /* best effort */ }
    try { await this.deleteKb(kbId) } catch { /* best effort */ }
  }

  // ------------------------------------------------------------------
  // 检索
  // ------------------------------------------------------------------

  async retrieve (options: {
    question: string
    kbId: string
    type?: 0 | 1
    topK?: number
    scoreThreshold?: number
  }): Promise<SearchGroup[]> {
    const groups = await this.post<SearchGroup[]>('/retrieval', {
      question: options.question,
      type: options.type ?? 0,
      bases: [{
        baseList: [`doc_${options.kbId}`],
        priority: 0,
        topK: options.topK ?? 8,
        scoreThreshold: options.scoreThreshold ?? 0
      }]
    })
    return Array.isArray(groups) ? groups : []
  }

  // ------------------------------------------------------------------
  // 检索编排
  // ------------------------------------------------------------------

  async createWorkflow (options: {
    name: string
    workFlowId: string
    template?: 'Sequential' | 'Blended' | 'Conditional'
    knowledgeType?: string
    description?: string
    boundInfo: Record<string, unknown>
  }): Promise<Record<string, unknown>> {
    return this.post<Record<string, unknown>>('/workflows', {
      name: options.name,
      workFlowId: options.workFlowId,
      template: options.template || 'Blended',
      knowledgeType: options.knowledgeType || 'knowledgeBase',
      description: options.description || 'E2E',
      boundInfo: options.boundInfo
    })
  }

  async publishFlow (workFlowId: string): Promise<unknown> {
    return this.post(`/workflows/${encodeURIComponent(workFlowId)}/publication`)
  }

  async listWorkflows (): Promise<Array<Record<string, unknown>>> {
    const page = await this.get<{ items?: Array<Record<string, unknown>> }>(
      '/workflows?page=1&size=100'
    )
    return page?.items || []
  }

  async deleteWorkflow (workFlowId: string): Promise<void> {
    await this.del(`/workflows/${encodeURIComponent(workFlowId)}`)
  }

  async waitForWorkflowPublished (
    workFlowId: string,
    timeoutMs = 30_000
  ): Promise<Record<string, unknown>> {
    const deadline = Date.now() + timeoutMs
    let last: Record<string, unknown> | undefined
    while (Date.now() < deadline) {
      const rows = await this.listWorkflows()
      last = rows.find(row => row.workFlowId === workFlowId)
      if (last && Number(last.publishType) !== 0) return last
      await new Promise(resolve => setTimeout(resolve, 500))
    }
    throw new Error(`工作流 ${workFlowId} 在 ${timeoutMs / 1000}s 内未发布：${JSON.stringify(last)}`)
  }

  // ------------------------------------------------------------------
  // 模型
  // ------------------------------------------------------------------

  async listModels (kind?: 'llm' | 'embedding' | 'rerank'): Promise<ModelRow[]> {
    const query = kind ? `?kind=${kind}` : ''
    const page = await this.get<{ items?: ModelRow[] }>(`/models${query}`)
    return page?.items || []
  }

  // ------------------------------------------------------------------
  // fake-model-gateway 控制面（宿主端口）
  // ------------------------------------------------------------------

  async mockReset (): Promise<void> {
    const response = await this.context.post(`${this.mockBaseURL()}/__mock__/reset`)
    if (!response.ok()) throw new Error(`mock reset 失败: ${response.status()}`)
  }

  async mockConfig (config: Record<string, unknown>): Promise<void> {
    const response = await this.context.post(`${this.mockBaseURL()}/__mock__/config`, {
      data: config
    })
    if (!response.ok()) throw new Error(`mock config 失败: ${response.status()}`)
  }

  async mockRequests (): Promise<Array<Record<string, unknown>>> {
    const response = await this.context.get(`${this.mockBaseURL()}/__mock__/requests`)
    if (!response.ok()) throw new Error(`mock requests 失败: ${response.status()}`)
    return response.json()
  }

  private mockBaseURL (): string {
    return (process.env.E2E_MOCK_BASE_URL || 'http://127.0.0.1:18081').replace(/\/+$/, '')
  }
}

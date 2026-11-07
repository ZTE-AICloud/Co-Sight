import type { ApiClient } from './api-client'

export interface WorkflowRow {
  workFlowId: string
  name: string
  template?: string
  publishType?: number
  version?: number
  [key: string]: unknown
}

export interface CanvasPayload {
  flowType?: string
  version?: number
  nodeConfigDTOList: Array<Record<string, unknown>>
  otherNodeConfigList: Array<Record<string, unknown>>
}

export class FlowApi {
  constructor (private readonly api: ApiClient) {}

  list (params: {
    currentPage?: number
    pageSize?: number
    name?: string
  } = {}): Promise<{ items?: WorkflowRow[]; total?: number }> {
    const query = new URLSearchParams({
      page: String(params.currentPage ?? 1),
      size: String(params.pageSize ?? 100),
      keyword: params.name || ''
    })
    return this.api.get(`/workflows?${query.toString()}`)
  }

  async findAll (): Promise<WorkflowRow[]> {
    const page = await this.list()
    return page?.items || []
  }

  async findByName (name: string): Promise<WorkflowRow | undefined> {
    return (await this.findAll()).find(row => row.name === name)
  }

  create (payload: {
    name: string
    workFlowId: string
    template?: 'Sequential' | 'Blended' | 'Conditional'
    knowledgeType?: string
    description?: string
    boundInfo: Record<string, unknown>
  }): Promise<WorkflowRow> {
    return this.api.post<WorkflowRow>('/workflows', {
      name: payload.name,
      workFlowId: payload.workFlowId,
      template: payload.template || 'Blended',
      knowledgeType: payload.knowledgeType || 'knowledgeBase',
      description: payload.description || 'E2E',
      boundInfo: payload.boundInfo
    })
  }

  update (payload: Record<string, unknown>): Promise<unknown> {
    const workflowId = payload.workFlowId || payload.workflowId || payload.appId
    return this.api.patch(`/workflows/${encodeURIComponent(String(workflowId))}`, payload)
  }

  delete (workFlowId: string): Promise<void> {
    return this.api.del(`/workflows/${encodeURIComponent(workFlowId)}`)
  }

  allStatusKbase (): Promise<Record<string, unknown>> {
    return this.api.get('/workflows/knowledge-bases')
  }

  llmModels (): Promise<Array<Record<string, unknown>>> {
    return this.api.get('/system/llm-models')
  }

  getConfig (appId: string): Promise<CanvasPayload> {
    return this.api.get<CanvasPayload>(`/workflows/${encodeURIComponent(appId)}/flow`)
  }

  getPublished (appId: string): Promise<CanvasPayload> {
    return this.api.get<CanvasPayload>(`/workflows/${encodeURIComponent(appId)}/publication`)
  }

  saveConfig (appId: string, payload: CanvasPayload): Promise<unknown> {
    return this.api.put(`/workflows/${encodeURIComponent(appId)}/flow`, payload)
  }

  precheck (appId: string, payload: CanvasPayload): Promise<{
    success?: boolean
    message?: string
  }> {
    return this.api.post(`/workflows/${encodeURIComponent(appId)}/validate`, payload)
  }

  publish (appId: string): Promise<unknown> {
    return this.api.post(`/workflows/${encodeURIComponent(appId)}/publication`)
  }

  async waitForPublished (
    workFlowId: string,
    timeoutMs = 30_000
  ): Promise<WorkflowRow> {
    const deadline = Date.now() + timeoutMs
    let last: WorkflowRow | undefined
    while (Date.now() < deadline) {
      last = (await this.findAll()).find(row => row.workFlowId === workFlowId)
      if (last && Number(last.publishType) !== 0) return last
      await new Promise(resolve => setTimeout(resolve, 500))
    }
    throw new Error(
      `工作流 ${workFlowId} 在 ${timeoutMs / 1000}s 内未发布：${JSON.stringify(last)}`
    )
  }

  async exportStatus (appId: string): Promise<{ status: number; contentType: string }> {
    const response = await this.api.fetchRaw(
      `/workflows/${encodeURIComponent(appId)}/export`,
      { method: 'GET' }
    )
    return {
      status: response.status(),
      contentType: response.headers()['content-type'] || ''
    }
  }

  query (options: {
    question: string
    workFlowId: string
    conversationId?: string
  }): Promise<Record<string, unknown>> {
    return this.api.post('/query', {
      question: options.question,
      workflow_id: options.workFlowId,
      conversation_id: options.conversationId || `e2e-${Date.now()}`,
      stream: false
    })
  }

  async queryStreamText (options: {
    question: string
    workFlowId: string
    conversationId?: string
  }): Promise<string> {
    const response = await this.api.fetchRaw('/query', {
      method: 'POST',
      data: {
        question: options.question,
        workflow_id: options.workFlowId,
        conversation_id: options.conversationId || `e2e-${Date.now()}`,
        stream: true
      },
      headers: { Accept: 'text/event-stream' }
    })
    if (!response.ok()) {
      throw new Error(`流式查询失败: ${response.status()} ${(await response.text()).slice(0, 300)}`)
    }
    return response.text()
  }
}

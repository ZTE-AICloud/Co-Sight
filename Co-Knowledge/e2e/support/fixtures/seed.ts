/**
 * 共享造数助手：KB + 一篇带唯一标记的 md；可选建流并发布。
 *
 * 只做“让用例进入可测状态”这件事；业务断言仍留在 spec 里。
 */
import type { ApiClient } from '../api/api-client'
import { resourceName } from '../env'

export interface SeededKb {
  kbId: string
  directoryId: string
  fileId: string
  fileName: string
  kbName: string
  marker: string
  embeddingModel: string
}

export async function seedKbWithMarkdown (
  api: ApiClient,
  caseId: string,
  markerPrefix = 'E2E-MARKER'
): Promise<SeededKb> {
  const models = await api.listEmbeddingModels()
  const embeddingModel = (process.env.E2E_EMBEDDING_MODEL || models[0] || '').trim()
  if (!embeddingModel) throw new Error('没有可用的 embedding 模型，无法造数据')

  const marker = `${markerPrefix}-${Date.now()}-${caseId}`
  const kbName = resourceName(caseId)
  const fileName = `${kbName}.md`
  const content = [
    `# ${kbName}`,
    '',
    // 标记后必须有一个分隔符：md 切片会把下一段正文直接拼在后面，若标记以数字
    // 结尾、后面又紧跟英文（如 `...-03RAG`），standard 分词会合成一个 token，
    // 关键词检索对完整标记反而查不到。
    `唯一标记：${marker}。`,
    '',
    'Knowledge Studio 端到端测试文档。本文用于验证检索与编排的来源可追溯性。'
  ].join('\n')

  const result = await api.createKbWithMarkdown(kbName, embeddingModel, fileName, content)
  return { ...result, kbName, marker, embeddingModel }
}

/**
 * 等知识库真正可检索。
 *
 * ⚠️ `waitForFile` 的 `status=1` **不等于**索引已完成：切片/向量/ES 落库是异步的，
 * 实测空环境里要再等约 30s。只断言「有回答」的用例看不出差别；一旦断言检索依据，
 * 就必须先等到一次真实命中，否则拿到的是零节点兜底。
 */
export async function waitForKbRetrieval (
  api: ApiClient,
  seeded: SeededKb,
  timeoutMs = 180_000
): Promise<void> {
  const deadline = Date.now() + timeoutMs
  // 与断言用例使用同一个问句：mock embedding 是词法相似度，问句与切片重叠太少
  // 会被工作流的 score_threshold(0.3) 挡掉（实测「请回答：marker」只有 0.35 左右）。
  const question = `请回答 Knowledge Studio 端到端测试文档里的唯一标记：${seeded.marker}`
  let lastCount = 0
  while (Date.now() < deadline) {
    try {
      const groups = await api.retrieve({
        question,
        kbId: seeded.kbId,
        type: 0,
        topK: 5
      })
      lastCount = (groups || []).flatMap(group => group.docs || []).length
      if (lastCount > 0) return
    } catch {
      // 索引/表还没建好：下一轮再试
    }
    await new Promise(resolve => setTimeout(resolve, 1_000))
  }
  throw new Error(
    `知识库 ${seeded.kbName} 在 ${timeoutMs / 1000}s 内没有可检索切片（最后命中 ${lastCount} 条）`
  )
}

export async function seedPublishedFlow (
  api: ApiClient,
  seeded: SeededKb,
  caseId: string
): Promise<string> {
  const workFlowId = `RAG_Workflow_${Date.now().toString(36)}${Math.floor(Math.random() * 1e6)}`
  await api.createWorkflow({
    name: resourceName(caseId),
    workFlowId,
    template: 'Blended',
    knowledgeType: 'knowledgeBase',
    boundInfo: {
      running: [{
        name: seeded.kbName,
        tableName: `doc_${seeded.kbId}`,
        embeddingModel: seeded.embeddingModel,
        type: 'document'
      }]
    }
  })
  await api.publishFlow(workFlowId)
  await api.waitForWorkflowPublished(workFlowId)
  return workFlowId
}

export async function cleanupSeed (
  api: ApiClient,
  seeded?: SeededKb,
  workFlowId?: string
): Promise<void> {
  if (workFlowId) {
    try { await api.deleteWorkflow(workFlowId) } catch { /* best effort */ }
  }
  if (seeded?.kbId) {
    await api.cleanupKb(seeded.kbId)
  }
}

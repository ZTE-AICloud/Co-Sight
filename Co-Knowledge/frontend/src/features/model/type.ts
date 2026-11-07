/**
 * 模型管理页的类型与「哪一类模型有哪些字段」的判定表。
 *
 * 三类模型的差异**只在这一张表里表达**（表格列、表单字段、校验都从它派生）——
 * 否则三类各写一遍，加一个字段就要同时改六处，必然漏。
 * 与后端 `backend/src/model/models.py` 的
 * `DEFAULT_PATHS` 一一对应，改一边要同步另一边。
 */

export type ModelKind = 'llm' | 'embedding' | 'rerank'

export type ThinkingMode = 'none' | 'auto' | 'preset' | 'custom'

export interface ThinkingPreset {
  presetId: string
  label: string
  labelEn: string
  note: string
  noteEn: string
  payload: Record<string, unknown>
  fullOff: boolean
  confidence: 'verified' | 'standard-doc'
}

export interface ThinkingCatalog {
  presets: ThinkingPreset[]
  matchedPresetId: string
  matchedBy: string
  confidence: string
  warning: string
  allowedPayloadKeys: string[]
  maxPayloadBytes: number
  modes: ThinkingMode[]
}

export interface ModelRow {
  modelId: string
  modelKind: ModelKind
  modelName: string
  displayName: string
  apiModel: string
  baseUrl: string
  apiKeyMasked: string
  hasApiKey: boolean
  chatPath: string
  embeddingsPath: string
  modelsPath: string
  rerankPath: string
  dimension: number | null
  maxTokens: number | null
  temperature: number | null
  timeout: number | null
  isReasoning: boolean
  thinkingMode: ThinkingMode
  thinkingPreset: string
  thinkingPayload: Record<string, unknown> | null
  thinkingMatchedPresetId: string
  thinkingMatchedPresetLabel: string
  thinkingMatchedPresetLabelEn: string
  thinkingPresetLabel: string
  thinkingPresetLabelEn: string
  thinkingWarning: string
  isDefault: boolean
  enabled: boolean
  source: 'env' | 'user'
  remark: string
  createTime: string
  modifyTime: string
  creator: string
}

export interface ModelTestResult {
  ok: boolean
  /** LLM 真实调用结果：true = 调通 / false = 调不通 / null = 未尝试（embedding/rerank）。
   *  **LLM 的 `ok` 只由它决定** —— `/models` 清单只说明网关声明了哪些名字。 */
  chatOk?: boolean | null
  /** LLM 真实调用失败的说明（HTTP 状态 + 端点错误信息）；成功时为空串 */
  chatError?: string
  /** rerank 真实调用结果：true = 调通 / false = 调不通 / null = 未尝试（llm/embedding）。
   *  **rerank 的 `ok` 只由它决定** —— 这类端点通常没有 `/models`，清单探测对它不适用。 */
  rerankOk?: boolean | null
  /** rerank 真实调用失败的说明（HTTP 状态 + 端点错误信息）；成功时为空串 */
  rerankError?: string
  /** embedding 真实调用结果：true = 调通 / false = 调不通 / null = 未尝试（llm/rerank）。
   *  **embedding 的 `ok` 只由它决定** —— 判据是一次最小向量调用实测到的维度。 */
  embeddingsOk?: boolean | null
  /** embedding 真实调用失败的说明（HTTP 状态 + **实际请求的 URL**）；成功时为空串 */
  embeddingsError?: string
  /** true = 探到清单 / false = 端点说没有这条能力 / null = 说不准（**不等于不可用**） */
  probed: boolean | null
  models: string[] | null
  dimension: number | null
  dimensionMatches: boolean | null
  latencyMs: number
  message: string
}

export const MODEL_KINDS: ModelKind[] = ['llm', 'embedding', 'rerank']

export const THINKING_MODES: ThinkingMode[] = ['none', 'auto', 'preset', 'custom']

export const THINKING_MODE_LABEL_KEY: Record<ThinkingMode, string> = {
  none: 'modules.modelManagement.thinkingModeNone',
  auto: 'modules.modelManagement.thinkingModeAuto',
  preset: 'modules.modelManagement.thinkingModePreset',
  custom: 'modules.modelManagement.thinkingModeCustom'
}

/** 页签与表单里的类型下拉共用 */
export const KIND_LABEL_KEY: Record<ModelKind, string> = {
  llm: 'modules.modelManagement.tabLlm',
  embedding: 'modules.modelManagement.tabEmbedding',
  rerank: 'modules.modelManagement.tabRerank'
}

/** 来源 → 文案键（管理页要能一眼看出哪几行是部署自带的） */
export const SOURCE_LABEL_KEY: Record<string, string> = {
  env: 'modules.modelManagement.sourceEnv',
  user: 'modules.modelManagement.sourceUser'
}

/** 需要向量维度的类型（只有 embedding：它是建库与写入的校验基准） */
export function needsDimension (kind: ModelKind): boolean {
  return kind === 'embedding'
}

/**
 * OpenAI 标准路径，仅用于表单占位提示（真正的默认值在后端）。
 * **`modelsPath` 只有 LLM 有**：清单探测的消费者只有生成端点那两处（发布校验 + 连接测试），
 * embedding / rerank 的判据分别是维度实测与重排调用（见后端 ``DEFAULT_PATHS``）。
 */
export const PATH_PLACEHOLDER: Record<ModelKind, Partial<Record<'chatPath' | 'embeddingsPath' | 'modelsPath' | 'rerankPath', string>>> = {
  llm: { chatPath: '/chat/completions', modelsPath: '/models' },
  embedding: { embeddingsPath: '/embeddings' },
  rerank: { rerankPath: '/rerank' }
}

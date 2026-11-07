/**
 * 0.1.3「新建图谱知识库」弹窗的选项与交接数据。
 *
 * 弹窗只负责第一步（名称 / 向量模型 / 描述 / 文件）；图谱库还需要
 * 抽图算子、schema 与 LLM 参数，这些只能由整页的建图流程收集。因此提交时
 * 把表单放进这个模块级草稿，整页 `CreateKnowledgeGraph` 挂载后取走并预填，
 * 用户在整页完成配置后由 `/graph/extract` 一次建库 + 上传 + 建任务。
 *
 * 草稿只在内存里活一次：`takeGraphQuickDraft` 读后即清空，刷新整页不会复活。
 */
import { getModelList } from '@/features/model/api/models'
import { getKbaseFileLimitApi, knowledgeGraphListApi } from '@/features/graph/api/knowledgeGraph'
import { fallbackUploadLimits, toUploadLimits, type UploadLimits } from '@/features/knowledge-base/lib/quick-create'

/** 图谱知识库在 `/kbase/search` 里的 category（构建页写死 10）。 */
const GRAPH_CATEGORY = 10
/** `/file/size_limit/{category}` 的图谱口径。 */
const GRAPH_FILE_LIMIT_CATEGORY = 10
const OPTION_PAGE_SIZE = 500
/** 建图页 `validateName` 的长度口径。 */
const GRAPH_NAME_MIN_LENGTH = 2
const GRAPH_NAME_MAX_LENGTH = 30
/** 建图页的文件选择显式排除了这两种格式，弹窗也不能放进来。 */
const UNSUPPORTED_GRAPH_EXTENSIONS = new Set(['ofd', 'zedx'])

export interface GraphQuickDraft {
  name: string
  description: string
  model: string
  files: File[]
}

export interface GraphCreateOptions {
  models: { name: string, recommended?: boolean }[]
  existingNames: string[]
  limits: UploadLimits
}

let quickDraft: GraphQuickDraft | null = null

/** 与整页 `CreateKnowledgeGraph.validateName` 同一条规则，避免弹窗放行后整页再报错。 */
export function isValidGraphQuickName (name: string): boolean {
  return name.length >= GRAPH_NAME_MIN_LENGTH &&
    name.length <= GRAPH_NAME_MAX_LENGTH &&
    !/^\s+$/.test(name) &&
    /^[\w一-龥.\-\s]+$/.test(name)
}

export function setGraphQuickDraft (draft: GraphQuickDraft | null): void {
  quickDraft = draft
}

/** 读取后立即清空：整页只消费一次，避免返回键又带出旧文件。 */
export function takeGraphQuickDraft (): GraphQuickDraft | null {
  const draft = quickDraft
  quickDraft = null
  return draft
}

function extractRows (response: any): any[] {
  if (!response) {
    return []
  }
  if (Array.isArray(response)) {
    return response
  }
  if (Array.isArray(response.data)) {
    return response.data
  }
  if (response.data && Array.isArray(response.data.data)) {
    return response.data.data
  }
  if (Array.isArray(response.items)) {
    return response.items
  }
  if (response.data && Array.isArray(response.data.items)) {
    return response.data.items
  }
  return []
}

function normalizeModels (response: any): { name: string }[] {
  return extractRows(response)
    .map((item: any) => (
      typeof item === 'string' ? item : item?.modelName || item?.name
    ))
    .filter((name: any): name is string => Boolean(name))
    .map((name: string) => ({ name }))
}

/** `/system/file-size-limits` 的响应是纯 JSON 对象。 */
function unwrapFileLimit (response: any): any {
  return response?.data || response || {}
}

function graphUploadLimits (response: any): UploadLimits {
  const fallback = fallbackUploadLimits()
  const payload = unwrapFileLimit(response)
  const limits = payload?.maxSizeMap ? toUploadLimits(payload) : fallback
  // 建图页的 accept 列表排除了 ofd/zedx（见 CreateKnowledgeGraph.filteredFileFormats）；
  // 弹窗若放行，用户会在整页构建时才被后端拒绝。
  const groups = limits.groups
    .map(group => ({
      ...group,
      extensions: group.extensions.filter(extension => !UNSUPPORTED_GRAPH_EXTENSIONS.has(extension))
    }))
    .filter(group => group.extensions.length)
  return {
    ...limits,
    groups: groups.length
      ? groups
      : fallback.groups
        .map(group => ({
          ...group,
          extensions: group.extensions.filter(extension => !UNSUPPORTED_GRAPH_EXTENSIONS.has(extension))
        }))
        .filter(group => group.extensions.length)
  }
}

/**
 * 弹窗打开前取三份真实数据；任一项失败都用缺省兜底值，不挡住弹窗。
 * 判重最终仍由后端在建库时做，这里的同名列表只做即时提示。
 */
export async function loadGraphCreateOptions (): Promise<GraphCreateOptions> {
  const [models, existingNames, limits] = await Promise.all([
    getModelList()
      .then(normalizeModels)
      .catch(() => [] as { name: string }[]),
    knowledgeGraphListApi(
      { categories: [GRAPH_CATEGORY], currentPage: 1, pageSize: OPTION_PAGE_SIZE },
      { skipErrorHandler: true }
    )
      .then(response => Array.from(new Set(
        extractRows(response)
          .map((row: any) => row?.name)
          .filter(Boolean)
      )) as string[])
      .catch(() => [] as string[]),
    getKbaseFileLimitApi(GRAPH_FILE_LIMIT_CATEGORY)
      .then(graphUploadLimits)
      .catch(() => graphUploadLimits(null))
  ])
  return { models, existingNames, limits }
}

/**
 * 「新建知识库」弹窗的真实建库 + 上传实现。
 *
 * 弹窗只收集「名称 / 向量模型 / 描述 / 文件」，但真实建库还差两步：
 * 1. 取知识库的默认目录（`/directory/descendants`）；
 * 2. 给每个扩展名挑一个系统切分算子并上传（`/file/upload` 的 metadata 里
 *    `splitOperator` 缺席会 NPE，空 Map 会报「请选择切分算子」）。
 *
 * 另外：
 * - 算子默认值的取法（优先 id=-1 的系统算子、prompt 参数走 i18n）复用
 *   `processOperatorMap` 的规则；
 * - 序列化前用同一个 `cleanOperatorList`；
 * - 上传加密头复用 `useCrypto(kbaseId).getConfig()`。
 *
 * 页面只负责 UI；本模块零组件状态，失败时抛出原始错误由调用方决定提示方式。
 */
import { $t } from '@/app/i18n/i18n.js'
import { createKnowledgeBase } from '@/features/knowledge-base/api/knowledgeBase'
import { getSupportOperatorApi, getFileSizeInfoApi, uploadFileAndSplitConfigApi } from '@/features/knowledge-base/api/kbaseApi.js'
import { getDescendantsDirectoryList } from '@/features/knowledge-base/api/directory'
import { useCrypto } from '@/shared/composables/useCrypto'
import { KB_CATEGORY } from '@/features/knowledge-base/constants.js'
import { cleanOperatorList } from '@/features/knowledge-base/lib/operator-config'
import { TOTAL_UPLOAD_SIZE_MB } from '@/features/knowledge-base/lib/file-limits'

export interface FileLimitGroup {
  extensions: string[]
  maxMB: number
}

export interface UploadLimits {
  groups: FileLimitGroup[]
  maxFiles: number
  maxTotalBytes: number
}

/** 后端 `/file/size_limit` 的缺省值（拿不到时使用）。 */
export function fallbackUploadLimits (): UploadLimits {
  return {
    groups: [
      { extensions: ['txt'], maxMB: 5 },
      { extensions: ['xlsx', 'csv', 'html'], maxMB: 10 },
      { extensions: ['pptx'], maxMB: 20 },
      { extensions: ['json'], maxMB: 50 },
      { extensions: ['docx', 'md'], maxMB: 100 },
      { extensions: ['pdf'], maxMB: 150 },
      { extensions: ['zedx'], maxMB: 650 }
    ],
    maxFiles: 50,
    maxTotalBytes: TOTAL_UPLOAD_SIZE_MB * 1024 * 1024
  }
}

/**
 * `GET /file/size_limit` → 弹窗要的分组。
 * 响应形如 `{ maxSizeMap: { pdf: 150, docx: 100, ... }, number: 50 }`；
 * 后端键按小写返回（`convertKeysToLower` 实际上不转小写，这里自己兜一道）。
 */
export function toUploadLimits (response: any): UploadLimits {
  const fallback = fallbackUploadLimits()
  const raw = response?.maxSizeMap || response
  if (!raw || typeof raw !== 'object') {
    return fallback
  }
  const bySize = new Map<number, string[]>()
  for (const [extension, value] of Object.entries(raw)) {
    const maxMB = Number(value)
    if (!Number.isFinite(maxMB) || maxMB <= 0) {
      continue
    }
    const key = String(extension).toLowerCase()
    if (!bySize.has(maxMB)) {
      bySize.set(maxMB, [])
    }
    bySize.get(maxMB)!.push(key)
  }
  if (!bySize.size) {
    return fallback
  }
  const groups = Array.from(bySize.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([maxMB, extensions]) => ({ extensions, maxMB }))
  return {
    groups,
    maxFiles: Number(response?.number) || fallback.maxFiles,
    maxTotalBytes: fallback.maxTotalBytes
  }
}

export async function loadUploadLimits (): Promise<UploadLimits> {
  try {
    const response = await getFileSizeInfoApi()
    return toUploadLimits(response)
  } catch {
    return fallbackUploadLimits()
  }
}

function suffixOf (file: File): string {
  const index = file.name.lastIndexOf('.')
  return index === -1 ? '' : file.name.slice(index + 1).toLowerCase()
}

export async function fetchDefaultDirectoryId (kbaseId: string): Promise<string> {
  const response = await getDescendantsDirectoryList({
    kbaseId,
    category: KB_CATEGORY.DOCUMENT
  })
  if (Array.isArray(response) && response.length > 0) {
    // 优先取默认目录；没有 Default 时沿用原行为取第一条。
    const defaultFolder = response.find((item: any) => item?.title === 'Default')
    return (defaultFolder || response[0]).id
  }
  throw new Error('未找到默认目录')
}

/**
 * 每个扩展名挑一个系统切分算子。
 * 与 `CreateKnowledgeBaseUnified.processOperatorMap` 同口径：
 * system 优先 id=-1，否则取列表第一个。
 */
export async function buildDefaultSplitOperator (files: File[]): Promise<Record<string, any>> {
  const suffixes = Array.from(new Set(files.map(suffixOf).filter(Boolean)))
  if (!suffixes.length) {
    return {}
  }
  const response: any = await getSupportOperatorApi({ formats: suffixes, module: 'text_split' })
  const splitOperator: Record<string, any> = {}
  for (const suffix of suffixes) {
    const list = Array.isArray(response?.[suffix]) ? response[suffix] : []
    const operator = list.find((item: any) => item.id === -1) || list[0]
    if (!operator) {
      throw new Error($t('modules.studioDialogs.createKnowledge.noSplitOperator', { ext: suffix }))
    }
    splitOperator[suffix] = {
      operatorId: operator.id,
      args: (operator.args || []).map((arg: any) => ({ ...arg }))
    }
  }
  return splitOperator
}

/** 扩展名统一小写（与 AddData / CreateKnowledgeBaseUnified 的上传前处理一致）。 */
function normalizeFileName (file: File): File {
  const index = file.name.lastIndexOf('.')
  if (index === -1) {
    return file
  }
  const name = `${file.name.slice(0, index)}.${file.name.slice(index + 1).toLowerCase()}`
  return name === file.name ? file : new File([file], name, { type: file.type })
}

export interface UploadToKbaseOptions {
  /** 目标目录；缺省取知识库的默认目录 */
  directoryId?: string
  /** 同名覆盖（默认 false） */
  coverFlag?: boolean
  /** 由调用方展示错误（弹窗内联提示）时跳过全局 toast */
  skipErrorHandler?: boolean
}

/**
 * 把文件上传到已有知识库（顶部「导入」）。
 *
 * 与建库上传走同一套校验/切分算子/加密配置，只是不创建知识库。
 */
export async function uploadFilesToKbase (
  kbaseId: string,
  files: File[],
  options: UploadToKbaseOptions = {}
): Promise<void> {
  const normalized = files.map(normalizeFileName)
  const directoryId = options.directoryId || await fetchDefaultDirectoryId(kbaseId)
  const splitOperator = await buildDefaultSplitOperator(normalized)
  cleanOperatorList(splitOperator)

  const data = new FormData()
  normalized.forEach(file => data.append('files', file))
  data.append('metadata', JSON.stringify({
    kType: 'outer-document',
    directoryId,
    kbaseId: String(kbaseId),
    splitType: 'system',
    splitOperator,
    coverFlag: Boolean(options.coverFlag)
  }))

  const { getConfig } = useCrypto(String(kbaseId))
  const config = await getConfig()
  await uploadFileAndSplitConfigApi(String(kbaseId), data, {
    ...config,
    ...(options.skipErrorHandler ? { skipErrorHandler: true } : {})
  })
}

export interface QuickCreatePayload {
  name: string
  description: string
  model: string
  files: File[]
}

export interface QuickCreateResult {
  kbId: string
  directoryId: string
}

/**
 * 建库 + 上传。返回真实 kbId / directoryId。
 *
 * ⚠️ 建库成功、上传失败时**抛出**，但也带上 `kbId`（挂在 error 上）—— 调用方据此
 * 把用户带到新库的文档页，而不是让他在弹窗里重试（重试会再建一个库）。
 */
export async function createKnowledgeBaseWithFiles (
  payload: QuickCreatePayload
): Promise<QuickCreateResult> {
  const created: any = await createKnowledgeBase({
    name: payload.name,
    description: payload.description,
    category: KB_CATEGORY.DOCUMENT,
    props: { embeddingModel: payload.model }
  })
  const kbId = created?.id || created?.kbaseId || created
  try {
    const directoryId = await fetchDefaultDirectoryId(String(kbId))
    const files = payload.files.map(normalizeFileName)
    const splitOperator = await buildDefaultSplitOperator(files)
    cleanOperatorList(splitOperator)

    const data = new FormData()
    files.forEach(file => data.append('files', file))
    data.append('metadata', JSON.stringify({
      kType: 'outer-document',
      directoryId,
      kbaseId: String(kbId),
      splitType: 'system',
      splitOperator,
      coverFlag: false
    }))

    const { getConfig } = useCrypto(String(kbId))
    const config = await getConfig()
    await uploadFileAndSplitConfigApi(String(kbId), data, config)
    return { kbId: String(kbId), directoryId }
  } catch (error: any) {
    // 目录获取失败也算「库已建好、后续步骤失败」，让 UI 把用户带到新库而不是重试建库
    if (error && typeof error === 'object') {
      error.kbId = String(kbId)
    }
    throw error
  }
}

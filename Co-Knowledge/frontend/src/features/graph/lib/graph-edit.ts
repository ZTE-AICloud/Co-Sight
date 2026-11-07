/**
 * 「修改知识图谱」页的草稿校验与脏状态快照（纯函数）。
 *
 * 修改页分成三张编号卡片：基本信息、来源文档、构建配置。
 * 「保存修改」不能只改内存；后端只有 `PUT /knowledge-bases/{id}/graph`
 * （更新并重新抽取），没有「只保存基本信息」的端点，所以本仓把唯一提交动作
 * 定为「保存并构建」，并在这里钉住页面侧的校验与脏状态口径。
 *
 * 名称规则与整页建图 / 新建弹窗一致：2–30 个字符，允许字母、数字、下划线、
 * 中文、点、中划线与空格，但不能全为空格。
 *
 * 零 Vue 依赖，可在 Node 里直接单测。
 */

import {
  validateBuildParams,
  type GraphBuildErrorCode,
  type GraphBuildParams,
  type GraphOperatorArg
} from './graph-build-config'

export interface GraphEditDraft {
  name: string
  description: string
  params: GraphBuildParams
}

export type GraphEditNameError = '' | 'nameRequired' | 'nameFormat' | 'descriptionTooLong'

export interface GraphEditErrors {
  name: GraphEditNameError
  description: '' | 'descriptionTooLong'
  params: Record<string, GraphBuildErrorCode>
}

export interface GraphEditSnapshotInput {
  draft: GraphEditDraft
  retainedFileIds: string[]
  newFileKeys: string[]
}

const NAME_MIN = 2
const NAME_MAX = 30
const DESCRIPTION_MAX = 1000
const NAME_PATTERN = /^[\w一-龥.\-\s]+$/

/** 名称校验：与后端建图页 `validateName` / 新建弹窗同一条规则。 */
export function validateGraphEditName (name: string): GraphEditNameError {
  const value = String(name || '').trim()
  if (!value) {
    return 'nameRequired'
  }
  if (value.length < NAME_MIN || value.length > NAME_MAX || !NAME_PATTERN.test(value)) {
    return 'nameFormat'
  }
  return ''
}

/** 整页校验：名称 + 描述长度 + 当前算子的必填参数。 */
export function validateGraphEditDraft (
  draft: GraphEditDraft,
  args: GraphOperatorArg[] | null | undefined
): GraphEditErrors {
  const description = String(draft?.description || '')
  return {
    name: validateGraphEditName(draft?.name || ''),
    description: isDescriptionTooLong(description) ? 'descriptionTooLong' : '',
    params: validateBuildParams(args, draft?.params)
  }
}

/** 是否存在任一错误（含参数级错误）。 */
export function hasGraphEditErrors (errors: GraphEditErrors | null | undefined): boolean {
  if (!errors) {
    return false
  }
  return Boolean(errors.name) ||
    Boolean(errors.description) ||
    Boolean(errors.params && Object.keys(errors.params).length)
}

/**
 * 脏状态快照：**按内容**序列化，键顺序固定，避免对象键顺序不同造成假脏。
 * 文件用 id / fileKey 参与比较，编辑后再换回原文件也能回到「已同步」。
 */
export function graphEditSnapshot (input: GraphEditSnapshotInput): string {
  const draft = input.draft || { name: '', description: '', params: {} }
  const params = draft.params || {}
  const paramKeys = Object.keys(params).sort()
  return JSON.stringify({
    name: String(draft.name || ''),
    description: String(draft.description || ''),
    params: paramKeys.map(key => [key, params[key] ?? null]),
    retainedFileIds: [...(input.retainedFileIds || [])].map(String).sort(),
    newFileKeys: [...(input.newFileKeys || [])].map(String).sort()
  })
}

/** 描述长度校验（与建图页 1000 字上限一致）。 */
export function isDescriptionTooLong (description: string): boolean {
  return String(description || '').length > DESCRIPTION_MAX
}

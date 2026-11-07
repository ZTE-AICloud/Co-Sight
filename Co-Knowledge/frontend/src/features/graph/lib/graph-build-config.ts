/**
 * 建图算子参数的「排序 / 默认值 / 校验 / 建库报文」纯函数。
 *
 * 两处消费方：
 *
 * 1. 图谱列表页「新建图谱知识库」弹窗（含构建配置区）；
 * 2. 整页建图 / 修改图谱页（沿用同一套算子 args）。
 *
 * 真实算子的参数是**数据驱动**的：`args[].argName` 决定控件（schemaId → 模板下拉、
 * llm → 大模型、overlap / chunkSize → 数字、其余 → 文本），而不是写死的
 * 「专业 / 通用两个算子」。这里保留数据驱动，只把三条约束落成校验：
 * 必填、整数、重叠字符数必须小于最大字符数。
 *
 * 数值范围按后端 `graph_extract_v2_api` 的口径：
 * `chunkSize ∈ [512, 10240]`、`overlap ∈ [0, 5120]`。
 *
 * 零 Vue 依赖，可在 Node 里直接单测。
 */

export interface GraphOperatorArg {
  argName?: string
  type?: string
  description?: string
  defaultValue?: string | number
  tips?: Record<string, string>
  placeholder?: Record<string, string>
}

export interface GraphOperator {
  id?: string | number
  name?: string
  nameEn?: string
  args?: GraphOperatorArg[]
}

export interface GraphBuildParams {
  schemaId?: string
  llm?: string
  overlap?: number | string
  chunkSize?: number | string
  [key: string]: unknown
}

export type GraphBuildErrorCode =
  | 'required'
  | 'integer'
  | 'chunkSizeRange'
  | 'overlapRange'
  | 'overlapLessThanChunkSize'

export interface GraphBuildPayloadInput {
  name: string
  description: string
  embeddingModel: string
  operatorId: string | number
  params: GraphBuildParams
}

export const CHUNK_SIZE_MIN = 512
export const CHUNK_SIZE_MAX = 10240
export const OVERLAP_MIN = 0
export const OVERLAP_MAX = 5120
export const GRAPH_CATEGORY = 10

const FIELD_ORDER = ['schemaId', 'llm', 'overlap', 'chunkSize']

/** 参数展示顺序：schemaId → llm → overlap → chunkSize → 其余（保持算子声明顺序）。 */
export function orderedOperatorArgs (args: GraphOperatorArg[] | null | undefined): GraphOperatorArg[] {
  const order = (arg: GraphOperatorArg): number => {
    const index = FIELD_ORDER.indexOf(String(arg?.argName || ''))
    return index === -1 ? FIELD_ORDER.length : index
  }
  return [...(args || [])].sort((a, b) => order(a) - order(b))
}

/** 整数参数：overlap / chunkSize 以及名字里带 Size / Overlap / Chars 的参数。 */
export function isIntegerArg (arg: GraphOperatorArg | null | undefined): boolean {
  const name = String(arg?.argName || '')
  return arg?.type === 'number' ||
    name === 'overlap' ||
    name === 'chunkSize' ||
    name.includes('Size') ||
    name.includes('Overlap') ||
    name.includes('Chars')
}

/** 参数默认值：数字参数转数字，其余按字符串；未声明默认值时给空串。 */
export function defaultBuildParams (args: GraphOperatorArg[] | null | undefined): GraphBuildParams {
  const params: GraphBuildParams = {}
  ;(args || []).forEach((arg) => {
    const name = String(arg?.argName || '')
    if (!name) {
      return
    }
    if (isIntegerArg(arg)) {
      const declared = arg?.defaultValue
      const fallback = name === 'chunkSize' ? CHUNK_SIZE_MIN : OVERLAP_MIN
      const parsed = Number.parseInt(declared === undefined || declared === null ? '' : String(declared), 10)
      params[name] = Number.isFinite(parsed) ? parsed : fallback
      return
    }
    params[name] = arg?.defaultValue === undefined || arg?.defaultValue === null
      ? ''
      : String(arg.defaultValue)
  })
  return params
}

/**
 * 校验算子参数。返回 `参数名 → 错误码`；空对象表示通过。
 * 只校验当前算子的 args —— 模板/大模型是否必填由算子声明，不在这里写死。
 */
export function validateBuildParams (
  args: GraphOperatorArg[] | null | undefined,
  params: GraphBuildParams | null | undefined
): Record<string, GraphBuildErrorCode> {
  const errors: Record<string, GraphBuildErrorCode> = {}
  const values = params || {}
  ;(args || []).forEach((arg) => {
    const name = String(arg?.argName || '')
    if (!name) {
      return
    }
    const value = values[name]
    if (value === undefined || value === null || String(value).trim() === '') {
      errors[name] = 'required'
      return
    }
    if (isIntegerArg(arg)) {
      const number = Number(value)
      if (!Number.isInteger(number)) {
        errors[name] = 'integer'
        return
      }
      if (name === 'chunkSize' && (number < CHUNK_SIZE_MIN || number > CHUNK_SIZE_MAX)) {
        errors[name] = 'chunkSizeRange'
      }
      if (name === 'overlap' && (number < OVERLAP_MIN || number > OVERLAP_MAX)) {
        errors[name] = 'overlapRange'
      }
    }
  })

  const chunkSize = Number(values.chunkSize)
  const overlap = Number(values.overlap)
  if (!errors.chunkSize && !errors.overlap &&
    Number.isFinite(chunkSize) && Number.isFinite(overlap) && overlap >= chunkSize) {
    errors.overlap = 'overlapLessThanChunkSize'
  }
  return errors
}

/**
 * 组装 `POST /graph-extractions` 的 `data` 字段（与整页建图同一报文）：
 * `schemaId` 提到顶层，其余参数进 `kwargs`；数字参数保持数字。
 */
export function buildGraphExtractPayload (input: GraphBuildPayloadInput): Record<string, unknown> {
  const params = input.params || {}
  const kwargs: Record<string, unknown> = {}
  Object.keys(params).forEach((key) => {
    if (key === 'schemaId') {
      return
    }
    const value = params[key]
    if (value === undefined || value === null || value === '') {
      return
    }
    kwargs[key] = value
  })

  const payload: Record<string, unknown> = {
    name: input.name,
    description: input.description,
    category: GRAPH_CATEGORY,
    props: { embeddingModel: input.embeddingModel },
    operatorId: input.operatorId,
    coverFlag: true,
    kwargs
  }
  if (params.schemaId) {
    payload.schemaId = params.schemaId
  }
  return payload
}

/** 算子显示名（与整页建图一致：`$globalZh` 控制中英文）。 */
export function operatorDisplayName (operator: GraphOperator | null | undefined, useZh: boolean): string {
  if (!operator) {
    return ''
  }
  return String(useZh ? operator.name || operator.nameEn || '' : operator.nameEn || operator.name || '')
}

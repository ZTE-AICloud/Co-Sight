import {
  buildGraphExtractPayload,
  defaultBuildParams,
  isIntegerArg,
  operatorDisplayName,
  orderedOperatorArgs,
  validateBuildParams
} from '@/features/graph/lib/graph-build-config'

// 测的是建图算子参数的纯逻辑层（9fa99ff 原型给「新建图谱」弹窗加的构建配置区）：
// 参数排序 / 默认值 / 校验 / `POST /graph-extractions` 的 data 报文。

const args = [
  { argName: 'llm', defaultValue: 'DeepSeek Chat' },
  { argName: 'chunkSize', defaultValue: '512', type: 'number' },
  { argName: 'schemaId' },
  { argName: 'overlap', defaultValue: '128', type: 'number' },
  { argName: 'prompt', defaultValue: '抽取实体' }
]

test('参数按 schemaId → llm → overlap → chunkSize → 其余排序', () => {
  expect(orderedOperatorArgs(args).map(item => item.argName)).toEqual([
    'schemaId', 'llm', 'overlap', 'chunkSize', 'prompt'
  ])
})

test('默认值：数字参数转数字，其余按字符串', () => {
  expect(defaultBuildParams(args)).toEqual({
    schemaId: '',
    llm: 'DeepSeek Chat',
    overlap: 128,
    chunkSize: 512,
    prompt: '抽取实体'
  })
  expect(defaultBuildParams(null)).toEqual({})
})

test('数字参数识别：type=number 或名字含 Size/Overlap/Chars', () => {
  expect(isIntegerArg({ argName: 'overlap' })).toBe(true)
  expect(isIntegerArg({ argName: 'maxChars' })).toBe(true)
  expect(isIntegerArg({ argName: 'batchSize' })).toBe(true)
  expect(isIntegerArg({ argName: 'prompt' })).toBe(false)
})

test('必填、整数与范围校验', () => {
  expect(validateBuildParams(args, { schemaId: '', llm: '', overlap: 128, chunkSize: 512, prompt: 'x' }))
    .toEqual({ schemaId: 'required', llm: 'required' })

  expect(validateBuildParams(args, { schemaId: 's', llm: 'l', overlap: 128.5, chunkSize: 512, prompt: 'x' }))
    .toEqual({ overlap: 'integer' })

  expect(validateBuildParams(args, { schemaId: 's', llm: 'l', overlap: 0, chunkSize: 100, prompt: 'x' }))
    .toEqual({ chunkSize: 'chunkSizeRange' })

  expect(validateBuildParams(args, { schemaId: 's', llm: 'l', overlap: 6000, chunkSize: 10240, prompt: 'x' }))
    .toEqual({ overlap: 'overlapRange' })
})

test('重叠字符数必须小于最大字符数', () => {
  expect(validateBuildParams(args, { schemaId: 's', llm: 'l', overlap: 512, chunkSize: 512, prompt: 'x' }))
    .toEqual({ overlap: 'overlapLessThanChunkSize' })
  expect(validateBuildParams(args, { schemaId: 's', llm: 'l', overlap: 128, chunkSize: 512, prompt: 'x' }))
    .toEqual({})
})

test('建库报文：schemaId 提到顶层，其余进 kwargs，空值不下发', () => {
  const payload = buildGraphExtractPayload({
    name: '图谱 A',
    description: '描述',
    embeddingModel: 'Qwen3-Embedding-0.6B',
    operatorId: '12',
    params: { schemaId: 'schema-1', llm: 'DeepSeek Chat', overlap: 128, chunkSize: 512, prompt: '' }
  })
  expect(payload).toEqual({
    name: '图谱 A',
    description: '描述',
    category: 10,
    props: { embeddingModel: 'Qwen3-Embedding-0.6B' },
    operatorId: '12',
    coverFlag: true,
    schemaId: 'schema-1',
    kwargs: { llm: 'DeepSeek Chat', overlap: 128, chunkSize: 512 }
  })

  const withoutSchema = buildGraphExtractPayload({
    name: '图谱 B',
    description: '',
    embeddingModel: 'm',
    operatorId: 3,
    params: { llm: 'm1', overlap: 0, chunkSize: 512 }
  })
  expect(withoutSchema.schemaId).toBeUndefined()
})

test('算子显示名跟随中英文', () => {
  const operator = { name: '专业知识图谱算子', nameEn: 'Professional Graph Operator' }
  expect(operatorDisplayName(operator, true)).toBe('专业知识图谱算子')
  expect(operatorDisplayName(operator, false)).toBe('Professional Graph Operator')
  expect(operatorDisplayName(null, true)).toBe('')
})

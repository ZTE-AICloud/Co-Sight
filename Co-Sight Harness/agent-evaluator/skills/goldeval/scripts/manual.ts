import { readFileSync } from 'fs'
import { extractJson, llmCall } from '../evaluators/llmasjudge/llm.ts'
import { CLASSIFY_PROMPT, SPLIT_PROMPT } from '../evaluators/llmasjudge/classifyPipeline.ts'

const args = process.argv.slice(2)

let dataset = ''
let dataId = ''
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--dataset') {
    dataset = args[i + 1] ?? ''
    i++
  } else if (args[i] === '--data-id') {
    dataId = args[i + 1] ?? ''
    i++
  }
}

if (!dataset) {
  console.error('ERROR: --dataset <path> is required')
  process.exit(1)
}

const lines = readFileSync(dataset, 'utf-8')
  .split('\n')
  .filter((line) => line.trim().length > 0)

let sample: Record<string, unknown> | undefined
if (dataId) {
  sample = lines
    .map((line) => JSON.parse(line) as Record<string, unknown>)
    .find((s) => s.data_id === dataId)
} else {
  sample = JSON.parse(lines[0]) as Record<string, unknown>
}

if (!sample) {
  console.error(`ERROR: sample not found: ${dataId}`)
  process.exit(1)
}

const output = String(sample.output ?? '')
const expected = String(sample.expected_output ?? '')

console.log(`sample: ${String(sample.data_id ?? '')}`)
console.log(`output: ${output}`)
console.log(`expected_output: ${expected}`)

const splitPrompt = SPLIT_PROMPT.replace('{output}', output).replace(
  '{expected_output}',
  expected,
)
console.log('\n========== 分句提示词 ==========')
console.log(splitPrompt)
console.log('\n========== 分句返回 ==========')
const splitRaw = await llmCall(splitPrompt)
console.log(splitRaw)
const split = extractJson(splitRaw) as {
  output_sentences?: unknown
  expected_sentences?: unknown
}

const classifyPrompt = CLASSIFY_PROMPT.replace(
  '{output_sentences}',
  JSON.stringify(split.output_sentences, null, 2),
).replace(
  '{expected_sentences}',
  JSON.stringify(split.expected_sentences, null, 2),
)
console.log('\n========== 归类提示词 ==========')
console.log(classifyPrompt)
console.log('\n========== 归类返回 ==========')
const classifyRaw = await llmCall(classifyPrompt)
console.log(classifyRaw)
console.log('\n========== 解析结果 ==========')
console.log(
  JSON.stringify(
    { data_id: sample.data_id, split, classify: extractJson(classifyRaw) },
    null,
    2,
  ),
)

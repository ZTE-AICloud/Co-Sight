import { readFileSync } from 'fs'
import { dirname, join } from 'path'
import { fileURLToPath } from 'url'

const skillDir = join(dirname(fileURLToPath(import.meta.url)), '..')
const datasetPath = join(skillDir, 'datasets', 'example.jsonl')

const lines = readFileSync(datasetPath, 'utf-8')
  .split('\n')
  .filter((line) => line.trim().length > 0)
  .slice(0, 3)

console.log('=== goldeval 测试集构造示例 ===')
console.log('')
console.log('测试集为 JSONL 格式（每行一个 JSON 对象），字段：')
console.log('- data_id（必填）：样本唯一 ID')
console.log('- input（必填）：问题/输入')
console.log('- output（必填）：待评测的模型输出')
console.log('- expected_output（必填）：黄金参考答案')
console.log('- context（可选）：参考上下文')
console.log('- metadata（可选）：元数据（category/difficulty/tags/model_under_test 等）')
console.log('')

console.log(`以下为 example.jsonl 的前 ${lines.length} 条示例：`)
lines.forEach((line, index) => {
  const sample = JSON.parse(line)
  console.log('')
  console.log(`--- 示例 ${index + 1}（data_id: ${String(sample.data_id ?? '')}） ---`)
  console.log(JSON.stringify(sample, null, 2))
})

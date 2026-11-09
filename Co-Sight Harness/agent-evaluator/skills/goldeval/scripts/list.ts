import { readdirSync } from 'fs'
import { dirname, join } from 'path'
import { fileURLToPath } from 'url'
import { listEvaluators } from '../evaluators/index.ts'

const skillDir = join(dirname(fileURLToPath(import.meta.url)), '..')

function listDatasets(): string[] {
  try {
    return readdirSync(join(skillDir, 'datasets')).filter((f) =>
      f.endsWith('.jsonl'),
    )
  } catch {
    return []
  }
}

const datasets = listDatasets()
const evaluators = listEvaluators()

console.log('=== 可用数据集 ===')
if (datasets.length === 0) console.log('(无)')
for (const d of datasets) console.log(`- ${d}`)

console.log('=== 可用评估器 ===')
if (evaluators.length === 0) console.log('(无)')
for (const e of evaluators) console.log(`- ${e.name}: ${e.description}`)

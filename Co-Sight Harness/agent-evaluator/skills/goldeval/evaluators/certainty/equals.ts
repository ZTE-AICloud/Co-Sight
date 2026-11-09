import { mkdirSync, writeFileSync } from 'fs'
import { join } from 'path'
import type { EvalOptions, EvalResult, EvalSample } from '../types.ts'

export async function equals(
  sample: EvalSample,
  options: EvalOptions,
): Promise<EvalResult> {
  const value = options.value ?? ''
  const rawMatched = sample.output === value
  const matched = options.negate ? !rawMatched : rawMatched

  const result: EvalResult = {
    data_id: options.dataId,
    evaluator: options.name ?? 'equals',
    output: sample.output,
    passed: matched,
    score: matched ? 1 : 0,
    score_detail: { matched, value },
    reason: '',
    metadata: sample.metadata ?? {},
  }

  const processDir = join(options.outputDir, 'process', options.dataId)
  mkdirSync(processDir, { recursive: true })
  writeFileSync(
    join(processDir, 'result_equals.json'),
    JSON.stringify(result, null, 2),
  )
  return result
}

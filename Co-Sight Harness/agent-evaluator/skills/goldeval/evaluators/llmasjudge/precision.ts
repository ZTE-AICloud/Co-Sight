import { writeFileSync } from 'fs'
import { join } from 'path'
import { classifyOutcome } from './classifyPipeline.ts'
import { precisionOf, round } from './metrics.ts'
import type { EvalOptions, EvalResult, EvalSample } from '../types.ts'

export async function precision(
  sample: EvalSample,
  options: EvalOptions,
): Promise<EvalResult> {
  const outcome = await classifyOutcome(sample, options)
  if (outcome.error) {
    const result: EvalResult = {
      data_id: options.dataId,
      evaluator: 'precision',
      score: 0,
      passed: false,
      threshold: options.threshold,
      score_detail: { score_mode: 'precision' },
      reason: outcome.error,
      error: outcome.error,
      metadata: sample.metadata ?? {},
    }
    writeFileSync(
      join(options.outputDir, 'process', options.dataId, 'result_precision.json'),
      JSON.stringify(result, null, 2),
    )
    return result
  }

  const tp = outcome.tp.length
  const fp = outcome.fp.length
  const fn = outcome.fn.length
  const score = round(precisionOf(tp, fp, fn))

  const result: EvalResult = {
    data_id: options.dataId,
    evaluator: 'precision',
    score,
    passed: score >= options.threshold,
    threshold: options.threshold,
    score_detail: {
      precision: score,
      tp: outcome.tp,
      fp: outcome.fp,
      fn: outcome.fn,
      score_mode: 'precision',
    },
    reason:
      outcome.reason ?? `TP=${tp}, FP=${fp}, FN=${fn}，precision=${score.toFixed(2)}`,
    metadata: sample.metadata ?? {},
  }

  writeFileSync(
    join(options.outputDir, 'process', options.dataId, 'result_precision.json'),
    JSON.stringify(result, null, 2),
  )
  return result
}

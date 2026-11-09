import { writeFileSync } from 'fs'
import { join } from 'path'
import { classifyOutcome } from './classifyPipeline.ts'
import { recallOf, round } from './metrics.ts'
import type { EvalOptions, EvalResult, EvalSample } from '../types.ts'

export async function recall(
  sample: EvalSample,
  options: EvalOptions,
): Promise<EvalResult> {
  const outcome = await classifyOutcome(sample, options)
  if (outcome.error) {
    const result: EvalResult = {
      data_id: options.dataId,
      evaluator: 'recall',
      score: 0,
      passed: false,
      threshold: options.threshold,
      score_detail: { score_mode: 'recall' },
      reason: outcome.error,
      error: outcome.error,
      metadata: sample.metadata ?? {},
    }
    writeFileSync(
      join(options.outputDir, 'process', options.dataId, 'result_recall.json'),
      JSON.stringify(result, null, 2),
    )
    return result
  }

  const tp = outcome.tp.length
  const fp = outcome.fp.length
  const fn = outcome.fn.length
  const score = round(recallOf(tp, fp, fn))

  const result: EvalResult = {
    data_id: options.dataId,
    evaluator: 'recall',
    score,
    passed: score >= options.threshold,
    threshold: options.threshold,
    score_detail: {
      recall: score,
      tp: outcome.tp,
      fp: outcome.fp,
      fn: outcome.fn,
      score_mode: 'recall',
    },
    reason:
      outcome.reason ?? `TP=${tp}, FP=${fp}, FN=${fn}，recall=${score.toFixed(2)}`,
    metadata: sample.metadata ?? {},
  }

  writeFileSync(
    join(options.outputDir, 'process', options.dataId, 'result_recall.json'),
    JSON.stringify(result, null, 2),
  )
  return result
}

import { writeFileSync } from 'fs'
import { join } from 'path'
import { classifyOutcome } from './classifyPipeline.ts'
import { f1Of, precisionOf, recallOf, round } from './metrics.ts'
import type { EvalOptions, EvalResult, EvalSample } from '../types.ts'

export async function f1_score(
  sample: EvalSample,
  options: EvalOptions,
): Promise<EvalResult> {
  const outcome = await classifyOutcome(sample, options)
  if (outcome.error) {
    const result: EvalResult = {
      data_id: options.dataId,
      evaluator: 'f1_score',
      score: 0,
      passed: false,
      threshold: options.threshold,
      score_detail: { score_mode: 'llm_score' },
      reason: outcome.error,
      error: outcome.error,
      metadata: sample.metadata ?? {},
    }
    writeFileSync(
      join(options.outputDir, 'process', options.dataId, 'result_f1_score.json'),
      JSON.stringify(result, null, 2),
    )
    return result
  }

  const tp = outcome.tp.length
  const fp = outcome.fp.length
  const fn = outcome.fn.length
  const f1 = round(f1Of(tp, fp, fn))
  const result: EvalResult = {
    data_id: options.dataId,
    evaluator: 'f1_score',
    score: f1,
    passed: f1 >= options.threshold,
    threshold: options.threshold,
    score_detail: {
      precision: round(precisionOf(tp, fp, fn)),
      recall: round(recallOf(tp, fp, fn)),
      f1,
      tp: outcome.tp,
      fp: outcome.fp,
      fn: outcome.fn,
      score_mode: 'llm_score',
    },
    reason:
      outcome.reason ?? `TP=${tp}, FP=${fp}, FN=${fn}，F1=${f1.toFixed(2)}`,
    metadata: sample.metadata ?? {},
  }

  writeFileSync(
    join(options.outputDir, 'process', options.dataId, 'result_f1_score.json'),
    JSON.stringify(result, null, 2),
  )
  return result
}

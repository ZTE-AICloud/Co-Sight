import { contains } from './certainty/contains.ts'
import { equals } from './certainty/equals.ts'
import { f1_score } from './llmasjudge/f1_score.ts'
import { precision } from './llmasjudge/precision.ts'
import { recall } from './llmasjudge/recall.ts'
import type { Evaluator } from './types.ts'

export const EVALUATORS: Record<string, Evaluator> = {
  f1_score: {
    name: 'f1_score',
    description: 'LLM 分句+归类 F1（2TP/(2TP+FP+FN)）',
    family: 'llmasjudge',
    pipeline: 'classify',
    evaluate: f1_score,
  },
  precision: {
    name: 'precision',
    description: '精确率 TP/(TP+FP)',
    family: 'llmasjudge',
    pipeline: 'classify',
    evaluate: precision,
  },
  recall: {
    name: 'recall',
    description: '召回率 TP/(TP+FN)',
    family: 'llmasjudge',
    pipeline: 'classify',
    evaluate: recall,
  },
  equals: {
    name: 'equals',
    description: '确定性判定：output 与 --value 完全匹配得 1，否则 0',
    family: 'certainty',
    evaluate: equals,
  },
  contains: {
    name: 'contains',
    description: '确定性判定：output 包含 --value 得 1，否则 0',
    family: 'certainty',
    evaluate: contains,
  },
}

export function getEvaluator(name: string): Evaluator | undefined {
  return EVALUATORS[name]
}

export interface ResolvedEvaluator {
  evaluator: Evaluator
  name: string
  negate: boolean
  family?: string
}

export function resolveEvaluator(name: string): ResolvedEvaluator | undefined {
  if (name.startsWith('not-')) {
    const base = EVALUATORS[name.slice(4)]
    if (!base) return undefined
    return { evaluator: base, name, negate: true, family: base.family }
  }
  const base = EVALUATORS[name]
  if (!base) return undefined
  return { evaluator: base, name, negate: false, family: base.family }
}

export function listEvaluators(): Evaluator[] {
  return Object.values(EVALUATORS)
}

export type {
  ClassifyOutcome,
  EvalSample,
  EvalOptions,
  EvalResult,
  ScoreDetail,
} from './types.ts'

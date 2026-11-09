export interface EvalSample {
  data_id: string
  input: string
  output: string
  expected_output: string
  context?: string
  metadata?: Record<string, unknown>
}

export interface ClassifyOutcome {
  tp: string[]
  fp: string[]
  fn: string[]
  reason?: string
  error?: string
}

export interface EvalOptions {
  threshold: number
  dataId: string
  outputDir: string
  value?: string
  name?: string
  negate?: boolean
  outcome?: ClassifyOutcome
}

export interface ScoreDetail {
  precision?: number
  recall?: number
  f1?: number
  tp?: string[]
  fp?: string[]
  fn?: string[]
  score_mode?: string
  matched?: boolean
  value?: string
}

export interface EvalResult {
  data_id: string
  evaluator: string
  output?: string
  score: number
  passed: boolean
  threshold?: number
  score_detail: ScoreDetail
  reason: string
  metadata: Record<string, unknown>
  error?: string
}

export interface Evaluator {
  name: string
  description: string
  family?: string
  pipeline?: 'classify'
  evaluate: (sample: EvalSample, options: EvalOptions) => Promise<EvalResult>
}

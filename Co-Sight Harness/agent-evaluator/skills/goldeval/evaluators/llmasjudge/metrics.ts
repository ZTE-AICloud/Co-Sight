export function round(value: number): number {
  return Math.round(value * 100) / 100
}

export function precisionOf(tp: number, fp: number, fn: number): number {
  return tp + fp === 0 ? (tp + fn === 0 ? 1 : 0) : tp / (tp + fp)
}

export function recallOf(tp: number, fp: number, fn: number): number {
  return tp + fn === 0 ? (tp + fp === 0 ? 1 : 0) : tp / (tp + fn)
}

export function f1Of(tp: number, fp: number, fn: number): number {
  const denominator = 2 * tp + fp + fn
  return denominator === 0 ? 1 : (2 * tp) / denominator
}

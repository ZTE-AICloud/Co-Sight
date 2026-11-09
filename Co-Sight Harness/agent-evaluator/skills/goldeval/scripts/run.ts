import { mkdirSync, readFileSync, writeFileSync } from 'fs'
import { join } from 'path'
import { listEvaluators, resolveEvaluator } from '../evaluators/index.ts'
import type {
  ClassifyOutcome,
  EvalResult,
  EvalSample,
  ResolvedEvaluator,
} from '../evaluators/index.ts'
import { classifyOutcome } from '../evaluators/llmasjudge/classifyPipeline.ts'
import { getMainLoopModel } from '../evaluators/llmasjudge/llm.ts'
import { GOLDEVAL_VERSION } from '../version.ts'

const MAX_SAMPLES = 100

interface EvalOptions {
  dataset: string
  evaluators: string[]
  threshold?: string
  outputs: string
  worker: number
  value?: string
}

function parseArgs(args: string[]): Partial<EvalOptions> {
  const options: Partial<EvalOptions> = { evaluators: [] }
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--dataset') {
      options.dataset = args[i + 1]
      i++
    } else if (args[i] === '--evaluators') {
      options.evaluators = (args[i + 1] ?? '')
        .split(',')
        .map((s) => s.trim())
        .filter((s) => s.length > 0)
      i++
    } else if (args[i] === '--threshold') {
      options.threshold = args[i + 1]
      i++
    } else if (args[i] === '--outputs') {
      options.outputs = args[i + 1]
      i++
    } else if (args[i] === '--worker') {
      options.worker = Number.parseInt(args[i + 1] ?? '', 10)
      i++
    } else if (args[i] === '--value') {
      options.value = args[i + 1]
      i++
    }
  }
  return options
}

function loadDataset(path: string): Array<Record<string, unknown>> {
  const content = readFileSync(path, 'utf-8')
  return content
    .split('\n')
    .filter((line) => line.trim().length > 0)
    .map((line) => JSON.parse(line) as Record<string, unknown>)
}

function toSample(sample: Record<string, unknown>): EvalSample {
  return {
    data_id: String(sample.data_id ?? ''),
    input: String(sample.input ?? ''),
    output: String(sample.output ?? ''),
    expected_output: String(sample.expected_output ?? ''),
    context:
      sample.context === undefined ? undefined : String(sample.context),
    metadata: (sample.metadata ?? {}) as Record<string, unknown>,
  }
}

function timestamp(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
}

async function runPool<T>(
  tasks: Array<() => Promise<T>>,
  concurrency: number,
): Promise<T[]> {
  const results = new Array<T>(tasks.length)
  let next = 0
  async function runner() {
    while (next < tasks.length) {
      const index = next
      next++
      results[index] = await tasks[index]()
    }
  }
  const workers = Array.from(
    { length: Math.min(concurrency, tasks.length) },
    () => runner(),
  )
  await Promise.all(workers)
  return results
}

const round2 = (value: number): number => Math.round(value * 100) / 100

function writeSummary(
  taskDir: string,
  data: {
    taskId: string
    dataset: string
    model: string
    threshold: string
    thresholds: Record<string, number>
    noThreshold: string[]
    evaluators: Record<string,{ results: EvalResult[]; mean: number; passed: number }>
  },
): void {
  const names = Object.keys(data.evaluators)
  const totalSamples =
    names.length > 0 ? data.evaluators[names[0]]!.results.length : 0

  const results: Record<string, Record<string, unknown>> = {}
  for (const name of names) {
    const { results: rs, mean, passed } = data.evaluators[name]!
    const scores = rs.map((r) => r.score)
    const item: Record<string, unknown> =
      scores.length === 0
        ? { avg: 0, min: 0, max: 0, passed: 0, pass_rate: 0, samples: 0, scores: [] }
        : {
            avg: round2(mean),
            min: round2(Math.min(...scores)),
            max: round2(Math.max(...scores)),
            passed,
            pass_rate: round2(passed / rs.length),
            samples: rs.length,
            scores: scores.map(round2),
          }
    if (!data.noThreshold.includes(name)) {
      item.threshold = data.thresholds[name] ?? data.threshold
    }
    results[name] = item
  }

  const generatedTime = new Date().toISOString()
  const report = {
    task_id: data.taskId,
    dataset: data.dataset,
    samples: totalSamples,
    threshold: data.threshold,
    evaluators: names,
    model: data.model.split(',').at(-1),
    generated_time: generatedTime,
    results,
  }
  writeFileSync(
    join(taskDir, 'summary.json'),
    JSON.stringify(report, null, 2) + '\n',
  )

  const lines: string[] = ['# 评测报告', '', '## 评测任务信息']
  lines.push(`- **任务ID(task_id)**: ${data.taskId}`)
  lines.push(`- **测试集(dataset)**: ${data.dataset}`)
  lines.push(`- **样本数量(samples)**: ${totalSamples}`)
  lines.push(`- **阈值(threshold)**: ${data.threshold}`)
  lines.push(`- **评估器(evaluators)**: ${names.join(', ') || '(无)'}`)
  lines.push(`- **模型名称(model)**: ${data.model.split(',').at(-1)}`)
  lines.push(`- **报告生成时间(generated_time)**: ${generatedTime}`)
  lines.push('', '## 评测结果汇总', '', '| 评估器 | 平均值 | 通过率(按阈值) | 阈值 |', '|---|---|---|---|')
  for (const name of names) {
    const r = results[name]!
    const rate = (Number(r.pass_rate) * 100).toFixed(0)
    const thr = r.threshold !== undefined ? String(r.threshold) : '—'
    lines.push(`| ${name} | ${Number(r.avg).toFixed(2)} | ${rate}% | ${thr} |`)
  }
  lines.push('', '## 评估结果详情')
  for (const name of names) {
    const r = results[name]!
    const rate = (Number(r.pass_rate) * 100).toFixed(0)
    lines.push('', `### ${name}`)
    lines.push(`- 样本数: ${r.samples}`)
    lines.push(`- 平均值: ${Number(r.avg).toFixed(2)}`)
    if (r.threshold !== undefined) lines.push(`- 阈值：${r.threshold}`)
    lines.push(`- 通过率(按阈值): ${r.passed}/${r.samples}（${rate}%）`)
    lines.push(`- 最大值：${Number(r.max).toFixed(2)}`)
    lines.push(`- 最小值：${Number(r.min).toFixed(2)}`)
    lines.push(
      `- 各样本得分: ${(r.scores as number[]).map((s) => s.toFixed(2)).join(', ')}`,
    )
  }
  writeFileSync(join(taskDir, 'report.md'), lines.join('\n') + '\n')
  console.log(`\n报告已写入: ${join(taskDir, 'summary.json')} / report.md`)
}

const DEFAULT_THRESHOLD = 0.6

interface ThresholdConfig {
  global?: number
  perEvaluator?: Map<string, number>
}

function parseThreshold(raw: string | undefined): ThresholdConfig {
  if (raw === undefined || raw.trim() === '') return {}
  if (raw.includes(':')) {
    const perEvaluator = new Map<string, number>()
    for (const part of raw.split(',')) {
      const colon = part.indexOf(':')
      if (colon === -1) {
        console.error(`ERROR: 无效的 threshold 配置: ${part}（应为 key:value）`)
        process.exit(1)
      }
      const key = part.slice(0, colon).trim()
      const num = Number.parseFloat(part.slice(colon + 1))
      if (!key || !Number.isFinite(num)) {
        console.error(`ERROR: 无效的 threshold 配置: ${part}`)
        process.exit(1)
      }
      perEvaluator.set(key, num)
    }
    return { perEvaluator }
  }
  const num = Number.parseFloat(raw)
  if (!Number.isFinite(num)) {
    console.error('ERROR: --threshold must be a float or key:value map')
    process.exit(1)
  }
  return { global: num }
}

function getThreshold(cfg: ThresholdConfig, name: string): number {
  if (cfg.perEvaluator) return cfg.perEvaluator.get(name) ?? DEFAULT_THRESHOLD
  return cfg.global ?? DEFAULT_THRESHOLD
}

const options = parseArgs(process.argv.slice(2))

if (!options.dataset) {
  console.error('ERROR: --dataset <path> is required')
  process.exit(1)
}

const thresholdCfg = parseThreshold(options.threshold)

let worker = 1
if (options.worker !== undefined) {
  if (!Number.isInteger(options.worker)) {
    console.error('ERROR: --worker must be an integer')
    process.exit(1)
  }
  worker = Math.min(5, Math.max(1, options.worker))
}

const requestedNames =
  options.evaluators && options.evaluators.length > 0
    ? options.evaluators
    : ['f1_score']

const resolved: ResolvedEvaluator[] = []
for (const name of requestedNames) {
  const item = resolveEvaluator(name)
  if (!item) {
    console.error(`ERROR: unknown evaluator '${name}'`)
    console.error(`available: ${listEvaluators().map((e) => e.name).join(', ')}`)
    process.exit(1)
  }
  if (item.negate && item.family !== 'certainty') {
    console.error(
      `ERROR: not- 前缀仅支持确定性评估器（certainty），'${name}' 属于 ${item.family ?? '未知'}`,
    )
    process.exit(1)
  }
  resolved.push(item)
}

const usesCertainty = resolved.some((r) => r.family === 'certainty')
if (usesCertainty && options.value === undefined) {
  console.error('ERROR: 确定性评估器（certainty）需要 --value <value> 参数')
  process.exit(1)
}

const samples = loadDataset(options.dataset)
if (samples.length > MAX_SAMPLES) {
  console.error(
    `ERROR: 数据集超过 ${MAX_SAMPLES} 条，不支持（当前 ${samples.length} 条）`,
  )
  process.exit(1)
}
const taskId = timestamp()
const taskDir = join(options.outputs ?? process.cwd(), 'eval_results', taskId)
mkdirSync(taskDir, { recursive: true })

console.log(`goldeval ${GOLDEVAL_VERSION}`)
console.log(`task_id: ${taskId}`)
console.log(`dataset: ${options.dataset} (${samples.length} samples)`)
const thresholdDesc = thresholdCfg.perEvaluator
  ? `per-evaluator: ${[...thresholdCfg.perEvaluator.entries()]
      .map(([k, v]) => `${k}=${v}`)
      .join(', ')}（未指定默认 ${DEFAULT_THRESHOLD}）`
  : `${thresholdCfg.global ?? DEFAULT_THRESHOLD}`
console.log(`threshold: ${thresholdDesc}`)
console.log(`worker: ${worker}`)
console.log(`output_dir: ${taskDir}`)

const useSharedOutcome =
  resolved.length >= 2 &&
  resolved.every((r) => r.evaluator.pipeline === 'classify')

let sharedOutcomes: ClassifyOutcome[] | undefined
if (useSharedOutcome) {
  console.log(
    `shared pipeline: ${resolved.length} 个评估器共用分句+归类（每样本只算一次）`,
  )
  sharedOutcomes = await runPool(
    samples.map(
      (sample, index) => () =>
        classifyOutcome(toSample(sample), {
          threshold: DEFAULT_THRESHOLD,
          dataId: String(sample.data_id ?? ''),
          outputDir: taskDir,
        }),
    ),
    worker,
  )
}

const summaryResults: Record<string,{ results: EvalResult[]; mean: number; passed: number }> = {}

const noThreshold = resolved
  .filter((r) => r.family === 'certainty')
  .map((r) => r.name)

const thresholds: Record<string, number> = {}

for (const item of resolved) {
  const evalThreshold = getThreshold(thresholdCfg, item.name)
  thresholds[item.name] = evalThreshold
  const results = await runPool(
    samples.map((sample, index) => () =>
      item.evaluator.evaluate(toSample(sample), {
        threshold: evalThreshold,
        dataId: String(sample.data_id ?? ''),
        outputDir: taskDir,
        value: options.value,
        name: item.name,
        negate: item.negate,
        ...(sharedOutcomes ? { outcome: sharedOutcomes[index] } : {}),
      }),
    ),
    worker,
  )
  const mean = results.reduce((sum, r) => sum + r.score, 0) / results.length
  const passed = results.filter((r) => r.passed).length
  summaryResults[item.name] = { results, mean, passed }
  const resultsPath = join(taskDir, `${item.name}_results.jsonl`)
  writeFileSync(
    resultsPath,
    results.map((r) => JSON.stringify(r)).join('\n') + '\n',
  )
  console.log(`\n=== ${item.name} ===`)
  results.forEach((r) => {
    const status = r.error
      ? ` [ERROR: ${r.error}]`
      : r.passed
        ? ' [PASS]'
        : ' [FAIL]'
    console.log(`${r.data_id} = ${r.score.toFixed(4)}${status}`)
  })
  console.log(`mean = ${mean.toFixed(4)}, passed = ${passed}/${results.length}`)
  console.log(`结果已写入: ${resultsPath}`)
}

writeSummary(taskDir, {
  taskId,
  dataset: options.dataset,
  model: getMainLoopModel(),
  threshold: options.threshold ?? String(DEFAULT_THRESHOLD),
  thresholds,
  noThreshold,
  evaluators: summaryResults,
})

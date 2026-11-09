import { mkdirSync, writeFileSync } from 'fs'
import { join } from 'path'
import { extractJson, llmCall } from './llm.ts'
import type { ClassifyOutcome, EvalOptions, EvalSample } from '../types.ts'

const MAX_RETRIES = 3

export const SPLIT_PROMPT = `你是评测助手，负责把文本按语义拆分为独立的句子（一个要点一句话，按逗号、分号、句号等合理切分）。
请对下面两段文本分别分句：

【文本A - output】
{output}

【文本B - expected_output】
{expected_output}

请只输出 JSON，不要任何其他内容或解释：
{"output_sentences": ["句子1", "句子2"], "expected_sentences": ["句子1", "句子2"]}`

export const CLASSIFY_PROMPT = `你是评测助手，根据分句结果判断句子归属：
- TP：output 与 expected_output 中语义等价的句子（都存在的句子）
- FP：output 中存在但 expected_output 中不存在的句子
- FN：expected_output 中存在但 output 中不存在的句子

【output 分句】
{output_sentences}

【expected_output 分句】
{expected_sentences}

请只输出 JSON，不要任何其他内容或解释：
{"tp": ["句子"], "fp": ["句子"], "fn": ["句子"], "reason": "简要打分说明"}`

interface SentenceSplit {
  output_sentences: string[]
  expected_sentences: string[]
}

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .map((v) => String(v).trim())
    .filter((s) => s.length > 0)
}

async function withRetry<T>(fn: () => Promise<T>): Promise<T> {
  let lastError: unknown
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      return await fn()
    } catch (error) {
      lastError = error
      if (attempt < MAX_RETRIES) {
        console.log(
          `LLM 输出解析失败，第 ${attempt}/${MAX_RETRIES - 1} 次重试：${error instanceof Error ? error.message : String(error)}`,
        )
      }
    }
  }
  throw lastError
}

async function splitSentences(sample: EvalSample): Promise<SentenceSplit> {
  const prompt = SPLIT_PROMPT.replace('{output}', sample.output).replace(
    '{expected_output}',
    sample.expected_output,
  )
  return withRetry(async () => {
    const parsed = extractJson(await llmCall(prompt)) as {
      output_sentences?: unknown
      expected_sentences?: unknown
    }
    return {
      output_sentences: toStringArray(parsed.output_sentences),
      expected_sentences: toStringArray(parsed.expected_sentences),
    }
  })
}

async function classifySentences(split: SentenceSplit): Promise<ClassifyOutcome> {
  const prompt = CLASSIFY_PROMPT.replace(
    '{output_sentences}',
    JSON.stringify(split.output_sentences, null, 2),
  ).replace(
    '{expected_sentences}',
    JSON.stringify(split.expected_sentences, null, 2),
  )
  return withRetry(async () => {
    const parsed = extractJson(await llmCall(prompt)) as {
      tp?: unknown
      fp?: unknown
      fn?: unknown
      reason?: unknown
    }
    return {
      tp: toStringArray(parsed.tp),
      fp: toStringArray(parsed.fp),
      fn: toStringArray(parsed.fn),
      reason: typeof parsed.reason === 'string' ? parsed.reason : undefined,
    }
  })
}

function parseError(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

export async function classifyOutcome(
  sample: EvalSample,
  options: EvalOptions,
): Promise<ClassifyOutcome> {
  if (options.outcome) return options.outcome

  const processDir = join(options.outputDir, 'process', options.dataId)
  mkdirSync(processDir, { recursive: true })

  let split: SentenceSplit
  let classify: ClassifyOutcome
  try {
    split = await splitSentences(sample)
  } catch (error) {
    const message = `分句失败：${parseError(error)}`
    console.error(`[${options.dataId}] ${message}`)
    return { tp: [], fp: [], fn: [], error: message }
  }
  writeFileSync(join(processDir, 'split.json'), JSON.stringify(split, null, 2))

  if (
    split.output_sentences.length === 0 &&
    split.expected_sentences.length === 0
  ) {
    const message = '分句结果为空，跳过归类'
    console.error(`[${options.dataId}] ${message}`)
    return { tp: [], fp: [], fn: [], error: message }
  }

  try {
    classify = await classifySentences(split)
  } catch (error) {
    const message = `归类失败：${parseError(error)}`
    console.error(`[${options.dataId}] ${message}`)
    return { tp: [], fp: [], fn: [], error: message }
  }
  writeFileSync(
    join(processDir, 'classify.json'),
    JSON.stringify(classify, null, 2),
  )

  if (classify.tp.length + classify.fp.length + classify.fn.length === 0) {
    const message = '归类结果为空，无法计分'
    console.error(`[${options.dataId}] ${message}`)
    return { tp: [], fp: [], fn: [], error: message }
  }

  return {
    tp: classify.tp,
    fp: classify.fp,
    fn: classify.fn,
    reason: classify.reason,
  }
}

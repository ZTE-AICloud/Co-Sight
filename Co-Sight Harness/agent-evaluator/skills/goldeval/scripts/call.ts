import { llmCall } from '../evaluators/llmasjudge/llm.ts'

const splitRaw = await llmCall("你好")
console.log(splitRaw)
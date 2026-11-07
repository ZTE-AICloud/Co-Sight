/**
 * 从模型答案里拆出思考块（`<think>…</think>`）。
 *
 * 为什么要前端拆：模型**自己**把 `<think>` 写进 `content` 时，编排侧是**原文透传**的
 * （适配器只在思考出现在 `reasoning_content` 时才代它包标记，见
 * `engine/custom_llm/openai_llm.py` 的文件头说明）。
 * 整段铺在气泡里等于把模型的草稿纸给用户看，而它对定位问题又确实有用 ——
 * 所以页面上是**收起**而不是丢掉。
 *
 * 零 Vue 依赖：纯字符串进、纯对象出。
 */

/** 拆分结果。`thinking` 为思考块正文，`text` 为剥掉思考块之后的答案正文。 */
export interface ReasoningParts {
  thinking: string
  text: string
}

/**
 * 三种情况都要处理，因为**流式下会先看到半个思考**（同一个函数会被逐帧调用，
 * 输入是「到目前为止累积的全部正文」）：
 *   ① 有成对标记 → 正常拆开（只取**第一对**，`replace` 传的是字符串不是正则，
 *      因此也只替换第一次出现——多余的 `<think>` 留在正文里原样可见）；
 *   ② 只有开标记（思考还没结束 / 被中断）→ 全算思考，正文为空；
 *   ③ 没有标记 → 全是正文。
 *
 * `raw` 声明成 `unknown` 而不是 `string`：调用方拿到的可能是任何东西（恢复出来的
 * 脏数据、非文本帧），这里统一按「没有思考块」处理，不在这一层抛错。
 */
export function splitReasoning (raw: unknown): ReasoningParts {
  const text = typeof raw === 'string' ? raw : ''
  const closed = text.match(/<think>([\s\S]*?)<\/think>/i)
  if (closed) {
    return {
      thinking: closed[1].trim(),
      text: text.replace(closed[0], '').trim()
    }
  }
  const opened = text.match(/<think>([\s\S]*)$/i)
  if (opened) {
    return { thinking: opened[1].trim(), text: '' }
  }
  return { thinking: '', text }
}

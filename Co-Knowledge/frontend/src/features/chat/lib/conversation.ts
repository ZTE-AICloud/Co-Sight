/**
 * 会话 id 生成。零 Vue 依赖的纯函数层。
 */

/** 随机 id 取多少个字节（16 字节 = 128 位，够用且不浪费） */
export const CONVERSATION_ID_BYTES = 16

const HEX_RADIX = 16
const BASE36_RADIX = 36
// `Math.random().toString(36)` 形如 "0.k3j9x..."：跳过前两个字符取 8 位做随机后缀
const RANDOM_SUFFIX_START = 2
const RANDOM_SUFFIX_END = 10

/**
 * 会话 id。服务端拿它当 chat memory 的键（必填，空值会被拒），多轮上下文靠它串。
 *
 * ⚠️ 不能用 `crypto.randomUUID()`：它只在 secure context 存在，而本应用是
 * `http://<ip>/` 部署，线上会直接 `undefined is not a function`。
 * `crypto.getRandomValues` 没有这个限制，下面的时间戳分支只是最后的兜底。
 *
 * 这里用 `typeof window === 'undefined'` 包一层再取 `window.crypto`：浏览器里与直接写
 * `window.crypto` **完全等价**（没有任何降级），但让这个函数在 Node（单测）里也能调用，
 * 从而可以分别把「有 crypto」和「无 crypto」两条分支都钉住。
 */
export function newConversationId (): string {
  const cryptoObj = typeof window === 'undefined' ? undefined : window.crypto
  if (cryptoObj && typeof cryptoObj.getRandomValues === 'function') {
    const bytes = cryptoObj.getRandomValues(new Uint8Array(CONVERSATION_ID_BYTES))
    const hex = Array.from(bytes, b => b.toString(HEX_RADIX).padStart(2, '0')).join('')
    return `conv-${hex}`
  }
  const suffix = Math.random()
    .toString(BASE36_RADIX)
    .slice(RANDOM_SUFFIX_START, RANDOM_SUFFIX_END)
  return `conv-${Date.now().toString(BASE36_RADIX)}-${suffix}`
}

/**
 * 确定性词法向量。
 *
 * 目标不是“语义质量”，而是让 E2E 的向量检索**可预测**：
 * - 同一文本 → 同一向量；
 * - 词元重叠越多 → 余弦相似度越高；
 * - 不依赖任何外部模型/网络。
 *
 * 中文按单字 + 相邻双字切分，英文/数字按连续串切分；用两个哈希做 signed
 * hashing trick，降低维度碰撞带来的噪声。
 */

export const DEFAULT_DIMENSION = 1024

function fnv1a (text) {
  let hash = 0x811c9dc5
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i)
    hash = Math.imul(hash, 0x01000193) >>> 0
  }
  return hash >>> 0
}

function hashPair (token) {
  const first = fnv1a(token)
  const second = fnv1a(`${token}#salt`)
  return [first, second]
}

export function tokenize (text) {
  const value = String(text || '').toLowerCase()
  const tokens = []

  for (const match of value.matchAll(/[a-z0-9]+/g)) {
    tokens.push(match[0])
  }

  const cjk = [...value].filter(char => /[㐀-鿿]/.test(char))
  tokens.push(...cjk)
  for (let i = 0; i < cjk.length - 1; i += 1) {
    tokens.push(cjk[i] + cjk[i + 1])
  }

  // 标点分隔的标记（如 E2E-MARKER-...）已经由 [a-z0-9]+ 覆盖。
  return tokens
}

export function embed (text, dimension = DEFAULT_DIMENSION) {
  const vector = new Float64Array(dimension)
  for (const token of tokenize(text)) {
    const [bucketHash, signHash] = hashPair(token)
    const bucket = bucketHash % dimension
    const sign = (signHash & 1) === 0 ? 1 : -1
    vector[bucket] += sign
  }

  let norm = 0
  for (const value of vector) norm += value * value
  norm = Math.sqrt(norm)
  if (norm === 0) {
    vector[0] = 1
    return Array.from(vector)
  }
  return Array.from(vector, value => value / norm)
}

/** 词元重叠度（用于 rerank 的稳定排序）。 */
export function lexicalScore (query, document) {
  const queryTokens = new Set(tokenize(query))
  const documentTokens = new Set(tokenize(document))
  if (queryTokens.size === 0 || documentTokens.size === 0) return 0
  let overlap = 0
  for (const token of queryTokens) {
    if (documentTokens.has(token)) overlap += 1
  }
  return overlap / Math.sqrt(queryTokens.size * documentTokens.size)
}

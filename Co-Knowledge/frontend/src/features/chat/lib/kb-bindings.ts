/**
 * 已发布工作流 → 绑定的知识库 → 是否仍然存在。
 *
 * 背景：知识库被删除后，已发布工作流里仍留着它的
 * `knowledge_base_name`；运行时按名称查不到库、静默召回 0 条，对话给出的
 * 「没有上下文」答复看不出任何异常。这里只做**纯判据**，网络与 UI 在
 * `useWorkflowBindingCheck` / `ChatTest.vue` 里。
 *
 * 零 Vue 依赖（`lib/` 的约定），可以直接在 Node 里单测。
 */

/** 画布里存库名的字段（向量/关键词/图谱检索、响应合成器都用它）。 */
const KB_NAME_KEY = 'knowledge_base_name'

/** 画布里的作用域后缀，例如 `doc_<uuid>|#|dev`、`graph_<uuid>|#|发布态`。 */
const SCOPE_SEPARATOR = '|#|'

/** 检索侧基名 / 物理表名的前缀（`data_` 是旧向量表拼法，保留兜底）。 */
const NAME_PREFIXES = ['doc_', 'graph_', 'data_']

/** 物理向量表名后缀（新库 `doc_<uuid>_vector`）。 */
const NAME_SUFFIXES = ['_vector']

/** `allStatusKbase` 返回的下拉项里，能用来比对身份的字段。 */
export interface KbBindingOption {
  tableName?: unknown
  dbTableName?: unknown
  assetId?: unknown
  kbaseId?: unknown
  [key: string]: unknown
}

/**
 * 把任意形态的库名归一成「身份 token」：
 *   `doc_<uuid>` / `graph_<uuid>` / `data_<uuid>` / `doc_<uuid>_vector` / `<uuid>|#|名称`
 * 都得到 `<uuid>`。
 *
 * 空值返回空串（调用方应跳过）。
 */
export function normalizeKbIdentity (name: unknown): string {
  if (typeof name !== 'string') {
    return ''
  }
  let value = name.trim()
  if (!value) {
    return ''
  }
  const scopeIndex = value.indexOf(SCOPE_SEPARATOR)
  if (scopeIndex >= 0) {
    value = value.slice(0, scopeIndex)
  }
  // 前缀可能叠加（如 data_ + doc_…），循环剥干净
  let stripped = true
  while (stripped) {
    stripped = false
    const lower = value.toLowerCase()
    for (const prefix of NAME_PREFIXES) {
      if (lower.startsWith(prefix)) {
        value = value.slice(prefix.length)
        stripped = true
        break
      }
    }
  }
  // 新物理向量表名带 `_vector` 后缀（doc_<uuid>_vector），身份 token 是中间的 uuid。
  const lowered = value.toLowerCase()
  for (const suffix of NAME_SUFFIXES) {
    if (lowered.endsWith(suffix)) {
      value = value.slice(0, -suffix.length)
      break
    }
  }
  return value.trim().toLowerCase()
}

/**
 * 从已发布画布 JSON 里收集所有 `knowledge_base_name` 的条目。
 *
 * 画布把同一份算子配置存了两遍（`data.variables` 与顶层 `variables`，见
 * `docs/canvas-two-variable-copies` 的历史教训），所以这里会自然收到重复项；
 * 按归一后的身份去重，返回**原始字符串**（用于告警文案）。
 */
export function collectBoundKbNames (config: unknown): string[] {
  const found: string[] = []
  const seen = new Set<string>()

  const visit = (node: unknown): void => {
    if (Array.isArray(node)) {
      node.forEach(visit)
      return
    }
    if (!node || typeof node !== 'object') {
      return
    }
    for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
      if (key === KB_NAME_KEY) {
        const names = Array.isArray(value) ? value : [value]
        for (const name of names) {
          const identity = normalizeKbIdentity(name)
          if (identity && !seen.has(identity)) {
            seen.add(identity)
            found.push(String(name).trim())
          }
        }
        continue
      }
      visit(value)
    }
  }

  visit(config)
  return found
}

/**
 * 找出「绑定里存在、但当前库列表里找不到」的库名。
 *
 * @param boundNames `collectBoundKbNames` 的结果
 * @param options    `/workflow/allStatusKbase` 的 `running` + `dev` 拍平
 * @returns 原始的、无法匹配的库名（顺序与输入一致，已按身份去重）
 */
export function findMissingKbNames (boundNames: string[], options: KbBindingOption[]): string[] {
  const available = new Set<string>()
  for (const option of options || []) {
    for (const field of ['tableName', 'dbTableName', 'assetId', 'kbaseId'] as const) {
      const identity = normalizeKbIdentity(option?.[field])
      if (identity) {
        available.add(identity)
      }
    }
  }

  const reported = new Set<string>()
  const missing: string[] = []
  for (const name of boundNames || []) {
    const identity = normalizeKbIdentity(name)
    if (!identity || available.has(identity) || reported.has(identity)) {
      continue
    }
    reported.add(identity)
    missing.push(name)
  }
  return missing
}

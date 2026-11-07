/**
 * 列表页指标卡的数据整形：把 `GET /knowledge-bases/stats` 的按分类汇总
 * 转成页面直接可用的 `{total, fileTotal, ready, pending, failed}`。
 *
 * 为什么分类规则留在前端：状态码的语义（0/5/7/8 = 就绪，1/2/3/4/6 = 进行中，
 * 101/102/103/104/106 = 失败）在列表页已经有一份，见 `./list-status`。
 * 后端只回原始 `statusCounts`，两端各写一份口径最容易漂移。
 *
 * 纯函数、零 Vue 依赖，可被 vitest 直接 import
 * （tests/unit/kbList.overview-stats.spec.js）。
 */
import { KB_STATUS, toNum } from './list-status'

/** 指标卡口径：这些状态算「已就绪」 */
export const READY_STATUSES: readonly number[] = [
  KB_STATUS.CREATED,
  KB_STATUS.PENDING_PUBLISH,
  KB_STATUS.PUBLISHED,
  KB_STATUS.PUBLISHED_MODIFIED
]

/** 这些状态算「进行中」（会自动往下走，列表页据此决定要不要轮询） */
export const PENDING_STATUSES: readonly number[] = [
  KB_STATUS.PARSING,
  KB_STATUS.SPLITTING,
  KB_STATUS.GENERATING,
  KB_STATUS.INDEXING,
  KB_STATUS.PUBLISHING
]

/** 这些状态算「异常」 */
export const FAILED_STATUSES: readonly number[] = [
  KB_STATUS.PARSE_FAILED,
  KB_STATUS.SPLIT_FAILED,
  KB_STATUS.GENERATE_FAILED,
  KB_STATUS.INDEX_FAILED,
  KB_STATUS.PUBLISH_FAILED
]

export interface CategoryOverview {
  total: number
  fileTotal: number
  ready: number
  pending: number
  failed: number
}

/**
 * 三类状态的划分口径。文档知识库与知识图谱对同一个状态码的解释不同
 * （0：文档知识库=已就绪、知识图谱=已创建），所以允许调用方传入自己的集合。
 */
export interface StatusBuckets {
  ready: readonly number[]
  pending: readonly number[]
  failed: readonly number[]
}

/** 默认口径：文档知识库（与拆分前 Knowledge.vue 逐值一致） */
const KB_STATUS_BUCKETS: StatusBuckets = {
  ready: READY_STATUSES,
  pending: PENDING_STATUSES,
  failed: FAILED_STATUSES
}

/** 空分类：`overviewFor` 在 stats 里没有该分类时返回它（每次一个新对象） */
export function emptyCategoryOverview (): CategoryOverview {
  return { total: 0, fileTotal: 0, ready: 0, pending: 0, failed: 0 }
}

function toCount (value: unknown): number {
  const count = Number(value)
  return Number.isFinite(count) ? count : 0
}

/**
 * 按调用方给定的三类口径汇总 `statusCounts`（知识图谱页用自己的一套集合）。
 *
 * 未知状态码不进任何一类（与拆分前逐行分类的 `else` 分支一致），因此三类之和
 * 可能小于 `total`。`statusCounts` 的键是数据库里的状态串（`'0'` / `'103'`），
 * 值也允许是字符串数字（后端一般给 number，这里不假设）。
 */
export function countStatusesWithBuckets (
  statusCounts: Record<string, unknown> | null | undefined,
  buckets: StatusBuckets
): Pick<CategoryOverview, 'ready' | 'pending' | 'failed'> {
  const counts = { ready: 0, pending: 0, failed: 0 }
  for (const [status, rawCount] of Object.entries(statusCounts || {})) {
    const count = toCount(rawCount)
    const statusCode = toNum(status)
    if (buckets.ready.includes(statusCode)) {
      counts.ready += count
    } else if (buckets.failed.includes(statusCode)) {
      counts.failed += count
    } else if (buckets.pending.includes(statusCode)) {
      counts.pending += count
    }
  }
  return counts
}

/** 按文档知识库口径汇总三类计数（默认口径，见 `KB_STATUS_BUCKETS`）。 */
export function countStatuses (
  statusCounts: Record<string, unknown> | null | undefined
): Pick<CategoryOverview, 'ready' | 'pending' | 'failed'> {
  return countStatusesWithBuckets(statusCounts, KB_STATUS_BUCKETS)
}

/** 从 `{categories: [...]}` 响应里取分类数组。 */
function categoryItems (response: unknown): any[] {
  const categories = (response as { categories?: unknown } | null | undefined)?.categories
  return Array.isArray(categories) ? categories : []
}

/**
 * `GET /knowledge-bases/stats` 的响应 → `{ [category]: CategoryOverview }`。
 * 非数字分类、缺字段、字符串数字都在这里归一；重复分类后者覆盖前者。
 * `buckets` 默认用文档知识库口径，知识图谱页传自己的集合。
 */
export function normalizeStatsResponse (
  response: unknown,
  buckets: StatusBuckets = KB_STATUS_BUCKETS
): Record<number, CategoryOverview> {
  const stats: Record<number, CategoryOverview> = {}
  for (const item of categoryItems(response)) {
    const category = Number(item?.category)
    if (!Number.isFinite(category)) {
      continue
    }
    stats[category] = {
      total: toCount(item?.total),
      fileTotal: toCount(item?.fileTotal),
      ...countStatusesWithBuckets(item?.statusCounts, buckets)
    }
  }
  return stats
}

/** 取某个分类的汇总；请求了但响应里没有时返回全零，不返回 undefined。 */
export function overviewFor (
  stats: Record<number, CategoryOverview>,
  category: number
): CategoryOverview {
  return stats[category] ? { ...stats[category] } : emptyCategoryOverview()
}

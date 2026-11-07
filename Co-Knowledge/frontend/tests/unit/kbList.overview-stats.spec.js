// 测的是 `views/kBase/lib/overview-stats.ts`：列表页指标卡的数据整形。
//
// 指标卡走 `GET /knowledge-bases/stats`（后端按分类聚合），
// 不把两个分类的 ≤500 行列表拉回来自己数。这里钉的是三样东西：
//   1. 三类状态的集合必须与列表页里的字面量一致（0/5/7/8 等）；
//   2. 「请求了但后端没返回」的分类要落成全零，不能是 undefined；
//   3. 响应形态兼容 `{categories: [...]}` 与裸数组，数字/字符串计数都吃得下。
import {
  READY_STATUSES,
  PENDING_STATUSES,
  FAILED_STATUSES,
  countStatuses,
  countStatusesWithBuckets,
  normalizeStatsResponse,
  overviewFor
} from '@/features/knowledge-base/lib/overview-stats'

function sorted (statuses) {
  return [...statuses].sort((a, b) => a - b)
}

describe('状态集合（与拆分前的页面口径逐值对齐）', () => {
  it('就绪 = 0/5/7/8，进行中 = 1/2/3/4/6，失败 = 101/102/103/104/106', () => {
    // 集合字面量在这里再抄一遍：如果重构时抄错一个数，这组断言先红
    expect(sorted(READY_STATUSES)).toEqual([0, 5, 7, 8])
    expect(sorted(PENDING_STATUSES)).toEqual([1, 2, 3, 4, 6])
    expect(sorted(FAILED_STATUSES)).toEqual([101, 102, 103, 104, 106])
  })
})

describe('countStatuses', () => {
  it('按三类分别求和，未知状态码不进任何一类', () => {
    // 三类之和 6 < total 7：未知状态不猜测归类，与拆分前逐行分类的 else 分支一致
    const counts = countStatuses({
      0: 2,
      5: 1,
      7: 1,
      8: 1,
      1: 1,
      103: 1,
      999: 5
    })

    expect(counts).toEqual({ ready: 5, pending: 1, failed: 1 })
  })

  it('空格与 null 返回全零，不抛错', () => {
    expect(countStatuses(undefined)).toEqual({ ready: 0, pending: 0, failed: 0 })
    expect(countStatuses(null)).toEqual({ ready: 0, pending: 0, failed: 0 })
    expect(countStatuses({})).toEqual({ ready: 0, pending: 0, failed: 0 })
  })

  it('字符串计数按数字累加；非数字计数按 0 处理', () => {
    const counts = countStatuses({ 0: '3', 101: '2', 5: 'abc' })

    expect(counts).toEqual({ ready: 3, pending: 0, failed: 2 })
  })

  it('状态键是数据库里的字符串，与 toNum 的字符串分支衔接', () => {
    // 后端 status 列是 varchar，JSON 里键本来就是字符串；这里不额外做转换
    expect(countStatuses({ '7': 4 })).toEqual({ ready: 4, pending: 0, failed: 0 })
  })
})

describe('countStatusesWithBuckets（知识图谱页口径）', () => {
  // 图谱页把 0 当「已创建」（不算就绪），就绪只有 5
  const GRAPH_BUCKETS = {
    ready: [5],
    pending: [0, 1, 2, 3, 4, 6],
    failed: [101, 102, 103, 104, 106]
  }

  it('同一个状态 0 在图谱口径下算「进行中」，文档口径下算「就绪」', () => {
    expect(countStatuses({ 0: 3 })).toEqual({ ready: 3, pending: 0, failed: 0 })
    expect(countStatusesWithBuckets({ 0: 3 }, GRAPH_BUCKETS)).toEqual({
      ready: 0,
      pending: 3,
      failed: 0
    })
  })

  it('按给定集合求和，未知状态不进任何一类', () => {
    const counts = countStatusesWithBuckets(
      { 5: 2, 0: 1, 1: 1, 4: '1', 103: 1, 999: 7 },
      GRAPH_BUCKETS
    )

    expect(counts).toEqual({ ready: 2, pending: 3, failed: 1 })
  })
})

describe('normalizeStatsResponse', () => {
  it('把 {categories:[...]} 归一成以分类号为键的对象', () => {
    const stats = normalizeStatsResponse({
      categories: [
        {
          category: 1,
          total: 6,
          fileTotal: 64,
          statusCounts: { 0: 5, 103: 1 }
        },
        {
          category: 10,
          total: 3,
          fileTotal: 0,
          statusCounts: { 5: 3 }
        }
      ]
    })

    expect(stats[1]).toEqual({ total: 6, fileTotal: 64, ready: 5, pending: 0, failed: 1 })
    expect(stats[10]).toEqual({ total: 3, fileTotal: 0, ready: 3, pending: 0, failed: 0 })
  })

  it('字符串分类号与计数按数字归一', () => {
    const stats = normalizeStatsResponse({
      categories: [
        { category: '10', total: '2', fileTotal: '0', statusCounts: { '101': '2' } }
      ]
    })

    expect(stats[10]).toEqual({ total: 2, fileTotal: 0, ready: 0, pending: 0, failed: 2 })
  })

  it('传自定义口径时按该口径分类（图谱页的 0 不算就绪）', () => {
    const stats = normalizeStatsResponse(
      { categories: [{ category: 10, total: 3, fileTotal: 5, statusCounts: { 0: 2, 5: 1 } }] },
      { ready: [5], pending: [0, 1, 2, 3, 4, 6], failed: [101, 102, 103, 104, 106] }
    )

    expect(stats[10]).toEqual({ total: 3, fileTotal: 5, ready: 1, pending: 2, failed: 0 })
  })

  it('缺字段按 0 处理，缺少 categories 时返回空对象', () => {
    expect(normalizeStatsResponse({ categories: [{ category: 1 }] })[1]).toEqual({
      total: 0,
      fileTotal: 0,
      ready: 0,
      pending: 0,
      failed: 0
    })
    expect(normalizeStatsResponse(null)).toEqual({})
    expect(normalizeStatsResponse({})).toEqual({})
    expect(normalizeStatsResponse({ categories: 'oops' })).toEqual({})
  })

  it('非数字分类号被丢弃', () => {
    expect(normalizeStatsResponse({ categories: [{ category: 'x', total: 1 }] })).toEqual({})
  })
})

describe('overviewFor', () => {
  it('命中时返回一份拷贝（改它不会污染 stats）', () => {
    const stats = normalizeStatsResponse({
      categories: [{ category: 1, total: 2, fileTotal: 3, statusCounts: { 0: 2 } }]
    })

    const item = overviewFor(stats, 1)
    item.total = 999

    expect(stats[1].total).toBe(2)
  })

  it('未命中时返回全零，而不是 undefined', () => {
    expect(overviewFor({}, 10)).toEqual({
      total: 0,
      fileTotal: 0,
      ready: 0,
      pending: 0,
      failed: 0
    })
  })
})

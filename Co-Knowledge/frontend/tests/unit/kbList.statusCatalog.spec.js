// 测的是 `features/knowledge-base/lib/status-catalog.ts`：状态列文案表 + 状态筛选分桶表
// （文档知识库列表页与知识图谱列表页各一套）。
//
// 钉住的是「筛选与实际状态值一致」这条口径：
//   * 目录里的每种文案都能在中英文 i18n 里取到（状态列与筛选项共用 i18n 树）；
//   * 状态码不重复归属，分桶**恰好划分**目录里的全部状态码 —— 状态列能显示的
//     每个状态都落进一个桶，不会出现「列里有、筛选里筛不到」；
//   * 选了某个桶，命中的行恰好就是桶里那些状态码。
// 页面模板不再各写一份 v-if 链，所以这里红了就是两页都会错。
import zhI18n from '@/app/i18n/zh.js'
import enI18n from '@/app/i18n/en.js'
import { KB_STATUS } from '@/features/knowledge-base/lib/list-status'
import {
  ALL_STATUS_FILTER,
  DOC_KB_STATUS_DEFINITIONS,
  DOC_KB_STATUS_FILTERS,
  GRAPH_STATUS_DEFINITIONS,
  GRAPH_STATUS_FILTERS,
  findStatusDefinition,
  findStatusFilterOption
} from '@/features/knowledge-base/lib/status-catalog'

/** 按 `modules.kb.xxx` 路径取文案；取不到返回 undefined（裸键名会直接渲染到界面上） */
function messageOf (messages, key) {
  return key.split('.').reduce((node, part) => (
    node && typeof node === 'object' ? node[part] : undefined
  ), messages)
}

/** 目录里出现过的全部状态码（含同一文案下的多个码） */
function allCodes (definitions) {
  return definitions.flatMap(definition => definition.codes)
}

/** 分桶里出现过的全部状态码 */
function allBucketCodes (filters) {
  return filters.flatMap(filter => filter.codes)
}

function sorted (values) {
  return [...values].sort((a, b) => a - b)
}

const catalogs = [
  ['文档知识库', DOC_KB_STATUS_DEFINITIONS, DOC_KB_STATUS_FILTERS],
  ['知识图谱', GRAPH_STATUS_DEFINITIONS, GRAPH_STATUS_FILTERS]
]

describe('状态目录：文案与 i18n', () => {
  it.each(catalogs)('given_%s目录_when_查i18n_then_状态列文案键都存在', (name, definitions) => {
    for (const definition of definitions) {
      expect(messageOf(zhI18n, definition.labelKey), `${name} 缺中文文案：${definition.labelKey}`)
        .toEqual(expect.any(String))
      expect(messageOf(enI18n, definition.labelKey), `${name} 缺英文文案：${definition.labelKey}`)
        .toEqual(expect.any(String))
    }
  })

  it.each(catalogs)('given_%s目录_when_查i18n_then_筛选项文案键都存在', (name, definitions, filters) => {
    for (const filter of filters) {
      expect(messageOf(zhI18n, filter.labelKey), `${name} 缺中文筛选项：${filter.labelKey}`)
        .toEqual(expect.any(String))
      expect(messageOf(enI18n, filter.labelKey), `${name} 缺英文筛选项：${filter.labelKey}`)
        .toEqual(expect.any(String))
    }
  })

  it.each(catalogs)('given_%s目录_when_同一文案绑定多个状态码_then_只绑定一次', (name, definitions) => {
    const codes = allCodes(definitions)
    expect(new Set(codes).size, `${name} 有状态码被两个文案重复认领：${codes.join(',')}`)
      .toBe(codes.length)
  })

  it.each(catalogs)('given_%s_when_检查筛选值_then_不重复', (name, definitions, filters) => {
    expect(new Set(filters.map(filter => filter.value)).size).toBe(filters.length)
  })
})

describe('状态筛选：分桶覆盖状态列', () => {
  it('文档知识库分桶覆盖 KB_STATUS 的全部状态码（不多不少）', () => {
    expect(sorted(allBucketCodes(DOC_KB_STATUS_FILTERS)))
      .toEqual(sorted(Object.values(KB_STATUS)))
  })

  it('图谱分桶覆盖图谱状态列会出现的全部状态码（不含发布态）', () => {
    const rendered = sorted(allCodes(GRAPH_STATUS_DEFINITIONS))
    expect(sorted(allBucketCodes(GRAPH_STATUS_FILTERS)))
      .toEqual(rendered)
  })

  it.each(catalogs)('given_%s_when_逐个状态码查桶_then_有且只有一个桶收编', (name, definitions, filters) => {
    for (const code of allCodes(definitions)) {
      const owners = filters.filter(filter => filter.codes.includes(code))
      expect(owners, `${name} 状态码 ${code} 的归属桶数量不是 1`).toHaveLength(1)
    }
  })

  it.each(catalogs)('given_%s_when_状态码不在目录里_then_不命中任何桶', (name, definitions, filters) => {
    for (const status of [999, 105, 107, -1, NaN]) {
      expect(filters.some(filter => filter.codes.includes(status)),
        `${name} 的筛选把未知状态 ${status} 收编了`).toBe(false)
    }
  })
})

describe('状态筛选：命中与状态列一致', () => {
  it('给定全部状态时不筛任何行', () => {
    expect(findStatusFilterOption(DOC_KB_STATUS_FILTERS, ALL_STATUS_FILTER)).toBeUndefined()
    expect(findStatusFilterOption(GRAPH_STATUS_FILTERS, ALL_STATUS_FILTER)).toBeUndefined()
  })

  it('已经失效的筛选值按不筛处理（不会筛成空列表）', () => {
    // 旧版本留下的 waiting / pending / 逐条状态码等值在页面重载前可能还在
    expect(findStatusFilterOption(DOC_KB_STATUS_FILTERS, 'waiting')).toBeUndefined()
    expect(findStatusFilterOption(GRAPH_STATUS_FILTERS, '2')).toBeUndefined()
  })

  it('图谱「已创建」只命中 0，不吞掉已就绪（5）', () => {
    const option = findStatusFilterOption(GRAPH_STATUS_FILTERS, 'created')
    expect(option.codes).toEqual([KB_STATUS.CREATED])
  })

  it('图谱「已就绪」只命中 5', () => {
    const option = findStatusFilterOption(GRAPH_STATUS_FILTERS, 'ready')
    expect(option.codes).toEqual([5])
  })

  it('图谱「处理中」命中四个构建阶段，且不含已创建/已就绪', () => {
    const option = findStatusFilterOption(GRAPH_STATUS_FILTERS, 'processing')
    expect(sorted(option.codes)).toEqual([
      KB_STATUS.PARSING,
      KB_STATUS.SPLITTING,
      KB_STATUS.GENERATING,
      KB_STATUS.INDEXING
    ])
  })

  it('文档「已就绪」同时命中 0（已创建）与 5（待发布）', () => {
    const option = findStatusFilterOption(DOC_KB_STATUS_FILTERS, 'ready')
    expect(option.codes).toEqual(expect.arrayContaining([
      KB_STATUS.CREATED,
      KB_STATUS.PENDING_PUBLISH
    ]))
  })

  it('文档「处理中」覆盖解析/切分/生成/入库/发布中', () => {
    const option = findStatusFilterOption(DOC_KB_STATUS_FILTERS, 'processing')
    expect(sorted(option.codes)).toEqual([
      KB_STATUS.PARSING,
      KB_STATUS.SPLITTING,
      KB_STATUS.GENERATING,
      KB_STATUS.INDEXING,
      KB_STATUS.PUBLISHING
    ])
  })

  it.each(catalogs)('given_%s_when_逐个选项筛选_then_命中集合与桶完全一致', (name, definitions, filters) => {
    for (const filter of filters) {
      const option = findStatusFilterOption(filters, filter.value)
      const matched = allCodes(definitions).filter(code => option.codes.includes(code))
      expect(sorted(matched), `${name} ${filter.labelKey} 的命中集合与分桶不一致`)
        .toEqual(sorted(filter.codes))
    }
  })

  it.each(catalogs)('given_%s_when_状态码有文案_then_状态列与筛选都认得它', (name, definitions) => {
    for (const code of allCodes(definitions)) {
      expect(findStatusDefinition(definitions, code), `${name} 状态列不认状态码 ${code}`)
        .toBeDefined()
    }
  })
})

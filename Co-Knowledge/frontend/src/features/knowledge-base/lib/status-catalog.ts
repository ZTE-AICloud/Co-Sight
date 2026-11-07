/**
 * 状态目录：状态列的文案表 + 状态筛选的分桶表。
 *
 * 两层各司其职，但都在这一份文件里，避免页面各写各的：
 *
 *   * `*_STATUS_DEFINITIONS`：状态列。每个定义对应状态列上一种实际文案，
 *     目录外的状态码渲染为「未知 / --」。
 *   * `*_STATUS_FILTERS`：筛选下拉。粗粒度分桶（已就绪 / 处理中 / 失败…），
 *     每个状态码恰好落在一个桶里，筛选项因此不会漏掉状态列能显示的任何状态。
 *
 * 分桶按各页真实链路定：文档知识库的库行状态只能由建库写成 0（文档处理进度
 * 记在文档行上），所以实际只会出现「已就绪」；图谱知识库有完整的构建生命周期
 * （已创建 → 处理中 → 已就绪，失败态另计），没有发布链路，所以没有发布相关桶。
 *
 * 纯数据 + 纯函数，零 Vue 依赖，可被 vitest 直接 import
 * （tests/unit/kbList.statusCatalog.spec.js）。
 */
import { KB_STATUS } from './list-status'

export type StatusTone = 'success' | 'warning' | 'danger' | 'muted'

export interface StatusDefinition {
  /** 归到同一文案下的状态码 */
  codes: readonly number[]
  /** i18n 键：状态列文案 */
  labelKey: string
  /** 状态圆点颜色 */
  tone: StatusTone
}

export interface StatusFilterOption {
  /** 下拉选项的 command 值；`all` 由页面单独提供 */
  value: string
  /** i18n 键：筛选选项文案 */
  labelKey: string
  /** 命中这个桶的全部状态码 */
  codes: readonly number[]
}

/** 「全部状态」的筛选值 */
export const ALL_STATUS_FILTER = 'all'

/**
 * 文档知识库列表：状态列可能出现的全部文案（按生命周期排序）。
 *
 * 0（已创建）与 5（待发布）都显示「已就绪」—— 文档库建好即可用；
 * 6/7/8/106 是发布态；101–106 是各阶段的失败态。
 */
export const DOC_KB_STATUS_DEFINITIONS: readonly StatusDefinition[] = [
  { codes: [KB_STATUS.CREATED, KB_STATUS.PENDING_PUBLISH], labelKey: 'modules.kb.statusReady', tone: 'success' },
  { codes: [KB_STATUS.PARSING], labelKey: 'modules.kb.statusParsing', tone: 'warning' },
  { codes: [KB_STATUS.SPLITTING], labelKey: 'modules.kb.statusSplitting', tone: 'warning' },
  { codes: [KB_STATUS.GENERATING], labelKey: 'modules.kb.statusGenerating', tone: 'warning' },
  { codes: [KB_STATUS.INDEXING], labelKey: 'modules.kb.statusIndexing', tone: 'warning' },
  { codes: [KB_STATUS.PUBLISHING], labelKey: 'modules.kb.statusPublishing', tone: 'warning' },
  { codes: [KB_STATUS.PUBLISHED], labelKey: 'modules.kb.statusPublished', tone: 'success' },
  { codes: [KB_STATUS.PUBLISHED_MODIFIED], labelKey: 'modules.kb.statusPublishedModified', tone: 'warning' },
  { codes: [KB_STATUS.PARSE_FAILED], labelKey: 'modules.kb.statusParseFailed', tone: 'danger' },
  { codes: [KB_STATUS.SPLIT_FAILED], labelKey: 'modules.kb.statusSplitFailed', tone: 'danger' },
  { codes: [KB_STATUS.GENERATE_FAILED], labelKey: 'modules.kb.statusGenerateFailed', tone: 'danger' },
  { codes: [KB_STATUS.INDEX_FAILED], labelKey: 'modules.kb.statusIndexFailed', tone: 'danger' },
  { codes: [KB_STATUS.PUBLISH_FAILED], labelKey: 'modules.kb.statusPublishFailed', tone: 'danger' }
]

/** 图谱的「已就绪」在库里的状态码是 5（同一个 5 在文档知识库那边叫「待发布」） */
const GRAPH_READY_STATUS = 5

/**
 * 知识图谱列表：状态列可能出现的全部文案（按生命周期排序）。
 *
 * 与文档知识库的差别：0 是「已创建」（抽图完成前不可用），5 才是「已就绪」。
 */
export const GRAPH_STATUS_DEFINITIONS: readonly StatusDefinition[] = [
  { codes: [KB_STATUS.CREATED], labelKey: 'modules.kb.statusCreated', tone: 'muted' },
  { codes: [KB_STATUS.PARSING], labelKey: 'modules.kb.statusParsing', tone: 'warning' },
  { codes: [KB_STATUS.SPLITTING], labelKey: 'modules.kb.statusSplitting', tone: 'warning' },
  { codes: [KB_STATUS.GENERATING], labelKey: 'modules.kb.statusGenerating', tone: 'warning' },
  { codes: [KB_STATUS.INDEXING], labelKey: 'modules.kb.statusIndexing', tone: 'warning' },
  { codes: [GRAPH_READY_STATUS], labelKey: 'modules.kb.statusReady', tone: 'success' },
  { codes: [KB_STATUS.PARSE_FAILED], labelKey: 'modules.kb.statusParseFailed', tone: 'danger' },
  { codes: [KB_STATUS.SPLIT_FAILED], labelKey: 'modules.kb.statusSplitFailed', tone: 'danger' },
  { codes: [KB_STATUS.GENERATE_FAILED], labelKey: 'modules.kb.statusGenerateFailed', tone: 'danger' },
  { codes: [KB_STATUS.INDEX_FAILED], labelKey: 'modules.kb.statusIndexFailed', tone: 'danger' }
]

/**
 * 文档知识库的筛选分桶：文档库状态恒为 0（已就绪），另两个桶为将来回写
 * 处理/失败进度留口；7/8（已发布）语义上仍属「可用」，归到已就绪。
 */
export const DOC_KB_STATUS_FILTERS: readonly StatusFilterOption[] = [
  {
    value: 'ready',
    labelKey: 'modules.kb.filterReady',
    codes: [
      KB_STATUS.CREATED,
      KB_STATUS.PENDING_PUBLISH,
      KB_STATUS.PUBLISHED,
      KB_STATUS.PUBLISHED_MODIFIED
    ]
  },
  {
    value: 'processing',
    labelKey: 'modules.kb.filterProcessing',
    codes: [
      KB_STATUS.PARSING,
      KB_STATUS.SPLITTING,
      KB_STATUS.GENERATING,
      KB_STATUS.INDEXING,
      KB_STATUS.PUBLISHING
    ]
  },
  {
    value: 'failed',
    labelKey: 'modules.kb.filterFailed',
    codes: [
      KB_STATUS.PARSE_FAILED,
      KB_STATUS.SPLIT_FAILED,
      KB_STATUS.GENERATE_FAILED,
      KB_STATUS.INDEX_FAILED,
      KB_STATUS.PUBLISH_FAILED
    ]
  }
]

/**
 * 知识图谱的筛选分桶：已创建是「还没开始建」，单独一桶；构建中的四个阶段
 * 合成「处理中」；失败态不用发布失败（图谱没有发布链路）。
 */
export const GRAPH_STATUS_FILTERS: readonly StatusFilterOption[] = [
  { value: 'ready', labelKey: 'modules.kb.filterReady', codes: [GRAPH_READY_STATUS] },
  { value: 'created', labelKey: 'modules.kb.filterCreated', codes: [KB_STATUS.CREATED] },
  {
    value: 'processing',
    labelKey: 'modules.kb.filterProcessing',
    codes: [
      KB_STATUS.PARSING,
      KB_STATUS.SPLITTING,
      KB_STATUS.GENERATING,
      KB_STATUS.INDEXING
    ]
  },
  {
    value: 'failed',
    labelKey: 'modules.kb.filterFailed',
    codes: [
      KB_STATUS.PARSE_FAILED,
      KB_STATUS.SPLIT_FAILED,
      KB_STATUS.GENERATE_FAILED,
      KB_STATUS.INDEX_FAILED
    ]
  }
]

/** 状态码 → 目录定义；目录外的状态码返回 undefined（由页面回落为「未知」） */
export function findStatusDefinition (
  definitions: readonly StatusDefinition[],
  status: number
): StatusDefinition | undefined {
  return definitions.find(definition => definition.codes.includes(status))
}

/** 筛选值 → 选项；`all` 或已失效的值返回 undefined，表示不筛 */
export function findStatusFilterOption (
  options: readonly StatusFilterOption[],
  filterValue: string
): StatusFilterOption | undefined {
  return options.find(option => option.value === filterValue)
}

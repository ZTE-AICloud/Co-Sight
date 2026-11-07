/**
 * 列表状态闸门：文档知识库列表与知识图谱列表共用的一份实现。
 *
 * 零 Vue 依赖：纯值进、纯布尔出，可被 vitest 直接 import（tests/unit/kbList.status.spec.js）。
 *
 * 三个 isXxxEnabled 结构相同（`allowList.includes(status)`），但**允许集合不一样**
 * （见下面各常量上的注释），不能合并成一个"通用"函数。
 *
 * 状态码取值来自两页模板「状态列」的 v-if 链。
 */

/**
 * 知识库/知识图谱行的状态码。
 *
 * 数值来自两页模板的状态列 v-if 链；两页共用同一套数值，但**个别状态在页面上的措辞不同**
 * （例如 0：文档知识库显示"已就绪"—— 文档库建好即可用且没有处理链路会改状态；
 * 图谱页显示"已创建"—— 抽图完成前不可用），这里按页面无关的中性名固化。
 */
export const KB_STATUS = {
  /** 0：已创建（图谱页）/ 已就绪（文档知识库，显示上与 5 合并） */
  CREATED: 0,
  /** 1：解析中 */
  PARSING: 1,
  /** 2：切分中 */
  SPLITTING: 2,
  /** 3：生成中 */
  GENERATING: 3,
  /** 4：入库中 */
  INDEXING: 4,
  /** 5：待发布 */
  PENDING_PUBLISH: 5,
  /** 6：发布中 */
  PUBLISHING: 6,
  /** 7：已发布 */
  PUBLISHED: 7,
  /** 8：已发布（改动后待再次发布，模板带 published_modify 提示） */
  PUBLISHED_MODIFIED: 8,
  /** 101：解析失败 */
  PARSE_FAILED: 101,
  /** 102：切分失败 */
  SPLIT_FAILED: 102,
  /** 103：生成失败 */
  GENERATE_FAILED: 103,
  /** 104：入库失败 */
  INDEX_FAILED: 104,
  /** 106：发布失败 */
  PUBLISH_FAILED: 106
} as const

/**
 * 后端可能把数值状态返回成字符串（"5" / "101"），列到处在用带 `===` 的 v-if 链，
 * 所以统一过这一道。
 *
 * 注意边界：只认 number/string 两种类型，其余（undefined/null/boolean/object）一律 -1；
 * 字符串里 `''` 会被 Number('') 转成 0（**不是 -1**），"12abc" 这类非数字字符串才是 -1。
 * 这些边界由 tests/unit/kbList.status.spec.js 钉住。
 *
 * ⚠️ `toNum('') === 0` 的后果（「有意不改」）：
 * 后端若真把状态写成空串，文档知识库列表会把它当状态 0 → 显示"已就绪"，
 * 并**点亮「修改」+「发布」两个按钮**（0 同时在这两个允许集合里）。图谱页则当"已创建"，
 * 只亮「修改」（0 不在发布集合）。
 *
 * 不改的理由：`Number('') === 0` 是既定语义。要修得先按行为变更评估，
 * 不要在这里顺手改。
 *
 * 可达性（**代码路径不可达，但结构上未禁止**）：
 * `kb_kbase.status` 是 `varchar(10) NOT NULL DEFAULT '0'`。
 * 仓库内全部写入点只写数字串 —— 一律经 `STATUS_*` 常量（'0'…'8'、'101'…'106'），
 * 没有任何路径产出 `''`；
 * 但列上没有 CHECK 约束，`''` 只是"没人会写"，不是"写不进去"（越权直写库才会出现）。
 */
export function toNum (val: unknown): number {
  if (typeof val === 'number') {
    return val
  }
  if (typeof val === 'string') {
    const n = Number(val)
    return Number.isNaN(n) ? -1 : n
  }
  return -1
}

/** 文档知识库（Kbase.vue）修改按钮的允许集合：0/5/6/7/8 + 四个失败态 + 发布失败 */
export const DOC_KB_MODIFY_ENABLED_STATUSES: readonly number[] = [
  KB_STATUS.CREATED,
  KB_STATUS.PENDING_PUBLISH,
  KB_STATUS.PUBLISHING,
  KB_STATUS.PUBLISHED,
  KB_STATUS.PUBLISHED_MODIFIED,
  KB_STATUS.PARSE_FAILED,
  KB_STATUS.SPLIT_FAILED,
  KB_STATUS.GENERATE_FAILED,
  KB_STATUS.INDEX_FAILED,
  KB_STATUS.PUBLISH_FAILED
]

/**
 * 图谱页（knowledgeGraph.vue）修改按钮的允许集合。
 *
 * ⚠️ 与文档知识库的**唯一差别是没有 6（发布中）**：图谱页不让你改一个正在发布的行。
 * 要统一两页的允许集合，先找产品确认。
 */
export const GRAPH_MODIFY_ENABLED_STATUSES: readonly number[] = [
  KB_STATUS.CREATED,
  KB_STATUS.PENDING_PUBLISH,
  KB_STATUS.PUBLISHED,
  KB_STATUS.PUBLISHED_MODIFIED,
  KB_STATUS.PARSE_FAILED,
  KB_STATUS.SPLIT_FAILED,
  KB_STATUS.GENERATE_FAILED,
  KB_STATUS.INDEX_FAILED,
  KB_STATUS.PUBLISH_FAILED
]

/** 文档知识库（Kbase.vue）发布按钮的允许集合：0/5/7/8/106 */
export const DOC_KB_PUBLISH_ENABLED_STATUSES: readonly number[] = [
  KB_STATUS.CREATED,
  KB_STATUS.PENDING_PUBLISH,
  KB_STATUS.PUBLISHED,
  KB_STATUS.PUBLISHED_MODIFIED,
  KB_STATUS.PUBLISH_FAILED
]

/**
 * 图谱页发布按钮的允许集合。
 *
 * ⚠️ 与文档知识库的差别是**没有 0**（图谱页把 0 当"已创建"、不是"待发布"，
 * 所以不允许发布；文档知识库把 0 和 5 都当"待发布"，允许发布）。
 */
export const GRAPH_PUBLISH_ENABLED_STATUSES: readonly number[] = [
  KB_STATUS.PENDING_PUBLISH,
  KB_STATUS.PUBLISHED,
  KB_STATUS.PUBLISHED_MODIFIED,
  KB_STATUS.PUBLISH_FAILED
]

/** 文档知识库的「修改」闸门（模板里的 isModifyEnabled 就是它） */
export function isDocKbModifyEnabled (status: number): boolean {
  return DOC_KB_MODIFY_ENABLED_STATUSES.includes(status)
}

/**
 * 文档知识库的「发布」闸门（模板里的 isPublishEnabled 就是它）。
 *
 * ⚠️ 当前**零生产调用方**（没有发布入口）。保留本函数与上面的允许集合是**有意**的：
 * 它记录了「状态 0 在两页语义不同」（文档页=待发布、图谱页=已创建）这个分叉，
 * 由 tests/unit/kbList.status.spec.js 钉住；将来若恢复发布入口，可直接沿用该语义。
 */
export function isDocKbPublishEnabled (status: number): boolean {
  return DOC_KB_PUBLISH_ENABLED_STATUSES.includes(status)
}

/** 图谱页的「修改」闸门（模板里的 isModifyEnabled 就是它） */
export function isGraphModifyEnabled (status: number): boolean {
  return GRAPH_MODIFY_ENABLED_STATUSES.includes(status)
}

/** 图谱页的「发布」闸门（模板里的 isPublishEnabled 就是它）。当前零生产调用方，保留理由同上。 */
export function isGraphPublishEnabled (status: number): boolean {
  return GRAPH_PUBLISH_ENABLED_STATUSES.includes(status)
}

/**
 * 图谱页的「删除」闸门：所有状态都允许。
 *
 * 参数保持存在：模板调用处就是 `isDeleteEnabled(toNum(row.status))`，
 * 保留签名免得调用点被顺带改掉。文档知识库页没有对应的删除闸门函数。
 */
// eslint-disable-next-line no-unused-vars
export function isGraphDeleteEnabled (status: number): boolean {
  return true
}

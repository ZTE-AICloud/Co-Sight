// 测的是 `views/kBase/lib/list-status.ts`：文档知识库列表页（views/Kbase.vue）与
// 知识图谱列表页（views/knowledgeGraphTab/knowledgeGraph.vue）合并出来的共用状态闸门。
//
// 这里钉的是三样东西：
//   1. `toNum` 的边界（两个页面共用同一个函数）；
//   2. 状态码清单（集中常量，不再散在两页模板的 v-if 链里）；
//   3. 两页的允许集合 —— 包括**它们不一样**的地方（修改允许 6、发布允许 0）。
//      集合字面量在这里独立再写一遍：如果合并时写错一个数，这组断言先红。
import {
  KB_STATUS,
  toNum,
  DOC_KB_MODIFY_ENABLED_STATUSES,
  DOC_KB_PUBLISH_ENABLED_STATUSES,
  GRAPH_MODIFY_ENABLED_STATUSES,
  GRAPH_PUBLISH_ENABLED_STATUSES,
  isDocKbModifyEnabled,
  isDocKbPublishEnabled,
  isGraphModifyEnabled,
  isGraphPublishEnabled,
  isGraphDeleteEnabled
} from '@/features/knowledge-base/lib/list-status'

/** 按数字升序拷贝一份，便于和字面量集合做全等比较（includes 不看顺序，但抄错值会露出来） */
function sorted (statuses) {
  return [...statuses].sort((a, b) => a - b)
}

describe('toNum', () => {
  describe('given_数字_when_toNum_then_原样返回', () => {
    it('0 / 5 / 101 / 106 这些状态码原样返回，不做字符串化', () => {
      // 钉住：number 分支直通，v-if 链里的 === 比较依赖它
      expect(toNum(0)).toBe(0)
      expect(toNum(5)).toBe(5)
      expect(toNum(101)).toBe(101)
      expect(toNum(106)).toBe(106)
    })

    it('NaN 属于 number 分支，也被原样返回（不会变成 -1）', () => {
      // 钉住：typeof NaN === 'number'，所以走第一分支。模板比较会一律为 false，
      // 按钮闸门会全部收紧（都不可用），这是既有行为，不要顺手"修"成 -1
      expect(Number.isNaN(toNum(NaN))).toBe(true)
    })
  })

  describe('given_字符串_when_toNum_then_按数字解析或落到_-1', () => {
    it('数字字符串转成数字', () => {
      expect(toNum('5')).toBe(5)
      expect(toNum('101')).toBe(101)
      expect(toNum('5.5')).toBe(5.5)
      expect(toNum('1e3')).toBe(1000)
      expect(toNum('0x10')).toBe(16)
      expect(toNum('  12  ')).toBe(12)
    })

    it('非数字字符串返回 -1', () => {
      expect(toNum('abc')).toBe(-1)
      expect(toNum('12abc')).toBe(-1)
      expect(toNum('NaN')).toBe(-1)
      expect(toNum('1,000')).toBe(-1)
    })

    it('空字符串返回 0 而不是 -1（含纯空白串）', () => {
      // 钉住 Number('') === 0 这个边界：后端把缺失状态返回成 '' 时，
      // 页面会把它当作状态 0（待发布/已创建），不是"未知"。
      // ⚠️ 这是**有意保持的行为**，「不要改」；它点亮哪些按钮见本文件
      // 「toNum 与闸门的衔接」组里的后果用例，可达性（后端会不会真返回空串）
      // 写在 lib/list-status.ts 的 toNum 头注记里。
      expect(toNum('')).toBe(0)
      // 纯空白串同上（Number('   ') === 0），别只盯空串本身
      expect(toNum('   ')).toBe(0)
    })

    it('Infinity 字符串会解析成 Infinity（不是 -1）', () => {
      // 钉住：Number('Infinity') === Infinity，且它不属于任何允许集合
      expect(toNum('Infinity')).toBe(Infinity)
    })
  })

  describe('given_非数字非字符串_when_toNum_then_一律_-1', () => {
    it('undefined / null / 布尔 / 对象 / 数组 / Symbol 全部落到 -1', () => {
      // 钉住：只有 number/string 两个分支，其它类型不尝试强转
      expect(toNum(undefined)).toBe(-1)
      expect(toNum(null)).toBe(-1)
      expect(toNum(true)).toBe(-1)
      expect(toNum(false)).toBe(-1)
      expect(toNum({})).toBe(-1)
      expect(toNum([])).toBe(-1)
      expect(toNum(Symbol('5'))).toBe(-1)
    })
  })
})

describe('知识库状态码清单', () => {
  it('KB_STATUS 的数值与两页模板 v-if 链一致', () => {
    // 钉住：这串数值不能只散在 Kbase.vue / knowledgeGraph.vue 的模板 v-if 链里
    // （0/1/2/3/4/5/6/7/8 + 101/102/103/104/106），现在集中在这里
    expect(KB_STATUS).toEqual({
      CREATED: 0,
      PARSING: 1,
      SPLITTING: 2,
      GENERATING: 3,
      INDEXING: 4,
      PENDING_PUBLISH: 5,
      PUBLISHING: 6,
      PUBLISHED: 7,
      PUBLISHED_MODIFIED: 8,
      PARSE_FAILED: 101,
      SPLIT_FAILED: 102,
      GENERATE_FAILED: 103,
      INDEX_FAILED: 104,
      PUBLISH_FAILED: 106
    })
  })
})

describe('按钮允许集合', () => {
  it('文档知识库修改：0/5/6/7/8/101/102/103/104/106', () => {
    // 钉住：与合并前 Kbase.vue 的 [0, 5, 6, 7, 8, 101, 102, 103, 104, 106] 全等
    expect(sorted(DOC_KB_MODIFY_ENABLED_STATUSES)).toEqual([0, 5, 6, 7, 8, 101, 102, 103, 104, 106])
  })

  it('文档知识库发布：0/5/7/8/106', () => {
    // 钉住：与合并前 Kbase.vue 的 [0, 5, 7, 8, 106] 全等（含 0）
    expect(sorted(DOC_KB_PUBLISH_ENABLED_STATUSES)).toEqual([0, 5, 7, 8, 106])
  })

  it('知识图谱修改：0/5/7/8/101/102/103/104/106（没有 6）', () => {
    // 钉住：与合并前 knowledgeGraph.vue 的 [0, 101, 102, 103, 104, 5, 106, 7, 8] 全等
    expect(sorted(GRAPH_MODIFY_ENABLED_STATUSES)).toEqual([0, 5, 7, 8, 101, 102, 103, 104, 106])
  })

  it('知识图谱发布：5/7/8/106（没有 0）', () => {
    // 钉住：与合并前 knowledgeGraph.vue 的 [5, 106, 7, 8] 全等
    expect(sorted(GRAPH_PUBLISH_ENABLED_STATUSES)).toEqual([5, 7, 8, 106])
  })
})

describe('逐状态判定（文档知识库）', () => {
  // 期望表按合并前 Kbase.vue 的两个数组抄写：
  // 修改 = [0,5,6,7,8,101,102,103,104,106]；发布 = [0,5,7,8,106]
  const cases = [
    { status: 0, modify: true, publish: true, label: '待发布' },
    { status: 1, modify: false, publish: false, label: '解析中' },
    { status: 2, modify: false, publish: false, label: '切分中' },
    { status: 3, modify: false, publish: false, label: '生成中' },
    { status: 4, modify: false, publish: false, label: '入库中' },
    { status: 5, modify: true, publish: true, label: '待发布' },
    { status: 6, modify: true, publish: false, label: '发布中' },
    { status: 7, modify: true, publish: true, label: '已发布' },
    { status: 8, modify: true, publish: true, label: '已发布（改动待发布）' },
    { status: 101, modify: true, publish: false, label: '解析失败' },
    { status: 102, modify: true, publish: false, label: '切分失败' },
    { status: 103, modify: true, publish: false, label: '生成失败' },
    { status: 104, modify: true, publish: false, label: '入库失败' },
    { status: 106, modify: true, publish: true, label: '发布失败' }
  ]

  cases.forEach(({ status, modify, publish, label }) => {
    it(`状态 ${status}（${label}）：修改=${modify}，发布=${publish}`, () => {
      expect(isDocKbModifyEnabled(status)).toBe(modify)
      expect(isDocKbPublishEnabled(status)).toBe(publish)
    })
  })

  it('集合外的状态一律不可用：-1/9/100/105/107/999', () => {
    // 钉住：toNum 的兜底值 -1 与未知状态都不放行（两个按钮都禁用）
    const outside = [-1, 9, 100, 105, 107, 999]
    outside.forEach((status) => {
      expect(isDocKbModifyEnabled(status)).toBe(false)
      expect(isDocKbPublishEnabled(status)).toBe(false)
    })
  })
})

describe('逐状态判定（知识图谱）', () => {
  // 期望表按合并前 knowledgeGraph.vue 的两个数组抄写：
  // 修改 = [0, 101, 102, 103, 104, 5, 106, 7, 8]；发布 = [5, 106, 7, 8]
  const cases = [
    { status: 0, modify: true, publish: false, label: '已创建' },
    { status: 1, modify: false, publish: false, label: '解析中' },
    { status: 2, modify: false, publish: false, label: '切分中' },
    { status: 3, modify: false, publish: false, label: '生成中' },
    { status: 4, modify: false, publish: false, label: '入库中' },
    { status: 5, modify: true, publish: true, label: '待发布' },
    { status: 6, modify: false, publish: false, label: '发布中' },
    { status: 7, modify: true, publish: true, label: '已发布' },
    { status: 8, modify: true, publish: true, label: '已发布（改动待发布）' },
    { status: 101, modify: true, publish: false, label: '解析失败' },
    { status: 102, modify: true, publish: false, label: '切分失败' },
    { status: 103, modify: true, publish: false, label: '生成失败' },
    { status: 104, modify: true, publish: false, label: '入库失败' },
    { status: 106, modify: true, publish: true, label: '发布失败' }
  ]

  cases.forEach(({ status, modify, publish, label }) => {
    it(`状态 ${status}（${label}）：修改=${modify}，发布=${publish}`, () => {
      expect(isGraphModifyEnabled(status)).toBe(modify)
      expect(isGraphPublishEnabled(status)).toBe(publish)
    })
  })

  it('集合外的状态一律不可用：-1/9/100/105/107/999', () => {
    const outside = [-1, 9, 100, 105, 107, 999]
    outside.forEach((status) => {
      expect(isGraphModifyEnabled(status)).toBe(false)
      expect(isGraphPublishEnabled(status)).toBe(false)
    })
  })

  it('删除闸门对所有状态都放行', () => {
    // 钉住 knowledgeGraph.vue 的 isDeleteEnabled：`return true`，不看状态
    expect(isGraphDeleteEnabled(0)).toBe(true)
    expect(isGraphDeleteEnabled(6)).toBe(true)
    expect(isGraphDeleteEnabled(106)).toBe(true)
    expect(isGraphDeleteEnabled(-1)).toBe(true)
    expect(isGraphDeleteEnabled(NaN)).toBe(true)
  })
})

describe('两页分叉点（合并时如实保留，未对齐）', () => {
  // ⚠️ 这组用例钉的是"分歧仍然存在"。哪天有人要把两页对齐，先改这里，
  // 说明产品/后端拍过板了 —— 而不是在合并里顺手抹平。
  it('状态 6（发布中）：文档知识库允许修改，图谱页不允许', () => {
    expect(isDocKbModifyEnabled(6)).toBe(true)
    expect(isGraphModifyEnabled(6)).toBe(false)
  })

  it('状态 0：文档知识库视为"待发布"可发布，图谱页视为"已创建"不可发布', () => {
    expect(isDocKbPublishEnabled(0)).toBe(true)
    expect(isGraphPublishEnabled(0)).toBe(false)
  })

  it('两个修改集合只差 6 这一个状态', () => {
    const diff = DOC_KB_MODIFY_ENABLED_STATUSES.filter(
      (status) => !GRAPH_MODIFY_ENABLED_STATUSES.includes(status)
    )
    expect(diff).toEqual([6])
  })

  it('两个发布集合只差 0 这一个状态', () => {
    const diff = DOC_KB_PUBLISH_ENABLED_STATUSES.filter(
      (status) => !GRAPH_PUBLISH_ENABLED_STATUSES.includes(status)
    )
    expect(diff).toEqual([0])
  })
})

describe('toNum 与闸门的衔接', () => {
  it('空串状态 = 状态 0：文档知识库「修改」「发布」都被点亮（登记为有意不改）', () => {
    // 钉住**后果**而不是"修好"它：toNum('') === 0 是有意保持的行为（见 toNum 用例与
    // lib/list-status.ts 的注记）。0 同时落在文档知识库的修改/发布允许集合里，
    // 所以后端若返回空串，列表会显示"待发布"且两个按钮可用 —— 这就是登记项描述的现场。
    expect(isDocKbModifyEnabled(toNum(''))).toBe(true)
    expect(isDocKbPublishEnabled(toNum(''))).toBe(true)
    // 对照组：图谱页 0 是"已创建"，发布不亮（两页分叉点，见上一组用例）
    expect(isGraphModifyEnabled(toNum(''))).toBe(true)
    expect(isGraphPublishEnabled(toNum(''))).toBe(false)
  })

  it('行里缺 status（undefined）时两个按钮都被收起', () => {
    // 钉住两页模板的组合用法：isModifyEnabled(toNum(row.status))
    const status = toNum(undefined)
    expect(isDocKbModifyEnabled(status)).toBe(false)
    expect(isGraphModifyEnabled(status)).toBe(false)
  })

  it('后端把状态返回成字符串时，闸门照样按数值判断', () => {
    // 钉住：'7' 与 7 走同一个判定
    expect(isDocKbModifyEnabled(toNum('7'))).toBe(true)
    expect(isDocKbPublishEnabled(toNum('7'))).toBe(true)
    expect(isGraphPublishEnabled(toNum('7'))).toBe(true)
    expect(isGraphModifyEnabled(toNum('abc'))).toBe(false)
  })
})

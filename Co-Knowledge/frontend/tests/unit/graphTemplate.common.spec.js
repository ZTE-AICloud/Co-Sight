import { formatTimestamp, generateUUID } from '@/features/graph/lib/graph-template-common'
// 另一份同名实现：零引用的「原始素材」（登记为保留不删），
// 只在这个 spec 里作为**对照组**引入 —— 用来把「两份不许合并」这个事实钉死。
import { formatTimestamp as formatTimestampWithGuard } from '@/features/graph/components/graphUtils'

// 测的是 `views/knowledgeGraphTab/lib/graph-template-common.ts` 的
// 两个零依赖工具函数（从 `knowledgeGraphTemplate.vue` 抽出）。
//
// ⚠️ 两份实现的差异（影响断言期望值）：
//   - `formatTimestamp` 在 `components/graphUtils.js:77` 还有一个同名导出，但那边多了
//     `isNaN(date.getTime())` 守卫；本模块的这一份**没有**守卫，非法输入会输出
//     `NaN-NaN-NaN NaN:NaN:NaN`。这里的用例钉的是本模块的行为。
//     ✅ 对照结论：另一份实现同样没有守卫 —— 本模块无守卫不是丢代码。
//     文件末尾「与 graphUtils 的差异」组把两份的**行为差**逐条钉住，
//     谁把两份合并（补/删守卫）都会让那组红。
//   - `generateUUID` 在 SFC 里本来就是死代码（没有任何调用点，eslint 一直报
//     no-unused-vars），SFC 里也没有 import 它；下面这些用例是目前唯一消费者。

describe('formatTimestamp', () => {
  it('0 / null / undefined / 空字符串都返回 "--"（0 也是 falsy，会被当成「没有值」）', () => {
    expect(formatTimestamp(0)).toBe('--')
    expect(formatTimestamp(null)).toBe('--')
    expect(formatTimestamp(undefined)).toBe('--')
    expect(formatTimestamp('')).toBe('--')
  })

  it('合法毫秒时间戳按本地时间输出 YYYY-MM-DD HH:mm:ss，且各段补零到两位', () => {
    // 用本地时间构造输入、函数也用本地 getter 取值，断言因此不依赖运行容器的时区
    expect(formatTimestamp(new Date(2024, 0, 2, 3, 4, 5).getTime())).toBe('2024-01-02 03:04:05')
  })

  it('两位数月份/日期/时分秒不再补零', () => {
    expect(formatTimestamp(new Date(2024, 11, 31, 23, 59, 59).getTime())).toBe('2024-12-31 23:59:59')
  })

  it('非日期字符串走 Invalid Date：输出 "NaN-NaN-NaN NaN:NaN:NaN"（没有 isNaN 守卫）', () => {
    expect(formatTimestamp('abc')).toBe('NaN-NaN-NaN NaN:NaN:NaN')
  })

  it('纯数字字符串不会被当成毫秒时间戳（new Date("1700000000000") 是 Invalid Date）', () => {
    expect(formatTimestamp('1700000000000')).toBe('NaN-NaN-NaN NaN:NaN:NaN')
  })
})

describe('与 graphUtils.formatTimestamp 的差异（两份不许合并）', () => {
  // 登记项：同名两份实现行为不同（本模块无 isNaN 守卫，graphUtils.js:77 那份有）。
  // 这组用例钉的是**差异本身** —— 它同时是"别合并""别顺手补守卫"两道闸门：
  //   谁给本模块补上守卫 → 第三条红；谁把 graphUtils 的守卫删掉 → 第三条也红；
  //   谁实现得两边一致 → 第一条/第二条的"相同"对照仍绿，但差异项立刻暴露。
  // 已确认：无守卫也是另一份实现的行为。

  it('对照组：falsy 输入两份行为**相同**，都返回 "--"', () => {
    ;[0, null, undefined, '', NaN].forEach((input) => {
      expect(formatTimestamp(input)).toBe('--')
      expect(formatTimestampWithGuard(input)).toBe('--')
    })
  })

  it('对照组：合法毫秒时间戳两份输出**逐字相同**', () => {
    const ts = new Date(2024, 0, 2, 3, 4, 5).getTime()
    expect(formatTimestamp(ts)).toBe('2024-01-02 03:04:05')
    expect(formatTimestampWithGuard(ts)).toBe(formatTimestamp(ts))
  })

  it('差异点：非法日期串下本模块出 NaN 串，带守卫的那份返回 "--"', () => {
    expect(formatTimestamp('abc')).toBe('NaN-NaN-NaN NaN:NaN:NaN')
    expect(formatTimestampWithGuard('abc')).toBe('--')
    expect(formatTimestamp('1700000000000')).toBe('NaN-NaN-NaN NaN:NaN:NaN')
    expect(formatTimestampWithGuard('1700000000000')).toBe('--')
  })
})

describe('generateUUID', () => {
  it('符合 UUID v4 形状：8-4-4-4-12 小写十六进制，版本位为 4，variant 位为 8/9/a/b', () => {
    expect(generateUUID()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  })

  it('连生成 1000 个：长度固定 36，且互不重复', () => {
    const ids = new Set()
    for (let i = 0; i < 1000; i++) {
      const id = generateUUID()
      expect(id).toHaveLength(36)
      ids.add(id)
    }
    expect(ids.size).toBe(1000)
  })
})

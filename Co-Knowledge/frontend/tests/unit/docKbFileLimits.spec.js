import { convertKeysToLower, getFileExtensions, calculateTotalFileSize } from '@/features/knowledge-base/lib/file-limits'

// 测的是 `views/docKnowledgeLibrary/lib/file-limits.ts`（从 CreateKnowledgeBaseUnified.vue
// 抽出来的纯函数）。
//
// 这三个函数处理的是后端 `getFileSizeInfo` 返回的 maxSizeMap：
//   - convertKeysToLower / getFileExtensions 一起产出上传白名单（`whiteList`）；
//   - calculateTotalFileSize 算「已选文件总大小」，超 650MB 直接拒绝上传。
// 最容易错的两处都钉在下面：① 函数名说转小写、实际**不转**（靠原文查表）；
// ② `size || raw.size` 里 0 是 falsy，会静默回落到 raw.size。

describe('convertKeysToLower', () => {
  describe('given_maxSizeMap_when_归一化_then_浅拷贝一份', () => {
    it('钉死现状：函数名/注释说「转小写」，实际**原样保留键**', () => {
      // maxSizeMap 的键就是白名单（后端给的是小写），这个「名字与行为不符」
      // 是历史遗留（注释：与 AddData.vue 保持一致）。测试按真实行为钉：
      // 如果哪天真的补上 toLowerCase，这条会红，逼一次显式决策。
      expect(convertKeysToLower({ TXT: 2, Md: 5 })).toEqual({ TXT: 2, Md: 5 })
    })

    it('返回新对象，改结果不会串改入参', () => {
      const raw = { txt: 1 }
      const out = convertKeysToLower(raw)

      expect(out).not.toBe(raw)

      out.txt = 99
      expect(raw.txt).toBe(1)
    })

    it('空对象进、空对象出', () => {
      expect(convertKeysToLower({})).toEqual({})
    })
  })
})

describe('getFileExtensions', () => {
  describe('given_maxSizeMap_when_取白名单_then_返回全部键', () => {
    it('返回全部键并保持对象键序', () => {
      expect(getFileExtensions({ txt: 5, md: 2, pdf: 20 })).toEqual(['txt', 'md', 'pdf'])
    })

    it('空对象 → 空数组', () => {
      expect(getFileExtensions({})).toEqual([])
    })
  })
})

describe('calculateTotalFileSize', () => {
  describe('given_文件列表_when_算总大小_then_累加字节数', () => {
    it('空列表为 0', () => {
      expect(calculateTotalFileSize([])).toBe(0)
    })

    it('优先用 size，缺了才用 raw.size 兜底', () => {
      expect(calculateTotalFileSize([{ size: 100 }, { raw: { size: 20 } }])).toBe(120)
    })

    it('钉死现状：size === 0 也会回落到 raw.size（0 是 falsy）', () => {
      // `item.size || item.raw?.size || 0`：显式给了 0 字节仍会被跳过，
      // 对「本地 0 字节 + raw 有大小」的项会取 raw.size——数值偏大而不是偏小，
      // 只会更早触发总量拦截，不会放行超限文件。
      expect(calculateTotalFileSize([{ size: 0, raw: { size: 100 } }])).toBe(100)
    })

    it('size 与 raw.size 都没有时计 0，不抛错', () => {
      expect(calculateTotalFileSize([{}, { size: null, raw: null }])).toBe(0)
    })

    it('多项混合求和', () => {
      expect(calculateTotalFileSize([
        { size: 10 },
        { size: 0, raw: { size: 5 } },
        { raw: { size: 1 } }
      ])).toBe(16)
    })
  })
})

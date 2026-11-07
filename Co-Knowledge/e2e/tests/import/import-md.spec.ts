import { test, expect } from '../../support/fixtures/test'
import { cleanupSeed, seedKbWithMarkdown } from '../../support/fixtures/seed'

test.describe('文档导入 / 切片 / 索引', () => {
  test('@fast @p0 IMP-01 md + 系统算子 -1 导入并建立索引', async ({ api }) => {
    test.setTimeout(120_000)
    const seeded = await seedKbWithMarkdown(api, 'IMP-01')
    try {
      const chunks = await api.listChunks(seeded.kbId, 100)
      expect(chunks.total, '导入后切片数应大于 0').toBeGreaterThan(0)

      const contents = (chunks.items || [])
        .map(item => String(item.content || item.text || ''))
        .filter(Boolean)
      expect(contents.length).toBeGreaterThan(0)
      expect(contents.some(content => content.includes(seeded.marker))).toBe(true)

      // 检索命中是“向量/ES 索引真的建立了”的最强可观察证据。
      const groups = await api.retrieve({
        question: seeded.marker,
        kbId: seeded.kbId,
        type: 0
      })
      const docs = groups.flatMap(group => group.docs || [])
      expect(docs.some(doc => (doc.content || '').includes(seeded.marker))).toBe(true)
    } finally {
      await cleanupSeed(api, seeded)
    }
  })
})

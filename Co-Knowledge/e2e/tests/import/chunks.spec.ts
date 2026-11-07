import { test, expect, resourceName } from '../../support/fixtures/test'
import type { ApiClient } from '../../support/api/api-client'

async function embeddingModel (api: ApiClient): Promise<string> {
  const models = await api.listEmbeddingModels()
  if (!models.length) throw new Error('没有可用的 embedding 模型')
  return models[0]
}

async function createKbWithMarkdown (
  api: ApiClient,
  caseId: string,
  marker: string
): Promise<{
  kbId: string
  dirId: string
  fileId: string
  fileName: string
  marker: string
}> {
  const name = resourceName(caseId)
  const fileName = `${name}.md`
  const seeded = await api.kb.createWithFile({
    name,
    embeddingModel: await embeddingModel(api),
    fileName,
    content: `# ${name}\n\n${marker}\n\nE2E 切片测试内容。\n`,
    format: 'md'
  })
  return { ...seeded, dirId: seeded.directoryId, marker }
}

async function firstChunk (api: ApiClient, kbId: string) {
  const chunks = await api.kb.chunks(kbId, undefined, 100)
  const chunk = (chunks.items || [])[0]
  if (!chunk) throw new Error('没有切片')
  return {
    chunkId: String(chunk.chunkId ?? chunk.id),
    content: String(chunk.content ?? chunk.text ?? '')
  }
}

test.describe('切片管理与文件生命周期', () => {
  test('@p1 IMP-11 同名文件 coverFlag 覆盖而非追加', async ({ api }) => {
    test.setTimeout(180_000)
    const firstMarker = `E2E-COVER-OLD-${Date.now()}`
    const seeded = await createKbWithMarkdown(api, 'IMP-11', firstMarker)
    try {
      const secondMarker = `E2E-COVER-NEW-${Date.now()}`
      await api.kb.uploadFile(
        seeded.kbId,
        seeded.dirId,
        {
          name: seeded.fileName,
          mimeType: 'text/markdown',
          buffer: Buffer.from(`# replaced\n\n${secondMarker}\n`)
        },
        'md',
        true
      )
      await api.kb.waitForFile(seeded.kbId, seeded.fileName, 180_000)

      const files = await api.kb.listAllFiles(seeded.kbId)
      expect(files.filter(row => (row.title || row.name) === seeded.fileName)).toHaveLength(1)

      const groups = await api.retrieve({ question: secondMarker, kbId: seeded.kbId, type: 0 })
      const docs = groups.flatMap(group => group.docs || [])
      expect(docs.some(doc => (doc.content || '').includes(secondMarker))).toBe(true)
      expect(docs.some(doc => (doc.content || '').includes(firstMarker))).toBe(false)
    } finally {
      await api.kb.cleanup(seeded.kbId)
    }
  })

  test('@p1 IMP-12 删除文件级联清理切片/索引', async ({ api }) => {
    test.setTimeout(180_000)
    const marker = `E2E-FILE-DELETE-${Date.now()}`
    const seeded = await createKbWithMarkdown(api, 'IMP-12', marker)
    try {
      expect((await api.kb.chunks(seeded.kbId, undefined, 100)).total || 0).toBeGreaterThan(0)
      await api.kb.deleteFile(seeded.kbId, seeded.fileId)

      await expect.poll(async () => {
        const chunks = await api.kb.chunks(seeded.kbId, undefined, 100)
        const files = await api.kb.listAllFiles(seeded.kbId)
        return (chunks.total || 0) + files.length
      }, { timeout: 30_000 }).toBe(0)

      const groups = await api.retrieve({ question: marker, kbId: seeded.kbId, type: 0 })
      const docs = groups.flatMap(group => group.docs || [])
      expect(docs.some(doc => (doc.content || '').includes(marker))).toBe(false)
    } finally {
      await api.kb.cleanup(seeded.kbId)
    }
  })

  test('@p2 IMP-14 多文件批量导入', async ({ api }) => {
    test.setTimeout(180_000)
    const name = resourceName('IMP-14')
    const kb = await api.kb.create({
      name,
      description: 'multi file',
      props: { embeddingModel: await embeddingModel(api) }
    })
    const dirId = await api.kb.defaultDirectoryId(kb.id)
    try {
      const first = `${name}-a.md`
      const second = `${name}-b.txt`
      await api.kb.uploadFile(kb.id, dirId, {
        name: first,
        mimeType: 'text/markdown',
        buffer: Buffer.from(`# A\n\nE2E multi file A ${Date.now()}\n`)
      }, 'md')
      await api.kb.uploadFile(kb.id, dirId, {
        name: second,
        mimeType: 'text/plain',
        buffer: Buffer.from(
          `E2E multi file B ${Date.now()}.\n\n` +
          'This text file has multiple paragraphs so the system splitter has content to emit.\n\n' +
          'Another paragraph for the E2E multi-file import case.\n'
        )
      }, 'txt')
      await api.kb.waitForFile(kb.id, first, 180_000)
      await api.kb.waitForFile(kb.id, second, 180_000)

      const files = await api.kb.listAllFiles(kb.id)
      expect(files.filter(row => row.status === 1)).toHaveLength(2)
      expect((await api.kb.chunks(kb.id, undefined, 100)).total || 0).toBeGreaterThan(0)
    } finally {
      await api.kb.cleanup(kb.id)
    }
  })
})

import fs from 'node:fs'
import path from 'node:path'
import { test, expect, resourceName } from '../../support/fixtures/test'
import { largeMarkdown } from '../../support/fixtures/files'
import type { ApiClient } from '../../support/api/api-client'
import type { FileInput } from '../../support/api/kb-api'

const DOCS = path.resolve(__dirname, '../../fixtures/docs')

async function embeddingModel (api: ApiClient): Promise<string> {
  const models = await api.listEmbeddingModels()
  if (!models.length) throw new Error('没有可用的 embedding 模型')
  return models[0]
}

async function createKb (api: ApiClient, caseId: string): Promise<{ name: string; kbId: string; dirId: string }> {
  const name = resourceName(caseId)
  const kb = await api.kb.create({
    name,
    description: 'E2E import',
    props: { embeddingModel: await embeddingModel(api) }
  })
  const dirId = await api.kb.defaultDirectoryId(kb.id)
  return { name, kbId: kb.id, dirId }
}

function docFile (name: string, format: string): FileInput {
  return {
    name,
    mimeType: format === 'pdf'
      ? 'application/pdf'
      : format === 'docx'
        ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        : format === 'txt'
          ? 'text/plain'
          : 'text/markdown',
    buffer: fs.readFileSync(path.join(DOCS, name))
  }
}

async function uploadAndWait (
  api: ApiClient,
  kbId: string,
  dirId: string,
  file: FileInput,
  format: string,
  coverFlag = false
): Promise<string> {
  const fileId = await api.kb.uploadFile(kbId, dirId, file, format, coverFlag)
  await api.kb.waitForFile(kbId, file.name, 240_000)
  return fileId
}

async function expectUploadFailure (
  api: ApiClient,
  kbId: string,
  dirId: string,
  file: FileInput,
  format: string
): Promise<void> {
  let error: unknown
  try {
    await api.kb.uploadFile(kbId, dirId, file, format)
    await api.kb.waitForFile(kbId, file.name, 60_000)
  } catch (caught) {
    error = caught
  }
  expect(error, '非法/超大文件应显式失败').toBeTruthy()
}

test.describe('文档导入格式与异常路径', () => {
  test('@p0 IMP-02 md/txt/docx 三种格式导入成功', async ({ api }) => {
    test.setTimeout(300_000)
    const kb = await createKb(api, 'IMP-02')
    try {
      const files: Array<[string, string]> = [
        ['sample-zh.md', 'md'],
        ['sample-en.txt', 'txt'],
        ['sample-zh.docx', 'docx']
      ]
      for (const [name, format] of files) {
        await uploadAndWait(api, kb.kbId, kb.dirId, docFile(name, format), format)
      }
      const chunks = await api.kb.chunks(kb.kbId, undefined, 100)
      expect(chunks.total || 0).toBeGreaterThan(0)
      const rows = await api.kb.listAllFiles(kb.kbId)
      expect(rows.length).toBe(3)
      expect(rows.every(row => row.status === 1)).toBe(true)
    } finally {
      await api.kb.cleanup(kb.kbId)
    }
  })

  // 已知限制：仓库自带的 sample-zh.pdf 在 RKB 解析器里抽不出文本（raw_docs=0），
  // 文件状态为失败并给出 ParseEmptyError。PDF 文本层抽取需要单独的环境/样本修复。
  test.fixme('@p0 IMP-02b PDF 文本层抽取', async ({ api }) => {
    const kb = await createKb(api, 'IMP-02B')
    await uploadAndWait(api, kb.kbId, kb.dirId, docFile('sample-zh.pdf', 'pdf'), 'pdf')
  })

  test('@p1 IMP-03 不支持格式 .xyz 返回业务错误', async ({ api }) => {
    test.setTimeout(120_000)
    const kb = await createKb(api, 'IMP-03')
    try {
      await expectUploadFailure(api, kb.kbId, kb.dirId, {
        name: `${kb.name}.xyz`,
        mimeType: 'application/octet-stream',
        buffer: Buffer.from('not supported')
      }, 'xyz')
    } finally {
      await api.kb.cleanup(kb.kbId)
    }
  })

  test('@p1 IMP-04 超出格式上限的 txt 被业务层拒绝', async ({ api }) => {
    test.setTimeout(180_000)
    const kb = await createKb(api, 'IMP-04')
    try {
      await expectUploadFailure(api, kb.kbId, kb.dirId, {
        name: `${kb.name}.txt`,
        mimeType: 'text/plain',
        buffer: Buffer.alloc(6 * 1024 * 1024, 'a')
      }, 'txt')
    } finally {
      await api.kb.cleanup(kb.kbId)
    }
  })

  test('@p0 IMP-06 系统算子参数缺失显式失败', async ({ api }) => {
    test.setTimeout(120_000)
    const kb = await createKb(api, 'IMP-06')
    try {
      const metadata = {
        kType: 'document',
        directoryId: kb.dirId,
        splitType: 'system',
        parseOperator: {},
        splitOperator: {
          md: {
            operatorId: -1,
            fileFormat: 'md',
            args: [{ argName: 'maxWordCount' }]
          }
        }
      }
      let error: unknown
      try {
        const fileId = await api.kb.uploadRaw(kb.kbId, {
          name: `${kb.name}.md`,
          mimeType: 'text/markdown',
          buffer: Buffer.from('# bad args\n\nE2E')
        }, metadata) as unknown as string
        await api.kb.waitForFile(kb.kbId, `${kb.name}.md`, 60_000)
        void fileId
      } catch (caught) {
        error = caught
      }
      expect(error, '缺失 argType/defaultValue 应被拒绝').toBeTruthy()
    } finally {
      await api.kb.cleanup(kb.kbId)
    }
  })

  test('@p0 IMP-07 自定义算子导入并用于切分', async ({ api }) => {
    test.setTimeout(180_000)
    const zip = fs.readFileSync(path.resolve(__dirname, '../../fixtures/operators/sample_operator.zip'))
    // 样例算子按固定英文名判重：先清掉上一轮残留，避免 409 级联到后续用例。
    for (const row of (await api.operator.findAll()).filter(item =>
      item.nameEn === 'sample_fixed_length_splitter' || item.name === '定长切分算子'
    )) {
      try { await api.operator.delete(row.id) } catch { /* best effort */ }
    }
    await api.operator.import({
      name: 'sample_operator.zip',
      mimeType: 'application/zip',
      buffer: zip
    })
    const operators = await api.operator.findAll()
    const operator = operators.find(row =>
      row.nameEn === 'sample_fixed_length_splitter' || row.name === '定长切分算子'
    )
    expect(operator, '自定义算子应出现在列表里').toBeTruthy()

    let kb: { name: string; kbId: string; dirId: string } | undefined
    try {
      kb = await createKb(api, 'IMP-07')
      const kbId = kb.kbId
      const fileName = `${kb.name}.md`
      const fileId = await api.kb.uploadWithCustomOperator(
        kb.kbId,
        kb.dirId,
        {
          name: fileName,
          mimeType: 'text/markdown',
          buffer: Buffer.from('# 自定义算子\n\n' + 'E2E 内容。'.repeat(80))
        },
        'md',
        Number(operator!.id),
        [{ argName: 'max_len', argType: 'int', defaultValue: 80 }]
      )
      await api.kb.waitForFile(kb.kbId, fileName, 180_000)
      const chunks = await api.kb.chunks(kb.kbId, undefined, 100)
      expect(chunks.total || 0).toBeGreaterThan(0)
      await expect.poll(async () => {
        const groups = await api.retrieve({
          question: 'E2E 内容',
          kbId,
          type: 0
        })
        return groups.flatMap(group => group.docs || []).length
      }, { timeout: 15_000 }).toBeGreaterThan(0)
    } finally {
      if (kb) await api.kb.cleanup(kb.kbId)
      if (operator) {
        try { await api.operator.delete(operator.id) } catch { /* best effort */ }
      }
    }
  })

  test('@p1 IMP-15 英文样本导入与检索', async ({ api }) => {
    test.setTimeout(120_000)
    const kb = await createKb(api, 'IMP-15')
    try {
      const marker = `E2E-EN-${Date.now()}`
      const fileName = `${kb.name}.txt`
      await uploadAndWait(api, kb.kbId, kb.dirId, {
        name: fileName,
        mimeType: 'text/plain',
        buffer: Buffer.from(`English sample for E2E with marker ${marker} in the first paragraph.\n`, 'utf8')
      }, 'txt')
      const groups = await api.retrieve({ question: marker, kbId: kb.kbId, type: 0 })
      const docs = groups.flatMap(group => group.docs || [])
      expect(docs.some(doc => (doc.content || '').includes(marker))).toBe(true)
    } finally {
      await api.kb.cleanup(kb.kbId)
    }
  })

  test('@p2 IMP-16 大文档切片分页（100+ 切片）', async ({ api }) => {
    test.setTimeout(300_000)
    const kb = await createKb(api, 'IMP-16')
    try {
      const fileName = `${kb.name}.md`
      await uploadAndWait(api, kb.kbId, kb.dirId, {
        name: fileName,
        mimeType: 'text/markdown',
        buffer: Buffer.from(largeMarkdown(260), 'utf8')
      }, 'md')
      const chunks = await api.kb.chunks(kb.kbId, undefined, 100)
      expect(chunks.total || 0).toBeGreaterThan(100)
    } finally {
      await api.kb.cleanup(kb.kbId)
    }
  })

  test('@p2 IMP-18 并发上传同名文件不产生脏状态', async ({ api }) => {
    test.setTimeout(180_000)
    const kb = await createKb(api, 'IMP-18')
    try {
      const fileName = `${kb.name}.md`
      const first = api.kb.uploadFile(kb.kbId, kb.dirId, {
        name: fileName,
        mimeType: 'text/markdown',
        buffer: Buffer.from('# A\n\nE2E first')
      }, 'md')
      const second = api.kb.uploadFile(kb.kbId, kb.dirId, {
        name: fileName,
        mimeType: 'text/markdown',
        buffer: Buffer.from('# B\n\nE2E second')
      }, 'md')
      const settled = await Promise.allSettled([first, second])
      expect(settled.some(item => item.status === 'fulfilled')).toBe(true)

      await expect.poll(async () => {
        const rows = await api.kb.listAllFiles(kb.kbId)
        return rows.filter(row => (row.title || row.name) === fileName).length
      }, { timeout: 30_000 }).toBeGreaterThanOrEqual(1)

      // 最终状态必须是成功或明确失败，不能永远卡在进行中。
      await expect.poll(async () => {
        const rows = await api.kb.listAllFiles(kb.kbId)
        return rows
          .filter(row => (row.title || row.name) === fileName)
          .every(row => row.status === 1 || row.status === 2)
      }, { timeout: 180_000 }).toBe(true)
    } finally {
      await api.kb.cleanup(kb.kbId)
    }
  })
})

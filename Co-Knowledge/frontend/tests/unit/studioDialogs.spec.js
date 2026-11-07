// @vitest-environment jsdom
/**
 * 0.1.3 / 0.1.4 原型合入的纯函数单测：
 * - `utils/knowledge-files` 的真值覆盖参数与默认值；
 * - `views/kBase/lib/quick-create` 的文件上限分组；
 * - `views/kBase/lib/chunk-display` 的切片标题/正文拆分；
 * - `utils/form-validators` 的判重、URL、到期日；
 * - `zh/en/studioDialogs` 两份文案的键集必须逐键一致。
 */
import {
  collectKnowledgeFiles,
  fileLimits,
  formatFileSize,
  fileKey
} from '@/features/knowledge-base/lib/knowledge-files'
import {
  fallbackUploadLimits,
  toUploadLimits
} from '@/features/knowledge-base/lib/quick-create'
import { chunkParts } from '@/features/knowledge-base/lib/chunk-display'
import {
  expiryDateToUTC,
  isHttpEndpoint,
  isValidExpiryDate,
  uniqueNameRule
} from '@/shared/lib/form-validators'
import zh from '@/app/i18n/zh/studioDialogs'
import en from '@/app/i18n/en/studioDialogs'

function makeFile (name, size = 10, lastModified = 1) {
  return { name, size, lastModified }
}

function allKeys (object, prefix = '') {
  const keys = []
  for (const key of Object.keys(object)) {
    const path = prefix ? `${prefix}.${key}` : key
    const value = object[key]
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      keys.push(...allKeys(value, path))
    } else {
      keys.push(path)
    }
  }
  return keys.sort()
}

describe('文件收集与上限', () => {
  test('默认限制与原型一致：pdf 150MB、最多 50 个、总量 650MB', () => {
    // Arrange
    const pdf = fileLimits.find(group => group.extensions.includes('pdf'))

    // Act
    const result = collectKnowledgeFiles([], [makeFile('a.pdf', 1024)])

    // Assert
    expect(pdf.maxMB).toBe(150)
    expect(result.errors).toEqual([])
    expect(result.files).toHaveLength(1)
  })

  test('真实部署上限覆盖默认值，错误文案走调用方给的 messages', () => {
    // Arrange
    const limits = [{ extensions: ['pdf'], maxMB: 1 }]
    const messages = {
      format: 'bad format',
      empty: 'empty',
      tooLarge: max => `too large ${max}`,
      duplicate: 'duplicate',
      tooMany: max => `too many ${max}`,
      totalTooLarge: max => `total ${max}`
    }

    // Act
    const result = collectKnowledgeFiles([], [makeFile('a.pdf', 2 * 1024 * 1024)], {
      limits,
      messages
    })

    // Assert
    expect(result.files).toHaveLength(0)
    expect(result.errors).toEqual(['a.pdf：too large 1'])
  })

  test('重复文件与数量上限的判定顺序与原型一致', () => {
    // Arrange
    const existing = [makeFile('a.md', 10, 1)]

    // Act
    const duplicate = collectKnowledgeFiles(existing, [makeFile('a.md', 10, 1)])
    const tooMany = collectKnowledgeFiles(
      Array.from({ length: 2 }, (_, index) => makeFile(`f${index}.md`, 10, index)),
      [makeFile('new.md', 10, 9)],
      { maxFiles: 2 }
    )

    // Assert
    expect(duplicate.errors[0]).toContain('已在文件列表中')
    expect(tooMany.errors[0]).toContain('最多添加 2 个文件')
  })

  test('数量超限只报一条聚合错误，不为每个被拒文件刷一行', () => {
    // Arrange：已有 2 个文件、上限 2；一次再选 5 个 → 5 个全部因数量超限被拒
    const existing = [makeFile('a.md'), makeFile('b.md')]
    const incoming = Array.from({ length: 5 }, (_, index) => makeFile(`n${index}.md`))
    const messages = { batchRejected: (reason, count) => `${reason} | ${count}` }

    // Act
    const result = collectKnowledgeFiles(existing, incoming, { maxFiles: 2, messages })

    // Assert
    expect(result.files).toHaveLength(2)
    expect(result.errors).toEqual(['最多添加 2 个文件 | 5'])
  })

  test('总量超限同样只报一条，并保留被拒数量', () => {
    // Arrange：单文件 6MB、上限 10MB → 第一个进、后两个因总量被拒
    const incoming = Array.from({ length: 3 }, (_, index) => makeFile(`n${index}.md`, 6 * 1024 * 1024))
    const messages = { batchRejected: (reason, count) => `${reason} | ${count}` }

    // Act
    const result = collectKnowledgeFiles([], incoming, { maxTotalBytes: 10 * 1024 * 1024, messages })

    // Assert
    expect(result.files).toHaveLength(1)
    expect(result.errors).toEqual(['文件总大小不能超过 10 MB | 2'])
  })

  test('formatFileSize 与 fileKey 保持原型口径', () => {
    expect(formatFileSize(0)).toBe('0 B')
    expect(formatFileSize(1024)).toBe('1.0 KB')
    expect(formatFileSize(1024 ** 2)).toBe('1.0 MB')
    expect(fileKey(makeFile('a.md', 1, 2))).toBe('a.md:1:2')
  })
})

describe('文件上限分组', () => {
  test('按 maxMB 升序分组并把扩展名转小写', () => {
    // Arrange
    const response = {
      maxSizeMap: { PDF: 150, MD: 100, docx: 100, TXT: 5 },
      number: 30
    }

    // Act
    const limits = toUploadLimits(response)

    // Assert
    expect(limits.groups).toEqual([
      { extensions: ['txt'], maxMB: 5 },
      { extensions: ['md', 'docx'], maxMB: 100 },
      { extensions: ['pdf'], maxMB: 150 }
    ])
    expect(limits.maxFiles).toBe(30)
    expect(limits.maxTotalBytes).toBe(650 * 1024 * 1024)
  })

  test('响应缺失或为空时回落到原型静态值', () => {
    // Act
    const missing = toUploadLimits(null)
    const empty = toUploadLimits({ maxSizeMap: {} })

    // Assert
    expect(missing).toEqual(fallbackUploadLimits())
    expect(empty).toEqual(fallbackUploadLimits())
    expect(missing.groups.find(group => group.extensions.includes('zedx')).maxMB).toBe(650)
  })
})

describe('切片展示拆分', () => {
  test('Markdown 标题作为标题，正文去掉标题行', () => {
    // Act
    const parts = chunkParts('# 检索增强生成\n\nRAG 将检索与生成结合。')

    // Assert
    expect(parts.title).toBe('检索增强生成')
    expect(parts.body).toBe('RAG 将检索与生成结合。')
  })

  test('无标题时标题取首行，正文保留全文', () => {
    // Act
    const parts = chunkParts('第一行\n第二行')

    // Assert
    expect(parts.title).toBe('第一行')
    expect(parts.body).toBe('第一行\n第二行')
  })

  test('空内容回落到 --，超长标题截断到 60 字', () => {
    // Act
    const empty = chunkParts('   ')
    const long = chunkParts('x'.repeat(100))

    // Assert
    expect(empty.title).toBe('--')
    expect(long.title).toHaveLength(60)
  })
})

describe('表单校验纯函数', () => {
  test('名称判重忽略大小写并排除当前编辑行', () => {
    // Arrange
    const rows = [{ name: 'Existing' }, { name: 'Other' }]
    const rule = uniqueNameRule(() => rows, '名称', () => rows[1])

    // Act
    let duplicateError = ''
    rule.validator(rule, ' existing ', error => { duplicateError = error ? error.message : '' })
    let excludedError = ''
    rule.validator(rule, 'other', error => { excludedError = error ? error.message : '' })

    // Assert
    expect(duplicateError).toContain('此名称已存在')
    expect(excludedError).toBe('')
  })

  test('isHttpEndpoint 只接受无凭证/查询/片段的 http(s) 地址', () => {
    expect(isHttpEndpoint('https://host/v1')).toBe(true)
    expect(isHttpEndpoint('http://host:4000/v1')).toBe(true)
    expect(isHttpEndpoint('ftp://host/v1')).toBe(false)
    expect(isHttpEndpoint('https://user:pass@host/v1')).toBe(false)
    expect(isHttpEndpoint('https://host/v1?x=1')).toBe(false)
    expect(isHttpEndpoint('not a url')).toBe(false)
  })

  test('到期日按 UTC 当天 23:59:59 换算并拒绝过去日期', () => {
    expect(expiryDateToUTC('2026-12-31')).toBe('2026-12-31T23:59:59.000Z')
    expect(expiryDateToUTC('')).toBeNull()
    const now = new Date('2026-10-23T00:00:00.000Z')
    expect(isValidExpiryDate('2026-12-31', now)).toBe(true)
    expect(isValidExpiryDate('2020-01-01', now)).toBe(false)
    expect(isValidExpiryDate('2026-02-31', now)).toBe(false)
  })
})

describe('studioDialogs 文案', () => {
  test('zh 与 en 的键集逐键一致', () => {
    expect(allKeys(en)).toEqual(allKeys(zh))
  })

  test('新增弹窗与详情页的关键键都存在', () => {
    expect(zh.createKnowledge.title).toBe('新建知识库')
    expect(zh.createWorkflow.submit).toBe('创建并编排')
    expect(zh.keyEditor.createButton).toBe('创建密钥')
    expect(zh.modelEditor.createButton).toBe('添加模型')
    expect(zh.knowledgeDetail.documents).toBe('文档管理')
  })
})

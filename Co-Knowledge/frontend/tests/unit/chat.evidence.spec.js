import {
  MAX_EVIDENCE_ITEMS,
  MAX_EVIDENCE_TEXT_CHARS,
  MAX_STORED_EVIDENCE_ITEMS,
  MAX_STORED_EVIDENCE_TEXT_CHARS,
  compactEvidence,
  formatEvidenceScore,
  normalizeEvidence
} from '@/features/chat/lib/evidence'
import { parseEvent } from '@/features/chat/lib/stream-frame'

// 测的是对话测试页「知识库依据」的数据层：服务端 SSE 帧与 localStorage 都是
// 不可信输入，重点不是「能渲染」，而是**坏数据不能把页面拖垮**。

function validEvidence (overrides = {}) {
  return {
    query: '改写后的问题',
    items: [
      {
        index: 1,
        kind: 'document',
        kb: 'kb_index_7',
        source: 'doc.md',
        sourceId: 'file-id',
        chunkId: 'chunk-1',
        chunkIndex: '3',
        score: 0.83,
        label: '',
        text: '片段正文',
        truncated: false
      }
    ],
    stats: { count: 1, total: 1, sources: 1, knowledgeBases: 1 },
    ...overrides
  }
}

describe('normalizeEvidence', () => {
  it('保留完整证据并重算统计', () => {
    // Act
    const evidence = normalizeEvidence(validEvidence())

    // Assert
    expect(evidence).not.toBeNull()
    expect(evidence.query).toBe('改写后的问题')
    expect(evidence.items).toHaveLength(1)
    expect(evidence.items[0]).toMatchObject({
      index: 1,
      kind: 'document',
      source: 'doc.md',
      chunkIndex: '3',
      score: 0.83
    })
    expect(evidence.stats).toEqual({ count: 1, total: 1, sources: 1, knowledgeBases: 1 })
  })

  it('统计不可信：count/sources 按 items 重算，total 不丢', () => {
    // Arrange
    const raw = validEvidence({
      stats: { count: 999, total: 9, sources: 999, knowledgeBases: 999 }
    })

    // Act
    const evidence = normalizeEvidence(raw)

    // Assert
    expect(evidence.stats).toEqual({ count: 1, total: 9, sources: 1, knowledgeBases: 1 })
  })

  it('结构不对（不是对象 / items 不是数组）返回 null', () => {
    expect(normalizeEvidence(null)).toBeNull()
    expect(normalizeEvidence('nope')).toBeNull()
    expect(normalizeEvidence({ items: 'nope' })).toBeNull()
  })

  it('丢弃空条目并重新编号', () => {
    // Arrange
    const raw = validEvidence({
      items: [
        { index: 7, text: '', source: '', label: '' },
        { index: 9, text: '有用片段', source: 'a.md' },
        null,
        { text: '第二段', source: 'b.md' }
      ]
    })

    // Act
    const evidence = normalizeEvidence(raw)

    // Assert
    expect(evidence.items.map(item => item.index)).toEqual([1, 2])
    expect(evidence.items.map(item => item.text)).toEqual(['有用片段', '第二段'])
  })

  it('按上限裁剪条数与正文', () => {
    // Arrange
    const items = Array.from({ length: MAX_EVIDENCE_ITEMS + 5 }, (_, index) => ({
      index: index + 1,
      text: 'x'.repeat(MAX_EVIDENCE_TEXT_CHARS + 10),
      source: `${index}.md`
    }))

    // Act
    const evidence = normalizeEvidence({ items })

    // Assert
    expect(evidence.items).toHaveLength(MAX_EVIDENCE_ITEMS)
    expect(evidence.items[0].text).toHaveLength(MAX_EVIDENCE_TEXT_CHARS)
    expect(evidence.items[0].truncated).toBe(true)
    expect(evidence.stats.total).toBe(MAX_EVIDENCE_ITEMS)
  })

  it('数值字段兼容字符串（chunkIndex / score）', () => {
    const evidence = normalizeEvidence({
      items: [{ text: 'x', source: 'a.md', chunkIndex: 12, score: '0.5' }]
    })

    expect(evidence.items[0].chunkIndex).toBe('12')
    expect(evidence.items[0].score).toBe(0.5)
  })
})

describe('compactEvidence', () => {
  it('落盘只保留前 6 条、正文 160 字，并保留 total', () => {
    // Arrange
    const items = Array.from({ length: 10 }, (_, index) => ({
      index: index + 1,
      kind: 'document',
      kb: 'kb_index_7',
      source: `${index}.md`,
      sourceId: '',
      chunkId: '',
      chunkIndex: '',
      score: null,
      label: '',
      text: 'y'.repeat(MAX_STORED_EVIDENCE_TEXT_CHARS + 20),
      truncated: false
    }))
    const evidence = {
      query: 'q',
      items,
      stats: { count: 10, total: 10, sources: 10, knowledgeBases: 1 }
    }

    // Act
    const compacted = compactEvidence(evidence)

    // Assert
    expect(compacted.items).toHaveLength(MAX_STORED_EVIDENCE_ITEMS)
    expect(compacted.items[0].text).toHaveLength(MAX_STORED_EVIDENCE_TEXT_CHARS)
    expect(compacted.items[0].truncated).toBe(true)
    expect(compacted.stats.total).toBe(10)
    expect(compacted.stats.count).toBe(MAX_STORED_EVIDENCE_ITEMS)
  })
})

describe('evidence timings', () => {
  it('保留服务端阶段耗时，0 也是有效值', () => {
    // Arrange
    const raw = validEvidence({
      timings: {
        understandingMs: 362.1,
        retrievalMs: 0,
        vectorRetrievalMs: 0,
        keywordRetrievalMs: 48,
        graphRetrievalMs: 21,
        rerankMs: 3391.2
      }
    })

    // Act
    const evidence = normalizeEvidence(raw)

    // Assert
    expect(evidence.timings).toEqual({
      understandingMs: 362.1,
      retrievalMs: 0,
      vectorRetrievalMs: 0,
      keywordRetrievalMs: 48,
      graphRetrievalMs: 21,
      rerankMs: 3391.2
    })
  })

  it('非法/未知字段丢弃；全部非法时不输出 timings', () => {
    const evidence = normalizeEvidence(validEvidence({
      timings: {
        understandingMs: -1,
        retrievalMs: '12.5',
        vectorRetrievalMs: -0.1,
        keywordRetrievalMs: '48',
        rerankMs: Infinity,
        generateMs: 10,
        unknown: 1
      }
    }))

    expect(evidence.timings).toBeUndefined()
  })

  it('部分阶段有效时只保留有效的 key', () => {
    const evidence = normalizeEvidence(validEvidence({
      timings: { retrievalMs: 93.4, rerankMs: -0.1 }
    }))

    expect(evidence.timings).toEqual({ retrievalMs: 93.4 })
  })

  it('落盘压缩后仍保留 timings（零命中时也不丢检索耗时）', () => {
    // Arrange
    const evidence = {
      query: '',
      items: [],
      stats: { count: 0, total: 0, sources: 0, knowledgeBases: 0 },
      timings: {
        understandingMs: 20,
        retrievalMs: 30,
        vectorRetrievalMs: 18,
        keywordRetrievalMs: 11
      }
    }

    // Act
    const compacted = compactEvidence(evidence)

    // Assert
    expect(compacted.timings).toEqual({
      understandingMs: 20,
      retrievalMs: 30,
      vectorRetrievalMs: 18,
      keywordRetrievalMs: 11
    })
  })

  it('retrieval SSE 帧解析后 timings 仍在', () => {
    const frame = parseEvent('retrieval', JSON.stringify({
      conversation_id: 'd1',
      evidence: validEvidence({ timings: { rerankMs: 123.4 } })
    }))

    expect(frame.type).toBe('retrieval')
    expect(frame.evidence.timings).toEqual({ rerankMs: 123.4 })
  })
})

describe('formatEvidenceScore', () => {
  it('0 / 空 / 非数字不显示，数字保留 4 位', () => {
    expect(formatEvidenceScore(0)).toBe('')
    expect(formatEvidenceScore(null)).toBe('')
    expect(formatEvidenceScore(undefined)).toBe('')
    expect(formatEvidenceScore('abc')).toBe('')
    expect(formatEvidenceScore(0.83)).toBe('0.8300')
    expect(formatEvidenceScore('12.5')).toBe('12.5000')
  })
})

describe('parseEvent', () => {
  it('token 事件取 content', () => {
    const frame = parseEvent('token', JSON.stringify({
      conversation_id: 'd1', content: '你好'
    }))

    expect(frame).toEqual({ type: 'text', content: '你好' })
  })

  it('retrieval 事件解析成结构化证据', () => {
    const frame = parseEvent('retrieval', JSON.stringify({
      conversation_id: 'd1', evidence: validEvidence()
    }))

    expect(frame.type).toBe('retrieval')
    expect(frame.evidence.items[0].source).toBe('doc.md')
  })

  it('证据非法 / 未知事件一律 unknown，不抛', () => {
    expect(parseEvent('retrieval', JSON.stringify({ evidence: { items: 'nope' } })))
      .toEqual({ type: 'unknown' })
    expect(parseEvent('something-new', JSON.stringify({ content: 'x' })))
      .toEqual({ type: 'unknown' })
    expect(parseEvent('token', '{不是 JSON')).toEqual({ type: 'unknown' })
    expect(parseEvent('token', null)).toEqual({ type: 'unknown' })
    expect(parseEvent('token', JSON.stringify({ content: 42 })))
      .toEqual({ type: 'unknown' })
  })
})

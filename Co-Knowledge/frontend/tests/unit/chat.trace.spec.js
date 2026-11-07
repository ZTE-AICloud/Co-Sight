import { formatMs, resolveRetrievalStages, resolveTraceTimings } from '@/features/chat/lib/trace'

// 面板四个阶段的取值规则：前三段用服务端实测，生成回答用客户端整段相位。
// 这里钉住的是「服务端/客户端各管哪一段」，避免以后又把重排时间算进生成。

function evidence (timings) {
  return {
    query: 'q',
    items: [],
    stats: { count: 0, total: 0, sources: 0, knowledgeBases: 0 },
    ...(timings ? { timings } : {})
  }
}

describe('resolveTraceTimings', () => {
  it('展示用检索优先服务端纯检索值，而不是客户端整段相位', () => {
    // Arrange：客户端相位 3953ms，服务端纯检索 142ms
    const reply = { retrievalMs: 3953, totalMs: 4696 }
    const value = evidence({
      understandingMs: 362,
      retrievalMs: 142,
      rerankMs: 3391
    })

    // Act
    const timings = resolveTraceTimings(value, reply)

    // Assert
    expect(timings).toEqual({
      understandingMs: 362,
      retrievalMs: 142,
      rerankMs: 3391,
      generateMs: 743
    })
  })

  it('老后端没有 timings：检索回落客户端相位，改写/重排为空', () => {
    const timings = resolveTraceTimings(evidence(), { retrievalMs: 900, totalMs: 1500 })

    expect(timings).toEqual({
      understandingMs: undefined,
      retrievalMs: 900,
      vectorRetrievalMs: undefined,
      keywordRetrievalMs: undefined,
      graphRetrievalMs: undefined,
      rerankMs: undefined,
      generateMs: 600
    })
  })

  it('保留混合检索的向量/关键字分项', () => {
    const timings = resolveTraceTimings(
      evidence({ retrievalMs: 150, vectorRetrievalMs: 100, keywordRetrievalMs: 48 }),
      { retrievalMs: 900, totalMs: 1500 }
    )

    expect(timings.vectorRetrievalMs).toBe(100)
    expect(timings.keywordRetrievalMs).toBe(48)
  })

  it('生成时间以客户端相位为基线，不把服务端检索段重复扣减', () => {
    // Arrange：如果错误地用服务端 retrievalMs 做基线，generate 会变成 4554ms
    const reply = { retrievalMs: 3953, totalMs: 4696 }
    const value = evidence({ understandingMs: 362, retrievalMs: 142, rerankMs: 3391 })

    // Act
    const timings = resolveTraceTimings(value, reply)

    // Assert
    expect(timings.generateMs).toBe(743)
  })

  it('总耗时小于相位时夹到 0', () => {
    const timings = resolveTraceTimings(evidence(), { retrievalMs: 1200, totalMs: 1000 })

    expect(timings.generateMs).toBe(0)
  })

  it('缺少 total 或客户端相位时不猜生成时间', () => {
    expect(resolveTraceTimings(evidence(), { retrievalMs: 100 }).generateMs)
      .toBeUndefined()
    expect(resolveTraceTimings(evidence(), { totalMs: 500 }).generateMs)
      .toBeUndefined()
  })

  it('0 是有效值，不会被当成缺失', () => {
    const timings = resolveTraceTimings(
      evidence({ understandingMs: 0, retrievalMs: 0, rerankMs: 0 }),
      { retrievalMs: 100, totalMs: 250 }
    )

    expect(timings.retrievalMs).toBe(0)
    expect(timings.understandingMs).toBe(0)
    expect(timings.rerankMs).toBe(0)
  })

  it('非有限/负数/非数字一律忽略', () => {
    const timings = resolveTraceTimings(
      evidence({ understandingMs: -1, retrievalMs: Number.NaN, rerankMs: '5' }),
      { retrievalMs: -10, totalMs: Number.POSITIVE_INFINITY }
    )

    expect(timings).toEqual({
      understandingMs: undefined,
      retrievalMs: undefined,
      rerankMs: undefined,
      generateMs: undefined
    })
  })

  it('没有证据/没有回复时全部为空', () => {
    expect(resolveTraceTimings(null, null)).toEqual({
      understandingMs: undefined,
      retrievalMs: undefined,
      vectorRetrievalMs: undefined,
      keywordRetrievalMs: undefined,
      rerankMs: undefined,
      generateMs: undefined
    })
  })
})

describe('resolveRetrievalStages', () => {
  const base = { understandingMs: 100, rerankMs: 300, generateMs: 400 }

  it('混合检索：向量与关键字分别展示，顺序固定', () => {
    // Arrange：合计 150 是两项之和（分项缺失时才用它占位）
    const timings = {
      ...base,
      retrievalMs: 150,
      vectorRetrievalMs: 100,
      keywordRetrievalMs: 48
    }

    // Act
    const stages = resolveRetrievalStages(timings)

    // Assert
    expect(stages).toEqual([
      { key: 'vector', ms: 100 },
      { key: 'keyword', ms: 48 }
    ])
  })

  it('条件工作流只走了关键字检索时只展示关键字', () => {
    const stages = resolveRetrievalStages({ ...base, keywordRetrievalMs: 33 })

    expect(stages).toEqual([{ key: 'keyword', ms: 33 }])
  })

  it('只有合计值（老后端/旧会话）时回落到单段向量检索', () => {
    const stages = resolveRetrievalStages({ ...base, retrievalMs: 142 })

    expect(stages).toEqual([{ key: 'vector', ms: 142 }])
  })

  it('图谱工作流：服务端给出 graphRetrievalMs 时展示图谱检索', () => {
    const stages = resolveRetrievalStages({
      ...base,
      retrievalMs: 300,
      graphRetrievalMs: 298
    })

    expect(stages).toEqual([{ key: 'graph', ms: 298 }])
  })

  it('老后端只有合计值：调用方按证据类型回落为图谱检索', () => {
    const stages = resolveRetrievalStages({ ...base, retrievalMs: 142 }, 'graph')

    expect(stages).toEqual([{ key: 'graph', ms: 142 }])
  })

  it('还没有证据时保留占位阶段（显示 —）', () => {
    expect(resolveRetrievalStages(base)).toEqual([{ key: 'vector', ms: undefined }])
  })

  it('0 是有效分项，不会被合计值覆盖', () => {
    const stages = resolveRetrievalStages({
      ...base,
      retrievalMs: 90,
      vectorRetrievalMs: 0,
      keywordRetrievalMs: 88
    })

    expect(stages).toEqual([
      { key: 'vector', ms: 0 },
      { key: 'keyword', ms: 88 }
    ])
  })
})

describe('formatMs', () => {
  it('按量级换单位：毫秒 / 秒 / 分秒', () => {
    // 1 秒以下保持整数毫秒
    expect(formatMs(12.6)).toBe('13 ms')
    expect(formatMs(0)).toBe('0 ms')
    expect(formatMs(999)).toBe('999 ms')
    // 1 秒以上改用秒，一位小数（长回答不会再出现「123456 ms」这种越界读数）
    expect(formatMs(4696)).toBe('4.7 s')
    expect(formatMs(1000)).toBe('1.0 s')
    expect(formatMs(59949)).toBe('59.9 s')
    // 1 分钟以上用分秒；整分钟不带秒
    expect(formatMs(60000)).toBe('1 min')
    expect(formatMs(123456)).toBe('2 min 3 s')
    expect(formatMs(119999)).toBe('2 min')
  })

  it('缺失/负数/非数字显示 —', () => {
    expect(formatMs(undefined)).toBe('—')
    expect(formatMs(-1)).toBe('—')
    expect(formatMs(Number.NaN)).toBe('—')
  })
})

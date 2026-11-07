import {
  collectBoundKbNames,
  findMissingKbNames,
  normalizeKbIdentity
} from '@/features/chat/lib/kb-bindings'

/**
 * 测的是 `chat/lib/kb-bindings.ts`：对话测试页用它判断「已发布工作流绑定的
 * 知识库是否还在」。判据错了有两种坏结果：误报（正常库被说成已删除）或漏报
 * （库真的没了却不提示，退回静默空召回）。
 */

describe('normalizeKbIdentity', () => {
  it('文档库的检索基名剥成 uuid', () => {
    expect(normalizeKbIdentity('doc_447a9eb509e44d399790dbfd97f25360'))
      .toBe('447a9eb509e44d399790dbfd97f25360')
  })

  it('图谱库名与叠加的 data_ 前缀都能剥干净', () => {
    expect(normalizeKbIdentity('graph_abc123')).toBe('abc123')
    expect(normalizeKbIdentity('data_doc_abc123')).toBe('abc123')
    expect(normalizeKbIdentity('doc_abc123_vector')).toBe('abc123')
    expect(normalizeKbIdentity('data_data_graph_abc123')).toBe('abc123')
  })

  it('作用域后缀（|#|dev）不参与身份', () => {
    expect(normalizeKbIdentity('doc_abc123|#|dev')).toBe('abc123')
    expect(normalizeKbIdentity('graph_abc123|#|publish')).toBe('abc123')
  })

  it('大小写与首尾空白归一', () => {
    expect(normalizeKbIdentity('  DOC_ABC123 ')).toBe('abc123')
  })

  it('空值/非字符串返回空串（调用方据此跳过）', () => {
    expect(normalizeKbIdentity('')).toBe('')
    expect(normalizeKbIdentity('   ')).toBe('')
    expect(normalizeKbIdentity(null)).toBe('')
    expect(normalizeKbIdentity(123)).toBe('')
  })
})

describe('collectBoundKbNames', () => {
  it('收集 data.variables 与顶层 variables 两份副本，并按身份去重', () => {
    // Arrange：画布把同一份算子配置存两遍（见 docs 的 canvas-two-variable-copies）
    const config = {
      nodeConfigDTOList: [{
        data: {
          variables: {
            retriever: [{ kwargs: { knowledge_base_name: ['doc_abc'] } }]
          }
        },
        variables: {
          retriever: [{ kwargs: { knowledge_base_name: ['doc_abc'] } }]
        }
      }]
    }

    // Act
    const names = collectBoundKbNames(config)

    // Assert
    expect(names).toEqual(['doc_abc'])
  })

  it('多库列表、响应合成器与作用域后缀都能收到', () => {
    const config = {
      nodeConfigDTOList: [
        { variables: { retriever: [{ kwargs: { knowledge_info_list: [
          { knowledge_base_name: ['doc_a', 'doc_b'] }
        ] } }] } },
        { variables: { responsesynthesizer: [{ kwargs: {
          'generator-config': [{ knowledge_base_name: ['graph_c|#|图谱库'] }]
        } }] } }
      ]
    }

    expect(collectBoundKbNames(config)).toEqual([
      'doc_a', 'doc_b', 'graph_c|#|图谱库'
    ])
  })

  it('没有 knowledge_base_name 时返回空数组', () => {
    expect(collectBoundKbNames({ nodeConfigDTOList: [{ id: 'x' }] })).toEqual([])
    expect(collectBoundKbNames(null)).toEqual([])
    expect(collectBoundKbNames('not-an-object')).toEqual([])
  })
})

describe('findMissingKbNames', () => {
  const options = [
    {
      tableName: 'doc_aaa',
      dbTableName: 'doc_aaa_vector',
      assetId: 'aaa',
      kbasePkId: 1
    },
    {
      tableName: 'graph_bbb',
      dbTableName: 'graph_bbb',
      assetId: 'bbb',
      kbasePkId: 2
    }
  ]

  it('三种可匹配形态都不算缺失（tableName / dbTableName / assetId）', () => {
    expect(findMissingKbNames(
      ['doc_aaa', 'data_doc_aaa', 'doc_aaa_vector', 'aaa', 'graph_bbb', 'bbb|#|dev'],
      options
    )).toEqual([])
  })

  it('只报告真正找不到的库，且按身份去重', () => {
    // 注意两个消失的库要用**不同的 uuid**：doc_gone 与 graph_gone 归一后
    // 都是 gone，会被当成同一个库去重（这本身是期望行为）。
    expect(findMissingKbNames(
      ['doc_aaa', 'doc_gone1', 'data_doc_gone1', 'graph_gone2|#|旧库'],
      options
    )).toEqual(['doc_gone1', 'graph_gone2|#|旧库'])
  })

  it('空绑定/空列表都安全', () => {
    expect(findMissingKbNames([], options)).toEqual([])
    expect(findMissingKbNames(['doc_aaa'], [])).toEqual(['doc_aaa'])
    expect(findMissingKbNames(null, options)).toEqual([])
  })

  it('阳性对照：库列表里存在时一定不报（避免「永远为空」的假绿）', () => {
    const missing = findMissingKbNames(['doc_aaa'], options)
    expect(missing).toHaveLength(0)
  })
})

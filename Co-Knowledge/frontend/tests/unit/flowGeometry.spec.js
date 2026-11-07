import { describe, it, expect } from 'vitest'
import {
  collectOperatorSources,
  directionOf,
  flowCurve,
  getNodeOperators,
  isFixedShape,
  moduleKeyOf,
  nodeGeometry,
  operatorDisplayName,
  outputFieldKey,
  portPosition,
  portSide,
  portSideFromPoint,
  shortKbName,
  sourceSummary,
  stripKbSuffix
} from '@/features/workflow/lib/flowGeometry'

describe('flowGeometry（0.1.6 卡片几何）', () => {
  it('固定节点 QUERY / RESPONSE 为 264×140', () => {
    expect(isFixedShape('QUERY')).toBe(true)
    expect(isFixedShape('RESPONSE')).toBe(true)
    expect(nodeGeometry({ shape: 'QUERY' })).toEqual({
      width: 264,
      height: 140,
      frameHeight: 140,
      inputY: 109,
      outputY: 109
    })
  })

  it('高度随算子与上游输入条数增长，frameHeight 含 2px 描边', () => {
    const one = nodeGeometry({ shape: 'POST_RETRIEVER', operatorCount: 1, inputCount: 1 })
    const two = nodeGeometry({ shape: 'POST_RETRIEVER', operatorCount: 2, inputCount: 1 })
    const twoInputs = nodeGeometry({ shape: 'POST_RETRIEVER', operatorCount: 1, inputCount: 2 })
    expect(two.height - one.height).toBe(38)
    expect(twoInputs.height - one.height).toBe(38)
    expect(two.frameHeight).toBe(two.height + 2)
    // 原型实测：预检索器 2 算子 / 1 输入 → 316 + 2px 描边
    expect(nodeGeometry({ shape: 'PRE_RETRIEVER', operatorCount: 2, inputCount: 1 }).frameHeight).toBe(318)
    // 检索器多一行来源摘要
    expect(nodeGeometry({ shape: 'RETRIEVER', operatorCount: 1, inputCount: 1 }).frameHeight).toBe(308)
  })

  it('端口方位：同列上下走 top/bottom，跨列走 left/right，删边保持上一次朝向', () => {
    const geometry = nodeGeometry({ shape: 'PRE_RETRIEVER', operatorCount: 1, inputCount: 1 })
    const node = { x: 100, y: 100 }
    expect(portSide({
      node,
      peers: [{ x: 100, y: 400, width: 264, height: 200 }],
      geometry,
      direction: 'output'
    })).toBe('bottom')
    expect(portSide({
      node,
      peers: [{ x: 100, y: 0, width: 264, height: 50 }],
      geometry,
      direction: 'input'
    })).toBe('top')
    expect(portSide({
      node,
      peers: [{ x: 500, y: 100, width: 264, height: 200 }],
      geometry,
      direction: 'output'
    })).toBe('right')
    expect(portSide({
      node,
      peers: [{ x: 0, y: 100, width: 50, height: 200 }],
      geometry,
      direction: 'input'
    })).toBe('left')
    expect(portSide({
      node,
      peers: [],
      geometry,
      direction: 'output',
      fallbackSide: 'bottom'
    })).toBe('bottom')
  })

  it('端口坐标与方向向量', () => {
    const geometry = nodeGeometry({ shape: 'PRE_RETRIEVER', operatorCount: 1, inputCount: 1 })
    expect(portPosition({ geometry, side: 'right', direction: 'output' })).toEqual({
      x: geometry.width,
      y: geometry.outputY
    })
    expect(portPosition({ geometry, side: 'left', direction: 'input' })).toEqual({
      x: 0,
      y: geometry.inputY
    })
    expect(portPosition({ geometry, side: 'bottom', direction: 'output' })).toEqual({
      x: geometry.width / 2,
      y: geometry.height
    })
    expect(directionOf('top')).toEqual({ dx: 0, dy: -1 })
  })

  it('端口朝向按最近的边判定，2px 描边差不会把下端口误判成左右', () => {
    // 非固定节点：DOM 高 = frameHeight = height + 2，端口 y 用的是 height
    const size = { width: 264, height: 280 }
    expect(portSideFromPoint({ x: 132, y: 278, ...size })).toBe('bottom')
    expect(portSideFromPoint({ x: 132, y: 0, ...size })).toBe('top')
    expect(portSideFromPoint({ x: 264, y: 250, ...size })).toBe('right')
    expect(portSideFromPoint({ x: 0, y: 180, ...size })).toBe('left')
    // 固定节点（QUERY / RESPONSE）没有描边差
    expect(portSideFromPoint({ x: 132, y: 140, width: 264, height: 140 })).toBe('bottom')
    // 端口还没定位（落在卡片中间 / 参数缺失）时不猜方向
    expect(portSideFromPoint({ x: 132, y: 140, ...size })).toBe('')
    expect(portSideFromPoint({})).toBe('')
  })

  it('贝塞尔曲线在两点之间并给出中点箭头角度', () => {
    const connection = flowCurve(
      { x: 0, y: 0 },
      { x: 300, y: 0 },
      directionOf('right'),
      directionOf('left')
    )
    expect(connection.path.startsWith('M0,0')).toBe(true)
    expect(connection.arrow.x).toBeGreaterThan(100)
    expect(connection.arrow.x).toBeLessThan(200)
    expect(Math.abs(connection.arrow.angle)).toBeLessThan(1)
    const vertical = flowCurve(
      { x: 0, y: 0 },
      { x: 0, y: 300 },
      directionOf('bottom'),
      directionOf('top')
    )
    expect(Math.abs(Math.abs(vertical.arrow.angle) - 90)).toBeLessThan(1)
  })

  it('算子数组、显示名与输出字段', () => {
    const node = {
      shape: 'PRE_RETRIEVER',
      variables: {
        preretriever: [{ operator: 'LLMQueryRewriter', kwargs: {} }]
      }
    }
    expect(moduleKeyOf('PRE_RETRIEVER')).toBe('preretriever')
    expect(getNodeOperators(node)).toHaveLength(1)
    const translate = key => key === 'ragFlow.LLMQueryRewriterOperator' ? '问题重构' : key
    expect(operatorDisplayName(node.variables.preretriever[0], translate)).toBe('问题重构')
    expect(operatorDisplayName({ custom: true, operatorName: '我的算子' }, translate)).toBe('我的算子')
    expect(outputFieldKey('RETRIEVER')).toBe('documents')
    expect(outputFieldKey('RESPONSE_SYNTHESIZER')).toBe('answer')
    expect(outputFieldKey('QUERY')).toBe('Question')
  })

  it('检索来源摘要与知识库短名', () => {
    expect(stripKbSuffix('demo|#|dev')).toBe('demo')
    expect(shortKbName('graph_abc')).toBe('图谱知识库')
    expect(collectOperatorSources({
      operator: 'VectorRetriever',
      kwargs: { knowledge_info_list: [{ knowledge_base_name: ['demo'], top_k: 5 }] }
    })).toEqual(['demo'])
    expect(collectOperatorSources({
      operator: 'KeywordRetriever',
      kwargs: { knowledge_base_name: ['demo'] }
    })).toEqual(['demo'])
    const summary = sourceSummary([
      { operator: 'KeywordRetriever', kwargs: { knowledge_base_name: ['demo|#|dev'], top_k: 30 } }
    ], () => '企业知识库')
    expect(summary.text).toBe('企业知识库 · Top 30')
    const fusion = sourceSummary([
      { operator: 'FusionRetriever', kwargs: { top_k: 30 } }
    ], value => value, '融合上游结果')
    expect(fusion.text).toBe('融合上游结果 · Top 30')
  })
})

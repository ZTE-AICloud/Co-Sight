// 测 `features/graph/lib/edge-label.ts`：通用抽图算子只产出泛化关系类型
// `Relation`，真正的关系名在 `properties.relationship_keywords` 里。画布标签
// 必须退回关键词，否则所有边都显示 `Relation`。
import { EDGE_LABEL_MAX_LENGTH, edgeInlineLabel, edgeLabelText } from '@/features/graph/lib/edge-label'

describe('edgeLabelText', () => {
  describe('given_通用算子的泛化类型_when_取标签_then_用关键词', () => {
    it('逗号分隔的关键词归一成顿号', () => {
      expect(edgeLabelText({
        edge_type: 'Relation',
        properties: { relationship_keywords: '产品发布, 技术研发' }
      })).toBe('产品发布、技术研发')
    })

    it('数组关键词同样拼接', () => {
      expect(edgeLabelText({
        edge_type: 'Relation',
        properties: { relationship_keywords: ['投资', '融资合作'] }
      })).toBe('投资、融资合作')
    })

    it('大小写变体也当作泛化类型', () => {
      expect(edgeLabelText({
        edge_type: 'relation',
        properties: { relationship_keywords: '产品发布' }
      })).toBe('产品发布')
    })
  })

  describe('given_业务类型_when_取标签_then_类型优先', () => {
    it('专业算子/模板的类型不被关键词覆盖', () => {
      expect(edgeLabelText({
        edge_type: '投资',
        properties: { relationship_keywords: '投资, 融资合作' }
      })).toBe('投资')
    })
  })

  describe('given_没有可用关键词_when_取标签_then_回落类型', () => {
    it('泛化类型原样返回', () => {
      expect(edgeLabelText({ edge_type: 'Relation', properties: {} })).toBe('Relation')
    })

    it('只有 class 时用 class', () => {
      expect(edgeLabelText({ class: 'Relation' })).toBe('Relation')
    })

    it('空边返回空串', () => {
      expect(edgeLabelText(null)).toBe('')
      expect(edgeLabelText(undefined)).toBe('')
    })
  })

  describe('given_超长关键词_when_取标签_then_截断', () => {
    it('内联标签截到上限', () => {
      const label = edgeLabelText({
        edge_type: 'Relation',
        properties: { relationship_keywords: '甲,乙,丙,丁,戊,己,庚,辛,壬,癸,子,丑,寅,卯' }
      })
      expect(label).toHaveLength(EDGE_LABEL_MAX_LENGTH)
      expect(label.endsWith('…')).toBe(true)
    })

    it('传 Infinity 不截断（悬浮气泡）', () => {
      const text = '甲、乙、丙、丁、戊、己、庚、辛、壬、癸、子、丑、寅、卯'
      expect(edgeLabelText({
        edge_type: 'Relation',
        properties: { relationship_keywords: text }
      }, Number.POSITIVE_INFINITY)).toBe(text)
    })
  })
})

describe('edgeInlineLabel', () => {
  describe('given_通用算子的泛化类型_when_取常显标签_then_只取第一个关键词', () => {
    it('逗号分隔的关键词只取第一个', () => {
      expect(edgeInlineLabel({
        edge_type: 'Relation',
        properties: { relationship_keywords: '产品发布, 技术研发' }
      })).toBe('产品发布')
    })

    it('数组关键词同样只取第一个', () => {
      expect(edgeInlineLabel({
        edge_type: 'Relation',
        properties: { relationship_keywords: ['投资', '融资合作'] }
      })).toBe('投资')
    })
  })

  describe('given_业务类型_when_取常显标签_then_类型优先', () => {
    it('专业算子/模板的类型不被关键词覆盖', () => {
      expect(edgeInlineLabel({
        edge_type: '投资',
        properties: { relationship_keywords: '投资, 融资合作' }
      })).toBe('投资')
    })
  })

  describe('given_没有可用关键词_when_取常显标签_then_回落类型', () => {
    it('泛化类型原样返回', () => {
      expect(edgeInlineLabel({ edge_type: 'Relation', properties: {} })).toBe('Relation')
    })

    it('空边返回空串', () => {
      expect(edgeInlineLabel(null)).toBe('')
    })
  })
})

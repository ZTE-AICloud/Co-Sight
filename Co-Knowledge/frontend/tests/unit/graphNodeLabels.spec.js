import {
  formatEdgeLabel,
  formatNodeLabel,
  splitLabelLines,
  NODE_LABEL_LINE_MAX,
  NODE_LABEL_MAX_LEN
} from '@/features/graph/lib/node-labels'

// 测的是 `knowledgeGraphTab/lib/node-labels.ts`（GraphCanvasVis.vue 画布标签的纯格式化层）。
// 不能把节点标签统一截断到 12 字符 + `...`，否则实体名（19~26 字符的 snake_case）大部分看不全。
// 这里钉住的是**可读性行为**：短名原样、长名在下划线处断两行、每行不超限、超长才省略。

describe('formatNodeLabel', () => {
  it('空值与空串返回空串', () => {
    expect(formatNodeLabel('')).toBe('')
    expect(formatNodeLabel(null)).toBe('')
    expect(formatNodeLabel(undefined)).toBe('')
  })

  it('不超过 16 字符的实体名原样返回，不换行也不截断', () => {
    expect(formatNodeLabel('ent_site_001')).toBe('ent_site_001')
    expect(formatNodeLabel('ent_district_001')).toBe('ent_district_001')
  })

  it('长实体名在最靠近中点的下划线后断成两行，字符不丢失', () => {
    // Arrange
    const name = 'ent_battery_backup_001'

    // Act
    const label = formatNodeLabel(name)

    // Assert
    expect(label).toBe('ent_battery_\nbackup_001')
    expect(label.replace('\n', '')).toBe(name)
  })

  it('常见实体名都能完整显示为两行（各 19~26 字符）', () => {
    const cases = [
      ['ent_metric_backup_duration', 'ent_metric_\nbackup_duration'],
      ['ent_rule_backup_low', 'ent_rule_\nbackup_low'],
      ['ent_action_query_backup', 'ent_action_\nquery_backup'],
      ['ent_scene_backup_alarm', 'ent_scene_\nbackup_alarm'],
      ['ent_process_backup_check', 'ent_process_\nbackup_check'],
      ['ent_mapping_backup_api', 'ent_mapping_\nbackup_api']
    ]

    cases.forEach(([name, expected]) => {
      const label = formatNodeLabel(name)
      expect(label).toBe(expected)
      expect(label.replace('\n', '')).toBe(name)
    })
  })

  it('两行都不超过每行上限', () => {
    const names = [
      'ent_battery_backup_001',
      'ent_metric_backup_duration',
      'ent_rule_backup_low',
      'ent_action_query_backup',
      'ent_scene_backup_alarm',
      'ent_process_backup_check',
      'ent_mapping_backup_api'
    ]

    names.forEach((name) => {
      formatNodeLabel(name).split('\n').forEach((line) => {
        expect(line.length).toBeLessThanOrEqual(NODE_LABEL_LINE_MAX)
      })
    })
  })

  it('没有下划线可断时按每行上限硬断', () => {
    expect(formatNodeLabel('abcdefghijklmnopqrstu')).toBe('abcdefghijklmnop\nqrstu')
  })

  it('超过 32 字符才截断，且以 ... 结尾并保持两行', () => {
    // Arrange
    const name = 'ent_this_is_a_very_long_entity_name_over_limit'
    expect(name.length).toBeGreaterThan(NODE_LABEL_MAX_LEN)

    // Act
    const label = formatNodeLabel(name)
    const lines = label.split('\n')

    // Assert
    expect(lines).toHaveLength(2)
    expect(label.endsWith('...')).toBe(true)
    expect(label.replace('\n', '')).toHaveLength(NODE_LABEL_MAX_LEN)
    lines.forEach((line) => {
      expect(line.length).toBeLessThanOrEqual(NODE_LABEL_LINE_MAX)
    })
  })
})

describe('formatEdgeLabel', () => {
  it('常见的关系类型原样显示，不再截到 8 字符', () => {
    expect(formatEdgeLabel('MapsEntity')).toBe('MapsEntity')
    expect(formatEdgeLabel('belongs_to')).toBe('belongs_to')
  })

  it('较长的关系类型断成两行而不是加省略号', () => {
    expect(formatEdgeLabel('has_related_metric')).toBe('has_related_\nmetric')
  })
})

describe('splitLabelLines', () => {
  it('优先选择靠近中点的下划线作为断点', () => {
    expect(splitLabelLines('ent_scene_root_01')).toBe('ent_scene_\nroot_01')
  })

  it('下划线过于靠边时不采用，改为硬断', () => {
    // 只有第 17 个字符处有下划线：两行放不下（第一行 18 > 16）
    expect(splitLabelLines('abcdefghijklmnop_qrst')).toBe('abcdefghijklmnop\n_qrst')
  })
})

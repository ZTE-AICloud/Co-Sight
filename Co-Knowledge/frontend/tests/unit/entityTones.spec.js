import { assignEntityTones, ENTITY_TONE_SEQUENCE } from '@/features/graph/lib/entity-tones'

// 画布、图例、基本信息页的类型标签共用这一份配色规则，钉住它避免三处颜色漂移。

describe('assignEntityTones', () => {
  it('按模板实体类型顺序轮转五个语义色', () => {
    const tones = assignEntityTones(
      ['Entity', 'MetricDefinition', 'BusinessRule', 'Action', 'Scene'],
      ['Action', 'Entity', 'MetricDefinition', 'BusinessRule', 'Scene']
    )

    expect(tones.Entity).toBe(ENTITY_TONE_SEQUENCE[0])
    expect(tones.MetricDefinition).toBe(ENTITY_TONE_SEQUENCE[1])
    expect(tones.BusinessRule).toBe(ENTITY_TONE_SEQUENCE[2])
    expect(tones.Action).toBe(ENTITY_TONE_SEQUENCE[3])
    expect(tones.Scene).toBe(ENTITY_TONE_SEQUENCE[4])
  })

  it('模板类型与数据大小写不一致时仍共用同一颜色', () => {
    const tones = assignEntityTones(['Person'], ['person'])
    expect(tones.person).toBe(ENTITY_TONE_SEQUENCE[0])
  })

  it('数据里多出来的类型按字典序补色', () => {
    const tones = assignEntityTones(['Person'], ['Person', 'Zoo', 'Alpha'])
    expect(tones.Person).toBe('purple')
    expect(tones.Alpha).toBe('blue')
    expect(tones.Zoo).toBe('green')
  })

  it('超过五个类型时循环使用语义色', () => {
    const types = ['A', 'B', 'C', 'D', 'E', 'F']
    const tones = assignEntityTones(types, types)
    expect(tones.F).toBe(ENTITY_TONE_SEQUENCE[0])
  })
})

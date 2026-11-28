import { describe, expect, it } from 'vitest'

import { buildChart } from '@/features/text2sql/utils/resultChart'

const labels = {
  city_name: '城市',
  paid_amount: '支付金额 / 元',
  month: '月份',
  paid_users: '付费用户数'
}

describe('buildChart', () => {
  it('任意「维度 + 数值列」都出图，按数值倒序，标题与单位来自列标签', () => {
    const chart = buildChart(
      ['city_name', 'paid_amount'],
      [['西安市', 34150], ['上海市', 33280], ['北京市', 37004]],
      labels)

    expect(chart).not.toBeNull()
    expect(chart.title).toBe('城市支付金额')
    expect(chart.subtitle).toBe('单位：元')
    expect(chart.rows.map(item => item.label)).toEqual(['北京市', '西安市', '上海市'])
    expect(chart.rows[0].value).toBe(37004)
  })

  it('时间类维度保持原顺序，不按数值排序', () => {
    const chart = buildChart(
      ['month', 'paid_users'],
      [['2026-09', 10], ['2026-10', 12], ['2026-11', 8]],
      labels)

    expect(chart.rows.map(item => item.label)).toEqual(['2026-09', '2026-10', '2026-11'])
    expect(chart.sorted).toBe(false)
  })

  it('数值列在第一位时仍能识别出维度列', () => {
    const chart = buildChart(
      ['paid_amount', 'city_name'],
      [[34150, '西安市'], [37004, '北京市']],
      labels)

    expect(chart.measure).toBe(0)
    expect(chart.dimension).toBe(1)
    expect(chart.rows[0].label).toBe('北京市')
  })

  it('无标签时回落到列名，并仍能出图', () => {
    const chart = buildChart(
      ['city_name', 'total_amount'],
      [['西安市', 10], ['北京市', 20]],
      {})

    expect(chart.title).toBe('city_nametotal_amount')
    expect(chart.subtitle).toBe('按city_name展示')
  })

  it('没有数值列、单行或单列时不出图', () => {
    expect(buildChart(['city_name'], [['西安市']], labels)).toBeNull()
    expect(buildChart(['city_name', 'paid_amount'], [['西安市', 34150]], labels)).toBeNull()
    expect(buildChart(['city_name', 'paid_amount'],
      [['西安市', 'x'], ['北京市', 'y']], labels)).toBeNull()
  })
})

describe('buildChart measure preference', () => {
  it('数值维度（user_id）不会被误当成度量', () => {
    const chart = buildChart(
      ['user_id', 'city_name', 'paid_amount'],
      [[1, '西安市', 34150], [2, '北京市', 37004]],
      labels)

    expect(chart.measure).toBe(2)
    expect(chart.dimension).toBe(1)
    expect(chart.rows[0].label).toBe('北京市')
  })
})

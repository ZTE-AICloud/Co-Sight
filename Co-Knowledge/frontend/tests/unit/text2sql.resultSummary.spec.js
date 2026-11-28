import { describe, expect, it } from 'vitest'

import { resultSummary } from '@/features/text2sql/utils/text2sqlWorkspace'

const response = (columns, rows) => ({ result: { columns, rows } })

describe('resultSummary', () => {
  it('单行单列的文本值原样展示，不转成数字', () => {
    expect(resultSummary(response(['city_name'], [['宝鸡市']]))).toBe('城市：宝鸡市')
  })

  it('单行单列的数值继续做千分位格式化', () => {
    expect(resultSummary(response(['paid_amount'], [[34150]]))).toBe('支付金额 / 元：34,150')
  })

  it('空值显示占位符', () => {
    expect(resultSummary(response(['city_name'], [[null]]))).toBe('城市：—')
  })

  it('两列数值结果保留最高值摘要', () => {
    const summary = resultSummary(response(
      ['city_name', 'paid_amount'],
      [['西安市', 34150], ['北京市', 37004]]))

    expect(summary).toBe('北京市 的 支付金额 / 元 最高，为 37,004；共返回 2 行。')
  })

  it('没有结果时给出可操作提示', () => {
    expect(resultSummary(response(['city_name'], [])))
      .toBe('当前条件下没有匹配的数据，可以调整条件后再查询。')
  })
})

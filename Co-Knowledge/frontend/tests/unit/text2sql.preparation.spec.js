import { describe, expect, it } from 'vitest'

import {
  buildColumnState,
  collectColumnChanges,
  countEnabledColumns
} from '@/features/text2sql/utils/text2sqlPreparation'

const tables = [
  {
    name: 'order_info',
    columns: [
      { id: 'c1', name: 'order_id', enabled: true, businessDescription: '订单号' },
      { id: 'c2', name: 'pay_channel', enabled: true, businessDescription: '' },
      { id: 'c3', name: 'memo', enabled: false, businessDescription: '备注' }
    ]
  },
  {
    name: 'city',
    columns: [
      { id: 'c4', name: 'city_name', enabled: true, businessDescription: '城市' }
    ]
  }
]

describe('buildColumnState', () => {
  it('按表/列记录启用状态与已填写的业务说明（不回填数据库注释）', () => {
    const state = buildColumnState(tables)

    expect(state.order_info.c1).toEqual({ enabled: true, businessDescription: '订单号' })
    expect(state.order_info.c2).toEqual({ enabled: true, businessDescription: '' })
    expect(state.order_info.c3).toEqual({ enabled: false, businessDescription: '备注' })
    expect(state.city.c4).toEqual({ enabled: true, businessDescription: '城市' })
  })

  it('缺省 enabled 视为启用', () => {
    const state = buildColumnState([{ name: 't', columns: [{ id: 'x', name: 'a' }] }])

    expect(state.t.x.enabled).toBe(true)
  })
})

describe('collectColumnChanges', () => {
  it('只返回启用状态或说明发生变化的字段', () => {
    const initial = buildColumnState(tables)
    const state = buildColumnState(tables)
    state.order_info.c2.enabled = false
    state.order_info.c3.businessDescription = '内部备注'

    const changes = collectColumnChanges(state, initial, tables)

    expect(changes).toEqual([
      {
        id: 'c2',
        tableName: 'order_info',
        columnName: 'pay_channel',
        enabled: false,
        businessDescription: ''
      },
      {
        id: 'c3',
        tableName: 'order_info',
        columnName: 'memo',
        enabled: false,
        businessDescription: '内部备注'
      }
    ])
  })

  it('清空说明也算一次修改', () => {
    const initial = buildColumnState(tables)
    const state = buildColumnState(tables)
    state.city.c4.businessDescription = ''

    const changes = collectColumnChanges(state, initial, tables)

    expect(changes).toHaveLength(1)
    expect(changes[0]).toMatchObject({ id: 'c4', businessDescription: '' })
  })

  it('没有变化时返回空数组', () => {
    const initial = buildColumnState(tables)

    expect(collectColumnChanges(buildColumnState(tables), initial, tables)).toEqual([])
  })
})

describe('countEnabledColumns', () => {
  it('只统计启用字段', () => {
    expect(countEnabledColumns(buildColumnState(tables), tables)).toBe(3)
  })
})

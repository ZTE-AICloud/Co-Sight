import { describe, expect, it } from 'vitest'

import { tableTitle } from '@/features/text2sql/utils/tableTitle'

const columns = [{ id: 'c1' }, { id: 'c2' }, { id: 'c3' }]

describe('tableTitle', () => {
  it('没有业务名称与数据库注释时，只显示一次表名', () => {
    const table = {
      name: 'doc_01003b5f06cc9a1d_chunk',
      fullName: 'kb_index.doc_01003b5f06cc9a1d_chunk',
      businessName: '',
      dbComment: '',
      type: 'BASE_TABLE',
      columns
    }

    expect(tableTitle(table)).toBe('kb_index.doc_01003b5f06cc9a1d_chunk · 3 个字段')
  })

  it('有业务名称时保留业务名称', () => {
    const table = {
      name: 'order_info',
      fullName: 'public.order_info',
      businessName: '订单',
      dbComment: '',
      type: 'BASE_TABLE',
      columns
    }

    expect(tableTitle(table)).toBe('public.order_info · 订单 · 3 个字段')
  })

  it('只有数据库注释时用注释补位', () => {
    const table = {
      name: 'order_info',
      fullName: 'public.order_info',
      businessName: '',
      dbComment: '订单主表',
      type: 'BASE_TABLE',
      columns
    }

    expect(tableTitle(table)).toBe('public.order_info · 订单主表 · 3 个字段')
  })

  it('业务名称被人工填成与表名相同时不再重复', () => {
    const table = {
      name: 'order_info',
      fullName: 'public.order_info',
      businessName: 'order_info',
      dbComment: '',
      type: 'BASE_TABLE',
      columns
    }

    expect(tableTitle(table)).toBe('public.order_info · 3 个字段')
  })

  it('业务名称与全名相同时不再重复', () => {
    const table = {
      name: 'order_info',
      fullName: 'public.order_info',
      businessName: 'public.order_info',
      dbComment: '',
      type: 'BASE_TABLE',
      columns
    }

    expect(tableTitle(table)).toBe('public.order_info · 3 个字段')
  })

  it('视图在字段数后标注', () => {
    const table = {
      name: 'order_summary',
      fullName: 'public.order_summary',
      businessName: '',
      dbComment: '',
      type: 'VIEW',
      columns
    }

    expect(tableTitle(table)).toBe('public.order_summary · 3 个字段 · 视图')
  })

  it('没有 fullName 时回落到表名；缺字段与类型也不报错', () => {
    expect(tableTitle({ name: 'order_info' })).toBe('order_info · 0 个字段')
  })
})

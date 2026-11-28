// Text2SQL API 契约：查询、历史、收藏、反馈与语义维护的路径/参数。
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/shared/api/client', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({})),
    post: vi.fn(() => Promise.resolve({})),
    put: vi.fn(() => Promise.resolve({})),
    patch: vi.fn(() => Promise.resolve({})),
    delete: vi.fn(() => Promise.resolve({}))
  }
}))

vi.mock('@/shared/api/stream', () => ({
  streamPost: vi.fn(() => Promise.resolve({ ok: true, errorEvent: null }))
}))

import client from '@/shared/api/client'
import { streamPost } from '@/shared/api/stream'
import {
  buildVersion, clearRuns, createDatasource, createFeedback, createValue,
  deleteRun, listRuns, listTables, publishVersion, runQuery, runQueryStream,
  saveWorkspace, testConnectionPayload, updateValue
} from '@/features/text2sql/api/text2sql'

describe('text2sql api', () => {
  beforeEach(() => {
    Object.values(client).forEach(fn => fn.mockClear())
    streamPost.mockClear()
  })

  it('数据源、表、查询与版本路径', async () => {
    await createDatasource({ name: 'demo' })
    await listTables('ds-1')
    await runQuery('ds-1', { question: 'q' })
    await buildVersion('ds-1', 'v-1')
    await publishVersion('ds-1', 'v-1', 4)

    expect(client.post.mock.calls[0][0]).toMatch(/\/text2sql\/datasources$/)
    expect(client.get.mock.calls[0][0]).toMatch(/\/text2sql\/datasources\/ds-1\/tables$/)
    expect(client.post.mock.calls[1][0]).toMatch(/\/text2sql\/datasources\/ds-1\/query$/)
    expect(client.post.mock.calls[2][0]).toMatch(/\/versions\/v-1\/build$/)
    expect(client.post.mock.calls[3][0]).toMatch(/\/publication$/)
    expect(client.post.mock.calls[3][1]).toEqual({ versionId: 'v-1', expectedRevision: 4 })
  })

  it('历史、反馈、枚举与工作台参数', async () => {
    await listRuns({ size: 20 })
    await deleteRun('run-1')
    await clearRuns('ds-1')
    await createFeedback('run-1', { category: 'meaning', notes: 'x' })
    await createValue('ds-1', { rawValue: '2' })
    await updateValue('ds-1', 'val-1', { businessName: '西安市', aliases: ['西安'] })
    await saveWorkspace({ questionDraft: 'q' })

    expect(client.get.mock.calls[0][0]).toMatch(/\/text2sql\/runs$/)
    expect(client.delete.mock.calls[0][0]).toMatch(/\/runs\/run-1$/)
    expect(client.delete.mock.calls[1][0]).toMatch(/\/runs$/)
    expect(client.delete.mock.calls[1][1].params).toEqual({ datasourceId: 'ds-1' })
    expect(client.post.mock.calls[0][0]).toMatch(/\/runs\/run-1\/feedback$/)
    expect(client.post.mock.calls[1][0]).toMatch(/\/datasources\/ds-1\/values$/)
    expect(client.patch.mock.calls[0][0]).toMatch(/\/datasources\/ds-1\/values\/val-1$/)
    expect(client.patch.mock.calls[0][1]).toEqual({ businessName: '西安市', aliases: ['西安'] })
    expect(client.put.mock.calls[0][0]).toMatch(/\/workspace$/)
  })

  it('未保存数据源的连接测试走独立动作', async () => {
    await testConnectionPayload({ host: 'db' })
    expect(client.post.mock.calls[0][0]).toMatch(/\/datasources\/connection-test$/)
  })

  it('流式查询走 SSE 端点并透传回调', async () => {
    const handlers = { onEvent: vi.fn() }
    await runQueryStream('ds-1', { question: 'q' }, handlers)
    expect(streamPost.mock.calls[0][0]).toMatch(/\/text2sql\/datasources\/ds-1\/query\/stream$/)
    expect(streamPost.mock.calls[0][1]).toEqual({ question: 'q' })
    expect(streamPost.mock.calls[0][2]).toBe(handlers)
  })
})

import { describe, expect, it } from 'vitest'

import {
  formatBytes, formatStageTimings, resultFacts, TASK_TYPES, typeLabel
} from '@/features/tasks/lib/display'

const t = key => key.split('.').pop()

describe('task display helpers', () => {
  it('格式化字节数', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(164)).toBe('164 B')
    expect(formatBytes(2048)).toBe('2.0 KB')
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB')
    expect(formatBytes(-1)).toBe('')
    expect(formatBytes('nope')).toBe('')
  })

  it('格式化阶段耗时按链路顺序展示（不受 JSONB 键序影响）', () => {
    const text = formatStageTimings({ embed: 300, parse: 12, split: 20 }, t)
    expect(text).toBe('stageParse 12ms · stageSplit 20ms · stageEmbed 300ms')
    expect(formatStageTimings(null, t)).toBe('')
  })

  it('文件导入摘要包含切片、向量与索引文档', () => {
    const facts = resultFacts({
      taskType: 'FILE_IMPORT',
      extra: {
        fileName: 'report.md',
        fileSize: 2048,
        chunkCount: 2,
        vectorCount: 3,
        indexDocCount: 3,
        stageTimingsMs: { parse: 12, split: 20, embed: 300 }
      }
    }, t)

    expect(facts).toEqual([
      { label: 'resultFileName', value: 'report.md' },
      { label: 'resultFileSize', value: '2.0 KB' },
      { label: 'resultChunks', value: '2' },
      { label: 'resultVectors', value: '3' },
      { label: 'resultIndexDocs', value: '3' },
      {
        label: 'resultStageTimings',
        value: 'stageParse 12ms · stageSplit 20ms · stageEmbed 300ms'
      }
    ])
  })

  it('图谱抽图摘要包含实体/边、schema、模型与关联导入任务', () => {
    const facts = resultFacts({
      taskType: 'GRAPH_EXTRACT',
      extra: {
        fileCount: 1,
        entity_success: 5,
        entity_total: 5,
        edge_success: 4,
        edge_total: 5,
        schemaId: 'General_Schema',
        operatorId: -6,
        llm: 'deepseek-v4-flash',
        vector_entities: 5,
        vector_edges: 4,
        vector_chunks: 1,
        importTaskId: 'import-1',
        failedRecordCount: 1
      }
    }, t)

    expect(facts.map(fact => [fact.label, fact.value])).toEqual([
      ['resultFiles', '1'],
      ['resultEntities', '5 / 5'],
      ['resultEdges', '4 / 5'],
      ['resultSchema', 'General_Schema'],
      ['resultOperator', '-6'],
      ['resultModel', 'deepseek-v4-flash'],
      ['resultVectorEntities', '5'],
      ['resultVectorEdges', '4'],
      ['resultVectorChunks', '1'],
      ['resultImportTask', 'import-1'],
      ['resultFailedRecords', '1']
    ])
  })

  it('图谱导入摘要包含向量计数、跳过数与索引错误', () => {
    const facts = resultFacts({
      taskType: 'GRAPH_IMPORT',
      extra: {
        entity_total: 5,
        entity_success: 5,
        edge_total: 5,
        edge_success: 5,
        vector_entities: 5,
        vector_edges: 5,
        vector_chunks: 2,
        vector_skipped: 0,
        failed_records: [{ id: 'e1' }],
        index_error: 'index boom'
      }
    }, t)

    expect(facts.map(fact => [fact.label, fact.value])).toEqual([
      ['resultEntities', '5 / 5'],
      ['resultEdges', '5 / 5'],
      ['resultVectorEntities', '5'],
      ['resultVectorEdges', '5'],
      ['resultVectorChunks', '2'],
      ['resultSkipped', '0'],
      ['resultFailedRecords', '1'],
      ['resultIndexError', 'index boom']
    ])
  })

  it('Text2SQL 索引任务有筛选标签与译名', () => {
    expect(TASK_TYPES).toContain('T2S_INDEX')
    expect(typeLabel('T2S_INDEX', t)).toBe('typeText2sqlIndex')
    expect(typeLabel('UNKNOWN', t)).toBe('UNKNOWN')
  })

  it('空 extra 不渲染摘要', () => {
    expect(resultFacts({ taskType: 'FILE_IMPORT', extra: {} }, t)).toEqual([])
    expect(resultFacts({ taskType: 'GRAPH_EXTRACT', extra: {} }, t)).toEqual([])
    expect(resultFacts({ taskType: 'GRAPH_IMPORT', extra: {} }, t)).toEqual([])
  })
})

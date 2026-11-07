import {
  graphEditSnapshot,
  hasGraphEditErrors,
  isDescriptionTooLong,
  validateGraphEditDraft,
  validateGraphEditName
} from '@/features/graph/lib/graph-edit'

// 测的是「修改知识图谱」页（e496779 原型 GraphEdit）的页面侧纯逻辑：
// 名称规则与整页建图一致、算子参数校验复用建图那套、脏状态按内容比较。

const args = [
  { argName: 'llm' },
  { argName: 'overlap', type: 'number' },
  { argName: 'chunkSize', type: 'number' }
]

test('名称规则：必填、2-30、字符集', () => {
  expect(validateGraphEditName('')).toBe('nameRequired')
  expect(validateGraphEditName('  ')).toBe('nameRequired')
  expect(validateGraphEditName('a')).toBe('nameFormat')
  expect(validateGraphEditName('图谱@1')).toBe('nameFormat')
  expect(validateGraphEditName('图谱 A-1.0_测试')).toBe('')
})

test('草稿校验：名称、描述长度与算子参数', () => {
  const errors = validateGraphEditDraft({
    name: '图谱 A',
    description: 'x'.repeat(1001),
    params: { llm: '', overlap: 128, chunkSize: 512 }
  }, args)
  expect(errors.name).toBe('')
  expect(errors.description).toBe('descriptionTooLong')
  expect(errors.params).toEqual({ llm: 'required' })
  expect(hasGraphEditErrors(errors)).toBe(true)

  expect(hasGraphEditErrors(validateGraphEditDraft({
    name: '图谱 A',
    description: '',
    params: { llm: 'm', overlap: 128, chunkSize: 512 }
  }, args))).toBe(false)
})

test('描述 1000 字以内不算超限', () => {
  expect(isDescriptionTooLong('x'.repeat(1000))).toBe(false)
  expect(isDescriptionTooLong('x'.repeat(1001))).toBe(true)
})

test('脏状态按内容比较，键顺序与数组顺序无关', () => {
  const base = graphEditSnapshot({
    draft: { name: 'A', description: 'd', params: { llm: 'm', overlap: 128, chunkSize: 512 } },
    retainedFileIds: ['2', '1'],
    newFileKeys: ['b:1:1', 'a:1:1']
  })
  const reordered = graphEditSnapshot({
    draft: { name: 'A', description: 'd', params: { chunkSize: 512, overlap: 128, llm: 'm' } },
    retainedFileIds: ['1', '2'],
    newFileKeys: ['a:1:1', 'b:1:1']
  })
  expect(reordered).toBe(base)

  const changed = graphEditSnapshot({
    draft: { name: 'A', description: 'd', params: { llm: 'm', overlap: 256, chunkSize: 512 } },
    retainedFileIds: ['1', '2'],
    newFileKeys: ['a:1:1', 'b:1:1']
  })
  expect(changed).not.toBe(base)
})

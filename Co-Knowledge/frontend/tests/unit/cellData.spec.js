// 检索器删掉两个知识库 → 应用配置 → 重新打开，三个库会全回来。
// 根因不是抽屉：`drawerSubmitHandle` 用 X6 `setData(x)`（默认深合并，内部是 lodash
// `merge`）回写，**数组按下标合并、旧的尾巴保留**，删掉的知识库原样留在数组里。
// 这里用真 X6 节点钉住「整体替换」的语义。
import { describe, it, expect } from 'vitest'
import { Node } from '@antv/x6'
import { replaceNodeVariables } from '@/features/workflow/lib/cellData'

const KB = (...names) => ({
  retriever: [{
    operator: 'VectorRetriever',
    kwargs: { knowledge_info_list: [{ knowledge_base_name: names, top_k: 30 }] }
  }]
})

const namesOf = node => node.getData().variables.retriever[0].kwargs.knowledge_info_list[0].knowledge_base_name

describe('replaceNodeVariables（应用配置回写画布节点）', () => {
  it('删掉的知识库不会留在数组尾巴里（深合并会留下）', () => {
    // Arrange：节点上存着 5 项（A 重复 3 次），与线上 89f4 的形状一致
    const node = new Node({ shape: 'rect' })
    node.setData({ type: 'displayData', variables: KB('A', 'A', 'B', 'A', 'C') }, { overwrite: true })

    // Act：抽屉里只留 A
    replaceNodeVariables(node, KB('A'))

    // Assert：两份副本都是 1 项
    expect(namesOf(node)).toEqual(['A'])
    expect(node.store.data.variables.retriever[0].kwargs.knowledge_info_list[0].knowledge_base_name).toEqual(['A'])
  })

  it('保留 data 里其它键，并把 type 标成 saveData（卡片据此刷新）', () => {
    const node = new Node({ shape: 'rect' })
    node.setData({ type: 'displayData', inputVariables: [{ key: 'x' }], variables: KB('A') }, { overwrite: true })

    replaceNodeVariables(node, KB('B'))

    const data = node.getData()
    expect(data.type).toBe('saveData')
    expect(data.inputVariables).toEqual([{ key: 'x' }])
    expect(namesOf(node)).toEqual(['B'])
  })

  it('算子数组变短同样生效（删除算子）', () => {
    const node = new Node({ shape: 'rect' })
    node.setData({
      type: 'displayData',
      variables: { retriever: [{ operator: 'VectorRetriever' }, { operator: 'KeywordRetriever' }] }
    }, { overwrite: true })

    replaceNodeVariables(node, { retriever: [{ operator: 'VectorRetriever' }] })

    expect(node.getData().variables.retriever).toHaveLength(1)
    expect(node.store.data.variables.retriever).toHaveLength(1)
  })
})

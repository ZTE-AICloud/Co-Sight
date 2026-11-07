import { removeExcessOperatorData, addOperatorValidateFields, cleanOperatorList } from '@/features/knowledge-base/lib/operator-config'

// 测的是 `views/docKnowledgeLibrary/lib/operator-config.ts`（从 CreateKnowledgeBaseUnified.vue
// 抽出来的纯函数）。
//
// 这组函数管的是「切分/解析操作符」数据从表单到上传 metadata 的整理：
//   - removeExcessOperatorData：换文件类型时把过期的后缀条目删掉；
//   - addOperatorValidateFields：生成 el-form 的校验字段路径（路径写错 = 校验静默通过，
//     所以下面把路径拼法逐段钉死）；
//   - cleanOperatorList：序列化前删掉 `operatorList`（Map，JSON 化后没有意义、还很大）。
// 三者都**就地修改传入的对象/数组**，断言按「就地改」写。

describe('removeExcessOperatorData', () => {
  describe('given_操作符表与后缀列表_when_裁剪_then_只留列表里的后缀', () => {
    it('删掉不在列表里的键，留下的键原样不动（就地改同一对象）', () => {
      // Arrange
      const data = { txt: { operatorId: 1 }, md: { operatorId: 2 }, pdf: { operatorId: 3 } }

      // Act
      removeExcessOperatorData(['txt', 'pdf'], data)

      // Assert
      expect(Object.keys(data)).toEqual(['txt', 'pdf'])
      expect(data.md).toBeUndefined()
      expect(data.txt).toEqual({ operatorId: 1 })
    })

    it('后缀列表为空 → 全部清掉', () => {
      const data = { txt: {}, md: {} }
      removeExcessOperatorData([], data)
      expect(data).toEqual({})
    })

    it('全都在列表里 → 一个键也不删', () => {
      const data = { txt: { operatorId: 1 } }
      removeExcessOperatorData(['txt', 'md'], data)
      expect(data).toEqual({ txt: { operatorId: 1 } })
    })

    it('空对象不抛错', () => {
      const data = {}
      expect(() => removeExcessOperatorData(['txt'], data)).not.toThrow()
      expect(data).toEqual({})
    })
  })
})

describe('addOperatorValidateFields', () => {
  describe('given_算子数据_when_生成校验字段_then_拼出 operatorId 与每个参数的路径', () => {
    it('没有算子数据（null / undefined）→ 一个字段都不加', () => {
      const fields = []
      addOperatorValidateFields(fields, null, 'system.splitOperator.txt')
      addOperatorValidateFields(fields, undefined, 'system.splitOperator.txt')
      expect(fields).toEqual([])
    })

    it('有算子 → 先 operatorId，再按参数下标逐个 defaultValue', () => {
      const fields = []

      addOperatorValidateFields(fields, { args: [{}, {}] }, 'system.splitOperator.txt')

      // 路径拼法跟 el-form 的 prop 一一对应；改这里等于改校验覆盖面。
      expect(fields).toEqual([
        'system.splitOperator.txt.operatorId',
        'system.splitOperator.txt.args.0.defaultValue',
        'system.splitOperator.txt.args.1.defaultValue'
      ])
    })

    it('args 缺失 → 只加 operatorId（`|| []` 兜底）', () => {
      const fields = []
      addOperatorValidateFields(fields, {}, 'custom.parseOperator.md')
      expect(fields).toEqual(['custom.parseOperator.md.operatorId'])
    })

    it('就地追加到已有数组末尾，旧字段保持不动', () => {
      const fields = ['custom.splitOperator.md.operatorId']
      addOperatorValidateFields(fields, { args: [{}] }, 'custom.parseOperator.md')
      expect(fields).toEqual([
        'custom.splitOperator.md.operatorId',
        'custom.parseOperator.md.operatorId',
        'custom.parseOperator.md.args.0.defaultValue'
      ])
    })
  })
})

describe('cleanOperatorList', () => {
  describe('given_操作符表_when_清理_then_删掉每项上的 operatorList', () => {
    it('删 operatorList、留其他字段（就地改）', () => {
      // Arrange
      const operator = {
        txt: { operatorId: 7, args: [{ argName: 'prompt' }], operatorList: new Map([['x', 1]]) },
        md: { operatorId: 9, operatorList: new Map() }
      }

      // Act
      cleanOperatorList(operator)

      // Assert
      expect('operatorList' in operator.txt).toBe(false)
      expect('operatorList' in operator.md).toBe(false)
      expect(operator.txt).toEqual({ operatorId: 7, args: [{ argName: 'prompt' }] })
    })

    it('值上没有 operatorList → delete 不存在的键，无碍', () => {
      const operator = { txt: { operatorId: 1 } }
      cleanOperatorList(operator)
      expect(operator.txt).toEqual({ operatorId: 1 })
    })

    it('空对象不抛错', () => {
      expect(() => cleanOperatorList({})).not.toThrow()
    })

    it('钉死现状：值为 null 时抛 TypeError（当前调用方不会传 null）', () => {
      // `operator[key].operatorList` 先解引用再看删不删；metadata 里的值都来自
      // fileOperatorDefaultData()，所以线上到不了这个分支。将来若要容错，
      // 这里会先红，提醒把「容错」当成显式决策。
      expect(() => cleanOperatorList({ txt: null })).toThrow(TypeError)
    })
  })
})

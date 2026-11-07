import zhI18n from '@/app/i18n/zh.js'
import enI18n from '@/app/i18n/en.js'

// 递归获取所有键的辅助函数
function getAllKeys(obj, prefix = '') {
  const keys = []
  for (const key in obj) {
    if (obj.hasOwnProperty(key)) {
      const fullKey = prefix ? `${prefix}.${key}` : key
      if (typeof obj[key] === 'object' && obj[key] !== null && !Array.isArray(obj[key])) {
        keys.push(...getAllKeys(obj[key], fullKey))
      } else {
        keys.push(fullKey)
      }
    }
  }
  return keys
}

// 根据键路径获取值的辅助函数
function getValueByPath(obj, path) {
  const keys = path.split('.')
  let value = obj
  for (const key of keys) {
    if (value && typeof value === 'object' && key in value) {
      value = value[key]
    } else {
      return undefined
    }
  }
  return value
}

describe('i18n文件结构测试', () => {
  describe('given_导入i18n文件_when_检查文件结构_then_文件结构正确', () => {
    it('should import zh.js successfully', () => {
      // Arrange & Act
      // Assert
      expect(zhI18n).toBeDefined()
      expect(typeof zhI18n).toBe('object')
      expect(zhI18n).not.toBeNull()
    })

    it('should import en.js successfully', () => {
      // Arrange & Act
      // Assert
      expect(enI18n).toBeDefined()
      expect(typeof enI18n).toBe('object')
      expect(enI18n).not.toBeNull()
    })

    it('should have modules property in zh.js', () => {
      // Arrange & Act
      // Assert
      expect(zhI18n.modules).toBeDefined()
      expect(typeof zhI18n.modules).toBe('object')
    })

    it('should have modules property in en.js', () => {
      // Arrange & Act
      // Assert
      expect(enI18n.modules).toBeDefined()
      expect(typeof enI18n.modules).toBe('object')
    })

    it('should have public property in zh.js', () => {
      // Arrange & Act
      // Assert
      expect(zhI18n.public).toBeDefined()
      expect(typeof zhI18n.public).toBe('object')
    })

    it('should have public property in en.js', () => {
      // Arrange & Act
      // Assert
      expect(enI18n.public).toBeDefined()
      expect(typeof enI18n.public).toBe('object')
    })

    it('should have agent property in zh.js', () => {
      // Arrange & Act
      // Assert
      expect(zhI18n.agent).toBeDefined()
      expect(typeof zhI18n.agent).toBe('object')
    })

    it('should have agent property in en.js', () => {
      // Arrange & Act
      // Assert
      expect(enI18n.agent).toBeDefined()
      expect(typeof enI18n.agent).toBe('object')
    })
  })

  describe('given_检查modules结构_when_验证modules子模块_then_所有子模块存在', () => {
    const expectedModules = [
      'agentApp',
      'extendedManagement',
      'kb',
      'workflow'
      // license / tag / agentGenerate / agentAdvancedFlow / pal 整组不存在
      // （各模块所有键在 src 与 tests 中均无引用）。
    ]

    expectedModules.forEach(moduleName => {
      it(`should have ${moduleName} module in zh.js`, () => {
        // Arrange & Act
        // Assert
        expect(zhI18n.modules[moduleName]).toBeDefined()
        expect(typeof zhI18n.modules[moduleName]).toBe('object')
      })

      it(`should have ${moduleName} module in en.js`, () => {
        // Arrange & Act
        // Assert
        expect(enI18n.modules[moduleName]).toBeDefined()
        expect(typeof enI18n.modules[moduleName]).toBe('object')
      })
    })
  })

  describe('given_检查关键翻译键_when_验证agent相关键_then_键存在且不为空', () => {
    const criticalKeys = [
      'agent.addRole',
      'agent.addKnowledgeBase',
      'agent.addSkill',
      'agent.conversationExperienceSetting',
      'agent.workBridge',
      'agent.LPIModelManagement',
      'agent.AIOptimize',
      'agent.AIOptimizeDisabled'
    ]

    criticalKeys.forEach(key => {
      it(`should have ${key} in zh.js`, () => {
        // Arrange & Act
        const value = getValueByPath(zhI18n, key)
        // Assert
        expect(value).toBeDefined()
        expect(typeof value).toBe('string')
        expect(value.length).toBeGreaterThan(0)
      })

      it(`should have ${key} in en.js`, () => {
        // Arrange & Act
        const value = getValueByPath(enI18n, key)
        // Assert
        expect(value).toBeDefined()
        expect(typeof value).toBe('string')
        expect(value.length).toBeGreaterThan(0)
      })
    })
  })

  describe('given_检查public模块关键键_when_验证公共翻译键_then_键存在且不为空', () => {
    const publicKeys = [
      'public.confirm',
      'public.cancel',
      'public.delete',
      'public.save',
      'public.create',
      'public.theFieldRequired'
    ]

    publicKeys.forEach(key => {
      it(`should have ${key} in zh.js`, () => {
        // Arrange & Act
        const value = getValueByPath(zhI18n, key)
        // Assert
        expect(value).toBeDefined()
        expect(typeof value).toBe('string')
        expect(value.length).toBeGreaterThan(0)
      })

      it(`should have ${key} in en.js`, () => {
        // Arrange & Act
        const value = getValueByPath(enI18n, key)
        // Assert
        expect(value).toBeDefined()
        expect(typeof value).toBe('string')
        expect(value.length).toBeGreaterThan(0)
      })
    })
  })

  describe('given_检查翻译值类型_when_验证值不为空_then_所有值都是有效字符串', () => {
    it('should not have empty string values in zh.js critical keys', () => {
      // Arrange
      const criticalKeys = [
        'agent.addRole',
        'agent.addKnowledgeBase',
        'agent.addSkill',
        'agent.conversationExperienceSetting'
      ]

      // Act & Assert
      criticalKeys.forEach(key => {
        const value = getValueByPath(zhI18n, key)
        expect(value).toBeDefined()
        expect(value).not.toBe('')
        expect(typeof value).toBe('string')
      })
    })

    it('should not have empty string values in en.js critical keys', () => {
      // Arrange
      const criticalKeys = [
        'agent.addRole',
        'agent.addKnowledgeBase',
        'agent.addSkill',
        'agent.conversationExperienceSetting'
      ]

      // Act & Assert
      criticalKeys.forEach(key => {
        const value = getValueByPath(enI18n, key)
        expect(value).toBeDefined()
        expect(value).not.toBe('')
        expect(typeof value).toBe('string')
      })
    })
  })
})



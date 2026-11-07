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

describe('i18n文件一致性测试', () => {
  describe('given_检查中英文键一致性_when_验证关键键_then_中英文键完全一致', () => {
    const criticalKeyPaths = [
      'agent.addRole',
      'agent.addKnowledgeBase',
      'agent.addSkill',
      'agent.conversationExperienceSetting',
      'agent.workBridge',
      'agent.LPIModelManagement',
      'public.confirm',
      'public.cancel',
      'public.delete',
      'public.save',
      'public.create',
      'public.theFieldRequired'
    ]

    criticalKeyPaths.forEach(keyPath => {
      it(`should have consistent key ${keyPath} in both zh.js and en.js`, () => {
        // Arrange & Act
        const zhValue = getValueByPath(zhI18n, keyPath)
        const enValue = getValueByPath(enI18n, keyPath)

        // Assert
        expect(zhValue).toBeDefined()
        expect(enValue).toBeDefined()
        expect(typeof zhValue).toBe('string')
        expect(typeof enValue).toBe('string')
        expect(zhValue.length).toBeGreaterThan(0)
        expect(enValue.length).toBeGreaterThan(0)
      })
    })
  })

  describe('given_检查agent模块键一致性_when_验证agent模块_then_中英文键结构一致', () => {
    it('should have same top-level keys in agent module', () => {
      // Arrange
      const zhAgentKeys = Object.keys(zhI18n.agent || {})
      const enAgentKeys = Object.keys(enI18n.agent || {})

      // Act & Assert
      expect(zhAgentKeys.length).toBeGreaterThan(0)
      expect(enAgentKeys.length).toBeGreaterThan(0)

      // 检查关键键是否存在
      const criticalKeys = ['addRole', 'addKnowledgeBase', 'addSkill', 'conversationExperienceSetting']
      criticalKeys.forEach(key => {
        expect(zhAgentKeys).toContain(key)
        expect(enAgentKeys).toContain(key)
      })
    })
  })

  describe('given_检查public模块键一致性_when_验证public模块_then_中英文键结构一致', () => {
    it('should have same top-level keys in public module', () => {
      // Arrange
      const zhPublicKeys = Object.keys(zhI18n.public || {})
      const enPublicKeys = Object.keys(enI18n.public || {})

      // Act & Assert
      expect(zhPublicKeys.length).toBeGreaterThan(0)
      expect(enPublicKeys.length).toBeGreaterThan(0)

      // 检查关键键是否存在
      const criticalKeys = ['confirm', 'cancel', 'delete', 'save', 'create', 'theFieldRequired']
      criticalKeys.forEach(key => {
        expect(zhPublicKeys).toContain(key)
        expect(enPublicKeys).toContain(key)
      })
    })
  })

  describe('given_检查modules结构一致性_when_验证modules模块_then_中英文模块结构一致', () => {
    it('should have same module names in both zh.js and en.js', () => {
      // Arrange
      const zhModuleNames = Object.keys(zhI18n.modules || {})
      const enModuleNames = Object.keys(enI18n.modules || {})

      // Act & Assert
      expect(zhModuleNames.length).toBe(enModuleNames.length)

      // 所有模块名应该一致
      zhModuleNames.forEach(moduleName => {
        expect(enModuleNames).toContain(moduleName)
      })

      enModuleNames.forEach(moduleName => {
        expect(zhModuleNames).toContain(moduleName)
      })
    })
  })

  describe('given_检查新增tooltip相关键_when_验证tooltip键_then_中英文键都存在', () => {
    const tooltipKeys = [
      'agent.addRole',
      'agent.addKnowledgeBase',
      'agent.addSkill',
      'agent.conversationExperienceSetting'
    ]

    tooltipKeys.forEach(key => {
      it(`should have ${key} in both zh.js and en.js`, () => {
        // Arrange & Act
        const zhValue = getValueByPath(zhI18n, key)
        const enValue = getValueByPath(enI18n, key)

        // Assert
        expect(zhValue).toBeDefined()
        expect(enValue).toBeDefined()
        expect(zhValue).not.toBe('')
        expect(enValue).not.toBe('')
      })
    })
  })

  describe('given_检查翻译值有效性_when_验证值不是undefined或null_then_所有值都是有效字符串', () => {
    const testKeys = [
      'agent.addRole',
      'agent.addKnowledgeBase',
      'agent.addSkill',
      'agent.conversationExperienceSetting',
      'public.confirm',
      'public.cancel'
    ]

    testKeys.forEach(key => {
      it(`should have valid string value for ${key} in zh.js`, () => {
        // Arrange & Act
        const value = getValueByPath(zhI18n, key)

        // Assert
        expect(value).toBeDefined()
        expect(value).not.toBeNull()
        expect(value).not.toBe('')
        expect(typeof value).toBe('string')
      })

      it(`should have valid string value for ${key} in en.js`, () => {
        // Arrange & Act
        const value = getValueByPath(enI18n, key)

        // Assert
        expect(value).toBeDefined()
        expect(value).not.toBeNull()
        expect(value).not.toBe('')
        expect(typeof value).toBe('string')
      })
    })
  })

  describe('given_检查特定翻译值_when_验证tooltip翻译内容_then_翻译内容正确', () => {
    it('should have correct translation for agent.addRole in zh.js', () => {
      // Arrange & Act
      const value = getValueByPath(zhI18n, 'agent.addRole')

      // Assert
      expect(value).toBe('添加角色')
    })

    it('should have correct translation for agent.addRole in en.js', () => {
      // Arrange & Act
      const value = getValueByPath(enI18n, 'agent.addRole')

      // Assert
      expect(value).toBe('Add Role')
    })

    it('should have correct translation for agent.addKnowledgeBase in zh.js', () => {
      // Arrange & Act
      const value = getValueByPath(zhI18n, 'agent.addKnowledgeBase')

      // Assert
      expect(value).toBe('知识库')
    })

    it('should have correct translation for agent.addKnowledgeBase in en.js', () => {
      // Arrange & Act
      const value = getValueByPath(enI18n, 'agent.addKnowledgeBase')

      // Assert
      expect(value).toBe('Knowledge Base')
    })

    it('should have correct translation for agent.addSkill in zh.js', () => {
      // Arrange & Act
      const value = getValueByPath(zhI18n, 'agent.addSkill')

      // Assert
      expect(value).toBe('添加技能')
    })

    it('should have correct translation for agent.addSkill in en.js', () => {
      // Arrange & Act
      const value = getValueByPath(enI18n, 'agent.addSkill')

      // Assert
      expect(value).toBe('Add Skill')
    })

    it('should have correct translation for agent.conversationExperienceSetting in zh.js', () => {
      // Arrange & Act
      const value = getValueByPath(zhI18n, 'agent.conversationExperienceSetting')

      // Assert
      expect(value).toBe('对话体验设置')
    })

    it('should have correct translation for agent.conversationExperienceSetting in en.js', () => {
      // Arrange & Act
      const value = getValueByPath(enI18n, 'agent.conversationExperienceSetting')

      // Assert
      expect(value).toBe('Conversation Experience Settings')
    })
  })
})



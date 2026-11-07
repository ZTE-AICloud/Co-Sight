<template>
  <div class="property-panel-drawer">
    <!-- 当选中项存在时显示配置内容 -->
    <div v-if="selectedItem" class="panel-content">
      <!-- 实体配置 -->
      <div v-if="itemType === 'node'" class="entity-config">
        <el-collapse v-model="activeNames" type="ghost" class="ghost-collapse">
          <!-- 基础设置 -->
          <el-collapse-item :title="proxy.$t('modules.kb.basicSettings')" name="basic">
            <el-form ref="nodeFormRef" :model="nodeForm" :rules="nodeFormRules" label-width="90px" size="default">
              <el-form-item :label="proxy.$t('modules.kb.entityClassName')" prop="name" required>
                <el-input
                  v-model="nodeForm.name"
                  :placeholder="proxy.$t('modules.kb.inputEntityClassName')"
                  maxlength="63"
                  show-word-limit
                  clearable
                  @input="validateNodeName"
                />
              </el-form-item>
              <el-form-item :label="proxy.$t('modules.kb.description')" prop="description" required>
                <el-input
                  v-model="nodeForm.description"
                  type="textarea"
                  :rows="6"
                  :placeholder="proxy.$t('modules.kb.entityDescriptionPlaceholder')"
                  maxlength="1000"
                  show-word-limit
                />
              </el-form-item>
            </el-form>
          </el-collapse-item>

          <!-- 属性设置 -->
          <el-collapse-item :title="proxy.$t('modules.kb.attributeSettings')" name="attributes">
            <div class="attributes-section">
              <el-tabs
                v-model="activePropTabName"
                type="card"
                editable
                class="prop-tabs"
                @edit="handlePropTabsEdit"
              >
                <el-tab-pane
                  v-for="(prop, idx) in nodeForm.properties"
                  :key="prop?.__key ?? idx"
                  :label="(prop && prop.name) ? prop.name : proxy.$t('modules.kb.propertyWithIndex', { index: idx + 1 })"
                  :name="prop?.__key ?? String(idx)"
                >
                  <el-form :model="prop" :rules="getNodePropertyRules(idx)" label-width="90px" size="default" :ref="el => setNodePropFormRef(el, idx)" :validate-on-rule-change="false">
                    <el-form-item :label="proxy.$t('modules.kb.propertyName')" prop="name" required>
                      <el-input
                        v-model="prop.name"
                        :placeholder="proxy.$t('modules.kb.inputPropertyName')"
                        maxlength="63"
                        show-word-limit
                        @blur="validateNodePropField(idx, 'name')"
                        @input="validateNodePropField(idx, 'name')"
                      />
                    </el-form-item>
                    <el-form-item :label="proxy.$t('modules.kb.propertyType')" required>
                      <el-select v-model="prop.type" :placeholder="proxy.$t('modules.kb.selectPropertyType')">
                        <el-option
                          v-for="option in propertyTypeOptions"
                          :key="option.value"
                          :label="option.label"
                          :value="option.value"
                        />
                      </el-select>
                    </el-form-item>
                    <el-form-item :label="proxy.$t('modules.kb.propertyDescription')" prop="desc" required>
                      <el-input
                        v-model="prop.desc"
                        type="textarea"
                        :rows="4"
                        :placeholder="proxy.$t('modules.kb.propertyDescriptionPlaceholder')"
                        maxlength="1000"
                        show-word-limit
                        @blur="validateNodePropField(idx, 'desc')"
                        @input="validateNodePropField(idx, 'desc')"
                      />
                    </el-form-item>
                    <el-form-item :label="proxy.$t('modules.kb.isPrimaryKey')">
                      <el-radio-group v-model="prop.is_primary">
                        <el-radio :label="true">{{ proxy.$t('modules.kb.yes') }}</el-radio>
                        <el-radio :label="false">{{ proxy.$t('modules.kb.no') }}</el-radio>
                      </el-radio-group>
                    </el-form-item>
                    <el-form-item :label="proxy.$t('modules.kb.isVectorized')">
                      <el-radio-group v-model="prop.is_embedding">
                        <el-radio :label="true">{{ proxy.$t('modules.kb.yes') }}</el-radio>
                        <el-radio :label="false">{{ proxy.$t('modules.kb.no') }}</el-radio>
                      </el-radio-group>
                    </el-form-item>
                    <el-form-item :label="proxy.$t('modules.kb.isIndexed')">
                      <el-radio-group v-model="prop.is_index">
                        <el-radio :label="true">{{ proxy.$t('modules.kb.yes') }}</el-radio>
                        <el-radio :label="false">{{ proxy.$t('modules.kb.no') }}</el-radio>
                      </el-radio-group>
                    </el-form-item>
                  </el-form>
                </el-tab-pane>
              </el-tabs>
            </div>
          </el-collapse-item>

        </el-collapse>
      </div>

      <!-- 关系配置 -->
      <div v-else-if="itemType === 'edge'" class="relationship-config">
        <el-collapse v-model="activeNames" type="ghost" class="ghost-collapse">
          <!-- 基础设置 -->
          <el-collapse-item :title="proxy.$t('modules.kb.relationshipSettings')" name="basic">
            <el-form ref="edgeFormRef" :model="edgeForm" :rules="edgeFormRules" label-width="100px" size="default">
              <el-form-item :label="proxy.$t('modules.kb.relationshipType')" prop="edge_type" required>
                <el-input
                  v-model="edgeForm.edge_type"
                  :placeholder="proxy.$t('modules.kb.inputRelationshipType')"
                  maxlength="63"
                  show-word-limit
                  clearable
                  @input="validateEdgeType"
                />
              </el-form-item>

              <el-form-item :label="proxy.$t('modules.kb.relationshipDescription')" prop="edge_desc" required>
                <el-input
                  v-model="edgeForm.edge_desc"
                  type="textarea"
                  :rows="5"
                  :placeholder="proxy.$t('modules.kb.relationshipDescriptionPlaceholder')"
                  maxlength="1000"
                  show-word-limit
                />
              </el-form-item>

              <!-- 关系方向字段暂时屏蔽 - 功能待完善后再开放 -->
              <!-- <el-form-item label="关系方向">
                <el-input :model-value="directionLabel" disabled />
              </el-form-item> -->

              <el-form-item :label="proxy.$t('modules.kb.sourceEntity')">
                <el-input v-model="edgeForm.source_entity" disabled />
              </el-form-item>

              <el-form-item :label="proxy.$t('modules.kb.targetEntity')">
                <el-input v-model="edgeForm.target_entity" disabled />
              </el-form-item>
            </el-form>
          </el-collapse-item>

          <!-- 关系属性 -->
          <el-collapse-item :title="proxy.$t('modules.kb.relationshipAttributes')" name="edge-attributes">
            <div class="attributes-section">
              <el-tabs
                v-model="activeEdgePropTabName"
                type="card"
                editable
                class="prop-tabs"
                @edit="handleEdgePropTabsEdit"
              >
                <el-tab-pane
                  v-for="(p, idx) in edgeForm.properties"
                  :key="p?.__key ?? idx"
                  :label="(p && p.name) ? p.name : proxy.$t('modules.kb.propertyWithIndex', { index: idx + 1 })"
                  :name="p?.__key ?? String(idx)"
                >
                  <el-form :model="p" :rules="getEdgePropertyRules(idx)" label-width="90px" size="default" :ref="el => setEdgePropFormRef(el, idx)" :validate-on-rule-change="false">
                    <el-form-item :label="proxy.$t('modules.kb.propertyName')" prop="name" required>
                      <el-input
                        v-model="p.name"
                        :placeholder="proxy.$t('modules.kb.inputPropertyName')"
                        maxlength="63"
                        show-word-limit
                        @blur="validateEdgePropField(idx, 'name')"
                        @input="validateEdgePropField(idx, 'name')"
                      />
                    </el-form-item>
                    <el-form-item :label="proxy.$t('modules.kb.propertyType')" required>
                      <el-select v-model="p.type" :placeholder="proxy.$t('modules.kb.selectPropertyType')">
                        <el-option
                          v-for="option in propertyTypeOptions"
                          :key="option.value"
                          :label="option.label"
                          :value="option.value"
                        />
                      </el-select>
                    </el-form-item>
                    <el-form-item :label="proxy.$t('modules.kb.propertyDescription')" prop="desc" required>
                      <el-input
                        v-model="p.desc"
                        type="textarea"
                        :rows="4"
                        :placeholder="proxy.$t('modules.kb.propertyDescriptionPlaceholder')"
                        maxlength="1000"
                        show-word-limit
                        @blur="validateEdgePropField(idx, 'desc')"
                        @input="validateEdgePropField(idx, 'desc')"
                      />
                    </el-form-item>
                    <el-form-item :label="proxy.$t('modules.kb.isVectorized')">
                      <el-radio-group v-model="p.is_embedding">
                        <el-radio :label="true">{{ proxy.$t('modules.kb.yes') }}</el-radio>
                        <el-radio :label="false">{{ proxy.$t('modules.kb.no') }}</el-radio>
                      </el-radio-group>
                    </el-form-item>
                    <el-form-item :label="proxy.$t('modules.kb.isIndexed')">
                      <el-radio-group v-model="p.is_index">
                        <el-radio :label="true">{{ proxy.$t('modules.kb.yes') }}</el-radio>
                        <el-radio :label="false">{{ proxy.$t('modules.kb.no') }}</el-radio>
                      </el-radio-group>
                    </el-form-item>
                  </el-form>
                </el-tab-pane>
              </el-tabs>
            </div>
          </el-collapse-item>

        </el-collapse>
      </div>

      <!-- 移除内部的操作按钮，改为由抽屉脚注控制 -->
    </div>

    <!-- 未选中时的提示 -->
    <div v-else class="empty-state">
      <div class="empty-content">
        <el-icon size="48" color="var(--rs-text-tertiary)">
          <Box />
        </el-icon>
        <p>{{ proxy.$t('modules.kb.pleaseSelectEntityOrRelationship') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, nextTick, getCurrentInstance } from 'vue'
import { Box } from '@/shared/lib/icons'

const props = defineProps<{
  selectedItem: any
  itemType: 'node' | 'edge' | null
}>()

const emit = defineEmits(['update-properties'])

// 获取当前实例用于消息提示
const { proxy } = getCurrentInstance() as any

// 面板状态
const activeNames = ref(['basic', 'attributes'])

const nodeFormRef = ref()
// 实体属性表单refs数组
const nodePropFormRefs = ref<any[]>([])

// 设置实体属性表单ref
const setNodePropFormRef = (el: any, index: number) => {
  if (el) {
    nodePropFormRefs.value[index] = el
  }
}

// 校验实体属性字段
const validateNodePropField = (index: number, field: string) => {
  const formRef = nodePropFormRefs.value[index]
  if (formRef) {
    formRef.validateField(field)
  }
}

// 统一的描述字段验证函数（与后端校验规则保持一致）
const validateDesc = (_rule: any, value: string, callback: any) => {
  if (!value) {
    return callback(new Error(proxy.$t('modules.kb.inputRequiredField')))
  }

  // 1. 长度检查：使用原始长度（不是trim后的长度），必须在1-1000之间
  const length = value.length
  if (length < 1 || length > 1000) {
    return callback(new Error(proxy.$t('modules.kb.descLengthInvalid', { length })))
  }

  // 2. 检查是否为全空格或空白字符
  if (value.trim() === '') {
    return callback(new Error(proxy.$t('modules.kb.descCannotBeWhitespace')))
  }

  return callback()
}

// 统一的实体类名/关系类名验证函数（与后端校验规则保持一致）
const validateClassType = (_rule: any, value: string, callback: any, fieldType: 'entity' | 'relationship' = 'entity') => {
  if (!value) {
    // 根据字段类型选择对应的国际化键
    const errorKey = fieldType === 'entity' ? 'modules.kb.entityClassNameRequired' : 'modules.kb.relationshipTypeRequired'
    return callback(new Error(proxy.$t(errorKey)))
  }

  // 获取字段名称用于错误提示
  const fieldName = fieldType === 'entity' ? proxy.$t('modules.kb.entityClassName') : proxy.$t('modules.kb.relationshipType')

  // 1. 长度检查：使用原始长度（不是trim后的长度），必须在1-63之间
  const length = value.length
  if (length < 1 || length > 63) {
    return callback(new Error(proxy.$t('modules.kb.classNameLengthInvalid', { fieldName, length })))
  }

  // 2. 格式检查：首字母必须为字母（A-Z 或 a-z），仅允许英文字母
  const pattern = /^[A-Za-z][A-Za-z]*$/
  if (!pattern.test(value)) {
    return callback(new Error(proxy.$t('modules.kb.classNameFormatInvalid', { fieldName })))
  }

  // 3. 检查是否为SQL保留关键字（忽略大小写）
  const sqlReservedKeywords = new Set([
    'ORDER', 'GROUP', 'AS', 'AND', 'OR', 'FROM', 'WHERE', 'SELECT', 'INSERT',
    'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER', 'TABLE', 'INDEX', 'VIEW',
    'JOIN', 'INNER', 'LEFT', 'RIGHT', 'FULL', 'OUTER', 'ON', 'HAVING',
    'DISTINCT', 'UNION', 'INTERSECT', 'EXCEPT', 'LIMIT', 'OFFSET', 'NULL',
    'TRUE', 'FALSE', 'IS', 'NOT', 'IN', 'EXISTS', 'BETWEEN', 'LIKE',
    'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'CAST', 'COUNT', 'SUM', 'AVG',
    'MAX', 'MIN', 'IF', 'ELSEIF', 'WHILE', 'FOR', 'DO', 'BEGIN',
    'VERTEX', 'EDGE'
  ])
  if (sqlReservedKeywords.has(value.toUpperCase())) {
    return callback(new Error(proxy.$t('modules.kb.classNameReservedKeyword', { fieldName, value })))
  }

  return callback()
}

// 验证类名的辅助函数（用于保存时验证，返回错误消息或null）
const validateClassTypeForSave = (value: string, fieldType: 'entity' | 'relationship' = 'entity'): string | null => {
  if (!value) {
    // 根据字段类型选择对应的国际化键
    const errorKey = fieldType === 'entity' ? 'modules.kb.entityClassNameRequired' : 'modules.kb.relationshipTypeRequired'
    return proxy.$t(errorKey)
  }

  // 获取字段名称用于错误提示
  const fieldName = fieldType === 'entity' ? proxy.$t('modules.kb.entityClassName') : proxy.$t('modules.kb.relationshipType')

  // 1. 长度检查：使用原始长度（不是trim后的长度），必须在1-63之间
  const length = value.length
  if (length < 1 || length > 63) {
    return proxy.$t('modules.kb.classNameLengthInvalid', { fieldName, length })
  }

  // 2. 格式检查：首字母必须为字母（A-Z 或 a-z），仅允许英文字母
  const pattern = /^[A-Za-z][A-Za-z]*$/
  if (!pattern.test(value)) {
    return proxy.$t('modules.kb.classNameFormatInvalid', { fieldName })
  }

  // 3. 检查是否为SQL保留关键字（忽略大小写）
  const sqlReservedKeywords = new Set([
    'ORDER', 'GROUP', 'AS', 'AND', 'OR', 'FROM', 'WHERE', 'SELECT', 'INSERT',
    'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER', 'TABLE', 'INDEX', 'VIEW',
    'JOIN', 'INNER', 'LEFT', 'RIGHT', 'FULL', 'OUTER', 'ON', 'HAVING',
    'DISTINCT', 'UNION', 'INTERSECT', 'EXCEPT', 'LIMIT', 'OFFSET', 'NULL',
    'TRUE', 'FALSE', 'IS', 'NOT', 'IN', 'EXISTS', 'BETWEEN', 'LIKE',
    'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'CAST', 'COUNT', 'SUM', 'AVG',
    'MAX', 'MIN', 'IF', 'ELSEIF', 'WHILE', 'FOR', 'DO', 'BEGIN',
    'VERTEX', 'EDGE'
  ])
  if (sqlReservedKeywords.has(value.toUpperCase())) {
    return proxy.$t('modules.kb.classNameReservedKeyword', { fieldName, value })
  }

  return null
}

const nodeFormRules = {
  name: [
    {
      required: true,
      validator: (_rule: any, value: string, callback: any) => {
        validateClassType(_rule, value, callback, 'entity')
      },
      trigger: ['blur', 'change']
    }
  ],
  description: [
    {
      required: true,
      validator: validateDesc,
      trigger: ['blur', 'change']
    }
  ]
}

const validateNodeName = () => {
  nodeFormRef.value?.validateField('name')
}

// 表单数据
const nodeForm = reactive({
  name: '',
  description: '',
  properties: [] as any[]
})

const edgeForm = reactive({
  edge_type: '',
  edge_desc: '',
  direction: 'one-way',
  source_entity: '',
  target_entity: '',
  properties: [] as any[]
})

const directionLabel = computed(() => {
  switch (edgeForm.direction) {
    case 'two-way': return proxy.$t('modules.kb.directionBoth')
    case 'self-loop': return proxy.$t('modules.kbWorkspace.graphEditor.directionSelfLoop')
    default: return proxy.$t('modules.kbWorkspace.graphEditor.directionOneWay')
  }
})

// 属性类型选项（根据后端 GraphPropertyTypeEnum 枚举）
const propertyTypeOptions = computed(() => [
  { value: 'BOOLEAN', label: proxy.$t('modules.kb.propertyTypeBoolean') },
  { value: 'BYTE', label: proxy.$t('modules.kb.propertyTypeByte') },
  { value: 'SHORT', label: proxy.$t('modules.kb.propertyTypeShort') },
  { value: 'INTEGER', label: proxy.$t('modules.kb.propertyTypeInteger') },
  { value: 'LONG', label: proxy.$t('modules.kb.propertyTypeLong') },
  { value: 'FLOAT', label: proxy.$t('modules.kb.propertyTypeFloat') },
  { value: 'DOUBLE', label: proxy.$t('modules.kb.propertyTypeDouble') },
  { value: 'DATE', label: proxy.$t('modules.kb.propertyTypeDate') },
  { value: 'DATETIME', label: proxy.$t('modules.kb.propertyTypeDatetime') },
  { value: 'STRING', label: proxy.$t('modules.kb.propertyTypeString') },
  { value: 'BINARY', label: proxy.$t('modules.kb.propertyTypeBinary') },
  { value: 'EMBEDDED', label: proxy.$t('modules.kb.propertyTypeEmbedded') },
  { value: 'EMBEDDEDLIST', label: proxy.$t('modules.kb.propertyTypeEmbeddedList') },
  { value: 'EMBEDDEDSET', label: proxy.$t('modules.kb.propertyTypeEmbeddedSet') },
  { value: 'EMBEDDEDMAP', label: proxy.$t('modules.kb.propertyTypeEmbeddedMap') },
  { value: 'LINK', label: proxy.$t('modules.kb.propertyTypeLink') },
  { value: 'LINKLIST', label: proxy.$t('modules.kb.propertyTypeLinkList') },
  { value: 'LINKSET', label: proxy.$t('modules.kb.propertyTypeLinkSet') },
  { value: 'LINKMAP', label: proxy.$t('modules.kb.propertyTypeLinkMap') }
])

// 实体属性 tabs
const activePropTabName = ref('')
let propTabIndex = 0
// 标记是否是新增tab触发的切换（用于阻止新增tab时自动校验）
const isAddingNodePropTab = ref(false)

// 属性数量上限（可根据需要修改此值）
const MAX_PROPERTY_COUNT = 100

const makeNewProperty = () => ({
  __key: `${++propTabIndex}`,
  name: '',
  type: 'STRING',  // 使用大写,符合API文档
  desc: '',
  is_primary: false,
  is_embedding: false,
  is_index: false
})

// 统一的属性名称验证函数（与后端校验规则保持一致）
const validatePropertyName = (value: string): string | null => {
  if (!value) {
    return proxy.$t('modules.kb.propertyNameRequired')
  }

  // 1. 长度检查：使用原始长度（不是trim后的长度），必须在1-63之间
  const length = value.length
  if (length < 1 || length > 63) {
    return proxy.$t('modules.kb.propertyNameLengthInvalid', { length })
  }

  // 2. 格式检查：必须以字母开头，仅允许字母、数字和下划线
  const pattern = /^[a-zA-Z][a-zA-Z0-9_]*$/
  if (!pattern.test(value)) {
    return proxy.$t('modules.kb.propertyNameFormatInvalid')
  }

  // 3. 检查是否为SQL保留关键字（忽略大小写）
  const sqlReservedKeywords = new Set([
    'ORDER', 'GROUP', 'AS', 'AND', 'OR', 'FROM', 'WHERE', 'SELECT', 'INSERT',
    'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER', 'TABLE', 'INDEX', 'VIEW',
    'JOIN', 'INNER', 'LEFT', 'RIGHT', 'FULL', 'OUTER', 'ON', 'HAVING',
    'DISTINCT', 'UNION', 'INTERSECT', 'EXCEPT', 'LIMIT', 'OFFSET', 'NULL',
    'TRUE', 'FALSE', 'IS', 'NOT', 'IN', 'EXISTS', 'BETWEEN', 'LIKE',
    'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'CAST', 'COUNT', 'SUM', 'AVG',
    'MAX', 'MIN', 'IF', 'ELSEIF', 'WHILE', 'FOR', 'DO', 'BEGIN',
    'VERTEX', 'EDGE'
  ])
  if (sqlReservedKeywords.has(value.toUpperCase())) {
    return proxy.$t('modules.kb.propertyNameReservedKeyword', { value })
  }

  return null
}

// 验证属性名称是否重复（用于实体属性）
const validateNodePropertyName = (rule: any, value: string, callback: any, currentIndex: number) => {
  // 先进行基础验证（长度、格式、保留关键字）
  const baseError = validatePropertyName(value)
  if (baseError) {
    callback(new Error(baseError))
    return
  }

  const trimmedValue = value.trim()
  // 检查是否有重复的属性名称（排除当前属性）
  const duplicateIndex = nodeForm.properties.findIndex((p: any, idx: number) =>
    idx !== currentIndex && p.name && p.name.trim() === trimmedValue
  )
  if (duplicateIndex !== -1) {
    callback(new Error(proxy.$t('modules.kb.propertyNameDuplicateSimple')))
    return
  }
  callback()
}

// 获取实体属性的验证规则
const getNodePropertyRules = (index: number) => {
  return {
    name: [
      {
        required: true,
        validator: (rule: any, value: string, callback: any) => {
          validateNodePropertyName(rule, value, callback, index)
        },
        trigger: 'blur' // 只保留blur触发，避免change时自动触发校验（输入时通过@input事件手动触发）
      }
    ],
    desc: [
      {
        required: true,
        validator: validateDesc,
        trigger: 'blur' // 只保留blur触发，避免change时自动触发校验（输入时通过@input事件手动触发）
      }
    ]
  }
}

const handlePropTabsEdit = (targetName: any, action: 'remove' | 'add') => {
  if (action === 'add') {
    // 检查属性数量上限
    if (nodeForm.properties.length >= MAX_PROPERTY_COUNT) {
      proxy?.$message?.warning(proxy.$t('modules.kb.propertyCountLimitExceeded', { count: MAX_PROPERTY_COUNT }))
      return
    }
    // 标记是新增tab触发的切换
    isAddingNodePropTab.value = true
    const tab = makeNewProperty()
    nodeForm.properties.push(tab)
    const newTabKey = tab.__key
    activePropTabName.value = newTabKey
    // 在下一个tick清除新tab的校验，然后清除标志位
    nextTick(() => {
      const newIndex = nodeForm.properties.findIndex((p: any) => p.__key === newTabKey)
      if (newIndex !== -1) {
        const formRef = nodePropFormRefs.value[newIndex]
        if (formRef) {
          formRef.clearValidate()
        }
      }
      // 延迟清除标志位，确保watch中的clearValidate也能执行
      setTimeout(() => {
        isAddingNodePropTab.value = false
      }, 0)
    })
  } else if (action === 'remove') {
    const tabs = nodeForm.properties
    let active = activePropTabName.value
    if (active === targetName) {
      const i = tabs.findIndex(t => t.__key === targetName)
      const next = tabs[i + 1] || tabs[i - 1]
      if (next) {
        active = next.__key
      }
    }
    activePropTabName.value = active
    const idx = nodeForm.properties.findIndex(t => t.__key === targetName)
    if (idx !== -1) {
      nodeForm.properties.splice(idx, 1)
    }
  }
}

// 关系属性 tabs
const activeEdgePropTabName = ref('')
let edgePropTabIndex = 0
// 标记是否是新增tab触发的切换（用于阻止新增tab时自动校验）
const isAddingEdgePropTab = ref(false)
const makeNewEdgeProperty = () => ({
  __key: `${++edgePropTabIndex}`,
  name: '',
  type: 'STRING',  // 使用大写,符合API文档
  desc: '',
  is_embedding: false,
  is_index: false
})

// 验证属性名称是否重复（用于关系属性）
const validateEdgePropertyName = (rule: any, value: string, callback: any, currentIndex: number) => {
  // 先进行基础验证（长度、格式、保留关键字）
  const baseError = validatePropertyName(value)
  if (baseError) {
    callback(new Error(baseError))
    return
  }

  const trimmedValue = value.trim()
  // 检查是否有重复的属性名称（排除当前属性）
  const duplicateIndex = edgeForm.properties.findIndex((p: any, idx: number) =>
    idx !== currentIndex && p.name && p.name.trim() === trimmedValue
  )
  if (duplicateIndex !== -1) {
    callback(new Error(proxy.$t('modules.kb.propertyNameDuplicateSimple')))
    return
  }
  callback()
}

// 获取关系属性的验证规则
const getEdgePropertyRules = (index: number) => {
  return {
    name: [
      {
        required: true,
        validator: (rule: any, value: string, callback: any) => {
          validateEdgePropertyName(rule, value, callback, index)
        },
        trigger: 'blur' // 只保留blur触发，避免change时自动触发校验
      }
    ],
    desc: [
      {
        required: true,
        validator: validateDesc,
        trigger: 'blur' // 只保留blur触发，避免change时自动触发校验
      }
    ]
  }
}

const handleEdgePropTabsEdit = (targetName: any, action: 'remove' | 'add') => {
  if (action === 'add') {
    // 检查属性数量上限
    if (edgeForm.properties.length >= MAX_PROPERTY_COUNT) {
      proxy?.$message?.warning(proxy.$t('modules.kb.propertyCountLimitExceeded', { count: MAX_PROPERTY_COUNT }))
      return
    }
    // 标记是新增tab触发的切换
    isAddingEdgePropTab.value = true
    const tab = makeNewEdgeProperty()
    edgeForm.properties.push(tab)
    const newTabKey = tab.__key
    activeEdgePropTabName.value = newTabKey
    // 在下一个tick清除新tab的校验，然后清除标志位
    nextTick(() => {
      const newIndex = edgeForm.properties.findIndex((p: any) => p.__key === newTabKey)
      if (newIndex !== -1) {
        const formRef = edgePropFormRefs.value[newIndex]
        if (formRef) {
          formRef.clearValidate()
        }
      }
      // 延迟清除标志位，确保watch中的clearValidate也能执行
      setTimeout(() => {
        isAddingEdgePropTab.value = false
      }, 0)
    })
  } else if (action === 'remove') {
    const tabs = edgeForm.properties
    let active = activeEdgePropTabName.value
    if (active === targetName) {
      const i = tabs.findIndex(t => t.__key === targetName)
      const next = tabs[i + 1] || tabs[i - 1]
      if (next) {
        active = next.__key
      }
    }
    activeEdgePropTabName.value = active
    const idx = edgeForm.properties.findIndex(t => t.__key === targetName)
    if (idx !== -1) {
      edgeForm.properties.splice(idx, 1)
    }
  }
}

// 边表单 ref 与规则（edge_type 实时必填且<=20）
const edgeFormRef = ref()
// 关系属性表单refs数组
const edgePropFormRefs = ref<any[]>([])

// 设置关系属性表单ref
const setEdgePropFormRef = (el: any, index: number) => {
  if (el) {
    edgePropFormRefs.value[index] = el
  }
}

// 校验关系属性字段
const validateEdgePropField = (index: number, field: string) => {
  const formRef = edgePropFormRefs.value[index]
  if (formRef) {
    formRef.validateField(field)
  }
}
const edgeFormRules = {
  edge_type: [
    {
      required: true,
      validator: (_rule: any, value: string, callback: any) => {
        validateClassType(_rule, value, callback, 'relationship')
      },
      trigger: ['blur', 'change']
    }
  ],
  edge_desc: [
    {
      required: true,
      validator: validateDesc,
      trigger: ['blur', 'change']
    }
  ]
}
const validateEdgeType = () => edgeFormRef.value?.validateField('edge_type')

// 根据 itemType 设置折叠面板的展开状态
watch(() => props.itemType, (newType) => {
  if (newType === 'node') {
    activeNames.value = ['basic', 'attributes']
  } else if (newType === 'edge') {
    activeNames.value = ['basic', 'edge-attributes']
  }
}, { immediate: true })

// 监听选中项变化
watch(() => props.selectedItem, (newItem) => {

  if (newItem && props.itemType === 'node') {
    // X6 node 对象可能需要通过 getData() 方法获取数据
    const nodeData = newItem.getData ? newItem.getData() : newItem.data

    nodeForm.name = nodeData?.name || ''
    nodeForm.description = nodeData?.description || ''

    const toPropList = (list: any[] = []) =>
      (Array.isArray(list) ? list : [])
        .filter(Boolean)
        .map((p: any, i: number) => ({
          __key: `${i + 1}`,
          name: p?.name || '',
          type: p?.type || 'STRING',  // 使用大写,符合API文档
          desc: p?.desc || p?.description || '',
          is_primary: !!(p?.is_primary || p?.isUnique || p?.isRequired),
          is_embedding: !!p?.is_embedding,
          is_index: !!p?.is_index
        }))

    const src = nodeData?.properties || []

    const propsList = toPropList(src)
    // 若没有任何属性，默认补一个“属性1”
    if (propsList.length === 0) {
      const first = makeNewProperty()
      propsList.push(first)
    }
    nodeForm.properties = [...propsList]
    propTabIndex = propsList.length
    activePropTabName.value = propsList[0]?.__key || ''

  } else if (newItem && props.itemType === 'edge') {
    // X6 edge 对象可能需要通过 getData() 方法获取数据
    const edgeData = newItem.getData ? newItem.getData() : newItem.data
    const d: any = edgeData || {}
    edgeForm.edge_type = d.edge_type || ''
    edgeForm.edge_desc = d.edge_desc || ''
    // 方向映射：优先用数据字段；否则根据边的形状推断 single/double/self
    const shapeName = (newItem as any)?.shape || (newItem as any)?.getShape?.()
    const inferred = shapeName === 'double-arrow-edge' ? 'double' : (shapeName === 'self-loop-edge' ? 'self' : 'single')
    // X6 连线模式是 single/double/self；表单用 one-way/two-way/self-loop
    const storedDirection = d.direction || inferred
    edgeForm.direction = storedDirection === 'double' ? 'two-way' : (storedDirection === 'self' ? 'self-loop' : 'one-way')

    // 起始/目标实体（优先已有字段，否则从连线源/目标节点获取名称）
    edgeForm.source_entity =
      d.source_entity ||
      (newItem.getSourceCell && newItem.getSourceCell()?.getData?.()?.name) ||
      ''
    edgeForm.target_entity =
      d.target_entity ||
      (newItem.getTargetCell && newItem.getTargetCell()?.getData?.()?.name) ||
      ''

    // 关系属性
    const toEdgePropList = (list: any[] = []) =>
      (Array.isArray(list) ? list : [])
        .filter(Boolean)
        .map((p: any, i: number) => ({
          __key: `${i + 1}`,
          name: p?.name || '',
          type: p?.type || 'STRING',  // 使用大写,符合API文档
          desc: p?.desc || p?.description || '',
          is_embedding: !!p?.is_embedding,
          is_index: !!p?.is_index
        }))

    const srcProps = d.properties || []
    const list = toEdgePropList(srcProps)
    if (list.length === 0) {
      list.push(makeNewEdgeProperty())
    }
    edgeForm.properties = [...list]
    edgePropTabIndex = list.length
    activeEdgePropTabName.value = list[0]?.__key || ''

  }
}, { immediate: true })

// 监听实体属性tab切换，只在用户手动切换时触发校验（新增tab时不校验）
watch(activePropTabName, (newVal, oldVal) => {
  // 如果是新增tab触发的切换，清除校验并返回
  if (isAddingNodePropTab.value) {
    // 清除新tab的校验
    const newIndex = nodeForm.properties.findIndex((p: any) => p.__key === newVal)
    if (newIndex !== -1) {
      const formRef = nodePropFormRefs.value[newIndex]
      if (formRef) {
        formRef.clearValidate()
      }
    }
    return
  }

  // 用户手动切换tab时，触发之前tab的校验
  if (oldVal && oldVal !== newVal) {
    const oldIndex = nodeForm.properties.findIndex((p: any) => p.__key === oldVal)
    if (oldIndex !== -1) {
      const formRef = nodePropFormRefs.value[oldIndex]
      if (formRef) {
        formRef.validate(() => {
          // 校验完成后的回调（可留空）
        })
      }
    }
  }
})

// 监听关系属性tab切换，只在用户手动切换时触发校验（新增tab时不校验）
watch(activeEdgePropTabName, (newVal, oldVal) => {
  // 如果是新增tab触发的切换，清除校验并返回
  if (isAddingEdgePropTab.value) {
    // 清除新tab的校验（使用nextTick确保DOM已渲染）
    nextTick(() => {
      const newIndex = edgeForm.properties.findIndex((p: any) => p.__key === newVal)
      if (newIndex !== -1) {
        const formRef = edgePropFormRefs.value[newIndex]
        if (formRef) {
          formRef.clearValidate()
        }
      }
    })
    return
  }

  // 用户手动切换tab时，触发之前tab的校验
  if (oldVal && oldVal !== newVal) {
    const oldIndex = edgeForm.properties.findIndex((p: any) => p.__key === oldVal)
    if (oldIndex !== -1) {
      const formRef = edgePropFormRefs.value[oldIndex]
      if (formRef) {
        formRef.validate(() => {
          // 校验完成后的回调（可留空）
        })
      }
    }
  }
})

// 应用更改 - 暴露给父组件调用
const applyChanges = async () => {
  return new Promise((resolve, reject) => {
    try {
      if (props.itemType === 'node') {
        // 验证实体类名（与后端校验规则保持一致）
        const entityTypeError = validateClassTypeForSave(nodeForm.name, 'entity')
        if (entityTypeError) {
          proxy?.$message?.error(entityTypeError)
          reject(new Error(entityTypeError))
          return
        }

        // 验证描述（与后端校验规则保持一致）
        if (!nodeForm.description) {
          proxy?.$message?.error(proxy.$t('modules.kb.inputRequiredField'))
          reject(new Error(proxy.$t('modules.kb.inputRequiredField')))
          return
        }
        const descLength = nodeForm.description.length
        if (descLength < 1 || descLength > 1000) {
          const errorMsg = proxy.$t('modules.kb.descLengthInvalid', { length: descLength })
          proxy?.$message?.error(errorMsg)
          reject(new Error(errorMsg))
          return
        }
        if (nodeForm.description.trim() === '') {
          proxy?.$message?.error(proxy.$t('modules.kb.descCannotBeWhitespace'))
          reject(new Error(proxy.$t('modules.kb.descCannotBeWhitespace')))
          return
        }

        // 验证至少有一个属性
        if (!nodeForm.properties || nodeForm.properties.length === 0) {
          proxy?.$message?.error(proxy.$t('modules.kb.atLeastOnePropertyRequired'))
          reject(new Error(proxy.$t('modules.kb.atLeastOnePropertyRequired')))
          return
        }

        // 验证每个属性都有名称（与后端校验规则保持一致）
        for (const p of nodeForm.properties) {
          if (!p.name) {
            proxy?.$message?.error(proxy.$t('modules.kb.propertyNameRequired'))
            reject(new Error(proxy.$t('modules.kb.propertyNameRequired')))
            return
          }
          const propertyNameError = validatePropertyName(p.name)
          if (propertyNameError) {
            proxy?.$message?.error(propertyNameError)
            reject(new Error(propertyNameError))
            return
          }
        }

        // 验证每个属性都有描述（与后端校验规则保持一致）
        for (const p of nodeForm.properties) {
          if (!p.desc) {
            proxy?.$message?.error(proxy.$t('modules.kb.inputRequiredField'))
            reject(new Error(proxy.$t('modules.kb.inputRequiredField')))
            return
          }
          const descLength = p.desc.length
          if (descLength < 1 || descLength > 1000) {
            const errorMsg = proxy.$t('modules.kb.propertyDescLengthInvalid', { length: descLength })
            proxy?.$message?.error(errorMsg)
            reject(new Error(errorMsg))
            return
          }
          if (p.desc.trim() === '') {
            proxy?.$message?.error(proxy.$t('modules.kb.propertyDescCannotBeWhitespace'))
            reject(new Error(proxy.$t('modules.kb.propertyDescCannotBeWhitespace')))
            return
          }
        }

        // 验证属性名称是否重复
        const propertyNames = nodeForm.properties.map((p: any) => (p.name || '').trim()).filter(Boolean)
        const duplicateNames = propertyNames.filter((name: string, index: number) => propertyNames.indexOf(name) !== index)
        if (duplicateNames.length > 0) {
          const duplicateName = duplicateNames[0]
          const errorMsg = proxy.$t('modules.kb.propertyNameDuplicate', { duplicateName })
          proxy?.$message?.error(errorMsg)
          reject(new Error(errorMsg))
          return
        }

        const payload = {
          type: 'node',
          id: props.selectedItem.id,
          data: {
            name: nodeForm.name,
            description: nodeForm.description,
            entity_type: nodeForm.name,
            properties: nodeForm.properties.map((p: any) => ({
              name: p.name,
              type: p.type,
              desc: p.desc,
              is_primary: p.is_primary,
              is_embedding: p.is_embedding,
              is_index: p.is_index
            }))
          }
        }

        emit('update-properties', payload)
        resolve(payload)
      } else {
        // 验证关系类型（与后端校验规则保持一致）
        const edgeTypeError = validateClassTypeForSave(edgeForm.edge_type, 'relationship')
        if (edgeTypeError) {
          proxy?.$message?.error(edgeTypeError)
          reject(new Error(edgeTypeError))
          return
        }

        // 验证关系描述（与后端校验规则保持一致）
        if (!edgeForm.edge_desc) {
          proxy?.$message?.error(proxy.$t('modules.kb.inputRequiredField'))
          reject(new Error(proxy.$t('modules.kb.inputRequiredField')))
          return
        }
        const edgeDescLength = edgeForm.edge_desc.length
        if (edgeDescLength < 1 || edgeDescLength > 1000) {
          const errorMsg = proxy.$t('modules.kb.relationshipDescLengthInvalid', { length: edgeDescLength })
          proxy?.$message?.error(errorMsg)
          reject(new Error(errorMsg))
          return
        }
        if (edgeForm.edge_desc.trim() === '') {
          proxy?.$message?.error(proxy.$t('modules.kb.relationshipDescCannotBeWhitespace'))
          reject(new Error(proxy.$t('modules.kb.relationshipDescCannotBeWhitespace')))
          return
        }

        // 关系属性允许为空，但如果有属性，则需要验证每个属性的字段
        if (edgeForm.properties && edgeForm.properties.length > 0) {
          // 验证每个属性都有名称（与后端校验规则保持一致）
          for (const p of edgeForm.properties) {
            if (!p.name) {
              proxy?.$message?.error(proxy.$t('modules.kb.propertyNameRequired'))
              reject(new Error(proxy.$t('modules.kb.propertyNameRequired')))
              return
            }
            const propertyNameError = validatePropertyName(p.name)
            if (propertyNameError) {
              proxy?.$message?.error(propertyNameError)
              reject(new Error(propertyNameError))
              return
            }
          }

          // 验证每个属性都有描述（与后端校验规则保持一致）
          for (const p of edgeForm.properties) {
            if (!p.desc) {
              proxy?.$message?.error(proxy.$t('modules.kb.inputRequiredField'))
              reject(new Error(proxy.$t('modules.kb.inputRequiredField')))
              return
            }
            const descLength = p.desc.length
            if (descLength < 1 || descLength > 1000) {
              const errorMsg = proxy.$t('modules.kb.propertyDescLengthInvalid', { length: descLength })
              proxy?.$message?.error(errorMsg)
              reject(new Error(errorMsg))
              return
            }
            if (p.desc.trim() === '') {
              proxy?.$message?.error(proxy.$t('modules.kb.propertyDescCannotBeWhitespace'))
              reject(new Error(proxy.$t('modules.kb.propertyDescCannotBeWhitespace')))
              return
            }
          }

          // 验证属性名称是否重复
          const propertyNames = edgeForm.properties.map((p: any) => (p.name || '').trim()).filter(Boolean)
          const duplicateNames = propertyNames.filter((name: string, index: number) => propertyNames.indexOf(name) !== index)
          if (duplicateNames.length > 0) {
            const duplicateName = duplicateNames[0]
            const errorMsg = proxy.$t('modules.kb.propertyNameDuplicate', { duplicateName })
            proxy?.$message?.error(errorMsg)
            reject(new Error(errorMsg))
            return
          }
        }

        // 关系属性
        // 方向回写 X6 连线模式
        const direction =
          edgeForm.direction === 'two-way' ? 'double' :
            edgeForm.direction === 'self-loop' ? 'self' : 'single'

        const payload = {
          type: 'edge',
          id: props.selectedItem.id,
          data: {
            edge_type: edgeForm.edge_type,
            edge_desc: edgeForm.edge_desc,
            direction,
            source_entity: edgeForm.source_entity,
            target_entity: edgeForm.target_entity,
            properties: edgeForm.properties.map((p: any) => ({
              name: p.name,
              type: p.type,
              desc: p.desc,
              is_embedding: p.is_embedding,
              is_index: p.is_index
            }))
          }
        }

        emit('update-properties', payload)
        resolve(payload)
      }
    } catch (error) {
      reject(error)
    }
  })
}

// 重置表单 - 暴露给父组件调用
const resetForm = () => {
  if (props.itemType === 'node') {
    const first = makeNewProperty()
    Object.assign(nodeForm, {
      name: '',
      description: '',
      properties: [first]
    })
  } else if (props.itemType === 'edge') {
    Object.assign(edgeForm, {
      edge_type: '',
      edge_desc: '',
      direction: 'one-way',
      source_entity: '',
      target_entity: '',
      properties: []
    })
  }
}

// 暴露方法给父组件
defineExpose({
  applyChanges,
  resetForm
})
</script>

<style scoped lang="less">
.property-panel-drawer {
  height: 100%;
  flex: 1;
  display: flex;
  flex-direction: column;
}

.panel-content {
  flex: 1;
  overflow-y: auto;
}

.entity-config,
.relationship-config {
  height: 100%;
}

// 折叠面板样式 - 使用 ghost-collapse 样式（参考 demo.vue）
:deep(.ghost-collapse) {
  padding-left: 16px;
  padding-right: 16px;

  .el-collapse-item,
  .el-collapse-item {
    margin-left: -16px !important;
  }

  .el-collapse-item__header,
  .el-collapse-item__header {
    padding: 0;
    padding-bottom: 16px;
    font-size: 14px !important;
    font-weight: bold !important;
    color: var(--el-text-color-primary, var(--rs-text));

    // 确保标题文字大小为 14px
    .el-collapse-item__header-text,
    .el-collapse-item__header-text,
    span {
      font-size: 14px !important;
      font-weight: bold !important;
    }
  }

  .el-collapse-item__content,
  .el-collapse-item__content {
    padding: 0;
  }

  // 只设置表单标签的字体样式，不影响间距
  .el-form .el-form-item__label,
  .el-form .el-form-item__label,
  .el-form .el-form-item__label,
  .el-form .el-form-item__label {
    font-size: 12px !important;
    font-weight: normal !important;

    span,
    label,
    .el-form-item__label-text,
    .el-form-item__label-text {
      font-size: 12px !important;
      font-weight: normal !important;
    }
  }
}

// 表单样式
:deep(.el-form) {
  padding-top: 24px;

  .el-form-item {
    margin-bottom: 32px;

    .el-form-item__label,
    .el-form-item__label {
      font-size: 12px !important;
      color: var(--rs-text) !important;
      font-weight: normal !important;
      line-height: 40px;
      padding-right: 12px;

      // 确保标签文字本身也是12px和非加粗
      .el-form-item__label-text,
      .el-form-item__label-text,
      span {
        font-size: 12px !important;
        font-weight: normal !important;
      }

      &::before {
        margin-right: 4px;
      }
    }

    .el-form-item__content {
      line-height: 40px;
    }

    .el-input__inner {
      height: 40px;
      line-height: 40px;
      color: var(--rs-text);

      &::placeholder {
        color: var(--rs-text-3);
      }
    }

    .el-textarea__inner {
      color: var(--rs-text);
      padding: 8px 12px;
      line-height: 1.8;

      &::placeholder {
        color: var(--rs-text-3);
      }
    }

    .el-select {
      width: 100%;
    }

    // Radio 组样式
    .el-radio-group {
      line-height: 40px;

      .el-radio {
        margin-right: 40px;

        .el-radio__label {
          font-size: 12px;
          color: var(--rs-text);
          padding-left: 10px;
        }

        .el-radio__input.is-checked {
          .el-radio__inner {
            border-color: var(--rs-primary);
            background: var(--rs-primary);
          }
        }

        .el-radio__inner {
          width: 16px;
          height: 16px;
        }
      }
    }
  }
}

.attributes-section {
  padding: 0;

  // Tabs 样式
  :deep(.prop-tabs) {
    .el-tabs__header {
      margin-bottom: 24px;

      .el-tabs__nav {
        border: 1px solid var(--rs-border);
        border-radius: 2px;

        .el-tabs__item {
          height: 40px;
          line-height: 40px;
          padding: 0 20px;
          font-size: 12px;
          color: var(--rs-text-2);
          border-right: 1px solid var(--rs-border);
          border-bottom: none;
          background: var(--rs-bg-soft);

          &:hover {
            color: var(--rs-primary);
            background: var(--rs-bg-card);
          }

          &.is-active {
            color: var(--rs-primary);
            background: var(--rs-bg-card);
            border-bottom: 2px solid var(--rs-primary);
          }

          &:last-child {
            border-right: none;
          }

          .el-icon-close {
            font-size: 12px;

            &:hover {
              background-color: var(--rs-bg-hover);
              color: var(--rs-danger);
            }
          }
        }

        .el-tabs__new-tab {
          width: 40px;
          height: 40px;
          line-height: 40px;
          font-size: 16px;
          color: var(--rs-text-2);
          border: 1px solid var(--rs-border);
          border-left: none;
          background: var(--rs-bg-soft);

          &:hover {
            color: var(--rs-primary);
            background: var(--rs-bg-card);
          }
        }
      }
    }

    .el-tabs__content {
      .el-tab-pane {
        .el-form,
        .el-form {
          // 确保属性表单中的标签也是12px和非加粗
          .el-form-item__label,
          .el-form-item__label {
            font-size: 12px !important;
            font-weight: normal !important;

            .el-form-item__label-text,
            .el-form-item__label-text,
            span {
              font-size: 12px !important;
              font-weight: normal !important;
            }
          }


          .el-form-item {
            margin-bottom: 28px;
          }
        }
      }
    }
  }
}

.attribute-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.attribute-tag {
  margin: 0;
}

.direction-display {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--rs-text-2);
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.empty-content {
  text-align: center;
  color: var(--rs-text-3);
}

.empty-content p {
  margin-top: 16px;
  font-size: 12px;
}
</style>


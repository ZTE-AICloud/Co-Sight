<template>
  <div class="fc-content">
    <div class="fc-operators-toolbar">
      <div>
        <h3>
          {{ $t('modules.workflow.operatorConfig') }}
          <span class="text-caption">{{ operatorList.length }}</span>
        </h3>
        <p class="text-caption">{{ $t('modules.workflow.operatorConfigHint') }}</p>
      </div>
      <el-dropdown v-if="!disableAddOperator" trigger="click" @command="addOperatorWithType">
        <el-button class="button-compact">
          <Plus />{{ $t('modules.workflow.addOperator') }}<ArrowDown />
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item
              v-for="item in builtinOperatorList"
              :key="item.id"
              :command="item.id"
            >
              {{ item.name }}
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>

    <OperatorSection
      v-for="(operator, index) in operatorList"
      :key="operator._key"
      :operator="operator"
      :index="index"
      :options="builtinOperatorList"
      :collapsed="operator._collapsed"
      :last="index === operatorList.length - 1"
      :single="operatorList.length === 1"
      @toggle="operator._collapsed = !operator._collapsed"
      @move="move(index, $event)"
      @remove="remove(index)"
      @change="changeOperator(operator, $event)"
    >
      <JsonEditorVue
        v-if="operator.custom || !isKnownOperator(operator)"
        v-model="operator.kwargs"
        v-bind="{ mode: 'text', stringified: false }"
        :main-menu-bar="false"
        class="ai-json-editor--drawer"
        :class="{ 'jse-theme-dark': theme === 'dark' }"
      />
      <el-form v-else label-position="top" @submit.prevent>
        <div class="fc-grid">
          <el-form-item :label="$t('kbEvaluation.llm')" required>
            <el-select
              v-model="operator.kwargs['generator-config'][0].llm"
              :placeholder="$t('kbEvaluation.llmPlaceholder')"
              :aria-label="$t('kbEvaluation.llm')"
            >
              <el-option
                v-for="item in LLMList"
                :key="item.modelValue"
                :label="item.nameZh"
                :value="item.modelValue"
              />
            </el-select>
          </el-form-item>
          <el-form-item :label="$t('app.temperature')" required>
            <el-input-number
              v-model="operator.kwargs['generator-config'][0].temperature"
              :min="0.01"
              :max="0.99"
              :step="0.01"
              :precision="2"
              :aria-label="$t('app.temperature')"
            />
          </el-form-item>
        </div>
        <el-form-item :label="$t('knowledge.knowledgeBase')" :required="!isStructKnowledgeMode">
          <el-tooltip :disabled="!isStructKnowledgeMode" placement="top" effect="light">
            <template #content>
              {{ $t('ragFlow.structKnowledgeNotSupportTip') }}
            </template>
            <el-select
              v-model="operator.kwargs['generator-config'][0].knowledge_base_name"
              multiple
              collapse-tags
              :disabled="isStructKnowledgeMode"
              :placeholder="isStructKnowledgeMode && getSelectedKbDisplayNames ? getSelectedKbDisplayNames : $t('knowledge.selectKnowledge')"
              :filterable="!isStructKnowledgeMode"
              :aria-label="$t('knowledge.knowledgeBase')"
            >
              <el-option-group
                v-for="group in allKBList"
                :key="group.label"
                :label="group.label"
              >
                <el-option
                  v-for="item in group.options"
                  :key="item.value"
                  :label="item.label"
                  :value="item.value"
                  :disabled="isStructKnowledgeMode"
                  @click="kbOptionClickHandler(item.value, operator.kwargs['generator-config'][0].knowledge_base_name)"
                />
              </el-option-group>
            </el-select>
          </el-tooltip>
          <el-alert
            v-if="!isStructKnowledgeMode"
            class="kb-alert"
            :description="$t('ragFlow.kbAlert')"
            type="info"
            :closable="false"
            show-icon
          />
        </el-form-item>
        <el-form-item :label="$t('modules.workflow.topKLabel')" required>
          <el-input-number
            v-model="operator.kwargs['generator-config'][0].top_k"
            :min="1"
            :max="100"
            :step="1"
            :precision="0"
            :aria-label="$t('modules.workflow.topKLabel')"
          />
        </el-form-item>
        <div class="fc-prompt-field">
          <div class="fc-field-label">
            <label>{{ $t('app.prompt') }}</label>
            <button
              type="button"
              class="fc-text-action text-caption"
              :aria-label="$t('modules.workflow.expandEditor')"
              @click="expandPrompt(operator, 'prompt')"
            >
              <FullScreen />{{ $t('modules.workflow.expandEditor') }}
            </button>
          </div>
          <el-input
            v-model="operator.kwargs['generator-config'][0].prompt"
            type="textarea"
            :rows="3"
            resize="vertical"
            maxlength="2048"
            :aria-label="$t('app.prompt')"
            :placeholder="$t('app.inputPrompt')"
          />
          <div class="fc-prompt-meta text-caption">
            <span>{{ $t('modules.workflow.promptMeta') }}</span>
            <span>{{ (operator.kwargs['generator-config'][0].prompt || '').length }} 字符</span>
          </div>
        </div>
        <div class="fc-prompt-field">
          <div class="fc-field-label">
            <label>{{ $t('ragFlow.no_context_prompt') }}</label>
            <button
              type="button"
              class="fc-text-action text-caption"
              :aria-label="$t('modules.workflow.expandEditor')"
              @click="expandPrompt(operator, 'no_context_prompt')"
            >
              <FullScreen />{{ $t('modules.workflow.expandEditor') }}
            </button>
          </div>
          <el-input
            v-model="operator.kwargs['generator-config'][0].no_context_prompt"
            type="textarea"
            :rows="3"
            resize="vertical"
            maxlength="2048"
            :aria-label="$t('ragFlow.no_context_prompt')"
            :placeholder="$t('ragFlow.no_context_promptPlc')"
          />
          <div class="fc-prompt-meta text-caption">
            <span>{{ $t('modules.workflow.promptMeta') }}</span>
            <span>{{ (operator.kwargs['generator-config'][0].no_context_prompt || '').length }} 字符</span>
          </div>
        </div>
      </el-form>
    </OperatorSection>

    <PromptEditorDialog
      v-model="promptOpen"
      :text="promptText"
      :subtitle="promptSubtitle"
      @confirm="applyPrompt"
    />
  </div>
</template>

<script setup>
import { computed, getCurrentInstance, onMounted, ref } from 'vue'
import { getAllKBList } from '@/features/workflow/api/workflow'
import { responsesynthesizerDefaultPrompt, defaultTopkMapper, default_RSS_no_context_prompt } from '@/features/workflow/lib/workflow'
import { KB_NAME_PREFIX } from '@/shared/constants/index.js'
import { getLLMModel } from '@/features/model/api/models'
import { useCustomOperator } from '@/features/workflow/modules/useCustomOperator.js'
import { theme } from '@/shared/lib/theme'
import { ArrowDown, FullScreen, Plus } from '@/shared/lib/icons'
import JsonEditorVue from 'json-editor-vue'
import { KB_PUBLISH_STATUS } from '@/features/knowledge-base/constants.js'
import { useKbOptions } from '@/features/knowledge-base/composables/useKbOptions'
import message from '@/shared/lib/message'
import OperatorSection from '@/features/workflow/OperatorSection.vue'
import PromptEditorDialog from '@/features/workflow/PromptEditorDialog.vue'

const { transKbsToPublishedOptions, kbOptionClickHandler } = useKbOptions()

const aipVueInstance = window.aipVueInstance
const { proxy } = getCurrentInstance()
const operatorList = ref([])
const builtinOperatorList = ref([])
const allKBList = ref([])
const LLMList = ref([])
const promptOpen = ref(false)
const promptText = ref('')
const promptSubtitle = ref('')
let promptTarget = null
let promptField = ''
let sequence = 0

const RagSimpleSummarizerOperatorId = 'RagSimpleSummarizer'

const props = defineProps({
  formData: { type: Object, default: () => ({}) },
  nodeId: { type: String }
})
const emit = defineEmits(['config-error', 'operator-count'])

const isStructKnowledgeMode = computed(() => !!aipVueInstance.$store.state.ragWorkflowIsStructKnowledge)
const disableAddOperator = computed(() => isStructKnowledgeMode.value)
const getSelectedKbDisplayNames = computed(() => {
  if (!isStructKnowledgeMode.value || !props.formData?.responsesynthesizer) {
    return ''
  }
  const kbNames = []
  props.formData.responsesynthesizer.forEach(item => {
    if (item?.kwargs?.['generator-config']?.[0]?.knowledge_base_name) {
      item.kwargs['generator-config'][0].knowledge_base_name.forEach(kbId => {
        for (const group of allKBList.value) {
          const option = group.options?.find(opt => opt.value === kbId)
          if (option) {
            kbNames.push(option.label)
            break
          }
        }
      })
    }
  })
  return kbNames.join(', ')
})

const { generateRandomUUID } = useCustomOperator(proxy, {
  props,
  type: 'response-synthesizer',
  operatorList,
  showAddOperatorPopover: ref(false)
})

function editable (operator) {
  return {
    ...JSON.parse(JSON.stringify(operator)),
    _key: `op-${++sequence}`,
    _collapsed: false
  }
}

onMounted(() => {
  const source = JSON.parse(JSON.stringify(props.formData.responsesynthesizer || []))
  source.forEach(item => {
    const config = item?.kwargs?.['generator-config']?.[0]
    if (config && !config.custom) {
      if (config.temperature === undefined || config.temperature === null) {
        config.temperature = 0.01
      }
      if (config.no_context_prompt === undefined) {
        config.no_context_prompt = default_RSS_no_context_prompt
      }
      if (config.top_k === undefined) {
        config.top_k = 8
      }
      if (!Array.isArray(config.knowledge_base_name)) {
        config.knowledge_base_name = config.knowledge_base_name ? [config.knowledge_base_name] : []
      }
    }
  })
  operatorList.value = source.map(editable)
  emit('operator-count', operatorList.value.length)
  builtinOperatorList.value = [
    { name: proxy.$t('ragFlow.RagSimpleSummarizerOperator'), id: RagSimpleSummarizerOperatorId }
  ]
  getLLMList()
  getAllKBList().then(res => {
    allKBList.value = transKbsToPublishedOptions(res)
    operatorList.value.forEach(item => {
      if (item?.custom) {
        return
      }
      const config = item.kwargs?.['generator-config']?.[0]
      if (config?.knowledge_base_name) {
        config.knowledge_base_name = config.knowledge_base_name.map(name => {
          if (typeof name === 'number' || String(name).includes(KB_NAME_PREFIX)) {
            return name
          }
          for (const group of allKBList.value) {
            if (group.status === KB_PUBLISH_STATUS.RUNNING) {
              const target = group.options.find(option => option.label === name)
              if (target) {
                return target.value
              }
            }
          }
          return name
        })
      }
    })
  })
})

async function getLLMList () {
  try {
    const res = await getLLMModel()
    LLMList.value = (Array.isArray(res) ? res : []).sort((a, b) =>
      (a.nameZh?.trim() || '').localeCompare(b.nameZh?.trim() || '')
    )
  } catch (error) {
    LLMList.value = []
  }
}

function getDefaultTopKWithType (operatorType) {
  const type = aipVueInstance.$store.state.ragWorkflowType
  if (type === 'BlendedQueryEngine') {
    return defaultTopkMapper[operatorType].BlendedQueryEngine
  }
  if (type === 'SequentialQueryEngine') {
    return defaultTopkMapper[operatorType].SequentialQueryEngine
  }
  return defaultTopkMapper[operatorType].ConditionalQueryEngine
}

function buildOperator () {
  return {
    package: 'core.rag.response_synthesizer.simple_summarizer',
    operator: RagSimpleSummarizerOperatorId,
    kwargs: {
      'generator-config': [
        {
          llm: '',
          prompt: responsesynthesizerDefaultPrompt,
          top_k: getDefaultTopKWithType(RagSimpleSummarizerOperatorId),
          knowledge_base_name: [],
          no_context_prompt: default_RSS_no_context_prompt,
          temperature: 0.01
        }
      ]
    }
  }
}

function addOperatorWithType () {
  operatorList.value.push(editable({
    id: `${props.nodeId}_${generateRandomUUID()}`,
    ...buildOperator()
  }))
  emit('operator-count', operatorList.value.length)

}

function changeOperator (operator, id) {
  if (!id || operator.operator === id) {
    return
  }
  const next = buildOperator()
  operator.operator = next.operator
  operator.package = next.package
  operator.kwargs = next.kwargs
}

function move (index, delta) {
  const target = index + delta
  if (target < 0 || target >= operatorList.value.length) {
    return
  }
  const [operator] = operatorList.value.splice(index, 1)
  operatorList.value.splice(target, 0, operator)
}

function remove (index) {
  if (operatorList.value.length <= 1) {
    return
  }
  operatorList.value.splice(index, 1)
  emit('operator-count', operatorList.value.length)
}

function isKnownOperator (operator) {
  return operator.operator === RagSimpleSummarizerOperatorId
}

function displayName (operator) {
  return operator?.custom
    ? operator.operatorName
    : proxy.$t(`ragFlow.${operator.operator}Operator`)
}

function expandPrompt (operator, field) {
  promptTarget = operator
  promptField = field
  promptText.value = operator.kwargs['generator-config'][0][field] || ''
  promptSubtitle.value = `${displayName(operator)} · ${proxy.$t('modules.workflow.fullPrompt')}`
  promptOpen.value = true
}

function applyPrompt (text) {
  if (promptTarget?.kwargs?.['generator-config']?.[0]) {
    promptTarget.kwargs['generator-config'][0][promptField] = text
  }
}

function validateAndStoreKnowledgeBaseNames () {
  // 知识库列表还没回来（或接口失败）时无法判定「库里是否还存在」，放行交给后端
  if (!allKBList.value.length) {
    return true
  }
  const notFoundKBNames = []
  operatorList.value.forEach(operator => {
    if (operator.custom) {
      return
    }
    const config = operator.kwargs?.['generator-config']?.[0]
    const kbNames = config?.knowledge_base_name || []
    kbNames.forEach(kbName => {
      const found = allKBList.value.some(group => group.options?.some(option => option.value === kbName))
      if (!found && !notFoundKBNames.includes(kbName)) {
        notFoundKBNames.push(kbName)
      }
    })
  })
  if (notFoundKBNames.length) {
    message.error(`${JSON.stringify(notFoundKBNames)}${proxy.$t('knowledge.notFoundKBNamesTip')}`)
    return false
  }
  return true
}

function validate () {
  return callback => {
    if (!validateAndStoreKnowledgeBaseNames()) {
      callback(false)
      return
    }
    for (const operator of operatorList.value) {
      if (operator.custom || !isKnownOperator(operator)) {
        continue
      }
      const config = operator.kwargs?.['generator-config']?.[0] || {}
      let error = ''
      if (!config.llm) {
        error = proxy.$t('ragFlow.llmTip')
      } else if (!Number.isFinite(Number(config.temperature)) || Number(config.temperature) < 0.01 || Number(config.temperature) > 0.99) {
        error = proxy.$t('ragFlow.temperatureTip')
      } else if (!isStructKnowledgeMode.value && !(config.knowledge_base_name || []).length) {
        error = proxy.$t('knowledge.selectKnowledge')
      } else if (!Number.isInteger(Number(config.top_k)) || Number(config.top_k) < 1 || Number(config.top_k) > 100) {
        error = proxy.$t('ragFlow.topNTip')
      } else if (!config.prompt?.trim()) {
        error = proxy.$t('app.inputPrompt')
      }
      if (error) {
        operator._collapsed = false
        emit('config-error', `${displayName(operator)}：${error}`)
        callback(false)
        return
      }
    }
    emit('config-error', '')
    callback(true)
  }
}

function sendOperatorListData () {
  const list = operatorList.value.map(({ _key, _collapsed, showConfig, ...operator }) => {
    const copy = JSON.parse(JSON.stringify(operator))
    if (copy.kwargs?.['generator-config']?.[0]?.knowledge_base_name) {
      copy.kwargs['generator-config'][0].knowledge_base_name = copy.kwargs['generator-config'][0].knowledge_base_name.map(name => `${name}`)
    }
    return copy
  })
  return { responsesynthesizer: list }
}

defineExpose({
  sendOperatorListData,
  validate
})
</script>

<style lang="less" scoped>
.ai-json-editor--drawer {
  height: 300px;
}
.kb-alert {
  padding: 0 4px;
  margin-top: 4px;
}
</style>

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
      <el-dropdown trigger="click" @command="addOperatorWithType">
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
        <el-form-item :label="$t('kbEvaluation.llm')" required>
          <el-select
            v-model="operator.kwargs.llm"
            filterable
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
        <div v-if="operator.operator === 'LLMQueryRewriter'" class="fc-history">
          <label>{{ $t('kbEvaluation.chatRecord') }}</label>
          <el-input-number
            v-model="operator.kwargs.multi_chat_limit"
            :min="0"
            :max="8"
            :step="1"
            :precision="0"
            :aria-label="$t('kbEvaluation.chatRecord')"
          />
          <span class="text-caption">{{ $t('modules.workflow.historyHint') }}</span>
        </div>
        <div class="fc-prompt-field">
          <div class="fc-field-label">
            <label>{{ $t('app.prompt') }}</label>
            <button
              type="button"
              class="fc-text-action text-caption"
              :aria-label="$t('modules.workflow.expandEditor')"
              @click="expandPrompt(operator)"
            >
              <FullScreen />{{ $t('modules.workflow.expandEditor') }}
            </button>
          </div>
          <el-input
            v-model="operator.kwargs.prompt"
            type="textarea"
            :rows="3"
            resize="vertical"
            maxlength="2048"
            :aria-label="$t('app.prompt')"
            :placeholder="$t('app.inputPrompt')"
          />
          <div class="fc-prompt-meta text-caption">
            <span>{{ $t('modules.workflow.promptMeta') }}</span>
            <span>{{ (operator.kwargs.prompt || '').length }} 字符</span>
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
import { getCurrentInstance, onMounted, ref } from 'vue'
import { getLLMModel } from '@/features/model/api/models'
import { preretrieverDefaultPrompt, LLMDefaultPrompt } from '@/features/workflow/lib/workflow'
import { useCustomOperator } from '@/features/workflow/modules/useCustomOperator.js'
import { theme } from '@/shared/lib/theme'
import { ArrowDown, FullScreen, Plus } from '@/shared/lib/icons'
import JsonEditorVue from 'json-editor-vue'
import OperatorSection from '@/features/workflow/OperatorSection.vue'
import PromptEditorDialog from '@/features/workflow/PromptEditorDialog.vue'

const { proxy } = getCurrentInstance()
const operatorList = ref([])
const builtinOperatorList = ref([])
const LLMList = ref([])
const promptOpen = ref(false)
const promptText = ref('')
const promptSubtitle = ref('')
let promptTarget = null
let sequence = 0

const LLMQueryRewriterOperatorId = 'LLMQueryRewriter'
const LLMSemanticRoutingOperatorId = 'LLMSemanticRouting'

const props = defineProps({
  formData: { type: Object, default: () => ({}) },
  nodeId: { type: String }
})
const emit = defineEmits(['config-error', 'operator-count'])

const { generateRandomUUID } = useCustomOperator(proxy, {
  props,
  type: 'pre-retriever',
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
  const source = JSON.parse(JSON.stringify(props.formData.preretriever || []))
  source.forEach(item => {
    item.kwargs = item.kwargs || {}
    if (item.kwargs.llm === undefined) {
      item.kwargs.llm = ''
    }
    if (item.kwargs.prompt === undefined) {
      item.kwargs.prompt = item.operator === LLMSemanticRoutingOperatorId ? LLMDefaultPrompt : preretrieverDefaultPrompt
    }
  })
  operatorList.value = source.map(editable)
  emit('operator-count', operatorList.value.length)
  builtinOperatorList.value = [
    { name: proxy.$t('ragFlow.LLMQueryRewriterOperator'), id: LLMQueryRewriterOperatorId },
    { name: proxy.$t('ragFlow.LLMSemanticRoutingOperator'), id: LLMSemanticRoutingOperatorId }
  ]
  getLLMList()
})

async function getLLMList () {
  try {
    const res = await getLLMModel()
    const list = Array.isArray(res) ? res : []
    LLMList.value = list.sort((a, b) => a.modelValue?.localeCompare(b.modelValue || ''))
  } catch (error) {
    LLMList.value = []
  }
}

function buildOperator (id) {
  if (id === LLMQueryRewriterOperatorId) {
    return {
      package: 'core.rag.pre_retriever.query_transform.query_rewrite',
      operator: LLMQueryRewriterOperatorId,
      kwargs: {
        llm: '',
        prompt: preretrieverDefaultPrompt,
        multi_chat_limit: 0
      }
    }
  }
  return {
    package: 'core.rag.pre_retriever.query_selector.query_routing',
    operator: LLMSemanticRoutingOperatorId,
    kwargs: {
      llm: '',
      prompt: LLMDefaultPrompt
    }
  }
}

function addOperatorWithType (id) {
  const operator = buildOperator(id)
  operatorList.value.push(editable({
    id: `${props.nodeId}_${generateRandomUUID()}`,
    ...operator
  }))
  emit('operator-count', operatorList.value.length)

}

function changeOperator (operator, id) {
  if (!id || operator.operator === id) {
    return
  }
  const next = buildOperator(id)
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

function expandPrompt (operator) {
  promptTarget = operator
  promptText.value = operator.kwargs?.prompt || ''
  promptSubtitle.value = `${displayName(operator)} · ${proxy.$t('modules.workflow.fullPrompt')}`
  promptOpen.value = true
}

function applyPrompt (text) {
  if (promptTarget?.kwargs) {
    promptTarget.kwargs.prompt = text
  }
}

function displayName (operator) {
  return operator?.custom
    ? operator.operatorName
    : proxy.$t(`ragFlow.${operator.operator}Operator`)
}

function isKnownOperator (operator) {
  return [LLMQueryRewriterOperatorId, LLMSemanticRoutingOperatorId].includes(operator.operator)
}

function validateOne (operator) {
  if (operator.custom || !isKnownOperator(operator)) {
    return ''
  }
  if (!operator.kwargs?.llm) {
    return proxy.$t('ragFlow.llmTip')
  }
  if (!operator.kwargs?.prompt?.trim()) {
    return proxy.$t('app.inputPrompt')
  }
  if (operator.operator === 'LLMQueryRewriter') {
    const history = operator.kwargs.multi_chat_limit
    if (history !== undefined && (!Number.isInteger(Number(history)) || Number(history) < 0 || Number(history) > 8)) {
      return proxy.$t('modules.workflow.historyRange')
    }
  }
  return ''
}

function validate () {
  return callback => {
    for (let index = 0; index < operatorList.value.length; index++) {
      const operator = operatorList.value[index]
      const error = validateOne(operator)
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
  const list = operatorList.value.map(({ _key, _collapsed, showConfig, ...operator }) => ({
    ...operator,
    kwargs: { ...(operator.kwargs || {}) }
  }))
  return { preretriever: list }
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
</style>

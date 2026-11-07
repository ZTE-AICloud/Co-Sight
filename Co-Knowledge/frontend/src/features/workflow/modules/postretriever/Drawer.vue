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
        <div class="fc-grid">
          <el-form-item v-if="operator.operator === 'LLMReranker'" :label="$t('kbEvaluation.llm')" required>
            <el-select
              v-model="operator.kwargs.llm"
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
          <el-form-item
            v-if="isExternalModelReranker(operator)"
            :label="$t('modules.workflow.rerankModelLabel')"
          >
            <el-select
              v-model="operator.kwargs.model"
              :placeholder="followDefaultLabel"
              :aria-label="$t('modules.workflow.rerankModelLabel')"
            >
              <el-option :label="followDefaultLabel" value="" />
              <el-option
                v-for="item in RerankModelList"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item :label="$t('modules.workflow.topNLabel')" required>
            <el-input-number
              v-model="operator.kwargs.top_n"
              :min="1"
              :max="20"
              :step="1"
              :precision="0"
              :aria-label="$t('modules.workflow.topNLabel')"
            />
          </el-form-item>
          <el-form-item
            v-if="isExternalModelReranker(operator)"
            :label="$t('ragFlow.score')"
          >
            <el-input-number
              v-model="operator.kwargs.score"
              :min="-100"
              :max="100"
              :step="0.01"
              :precision="2"
              :aria-label="$t('ragFlow.score')"
            />
          </el-form-item>
        </div>
        <p v-if="['相似度过滤', 'SimilarityFilter', '去重', 'Dedup'].includes(operator.operator)" class="text-secondary fc-no-params">
          {{ $t('modules.workflow.noParams') }}
        </p>
      </el-form>
    </OperatorSection>
  </div>
</template>

<script setup>
import { computed, getCurrentInstance, onMounted, ref } from 'vue'
import { getLLMModel, getRerankModels } from '@/features/model/api/models'
import { defaultTopkMapper, default_BGM_score } from '@/features/workflow/lib/workflow'
import { useCustomOperator } from '@/features/workflow/modules/useCustomOperator.js'
import { theme } from '@/shared/lib/theme'
import { ArrowDown, Plus } from '@/shared/lib/icons'
import JsonEditorVue from 'json-editor-vue'
import OperatorSection from '@/features/workflow/OperatorSection.vue'
import {
  EXTERNAL_MODEL_RERANKER_OPERATOR,
  isExternalModelReranker
} from '@/features/workflow/lib/externalModelReranker'

const aipVueInstance = window.aipVueInstance
const { proxy } = getCurrentInstance()
const operatorList = ref([])
const builtinOperatorList = ref([])
const LLMList = ref([])
const RerankModelList = ref([])
let sequence = 0

const LLMRerankerOperatorId = 'LLMReranker'

const props = defineProps({
  formData: { type: Object, default: () => ({}) },
  nodeId: { type: String }
})
const emit = defineEmits(['config-error', 'operator-count'])

const { generateRandomUUID } = useCustomOperator(proxy, {
  props,
  type: 'post-retriever',
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
  const source = JSON.parse(JSON.stringify(props.formData.postretriever || []))
  source.forEach(item => {
    item.kwargs = item.kwargs || {}
    if (item.kwargs.top_n === undefined) {
      item.kwargs.top_n = 5
    }
    // 空串 = 跟随部署默认；下拉才会选中「跟随部署默认」
    if (isExternalModelReranker(item) && item.kwargs.model === undefined) {
      item.kwargs.model = ''
    }
  })
  operatorList.value = source.map(editable)
  emit('operator-count', operatorList.value.length)
  builtinOperatorList.value = [
    { name: proxy.$t('ragFlow.LLMRerankerOperator'), id: LLMRerankerOperatorId },
    { name: proxy.$t('ragFlow.ExternalModelRerankerOperator'), id: EXTERNAL_MODEL_RERANKER_OPERATOR }
  ]
  getLLMList()
  getRerankModelList()
})

async function getLLMList () {
  try {
    const res = await getLLMModel()
    LLMList.value = Array.isArray(res) ? res : []
  } catch (error) {
    LLMList.value = []
  }
}

async function getRerankModelList () {
  try {
    const res = await getRerankModels()
    RerankModelList.value = Array.isArray(res) ? res : []
  } catch (error) {
    // 接口失败时保留空清单：模型下拉仍可留空（= 跟随部署默认），保存不被卡住
    RerankModelList.value = []
  }
}

// 「跟随部署默认」的展示文案：带上默认行的名字，避免用户以为这里没配模型
const followDefaultLabel = computed(() => {
  const fallback = RerankModelList.value.find(item => item.isDefault)
  return fallback
    ? proxy.$t('modules.workflow.rerankModelFollowDefault', { model: fallback.label })
    : proxy.$t('modules.workflow.rerankModelFollowDefaultEmpty')
})

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

function buildOperator (id) {
  if (id === LLMRerankerOperatorId) {
    return {
      package: 'core.rag.post_retriever.llm_reranker',
      operator: LLMRerankerOperatorId,
      kwargs: {
        llm: '',
        top_n: getDefaultTopKWithType(LLMRerankerOperatorId)
      }
    }
  }
  return {
    package: 'core.rag.post_retriever.external_model_reranker',
    operator: EXTERNAL_MODEL_RERANKER_OPERATOR,
    kwargs: {
      model: '',
      top_n: getDefaultTopKWithType(EXTERNAL_MODEL_RERANKER_OPERATOR),
      score: default_BGM_score
    }
  }
}

function addOperatorWithType (id) {
  operatorList.value.push(editable({
    id: `${props.nodeId}_${generateRandomUUID()}`,
    ...buildOperator(id)
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

function isKnownOperator (operator) {
  return operator.operator === LLMRerankerOperatorId || isExternalModelReranker(operator)
}

function displayName (operator) {
  return operator?.custom
    ? operator.operatorName
    : proxy.$t(`ragFlow.${operator.operator}Operator`)
}

function validate () {
  return callback => {
    for (const operator of operatorList.value) {
      if (operator.custom || !isKnownOperator(operator)) {
        continue
      }
      if (operator.operator === 'LLMReranker' && !operator.kwargs?.llm) {
        operator._collapsed = false
        emit('config-error', `${displayName(operator)}：${proxy.$t('kbEvaluation.llmPlaceholder')}`)
        callback(false)
        return
      }
      const topN = Number(operator.kwargs?.top_n)
      if (!Number.isInteger(topN) || topN < 1 || topN > 20) {
        operator._collapsed = false
        emit('config-error', `${displayName(operator)}：${proxy.$t('ragFlow.topKTip')}`)
        callback(false)
        return
      }
    }
    emit('config-error', '')
    callback(true)
  }
}

function sendOperatorListData () {
  // 这三个是抽屉自己的 UI 字段，提交前刻意剥离；解构出来的变量不参与计算。
  // eslint-disable-next-line no-unused-vars
  const list = operatorList.value.map(({ _key, _collapsed, showConfig, ...operator }) => ({
    ...operator,
    kwargs: { ...(operator.kwargs || {}) }
  }))
  return { postretriever: list }
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

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
        <div v-if="operatorKind(operator)" class="fc-source-context text-caption">
          <span :class="['tag-soft', operatorKind(operator).tone]">
            <component :is="operatorKind(operator).icon" />{{ $t(operatorKind(operator).labelKey) }}
          </span>
          <span>{{ $t('modules.workflow.operatorSourceOnly', { operator: displayName(operator), kind: $t(operatorKind(operator).labelKey) }) }}</span>
        </div>
        <p v-if="operator._sourceNotice && !operatorHasSources(operator)" class="fc-source-notice text-caption" role="status">
          {{ operator._sourceNotice }}
        </p>
        <template v-if="operator.operator === 'VectorRetriever'">
          <div class="fc-grid">
            <el-form-item :label="$t('knowledge.kbRetrieveStrategy')" required>
              <el-select
                v-model="operator.kwargs.strategy"
                :aria-label="$t('knowledge.kbRetrieveStrategy')"
              >
                <el-option
                  v-for="item in kbRetrieveStrategyList"
                  :key="item.value"
                  :label="item.name"
                  :value="item.value"
                />
              </el-select>
            </el-form-item>
            <el-form-item :label="$t('ragFlow.vectorModel')" required>
              <el-select
                v-model="operator.kwargs.embedding"
                :placeholder="$t('ragFlow.vectorModelPlc')"
                :aria-label="$t('ragFlow.vectorModel')"
              >
                <el-option
                  v-for="item in vectorModelOptionsFor()"
                  :key="item.modelId || item.value"
                  :label="item.label"
                  :value="item.value"
                />
              </el-select>
            </el-form-item>
          </div>
          <div class="fc-source-list">
            <section
              v-for="(item, kbIndex) in operator.kwargs.knowledge_info_list"
              :key="kbIndex"
              class="fc-source"
            >
              <div class="fc-source-header">
                <span>
                  {{ $t('modules.workflow.sourceIndex', { index: kbIndex + 1 }) }}
                </span>
                <button
                  v-if="operator.kwargs.knowledge_info_list.length > 1"
                  type="button"
                  class="fc-text-action fc-delete text-caption"
                  :aria-label="$t('modules.workflow.removeSource')"
                  @click="deleteKb(operator.kwargs.knowledge_info_list, kbIndex)"
                >
                  <Delete />{{ $t('public.delete') }}
                </button>
              </div>
              <el-form-item :label="$t('knowledge.knowledgeBase')" required>
                <el-select
                  v-model="item.knowledge_base_name"
                  multiple
                  filterable
                  :placeholder="$t('knowledge.selectKnowledge')"
                  :aria-label="$t('knowledge.knowledgeBase')"
                >
                  <el-option-group
                    v-for="group in (kbListWithModel[operator.kwargs.embedding] || [])"
                    :key="group.label"
                    :label="group.label"
                  >
                    <el-option
                      v-for="option in group.options.filter(opt => !opt.value.includes('graph'))"
                      :key="option.value"
                      :label="option.label"
                      :value="option.value"
                      @click="kbOptionClickHandler(option.value, item.knowledge_base_name)"
                    />
                  </el-option-group>
                </el-select>
              </el-form-item>
              <div class="fc-grid">
                <el-form-item :label="$t('modules.workflow.topKLabel')" required>
                  <el-input-number
                    v-model="item.top_k"
                    :min="1"
                    :max="80"
                    :step="1"
                    :precision="0"
                    :aria-label="$t('modules.workflow.topKLabel')"
                  />
                </el-form-item>
                <el-form-item
                  v-if="operator.kwargs.strategy !== 0"
                  :label="$t('knowledge.priority')"
                >
                  <el-input-number
                    v-model="item.priority"
                    :min="0"
                    :max="10"
                    :step="1"
                    :precision="0"
                    :aria-label="$t('knowledge.priority')"
                  />
                </el-form-item>
                <el-form-item :label="$t('modules.workflow.minScore')">
                  <el-input-number
                    v-model="item.score"
                    :min="0"
                    :max="1"
                    :step="0.01"
                    :precision="2"
                    :aria-label="$t('modules.workflow.minScore')"
                  />
                </el-form-item>
              </div>
            </section>
            <el-button
              v-if="operator.kwargs.knowledge_info_list.length < 50"
              class="button-compact"
              @click="addKb(operator.kwargs.knowledge_info_list)"
            >
              <Plus />{{ $t('modules.workflow.addSource') }}
            </el-button>
          </div>
        </template>

        <template v-else-if="operator.operator === 'KeywordRetriever'">
          <el-form-item :label="$t('knowledge.knowledgeBase')" required>
            <el-select
              v-model="operator.kwargs.knowledge_base_name"
              multiple
              filterable
              :placeholder="$t('knowledge.selectKnowledge')"
              :aria-label="$t('knowledge.knowledgeBase')"
            >
              <el-option-group
                v-for="group in allKBList"
                :key="group.label"
                :label="group.label"
              >
                <el-option
                  v-for="option in group.options.filter(opt => !opt.value.includes('graph'))"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                  @click="kbOptionClickHandler(option.value, operator.kwargs.knowledge_base_name)"
                />
              </el-option-group>
            </el-select>
          </el-form-item>
          <el-form-item :label="$t('modules.workflow.topKLabel')" required>
            <el-input-number
              v-model="operator.kwargs.top_k"
              :min="1"
              :max="80"
              :step="1"
              :precision="0"
              :aria-label="$t('modules.workflow.topKLabel')"
            />
          </el-form-item>
        </template>

        <template v-else-if="operator.operator === 'KnowledgeGraphRetriever'">
          <el-form-item :label="$t('knowledge.knowledgeBase')" required>
            <el-select
              v-model="operator.kwargs.knowledge_base_name"
              multiple
              filterable
              :placeholder="$t('knowledge.selectKnowledge')"
              :aria-label="$t('knowledge.knowledgeBase')"
            >
              <el-option-group
                v-for="group in allKBList"
                :key="group.label"
                :label="group.label"
              >
                <el-option
                  v-for="option in group.options.filter(opt => opt.value.includes('graph'))"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                  @click="kbOptionClickHandler(option.value, operator.kwargs.knowledge_base_name)"
                />
              </el-option-group>
            </el-select>
          </el-form-item>
          <div class="fc-grid">
            <el-form-item :label="$t('ragFlow.vectorModel')">
              <el-input
                :model-value="operator.kwargs.embedding"
                disabled
                :placeholder="$t('ragFlow.vectorModelPlc')"
              />
            </el-form-item>
            <el-form-item :label="$t('modules.workflow.topKLabel')" required>
              <el-input-number
                v-model="operator.kwargs.top_k"
                :min="1"
                :max="80"
                :step="1"
                :precision="0"
                :aria-label="$t('modules.workflow.topKLabel')"
              />
            </el-form-item>
            <el-form-item :label="$t('knowledge.depth')">
              <el-input-number
                v-model="operator.kwargs.depth"
                :min="1"
                :max="10"
                :step="1"
                :precision="0"
                :aria-label="$t('knowledge.depth')"
              />
            </el-form-item>
            <el-form-item :label="$t('modules.workflow.minScore')">
              <el-input-number
                v-model="operator.kwargs.score"
                :min="0"
                :max="1"
                :step="0.01"
                :precision="2"
                :aria-label="$t('modules.workflow.minScore')"
              />
            </el-form-item>
          </div>
          <el-form-item :label="$t('modules.workflow.includeEdgeFacts')">
            <div class="fc-edge-facts">
              <el-switch
                v-model="operator.kwargs.include_edge_facts"
                :aria-label="$t('modules.workflow.includeEdgeFacts')"
              />
              <span class="fc-edge-facts-hint">{{ $t('modules.workflow.includeEdgeFactsHint') }}</span>
            </div>
          </el-form-item>
        </template>

        <template v-else>
          <el-form-item :label="$t('modules.workflow.topKLabel')" required>
            <el-input-number
              v-model="operator.kwargs.top_k"
              :min="1"
              :max="80"
              :step="1"
              :precision="0"
              :aria-label="$t('modules.workflow.topKLabel')"
            />
          </el-form-item>
        </template>

        <el-form-item :label="$t('ragFlow.operatorDesc')">
          <el-input
            v-model.trim="operator.kwargs.desc_info"
            type="textarea"
            :rows="3"
            maxlength="512"
            :placeholder="$t('ragFlow.operatorDescPlacehodler')"
            :aria-label="$t('ragFlow.operatorDesc')"
          />
        </el-form-item>
      </el-form>
    </OperatorSection>
  </div>
</template>

<script setup>
import { computed, getCurrentInstance, onMounted, ref } from 'vue'
import { getModelList } from '@/features/model/api/models'
import { getAllKBList } from '@/features/workflow/api/workflow'
import { defaultTopkMapper } from '@/features/workflow/lib/workflow'
import { uniqueKbNames } from '@/features/workflow/lib/kbSelection'
import { KB_NAME_PREFIX } from '@/shared/constants/index.js'
import { useCustomOperator } from '@/features/workflow/modules/useCustomOperator.js'
import JsonEditorVue from 'json-editor-vue'
import { theme } from '@/shared/lib/theme'
import { ArrowDown, Delete, Plus, Document, Share, Coin } from '@/shared/lib/icons'
import { operatorSourceMismatch, sourceKindMeta, sourceKindOfOperator } from '@/features/workflow/lib/retrievalSources'
import { KB_PUBLISH_STATUS, KB_OPTION_KEY_HYPHEN } from '@/features/knowledge-base/constants.js'
import { useKbOptions } from '@/features/knowledge-base/composables/useKbOptions.ts'
import message from '@/shared/lib/message'
import { checkEnvironmentApi } from '@/features/knowledge-base/api/kbaseApi.js'
import OperatorSection from '@/features/workflow/OperatorSection.vue'

const { transKbsToPublishedOptions, kbOptionClickHandler } = useKbOptions()

const aipVueInstance = window.aipVueInstance
const { proxy } = getCurrentInstance()
const operatorList = ref([])
const builtinOperatorList = ref([])
let sequence = 0

const VectorRetrieverOperatorId = 'VectorRetriever'
const KeywordRetrieverOperatorId = 'KeywordRetriever'
const KnowledgeGraphRetrieverOperatorId = 'KnowledgeGraphRetriever'
const FusionRetrieverOperatorId = 'FusionRetriever'
const SqlOperatorNames = ['SqlRetriever', 'SqlExecutor', 'SqlRetrieverOperator', 'SqlExecutorOperator']

const kbRetrieveStrategyList = ref([])
const allKBList = ref([])
const kbListWithModel = ref({})
const vectorModelList = ref([])
const showKnowledgeGraphRetriever = ref(true)

const props = defineProps({
  formData: { type: Object, default: () => ({}) },
  nodeId: { type: String }
})
const emit = defineEmits(['config-error', 'operator-count'])

const disableAddOperator = computed(() => operatorList.value.some(item => SqlOperatorNames.includes(item?.operator)))

const { generateRandomUUID } = useCustomOperator(proxy, {
  props,
  type: 'retriever',
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

function updateBuiltinOperatorList () {
  const baseList = [
    { name: proxy.$t('ragFlow.VectorRetrieverOperator'), id: VectorRetrieverOperatorId },
    { name: proxy.$t('ragFlow.KeywordRetrieverOperator'), id: KeywordRetrieverOperatorId },
    { name: proxy.$t('ragFlow.KnowledgeGraphRetrieverOperator'), id: KnowledgeGraphRetrieverOperatorId },
    { name: proxy.$t('ragFlow.FusionRetrieverOperator'), id: FusionRetrieverOperatorId }
  ]
  builtinOperatorList.value = showKnowledgeGraphRetriever.value
    ? baseList
    : baseList.filter(item => item.id !== KnowledgeGraphRetrieverOperatorId)
}

function handleDeploymentEnvironmentCheck (res) {
  const deployedBy = res?.DEPLOYED_BY || res?.deployedBy
  // okiv5 部署没有图谱检索能力
  showKnowledgeGraphRetriever.value = deployedBy !== 'okiv5'
  updateBuiltinOperatorList()
}

function checkDeploymentEnvironment () {
  return checkEnvironmentApi()
    .then(handleDeploymentEnvironmentCheck)
    .catch(() => {
      showKnowledgeGraphRetriever.value = true
      updateBuiltinOperatorList()
    })
}

onMounted(() => {
  const source = JSON.parse(JSON.stringify(props.formData.retriever || []))
  source.forEach(item => {
    item.kwargs = item.kwargs || {}
    if (item.operator === VectorRetrieverOperatorId) {
      if (!Array.isArray(item.kwargs.knowledge_info_list) || !item.kwargs.knowledge_info_list.length) {
        item.kwargs.knowledge_info_list = [{ knowledge_base_name: [], priority: 10, top_k: 8, score: 0.3 }]
      }
      item.kwargs.knowledge_info_list.forEach(kb => {
        if (!kb.priority) {
          kb.priority = undefined
        }
        if (!Array.isArray(kb.knowledge_base_name)) {
          kb.knowledge_base_name = kb.knowledge_base_name ? [kb.knowledge_base_name] : []
        }
        // 历史配置里同一个库会重复出现：不去重的话标签的 × 只删掉一份，看起来像删不掉
        kb.knowledge_base_name = uniqueKbNames(kb.knowledge_base_name)
        if (kb.top_k === undefined) {
          kb.top_k = 8
        }
        if (kb.score === undefined) {
          kb.score = 0.3
        }
      })
    }
    if (item.operator === KeywordRetrieverOperatorId || item.operator === FusionRetrieverOperatorId) {
      if (item.operator === KeywordRetrieverOperatorId) {
        if (!Array.isArray(item.kwargs.knowledge_base_name)) {
          item.kwargs.knowledge_base_name = item.kwargs.knowledge_base_name ? [item.kwargs.knowledge_base_name] : []
        }
        item.kwargs.knowledge_base_name = uniqueKbNames(item.kwargs.knowledge_base_name)
      }
      if (item.kwargs.top_k === undefined) {
        item.kwargs.top_k = 8
      }
    }
    if (item.operator === KnowledgeGraphRetrieverOperatorId) {
      if (typeof item.kwargs.knowledge_base_name === 'string') {
        item.kwargs.knowledge_base_name = item.kwargs.knowledge_base_name ? [item.kwargs.knowledge_base_name] : []
      } else if (!Array.isArray(item.kwargs.knowledge_base_name)) {
        item.kwargs.knowledge_base_name = []
      }
      item.kwargs.knowledge_base_name = uniqueKbNames(item.kwargs.knowledge_base_name)
      if (!Object.prototype.hasOwnProperty.call(item.kwargs, 'depth')) {
        item.kwargs.depth = 1
      }
      if (!Object.prototype.hasOwnProperty.call(item.kwargs, 'score')) {
        item.kwargs.score = 0
      }
      if (!Object.prototype.hasOwnProperty.call(item.kwargs, 'embedding')) {
        item.kwargs.embedding = ''
      }
    }
  })
  operatorList.value = source.map(editable)
  emit('operator-count', operatorList.value.length)

  kbRetrieveStrategyList.value = [
    { name: proxy.$t('knowledge.retrieveAll'), value: 0 },
    { name: proxy.$t('knowledge.retrieveWithPriority'), value: 1 }
  ]
  updateBuiltinOperatorList()
  checkDeploymentEnvironment()

  getModelList().then(res => {
    if (isObjectArray(res)) {
      vectorModelList.value = res
    } else if (isStringArray(res)) {
      vectorModelList.value = res.map(item => ({ modelName: item }))
    }
    vectorModelList.value.forEach(item => {
      getAllKBList({ embedding: item.modelName }).then(response => {
        kbListWithModel.value[item.modelName] = transKbsToPublishedOptions(response)
        resolveVectorKbNames()
      }).catch(() => {})
    })
  })

  getAllKBList().then(res => {
    allKBList.value = transKbsToPublishedOptions(res)
    resolveKeywordKbNames()
  })
})

function isObjectArray (arr) {
  return Array.isArray(arr) && arr.every(item => typeof item === 'object')
}

function isStringArray (arr) {
  return Array.isArray(arr) && arr.every(item => typeof item === 'string')
}

function resolveVectorKbNames () {
  operatorList.value.forEach(item => {
    if (item.operator !== VectorRetrieverOperatorId || !item.kwargs?.knowledge_info_list) {
      return
    }
    item.kwargs.knowledge_info_list.forEach(kb => {
      // 两个不同的存储名（例如旧名称 + tableName）可能解析到同一个库，映射后重新去重
      kb.knowledge_base_name = uniqueKbNames(
        (kb.knowledge_base_name || []).map(name => resolveKbName(name, kbListWithModel.value[item.kwargs.embedding] || [])))
    })
  })
}

function resolveKeywordKbNames () {
  operatorList.value.forEach(item => {
    if (item.operator === KeywordRetrieverOperatorId && item.kwargs?.knowledge_base_name) {
      item.kwargs.knowledge_base_name = uniqueKbNames(
        item.kwargs.knowledge_base_name.map(name => resolveKbName(name, allKBList.value)))
    }
  })
}

function resolveKbName (name, groups) {
  if (typeof name === 'number' || String(name).includes(KB_NAME_PREFIX)) {
    return name
  }
  for (const group of groups) {
    if (group.status === KB_PUBLISH_STATUS.RUNNING) {
      const target = group.options.find(option => option.label === name)
      if (target) {
        return target.value
      }
    }
  }
  return name
}

function vectorModelOptionsFor () {
  const list = vectorModelList.value || []
  const options = list.filter(model => model?.modelName).map(model => ({
    modelId: model.modelId,
    label: model.modelName,
    value: model.modelName
  }))
  return options
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

function buildOperator (id) {
  if (id === VectorRetrieverOperatorId) {
    return {
      package: 'core.rag.retriever.vector_retriever',
      operator: VectorRetrieverOperatorId,
      kwargs: {
        strategy: 0,
        knowledge_info_list: [{
          knowledge_base_name: [],
          priority: 10,
          top_k: getDefaultTopKWithType(VectorRetrieverOperatorId),
          score: 0.3
        }],
        desc_info: ''
      }
    }
  }
  if (id === KeywordRetrieverOperatorId) {
    return {
      package: 'core.rag.retriever.keyword_retriever',
      operator: KeywordRetrieverOperatorId,
      kwargs: {
        knowledge_base_name: [],
        top_k: getDefaultTopKWithType(KeywordRetrieverOperatorId),
        desc_info: ''
      }
    }
  }
  if (id === KnowledgeGraphRetrieverOperatorId) {
    return {
      package: 'core.rag.retriever.knowledgegraph_retriever',
      operator: KnowledgeGraphRetrieverOperatorId,
      kwargs: {
        knowledge_base_name: [],
        top_k: 30,
        depth: 1,
        score: 0,
        desc_info: '',
        embedding: vectorModelList.value[0]?.modelName || ''
      }
    }
  }
  return {
    package: 'core.rag.retriever.fusion_retriever',
    operator: FusionRetrieverOperatorId,
    kwargs: {
      top_k: getDefaultTopKWithType(FusionRetrieverOperatorId),
      desc_info: ''
    }
  }
}

const SOURCE_KIND_ICONS = { knowledge: Document, graph: Share, database: Coin }

/** 算子对应的来源类型（文档 / 图谱 / 数据库）；融合检索等没有来源的算子返回 null。 */
function operatorKind (operator) {
  const kind = sourceKindOfOperator(operator)
  if (!kind) {
    return null
  }
  return { ...sourceKindMeta(kind), icon: SOURCE_KIND_ICONS[kind] || Document }
}

function operatorHasSources (operator) {
  return extractKbNamesFromOperator(operator).filter(Boolean).length > 0
}

/** 新增算子时沿用同类算子已选的库：空白重选一遍没有意义，也不容易选错。 */
function seedOperatorSources (operator) {
  const kind = sourceKindOfOperator(operator.operator)
  if (!kind) {
    return
  }
  const peer = operatorList.value.find(item => (
    sourceKindOfOperator(item.operator) === kind && operatorHasSources(item)
  ))
  if (!peer) {
    return
  }
  const names = [...extractKbNamesFromOperator(peer)]
  if (operator.operator === VectorRetrieverOperatorId) {
    const source = peer.operator === VectorRetrieverOperatorId ? peer : null
    if (source?.kwargs) {
      operator.kwargs.embedding = source.kwargs.embedding
      operator.kwargs.strategy = source.kwargs.strategy
    }
    operator.kwargs.knowledge_info_list[0].knowledge_base_name = names
  } else if (operator.operator === KeywordRetrieverOperatorId) {
    operator.kwargs.knowledge_base_name = names
  } else if (operator.operator === KnowledgeGraphRetrieverOperatorId) {
    const source = peer.operator === KnowledgeGraphRetrieverOperatorId ? peer : null
    if (source?.kwargs) {
      operator.kwargs.embedding = source.kwargs.embedding
    }
    operator.kwargs.knowledge_base_name = names
  }
}

function addOperatorWithType (id) {
  const next = buildOperator(id)
  seedOperatorSources(next)
  operatorList.value.push(editable({
    id: `${props.nodeId}_${generateRandomUUID()}`,
    ...next
  }))
  emit('operator-count', operatorList.value.length)

}

function changeOperator (operator, id) {
  if (!id || operator.operator === id) {
    return
  }
  const hadSources = operatorHasSources(operator)
  const next = buildOperator(id)
  operator.operator = next.operator
  operator.package = next.package
  operator.kwargs = next.kwargs
  // 换了算子就是换了来源类型：旧库已清空，提示用户重新选择（选中后提示自动消失）
  const kind = sourceKindOfOperator(id)
  operator._sourceNotice = hadSources && kind
    ? proxy.$t('modules.workflow.sourceSwitchedNotice', { kind: proxy.$t(sourceKindMeta(kind).labelKey) })
    : ''
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

function addKb (list) {
  list.push({
    knowledge_base_name: [],
    priority: 10,
    top_k: 8,
    score: 0.3
  })
}

function deleteKb (list, index) {
  list.splice(index, 1)
}

function isKnownOperator (operator) {
  return [VectorRetrieverOperatorId, KeywordRetrieverOperatorId, KnowledgeGraphRetrieverOperatorId, FusionRetrieverOperatorId].includes(operator.operator)
}

function displayName (operator) {
  return operator?.custom
    ? operator.operatorName
    : proxy.$t(`ragFlow.${operator.operator}Operator`)
}

function removeKbNameSuffix (kbName) {
  if (typeof kbName === 'string' && kbName.includes(KB_OPTION_KEY_HYPHEN)) {
    return kbName.split(KB_OPTION_KEY_HYPHEN)[0]
  }
  return kbName
}

function processKbNameArray (names) {
  return (names || []).map(name => removeKbNameSuffix(String(name)))
}

function sendOperatorListData () {
  operatorList.value.forEach(item => {
    if (item.operator === KnowledgeGraphRetrieverOperatorId) {
      if (typeof item.kwargs.knowledge_base_name === 'string') {
        item.kwargs.knowledge_base_name = item.kwargs.knowledge_base_name
          .split(',')
          .map(name => removeKbNameSuffix(name.trim()))
      } else if (Array.isArray(item.kwargs.knowledge_base_name)) {
        item.kwargs.knowledge_base_name = processKbNameArray(item.kwargs.knowledge_base_name)
      }
      // 只收敛数组形态：奇形怪状的老值原样交给后端，别在这里静默清空
      if (Array.isArray(item.kwargs.knowledge_base_name)) {
        item.kwargs.knowledge_base_name = uniqueKbNames(item.kwargs.knowledge_base_name)
      }
    } else if (item.operator === VectorRetrieverOperatorId) {
      ;(item.kwargs.knowledge_info_list || []).forEach(listItem => {
        Reflect.deleteProperty(listItem, 'showConfig')
        if (!listItem.priority) {
          listItem.priority = 0
        }
        listItem.knowledge_base_name = uniqueKbNames(processKbNameArray(listItem.knowledge_base_name))
      })
    } else if (item.operator === KeywordRetrieverOperatorId) {
      item.kwargs.knowledge_base_name = uniqueKbNames(processKbNameArray(item.kwargs.knowledge_base_name))
    }
  })
  const list = operatorList.value.map(operator => {
    const copy = JSON.parse(JSON.stringify(operator))
    // 抽屉内部状态不落库（_key/_collapsed 只是渲染用，提示在选中来源后自动消失）
    ;['_key', '_collapsed', 'showConfig', '_sourceNotice'].forEach(key => Reflect.deleteProperty(copy, key))
    if (copy.kwargs?.knowledge_info_list) {
      copy.kwargs.knowledge_info_list.forEach(item => Reflect.deleteProperty(item, 'showConfig'))
    }
    return copy
  })
  return { retriever: list }
}

function extractTableName (kbName) {
  return kbName.includes(KB_OPTION_KEY_HYPHEN) ? kbName.split(KB_OPTION_KEY_HYPHEN)[0] : kbName
}

function extractKbNamesFromOperator (operator) {
  if (operator.operator === 'VectorRetriever') {
    return (operator.kwargs.knowledge_info_list || []).flatMap(info => info.knowledge_base_name || [])
  }
  if (operator.operator === 'KeywordRetriever' || operator.operator === 'KnowledgeGraphRetriever') {
    const names = operator.kwargs.knowledge_base_name
    return typeof names === 'string' ? [names] : (names || [])
  }
  return []
}

function findKbInList (kbName, kbList) {
  const tableName = extractTableName(kbName)
  return (kbList || []).some(group => (group.options || []).some(option =>
    option.value === kbName || extractTableName(option.value) === tableName
  ))
}

function validateKbName (kbName, operator) {
  if (!kbName) {
    return true
  }
  if (operator.operator === 'VectorRetriever') {
    const embedding = operator.kwargs.embedding
    if (embedding && kbListWithModel.value[embedding]) {
      return findKbInList(kbName, kbListWithModel.value[embedding])
    }
    return false
  }
  return findKbInList(kbName, allKBList.value)
}

function validateAndStoreKnowledgeBaseNames () {
  // 模型/知识库列表尚未加载（或接口失败）时无法判定，放行交给后端
  if (!vectorModelList.value.length && !allKBList.value.length && !Object.keys(kbListWithModel.value).length) {
    return true
  }
  const notFoundKBNames = []
  const missingModels = []
  const modelMismatchNames = []
  operatorList.value.forEach(operator => {
    if (operator.custom || !isKnownOperator(operator) || operator.operator === 'FusionRetriever') {
      return
    }
    if (operator.operator === 'VectorRetriever') {
      const embedding = operator.kwargs?.embedding
      if (embedding && !kbListWithModel.value[embedding] && !missingModels.includes(embedding)) {
        missingModels.push(embedding)
      }
    }
    extractKbNamesFromOperator(operator).forEach(kbName => {
      if (!kbName || validateKbName(kbName, operator)) {
        return
      }
      if (operator.operator === 'VectorRetriever' && findKbInList(kbName, allKBList.value)) {
        if (!modelMismatchNames.includes(kbName)) {
          modelMismatchNames.push(kbName)
        }
      } else if (!notFoundKBNames.includes(kbName)) {
        notFoundKBNames.push(kbName)
      }
    })
  })
  if (missingModels.length) {
    message.error(proxy.$t('ragFlow.vectorModelUnavailable', { models: missingModels.join('、') }))
    return false
  }
  if (modelMismatchNames.length) {
    message.error(proxy.$t('ragFlow.kbModelMismatch', { names: modelMismatchNames.join('、') }))
    return false
  }
  if (notFoundKBNames.length) {
    message.error(`${JSON.stringify(notFoundKBNames)}${proxy.$t('knowledge.notFoundKBNamesTip')}`)
    return false
  }
  return true
}

function validateOperator (operator) {
  if (operator.custom || !isKnownOperator(operator)) {
    return ''
  }
  const kwargs = operator.kwargs || {}
  // 0.1.10：库类型必须与算子匹配（历史/导入配置里可能残留反类型绑定）
  const kind = sourceKindOfOperator(operator)
  if (kind && operatorSourceMismatch(operator).length) {
    return proxy.$t('modules.workflow.sourceKindMismatch', {
      operator: displayName(operator),
      kind: proxy.$t(sourceKindMeta(kind).labelKey)
    })
  }
  if (operator.operator === 'VectorRetriever') {
    if (kwargs.strategy === undefined || kwargs.strategy === null) {
      return proxy.$t('ragFlow.kbRetrieveStrategyPlc')
    }
    if (!kwargs.embedding) {
      return proxy.$t('ragFlow.vectorModelPlc')
    }
    if (!(kwargs.knowledge_info_list || []).length) {
      return proxy.$t('knowledge.selectKnowledge')
    }
    for (const item of kwargs.knowledge_info_list) {
      if (!(item.knowledge_base_name || []).length) {
        return proxy.$t('knowledge.selectKnowledge')
      }
      if (!Number.isInteger(Number(item.top_k)) || Number(item.top_k) < 1 || Number(item.top_k) > 80) {
        return proxy.$t('knowledge.top_kTip')
      }
      if (Number(item.score) < 0 || Number(item.score) > 1) {
        return proxy.$t('knowledge.scoreTip')
      }
    }
    return ''
  }
  if (operator.operator === 'KeywordRetriever') {
    if (!(kwargs.knowledge_base_name || []).length) {
      return proxy.$t('knowledge.selectKnowledge')
    }
    if (!Number.isInteger(Number(kwargs.top_k)) || Number(kwargs.top_k) < 1 || Number(kwargs.top_k) > 80) {
      return proxy.$t('knowledge.top_kTip')
    }
    return ''
  }
  if (operator.operator === 'KnowledgeGraphRetriever') {
    if (!(kwargs.knowledge_base_name || []).length) {
      return proxy.$t('knowledge.selectKnowledge')
    }
    if (!Number.isInteger(Number(kwargs.top_k)) || Number(kwargs.top_k) < 1 || Number(kwargs.top_k) > 80) {
      return proxy.$t('knowledge.top_kTip')
    }
    if (!Number.isInteger(Number(kwargs.depth)) || Number(kwargs.depth) < 1 || Number(kwargs.depth) > 10) {
      return proxy.$t('modules.workflow.depthRange')
    }
    return ''
  }
  if (!Number.isInteger(Number(kwargs.top_k)) || Number(kwargs.top_k) < 1 || Number(kwargs.top_k) > 80) {
    return proxy.$t('knowledge.top_kTip')
  }
  return ''
}

function validate () {
  return callback => {
    if (!validateAndStoreKnowledgeBaseNames()) {
      callback(false)
      return
    }
    for (const operator of operatorList.value) {
      const error = validateOperator(operator)
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

defineExpose({
  sendOperatorListData,
  validate
})
</script>

<style lang="less" scoped>
.ai-json-editor--drawer {
  height: 300px;
}
.fc-edge-facts {
  display: flex;
  align-items: center;
  gap: 10px;
}
.fc-edge-facts-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.4;
}
</style>

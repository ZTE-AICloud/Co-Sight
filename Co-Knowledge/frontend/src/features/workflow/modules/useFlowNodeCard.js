/**
 * 0.1.6 卡片（算子链 / 上游输入 / 输出字段）的共享数据层。
 *
 * 四个业务节点 + QUERY/RESPONSE 的模板只剩「标题、主题、默认变量、图标」不同，
 * 其余（端口尺寸、输入列表、来源摘要、算子显示名）全部收在这里，避免六份漂移。
 */
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  getNodeOperators,
  isFixedShape,
  nodeGeometry,
  operatorDisplayName,
  outputFieldKey,
  sourceSummary as buildSourceSummary
} from '@/features/workflow/lib/flowGeometry'
import { kbDisplayName, loadKbNames } from '@/features/knowledge-base/lib/kbNames'
import { sourceKindOfOperator } from '@/features/workflow/lib/retrievalSources'

const aipVueInstance = window.aipVueInstance

const MODULE_TITLE_KEYS = {
  PRE_RETRIEVER: 'ragFlow.preretrieverTitle',
  RETRIEVER: 'ragFlow.retrieverTitle',
  POST_RETRIEVER: 'ragFlow.postretrieverTitle',
  RESPONSE_SYNTHESIZER: 'ragFlow.responsesynthesizerTitle',
  QUERY: 'ragFlow.start',
  RESPONSE: 'ragFlow.end'
}

const MODULE_TONES = {
  PRE_RETRIEVER: 'purple',
  RETRIEVER: 'orange',
  POST_RETRIEVER: 'blue',
  RESPONSE_SYNTHESIZER: 'green',
  QUERY: 'blue',
  RESPONSE: 'blue'
}

export function moduleTitleOf (shape) {
  const key = MODULE_TITLE_KEYS[shape]
  return key ? aipVueInstance.$t(key) : ''
}

export function moduleToneOf (shape) {
  return MODULE_TONES[shape] || 'blue'
}

/**
 * @param {object} options
 * @param {string} options.componentType 节点 componentType / shape
 * @param {object} options.defaultVariables 新节点没有 variables 时用来初始化
 * @param {string} options.moduleTitleKey
 */
export function useFlowNodeCard (options) {
  const nodeInject = inject('getNode')
  const shape = options.componentType
  const fixed = isFixedShape(shape)
  const nodeInfo = ref({
    id: '',
    componentType: shape,
    label: '',
    variables: options.defaultVariables ? JSON.parse(JSON.stringify(options.defaultVariables)) : null,
    inputVariables: []
  })
  const inputs = ref([])
  const kbVersion = ref(0)
  let nodeObject = null
  let nodeModel = null

  const title = computed(() => aipVueInstance.$t(options.moduleTitleKey))
  const tone = computed(() => moduleToneOf(shape))
  const operators = computed(() => getNodeOperators({
    shape,
    variables: nodeInfo.value.variables
  }).map((operator, index) => ({
    key: operator?.id || index,
    name: operatorDisplayName(operator, key => aipVueInstance.$t(key))
  })))
  const sourceSummary = computed(() => {
    // kbVersion 参与依赖，名称映射异步到达后卡片会重新渲染
    void kbVersion.value
    if (shape !== 'RETRIEVER') {
      return null
    }
    const operators = getNodeOperators({ shape, variables: nodeInfo.value.variables })
    const fallback = operators[0]?.operator === 'FusionRetriever'
      ? aipVueInstance.$t('modules.workflow.fusionSource')
      : ''
    const summary = buildSourceSummary(operators, kbDisplayName, fallback)
    // 0.1.10：来源摘要前带上类型（文档 / 图谱），一眼能看出这个检索器绑的是哪类库
    const kind = sourceKindOfOperator(operators[0]?.operator)
    const kindKey = {
      knowledge: 'sourceKindShortKnowledge',
      graph: 'sourceKindShortGraph',
      database: 'sourceKindShortDatabase'
    }[kind]
    if (!summary || !summary.text || !kindKey) {
      return summary
    }
    const prefix = aipVueInstance.$t(`modules.workflow.${kindKey}`)
    return {
      text: `${prefix} · ${summary.text}`,
      title: `${prefix} · ${summary.title}`
    }
  })
  const outputField = computed(() => outputFieldKey(shape))
  const fixedDirection = computed(() => shape === 'QUERY'
    ? aipVueInstance.$t('modules.workflow.output')
    : aipVueInstance.$t('modules.workflow.inputs'))
  const fixedField = computed(() => shape === 'RESPONSE' ? 'Answer' : 'Question')

  function refreshInputs () {
    if (!nodeModel || !nodeInfo.value.id) {
      inputs.value = []
      return
    }
    const edges = nodeModel.getEdges().filter(edge => edge.getTargetCellId() === nodeInfo.value.id)
    inputs.value = edges.map(edge => {
      const sourceId = edge.getSourceCellId()
      const source = nodeModel.getCell(sourceId)
      const sourceShape = source?.shape || source?.store?.data?.shape
      return {
        id: edge.id,
        title: sourceShape === 'QUERY'
          ? aipVueInstance.$t('modules.workflow.question')
          : moduleTitleOf(sourceShape),
        label: source?.store?.data?.label || sourceId,
        tone: moduleToneOf(sourceShape)
      }
    })
  }

  function editCardHandle () {
    const node = nodeObject
    nodeInfo.value.inputVariables = (node?.store?.data?.inputVariables || []).slice()
    emitEdit(nodeInfo.value, node?.id)
  }

  const emitHandlers = {
    edit: null,
    init: null,
    delete: null
  }

  function emitEdit (info, id) {
    if (typeof emitHandlers.edit === 'function') {
      emitHandlers.edit(info, id)
    }
  }

  function bindEmits (handlers) {
    Object.assign(emitHandlers, handlers)
  }

  onMounted(() => {
    nodeObject = nodeInject()
    nodeModel = nodeObject.model
    nodeInfo.value.id = nodeObject.id
    nodeInfo.value.label = nodeObject.store?.data?.label || ''
    nodeInfo.value.inputVariables = nodeObject.store?.data?.inputVariables || []
    const initialVariables = nodeObject.store?.data?.data?.variables ?? nodeObject.store?.data?.variables
    if (initialVariables) {
      nodeInfo.value.variables = initialVariables
    } else if (!fixed) {
      emitInit()
    }

    nodeObject.on('change:data', ({ current } = {}) => {
      if (current?.type === 'saveData' || current?.type === 'displayData') {
        nodeInfo.value.variables = current.variables
      }
    })
    nodeObject.on('change:label', () => {
      nodeInfo.value.label = nodeObject.store?.data?.label || ''
    })
    nodeModel.on('cell:added', refreshInputs)
    nodeModel.on('cell:removed', refreshInputs)
    nodeModel.on('cell:changed', refreshInputs)
    refreshInputs()
    if (shape === 'RETRIEVER') {
      loadKbNames().then(() => {
        kbVersion.value += 1
      })
    }
  })

  onBeforeUnmount(() => {
    if (nodeModel) {
      nodeModel.off('cell:added', refreshInputs)
      nodeModel.off('cell:removed', refreshInputs)
      nodeModel.off('cell:changed', refreshInputs)
    }
  })

  function emitInit () {
    if (typeof emitHandlers.init === 'function') {
      emitHandlers.init({
        id: nodeInfo.value.id,
        componentType: shape,
        label: nodeInfo.value.label,
        variables: nodeInfo.value.variables,
        inputVariables: []
      })
    }
  }

  function deleteCardHandle () {
    if (typeof emitHandlers.delete === 'function') {
      emitHandlers.delete(nodeObject?.id)
    }
  }

  return {
    nodeInfo,
    title,
    tone,
    fixed,
    operators,
    inputs,
    outputField,
    fixedDirection,
    fixedField,
    sourceSummary,
    editCardHandle,
    deleteCardHandle,
    bindEmits
  }
}

/** 供 FlowDetail 复用的几何计算（避免父组件重复一套）。 */
export function geometryForNode (node) {
  const data = node?.store?.data || {}
  const variables = data.data?.variables ?? data.variables
  const operators = getNodeOperators({ shape: node?.shape, variables })
  const inputCount = node?.model?.getEdges?.().filter(edge => edge.getTargetCellId() === node.id).length || 0
  return nodeGeometry({ shape: node?.shape, operatorCount: operators.length, inputCount })
}

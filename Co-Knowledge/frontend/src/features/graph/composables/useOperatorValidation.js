import { ref, computed, reactive } from 'vue'
import { getOperatorListApi, getLlmListApi, knowledgeGraphTemplateListApi } from '@/features/graph/api/knowledgeGraph'

export function useOperatorValidation () {
  // 算子相关状态
  const operatorList = ref([])
  const llmModelList = ref([])
  const templateList = ref([])
  const operatorNotFound = ref(false)
  const currentOperator = ref(null)
  const templateNotFound = ref(false)
  const dynamicParams = reactive({})

  // 计算属性
  const selectedOperator = computed(() =>
    operatorList.value.find((op) => String(op.id) === String(dynamicParams.operatorId)) || null
  )
  const operatorArgs = computed(() => {
    const args = selectedOperator.value?.args || []
    // 定义参数显示顺序
    const orderMap = {
      schemaId: 1,
      llm: 2,
      overlap: 3,
      chunkSize: 4
    }
    // 按照指定顺序排序
    return [...args].sort((a, b) => {
      const orderA = orderMap[a.argName] || 999
      const orderB = orderMap[b.argName] || 999
      return orderA - orderB
    })
  })

  // 加载算子列表
  async function loadOperatorList () {
    const res = await getOperatorListApi('graph_extract')
    const list = res || []
    operatorList.value = Array.isArray(list) ? list : []
  }

  // 查找算子
  function findOperatorById (operatorId) {
    return operatorList.value.find((op) => {
      return String(op.id) === String(operatorId)
    })
  }

  // 处理算子参数
  function processOperatorArgs (foundOperator, schemaInfo) {
    if (!foundOperator.args || foundOperator.args.length === 0) {
      return
    }

    foundOperator.args.forEach((arg) => {
      if (arg.argName === 'schemaId') {
        processSchemaIdArg(arg, schemaInfo)
      } else if (arg.argName === 'llm') {
        processLlmArg(arg)
      } else {
        processOtherArg(arg)
      }
    })
  }

  // 处理schemaId参数
  function processSchemaIdArg (arg, schemaInfo) {
    if (schemaInfo && schemaInfo.schema_name) {
      dynamicParams[arg.argName] = schemaInfo.schema_id
      templateNotFound.value = false
    } else {
      templateNotFound.value = true
      dynamicParams[arg.argName] = ''
    }
  }

  // 处理llm参数
  function processLlmArg (arg) {
    dynamicParams[arg.argName] = llmModelList.value.length > 0
      ? (llmModelList.value[0].value || llmModelList.value[0].id)
      : (arg.defaultValue ?? '')
  }

  // 处理其他参数
  function processOtherArg (arg) {

    // 对于overlap和chunkSize，需要转换为数字
    if (arg.argName === 'overlap' || arg.argName === 'chunkSize') {
      const defaultValue = arg.defaultValue || (arg.argName === 'chunkSize' ? '512' : '0')
      dynamicParams[arg.argName] = parseInt(defaultValue, 10) || 0
    } else {
      // 根据参数类型设置不同的默认值
      let defaultValue = arg.defaultValue ?? ''

      // 如果是数字类型参数，确保默认值是数字
      if (arg.type === 'number' || arg.argName.includes('Size') || arg.argName.includes('Overlap') || arg.argName.includes('Chars')) {
        defaultValue = Number(defaultValue) || 0
      }

      dynamicParams[arg.argName] = defaultValue
    }
  }

  // 加载相关数据
  async function loadRelatedData (foundOperator) {
    const hasSchemaId = foundOperator.args.some((arg) => arg.argName === 'schemaId')
    const hasLlm = foundOperator.args.some((arg) => arg.argName === 'llm')

    if (hasSchemaId) {
      await loadTemplateList()
    }

    if (hasLlm) {
      await loadLLMModels()
      const llmArg = foundOperator.args.find((arg) => arg.argName === 'llm')
      if (llmArg && llmModelList.value.length > 0) {
        dynamicParams[llmArg.argName] = llmModelList.value[0].value || llmModelList.value[0].id
      }
    }
  }

  // 加载模版列表
  async function loadTemplateList () {
    try {
      const res = await knowledgeGraphTemplateListApi({}, {})
      const data = res || []
      templateList.value = Array.isArray(data) ? data : []
    } catch (error) {
      console.error('加载模版列表失败:', error)
    }
  }

  // 加载大模型列表
  async function loadLLMModels () {
    try {
      const res = await getLlmListApi()
      const list = res || []
      llmModelList.value = Array.isArray(list) ? list : []
    } catch (error) {
      console.error('加载大模型列表失败:', error)
    }
  }

  // 设置算子不存在状态
  function setOperatorNotFound () {
    operatorNotFound.value = true
    currentOperator.value = null
    dynamicParams.operatorId = ''
  }

  // 验证算子是否存在
  async function validateOperator (operatorId, schemaInfo, isCurrent = () => true) {
    try {
      await loadOperatorList()
      if (!isCurrent()) {
        return
      }
      const foundOperator = findOperatorById(operatorId)

      if (foundOperator) {
        currentOperator.value = foundOperator
        dynamicParams.operatorId = operatorId.toString()
        operatorNotFound.value = false

        processOperatorArgs(foundOperator, schemaInfo)
        await loadRelatedData(foundOperator)
      } else {
        setOperatorNotFound()
      }
    } catch (error) {
      console.error('验证算子失败:', error)
      setOperatorNotFound()
    }
  }

  return {
    operatorList,
    llmModelList,
    templateList,
    operatorNotFound,
    currentOperator,
    templateNotFound,
    dynamicParams,
    selectedOperator,
    operatorArgs,
    validateOperator,
    loadTemplateList,
    loadLLMModels
  }
}
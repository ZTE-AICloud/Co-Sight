import { ref, reactive, getCurrentInstance } from 'vue'
import message from '@/shared/lib/message'
import { getModelList as getEmbeddingModelListApi } from '@/features/model/api/models'
import { getKnowledgeGraphBasicInfoApi, updateKnowledgeGraphExtractApi } from '@/features/graph/api/knowledgeGraph'

export function useKnowledgeGraphForm () {
  const { proxy } = getCurrentInstance()

  // 表单数据
  const formData = reactive({
    name: '',
    description: '',
    embeddingModel: ''
  })

  // 步骤二表单数据
  const step2Form = reactive({
    accessType: 'local', // 接入类型：local-本地文件, knowledge-知识接入
    config: {
      operator: '', // 知识图谱算子：professional-专业域, general-通用域
      template: '', // 知识图谱模版（专业域时需要）
      llmModel: '', // 大模型
      prompt: '' // 提示词（通用域时可选）
    }
  })

  // 加载状态
  const buildLoading = ref(false)
  const knowledgeGraphId = ref('')
  const schemaInfo = ref(null)

  // Embedding模型列表
  const embeddingModelList = ref([])

  // 名称校验函数：允许空格，但不能全为空格
  const validateName = (rule, value, callback) => {
    if (!value) {
      callback();
      return;
    }
    // 检查是否全为空格
    if (/^\s+$/.test(value)) {
      callback(new Error(proxy.$t('modules.kb.knowledgeGraphNameValidation')));
      return;
    }
    // 检查字符格式：允许英文、数字、下划线、中文、英文点、英文中划线和空格
    if (!/^[\w\u4e00-\u9fa5.\-\s]+$/.test(value)) {
      callback(new Error(proxy.$t('modules.kb.knowledgeGraphNameValidation')));
      return;
    }
    // 检查长度
    if (value.length < 2 || value.length > 30) {
      callback(new Error(proxy.$t('modules.kb.knowledgeGraphNameValidation')));
      return;
    }
    callback();
  };

  // 表单验证规则
  const formRules = {
    name: [
      { required: true, message: proxy.$t('modules.kb.pleaseInputKnowledgeGraphName'), trigger: ['blur', 'change'] },
      { validator: validateName, trigger: ['blur', 'change'] }
    ],
    description: [
      { max: 1000, message: proxy.$t('modules.knowledgeGraphStudio.form.descriptionMaxLength'), trigger: 'change' }
    ]
  }

  // 安全返回图谱列表：
  //   错误分支不能直接 `router.back()`；当页面是「新标签页直开的深链」
  //   （history 里没有本应用的上一条目）时，back() 会退到 about:blank —— 整页白屏、
  //   页内无任何自愈入口。有可退历史时正常退回，只在无历史时 replace 到图谱列表兜底。
  //   调用方都先弹了错误 toast —— message 是全局挂载，replace 后提示仍显示在列表页上。
  //   判别法：vue-router 4 会给每个历史条目写 state，首个条目 `state.back === null`。
  function goBackToListSafely (router) {
    const state = window.history.state
    if (state && state.back) {
      router.back()
      return
    }
    router.replace({ path: '/graph' })
  }

  // 获取知识图谱详情
  async function fetchKnowledgeGraphInfo (route, router) {
    const id = route.params.id
    if (!id) {
      proxy.$message.error(proxy.$t('modules.kb.knowledgeGraphIdMissing'))
      goBackToListSafely(router)
      return
    }
    knowledgeGraphId.value = id
    try {
      const res = await getKnowledgeGraphBasicInfoApi(id)
      // 连续切换图谱时先发出的请求可能后返回：旧响应不能再写入表单，
      // 也不能在用户已经停留在新图谱上时弹错误/踢回列表。
      if (route.params.id !== id) {
        return null
      }

      if (res) {
        formData.name = res.data?.name || ''
        formData.description = res.data?.description || ''
        formData.embeddingModel = res.data?.embeddingModel || ''
        schemaInfo.value = res.schemaInfo
        return res
      } else {
        proxy.$message.error(proxy.$t('modules.kb.getDetailFailed'))
        goBackToListSafely(router)
      }
    } catch (error) {
      if (route.params.id !== id) {
        return null
      }
      proxy.$message.error(`${proxy.$t('modules.kb.getDetailFailed')}：${error.message || proxy.$t('public.noData')}`)
      goBackToListSafely(router)
    }
  }

  // 加载Embedding模型列表
  async function loadEmbeddingModels () {
    try {
      const res = await getEmbeddingModelListApi()

      if (Array.isArray(res)) {
        embeddingModelList.value = res.map(item => {
          if (typeof item === 'string') {
            return { modelName: item }
          } else if (typeof item === 'object' && item !== null && !Array.isArray(item)) {
            return item
          }
          return {}
        }).filter(item => item.modelName)
      } else {
        embeddingModelList.value = []
      }
    } catch (error) {
      console.error('加载Embedding模型失败:', error)
      embeddingModelList.value = []
    }
  }

  // 算子变化时的处理
  async function handleOperatorChange (value, operatorList, llmModelList, dynamicParams, loadLLMModels) {
    step2Form.config.template = ''
    step2Form.config.llmModel = ''
    step2Form.config.prompt = ''
    Object.keys(dynamicParams).forEach(k => delete dynamicParams[k])

    const op = operatorList.value.find((op) => op.id === value)
    const args = op?.args || []

    for (const arg of args) {
      if (arg.argName === 'llm') {
        await loadLLMModels()
        dynamicParams[arg.argName] = llmModelList.value.length > 0
          ? (llmModelList.value[0].value || llmModelList.value[0].id)
          : (arg.defaultValue ?? '')
      } else if (arg.argName === 'overlap' || arg.argName === 'chunkSize') {
        // 对于overlap和chunkSize，将默认值转换为数字
        const defaultValue = arg.defaultValue || (arg.argName === 'chunkSize' ? '512' : '0')
        dynamicParams[arg.argName] = parseInt(defaultValue, 10) || 0
      } else {
        dynamicParams[arg.argName] = arg.defaultValue ?? ''
      }
    }
  }

  // 构建知识图谱
  async function handleBuild (canBuild, uploadedFiles, deletedFiles, remainingFiles, dynamicParams, router) {
    if (!canBuild.value) {
      message.warning(proxy.$t('modules.kb.pleaseCompleteRequiredFields'))
      return
    }

    buildLoading.value = true

    try {
      const fd = new FormData()

      uploadedFiles.value.forEach((f) => {
        fd.append('files', f.raw || f)
      })

      fd.append('accessFiles', JSON.stringify([]))
      fd.append('deleteFiles', JSON.stringify(deletedFiles.value))
      fd.append('localFiles', JSON.stringify(remainingFiles.value))

      const kwargs = { ...dynamicParams }
      const payload = {
        name: formData.name,
        description: formData.description,
        category: 10,
        props: {
          embeddingModel: formData.embeddingModel
        },
        operatorId: step2Form.config.operator,
        coverFlag: true,
        kwargs: {}
      }

      if (kwargs.schemaId) {
        payload.schemaId = kwargs.schemaId
        delete kwargs.schemaId
      }
      payload.kwargs = kwargs

      fd.append('data', JSON.stringify(payload))


      await updateKnowledgeGraphExtractApi(knowledgeGraphId.value, fd)
      message.success(proxy.$t('modules.kb.updateKnowledgeGraphSuccess'))
      // 图谱知识库是独立页面（/graph）
      router.push({ path: '/graph' })
    } catch (error) {
      console.error('构建失败:', error)
    } finally {
      buildLoading.value = false
    }
  }

  return {
    formData,
    step2Form,
    buildLoading,
    knowledgeGraphId,
    schemaInfo,
    embeddingModelList,
    formRules,
    fetchKnowledgeGraphInfo,
    loadEmbeddingModels,
    handleOperatorChange,
    handleBuild
  }
}

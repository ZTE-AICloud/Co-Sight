<template>
  <div class="page">
    <div class="page-inner">
      <div class="create-knowledge-graph-page">
        <!-- 面包屑 -->
        <el-breadcrumb class="breadcrumb">
          <el-breadcrumb-item>
            <router-link to="/knowledge">
              {{ $t('modules.kb.kb') }}
            </router-link>
          </el-breadcrumb-item>
          <el-breadcrumb-item>
            <router-link to="/graph">
              {{ $t('modules.kb.graphKnowledgeBase') }} - {{ $t('modules.kb.knowledgeGraph') }}
            </router-link>
          </el-breadcrumb-item>
          <el-breadcrumb-item>{{ $t('modules.kb.createKnowledgeGraph') }}</el-breadcrumb-item>
        </el-breadcrumb>

        <!-- 内容区域 -->
        <div class="step-content">
          <div class="content-layout">
            <!-- 左侧：基础信息和文档选择 -->
            <div class="left-section">
              <!-- 基础信息 -->
              <SectionTitle :level="2" type="vertical">
                {{ $t('modules.kb.basicInfo') }}
              </SectionTitle>
              <el-form :model="formData" :rules="formRules" label-width="180px" class="basic-form">
                <el-form-item :label="$t('modules.kb.knowledgeGraphName')" prop="name">
                  <el-input
                    v-model="formData.name"
                    v-trim
                    :placeholder="$t('modules.kb.pleaseInputKnowledgeGraphName')"
                    class="form-input"
                  />
                </el-form-item>

                <el-form-item :label="$t('modules.kb.knowledgeGraphDescription')" prop="description" class="description-form-item">
                  <el-input
                    v-model="formData.description"
                    type="textarea"
                    :rows="4"
                    :placeholder="$t('modules.kb.pleaseInputKnowledgeGraphDescription')"
                    maxlength="1000"
                    show-word-limit
                    class="form-textarea"
                  />
                </el-form-item>
              </el-form>

              <!-- 文档选择 -->
              <SectionTitle :level="2" type="vertical">
                {{ $t('modules.kb.documentSelection') }}
              </SectionTitle>
              <el-form :model="step2Form" label-width="180px" class="upload-form">
                <!-- 接入类型 -->
                <el-form-item :label="$t('modules.kb.accessType')" required>
                  <el-radio-group v-model="step2Form.accessType">
                    <el-radio label="local">
                      {{ $t('modules.kb.localFile') }}
                    </el-radio>
                    <el-radio label="knowledge" disabled>
                      {{ $t('modules.kb.knowledgeAccess') }}
                    </el-radio>
                  </el-radio-group>
                </el-form-item>

                <!-- 文件上传区域 -->
                <el-form-item :label="$t('modules.kb.uploadFile')" required>
                  <el-upload
                    ref="uploadRef"
                    class="upload-demo"
                    drag
                    :auto-upload="false"
                    :show-file-list="false"
                    :on-change="handleFileChange"
                    :multiple="true"
                    :accept="acceptAttr"
                  >
                    <el-icon class="upload-icon">
                      <UploadFilled />
                    </el-icon>
                    <div class="upload-text">
                      {{ $t('modules.kb.dragOrClickToUpload') }}
                    </div>
                    <div class="upload-hint" v-html="formatUploadTip()" />
                  </el-upload>
                </el-form-item>

                <!-- 已导入文件列表 -->
                <el-form-item :label="$t('modules.kb.fileList')">
                  <el-table
                    :data="uploadedFiles"
                    border
                    max-height="300"
                    style="width: 100%"
                    :empty-text="$t('modules.kb.nodataNeedAdd')"
                    class="file-list-table"
                  >
                    <!-- 两栏等宽后内容区约 429px：文件名列最小宽从 300 收到 150，
                     否则 48+300+120+100 会把「操作」列挤出可视区（横向滚动） -->
                    <el-table-column
                      prop="name" :label="$t('modules.kb.fileName')" min-width="150" max-width="400" show-overflow-tooltip
                      :resizable="true"
                    />
                    <el-table-column prop="size" :label="$t('modules.kb.fileSize')" width="120" :resizable="false">
                      <template #default="{ row }">
                        {{ formatFileSize(row.size) }}
                      </template>
                    </el-table-column>
                    <el-table-column :label="$t('public.operate')" width="100" :resizable="false">
                      <template #default="{ $index }">
                        <el-button type="text" size="small" @click="removeFile($index)">
                          <el-icon><Delete /></el-icon>
                        </el-button>
                      </template>
                    </el-table-column>
                  </el-table>
                </el-form-item>
              </el-form>
            </div>

            <!-- 右侧：知识图谱构建配置 -->
            <div class="right-section">
              <SectionTitle :level="2" type="vertical">
                {{ $t('modules.kb.knowledgeGraphBuildConfig') }}
              </SectionTitle>
              <el-form :model="step2Form.config" label-width="180px" class="config-form">
                <!-- Embedding模型 -->
                <el-form-item :label="$t('advancedFlow.vectorType1')" required>
                  <el-select
                    v-model="formData.embeddingModel"
                    :placeholder="$t('modules.kb.pleaseSelectEmbeddingModel')"
                    class="form-select"
                    filterable
                    style="width: 100%"
                  >
                    <el-option
                      v-for="model in embeddingModelList"
                      :key="model.modelName"
                      :label="model.modelName"
                      :value="model.modelName"
                    />
                  </el-select>
                </el-form-item>

                <!-- 知识图谱算子（来自接口） -->
                <el-form-item :label="$t('modules.kb.knowledgeGraphOperator')" required>
                  <el-select
                    v-model="step2Form.config.operator"
                    :placeholder="$t('modules.kb.selectOperator')"
                    filterable
                    style="width: 100%"
                    @change="handleOperatorChange"
                  >
                    <el-option
                      v-for="op in operatorList"
                      :key="op.id"
                      :label="getOperatorLabel(op)"
                      :value="op.id"
                    />
                  </el-select>
                </el-form-item>

                <!-- 联动参数区域：根据所选算子的 args 渲染 -->
                <template v-for="arg in operatorArgs" :key="arg.argName">
                  <!-- schemaId → 模版下拉，必填 -->
                  <el-form-item v-if="arg.argName === 'schemaId'" required>
                    <template #label>
                      <span>{{ $t('modules.kb.graphTemplate') }}</span>
                      <el-tooltip v-if="getTipsText(arg)" :content="getTipsText(arg)" placement="top">
                        <el-icon class="question-icon">
                          <QuestionFilled />
                        </el-icon>
                      </el-tooltip>
                    </template>
                    <el-select v-model="dynamicParams.schemaId" :placeholder="$t('modules.kb.selectGraphTemplate')" filterable style="width: 100%">
                      <el-option v-for="tpl in templateList" :key="tpl.schemaId || tpl.id" :label="tpl.schemaName || tpl.name" :value="tpl.schemaId || tpl.id" />
                    </el-select>
                  </el-form-item>

                  <!-- llm → 大模型下拉，必填 -->
                  <el-form-item v-else-if="arg.argName === 'llm'" required>
                    <template #label>
                      <span>{{ $t('modules.kb.llmModel') }}</span>
                      <el-tooltip v-if="getTipsText(arg)" :content="getTipsText(arg)" placement="top">
                        <el-icon class="question-icon">
                          <QuestionFilled />
                        </el-icon>
                      </el-tooltip>
                    </template>
                    <el-select v-model="dynamicParams.llm" :placeholder="$t('modules.kb.selectLlmModel')" filterable style="width: 100%">
                      <el-option v-for="m in llmModelList" :key="m.value || m.id" :label="m.label || m.name || m.value" :value="m.value || m.id" />
                    </el-select>
                  </el-form-item>

                  <!-- extractionProfile → 通用 / 通用+属性（同一次 LLM 调用） -->
                  <el-form-item v-else-if="arg.argName === 'extractionProfile'">
                    <template #label>
                      <span>{{ arg.description || $t('modules.kb.graphArgExtractionProfile') }}</span>
                      <el-tooltip v-if="getTipsText(arg)" :content="getTipsText(arg)" placement="top">
                        <el-icon class="question-icon">
                          <QuestionFilled />
                        </el-icon>
                      </el-tooltip>
                    </template>
                    <el-select v-model="dynamicParams.extractionProfile" style="width: 100%">
                      <el-option :label="$t('modules.kb.extractionProfileGeneral')" value="general" />
                      <el-option :label="$t('modules.kb.extractionProfileAttributes')" value="general_attributes" />
                    </el-select>
                  </el-form-item>

                  <!-- overlap → 数字输入框，最小值0，最大值5120 -->
                  <el-form-item v-else-if="arg.argName === 'overlap'" required>
                    <template #label>
                      <span>{{ arg.description || arg.argName }}</span>
                      <el-tooltip v-if="getTipsText(arg)" :content="getTipsText(arg)" placement="top">
                        <el-icon class="question-icon">
                          <QuestionFilled />
                        </el-icon>
                      </el-tooltip>
                    </template>
                    <el-input-number
                      v-model="dynamicParams.overlap"
                      :min="0"
                      :max="5120"
                      :placeholder="getPlaceholderText(arg) || '0'"
                      style="width: 100%"
                    />
                  </el-form-item>

                  <!-- chunkSize → 数字输入框，最小值512，最大值10240 -->
                  <el-form-item v-else-if="arg.argName === 'chunkSize'" required>
                    <template #label>
                      <span>{{ arg.description || arg.argName }}</span>
                      <el-tooltip v-if="getTipsText(arg)" :content="getTipsText(arg)" placement="top">
                        <el-icon class="question-icon">
                          <QuestionFilled />
                        </el-icon>
                      </el-tooltip>
                    </template>
                    <el-input-number
                      v-model="dynamicParams.chunkSize"
                      :min="512"
                      :max="10240"
                      :placeholder="getPlaceholderText(arg) || '512'"
                      style="width: 100%"
                    />
                  </el-form-item>

                  <!-- 其他参数 → 输入框（默认值展示），必填 -->
                  <el-form-item v-else required>
                    <template #label>
                      <span>{{ arg.description || arg.argName }}</span>
                      <el-tooltip v-if="getTipsText(arg)" :content="getTipsText(arg)" placement="top">
                        <el-icon class="question-icon">
                          <QuestionFilled />
                        </el-icon>
                      </el-tooltip>
                    </template>
                    <el-input v-model="dynamicParams[arg.argName]" :placeholder="getPlaceholderText(arg)" />
                  </el-form-item>
                </template>

                <!-- 操作按钮 -->
                <el-form-item>
                  <el-button
                    type="primary"
                    :loading="buildLoading"
                    :disabled="!canBuild"
                    @click="handleBuild"
                  >
                    {{ $t('modules.kb.buildKnowledgeGraph') }}
                  </el-button>
                  <el-button @click="handleCancel">
                    {{ $t('public.cancel') }}
                  </el-button>
                </el-form-item>
              </el-form>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script lang="ts" setup>
import { ref, reactive, computed, getCurrentInstance, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import message from '@/shared/lib/message'
import { UploadFilled, Delete, QuestionFilled } from '@element-plus/icons-vue'
import { getModelList as getEmbeddingModelListApi } from '@/features/model/api/models'
import { getKbaseFileLimitApi, getOperatorListApi, knowledgeGraphTemplateListApi, getLlmListApi, extractKnowledgeGraphApi } from '@/features/graph/api/knowledgeGraph'
import SectionTitle from '@/shared/ui/SectionTitle.vue';
import { TOTAL_UPLOAD_SIZE_MB } from '@/features/knowledge-base/lib/file-limits';
import { takeGraphQuickDraft } from './lib/graph-quick-create';

const { proxy } = getCurrentInstance() as any
const router = useRouter()
// 移除未使用的responseCache变量

// 移除步骤逻辑，直接显示合并后的内容

// 根据语言环境获取tips值
function getTipsText (arg: any): string | null {
  if (!arg.tips) {
    return null
  }
  const locale = proxy.$i18n.locale
  return arg.tips[locale] || arg.tips.zh || null
}

// 根据语言环境获取placeholder值
function getPlaceholderText (arg: any): string {
  // 优先使用defaultValue
  if (arg.defaultValue) {
    return arg.defaultValue
  }
  // 如果defaultValue为空，使用placeholder
  if (arg.placeholder) {
    const locale = proxy.$i18n.locale
    return arg.placeholder[locale] || arg.placeholder.zh || ''
  }
  return ''
}

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

// 文件上传相关
const uploadedFiles = ref<any[]>([])
const uploadRef = ref()
// 文件数量超限提示标志位，记录当前批次开始时的文件数量
// 用于避免在同一次批量选择中重复提示
const fileSelectionBatchCount = ref<number | null>(null)
// 上次文件选择的时间戳，用于判断是否是新的批次
let lastFileSelectionTime = 0

// 文件限制（由后端返回）
const fileLimit = ref<{ maxSizeMap: Record<string, number>, number: number } | null>(null)

// 过滤后的文件格式列表（去掉 ofd 和 zedx）
const filteredFileFormats = computed(() => {
  const maxSizeMap = fileLimit.value?.maxSizeMap || {}
  const filtered: Record<string, number> = {}
  Object.keys(maxSizeMap).forEach(ext => {
    const extLower = ext.toLowerCase()
    if (extLower !== 'ofd' && extLower !== 'zedx') {
      filtered[ext] = maxSizeMap[ext]
    }
  })
  return filtered
})

const acceptAttr = computed(() => {
  const keys = Object.keys(filteredFileFormats.value)
  if (keys.length === 0) {
    return '.pdf,.doc,.docx,.txt,.md,.xlsx,.xls,.csv'
  }
  return keys.map(ext => `.${ext}`).join(',')
})

// 模版列表和模型列表
const templateList = ref<any[]>([])
const llmModelList = ref<any[]>([])
// 算子与联动参数
const operatorList = ref<any[]>([])
const dynamicParams = reactive<Record<string, any>>({})
const selectedOperator = computed(() => operatorList.value.find((op: any) => op.id === step2Form.config.operator) || null)
const operatorArgs = computed(() => {
  const args = selectedOperator.value?.args || []
  // 定义参数显示顺序
  const orderMap: Record<string, number> = {
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
const getOperatorLabel = (op: any) => (proxy.$globalZh ? op.name : (op.nameEn || op.name))

// 加载状态
const buildLoading = ref(false)

// 名称校验函数：允许空格，但不能全为空格
const validateName = (rule: any, value: any, callback: any) => {
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

// Embedding模型列表
const embeddingModelList = ref([])

// 移除未使用的formRef变量

// 计算属性：是否可以构建
const canBuild = computed(() => {
  // 基础信息必填字段检查
  if (!formData.name || !formData.name.trim()) {
    return false
  }
  if (!formData.embeddingModel) {
    return false
  }

  // 必须已选择并上传至少一个文件
  if (uploadedFiles.value.length === 0) {
    return false
  }

  // 必须已选择算子
  if (!step2Form.config.operator) {
    return false
  }

  // 根据所选算子的 args 判定是否填完必填参数
  const args = operatorArgs.value || []
  if (!args.length) {
    return true
  }

  return args.every((arg: any) => {
    const key = arg.argName
    const val = dynamicParams[key]
    return val !== undefined && val !== null && String(val).trim() !== ''
  })
})

// 加载Embedding模型列表
async function loadEmbeddingModels () {
  try {
    const res = await getEmbeddingModelListApi()

    if (Array.isArray(res)) {
      // 处理API响应数据
      embeddingModelList.value = res.map(item => {
        if (typeof item === 'string') {
          // 如果数组中的元素是字符串，则将其转换为含有modelName的对象
          return { modelName: item }
        } else if (typeof item === 'object' && item !== null && !Array.isArray(item)) {
          // 如果数组中的元素是对象，则假设它已经是一个含有modelName的对象
          return item
        }
        // 对于其他类型的元素，返回空对象
        return {}
      }).filter(item => item.modelName) // 过滤掉没有modelName的项
    } else {
      embeddingModelList.value = []
    }
  } catch (error) {
    console.error('加载Embedding模型失败:', error)
    // message.error('加载Embedding模型失败')
    embeddingModelList.value = []
  }
}

// 组件挂载时加载必要数据
onMounted(async () => {
  // 加载Embedding模型列表
  await loadEmbeddingModels()

  // 弹窗交过来的草稿：名称 / 描述 / 模型 / 文件先填好，
  // 用户在整页继续选算子、schema 与 LLM 参数，构建时一次建库 + 上传 + 抽图。
  const quickDraft = takeGraphQuickDraft()
  if (quickDraft) {
    formData.name = quickDraft.name
    formData.description = quickDraft.description
    formData.embeddingModel = quickDraft.model
    uploadedFiles.value = quickDraft.files.map(file => ({
      name: file.name,
      size: file.size,
      raw: file
    }))
  }

  // 加载文件上传限制
  try {
    const limitRes = await getKbaseFileLimitApi(10)
    const data = limitRes || {}
    if (data.maxSizeMap && data.number) {
      fileLimit.value = { maxSizeMap: data.maxSizeMap, number: data.number }
    } else {
      fileLimit.value = null
    }
  } catch (e) {
    console.error('获取文件限制失败:', e)
    fileLimit.value = null
  }

  // 加载算子列表
  try {
    const res = await getOperatorListApi('graph_extract')
    const list = res || []
    operatorList.value = Array.isArray(list) ? list : []
  } catch (e) {
    console.error('加载算子列表失败:', e)
    operatorList.value = []
  }
})

// 已取消上一步按钮

// 创建
// 文件上传相关方法
function handleFileChange (file: any) {

  // 判断是否是新的文件选择批次
  // 如果距离上次文件选择超过500ms，认为是新的批次
  const now = Date.now()
  const isNewBatch = now - lastFileSelectionTime > 500
  lastFileSelectionTime = now

  const numberLimit = fileLimit.value?.number || 50
  const currentFileCount = uploadedFiles.value.length

  // 如果是新的批次，重置批次记录
  // 这样可以确保每次新的文件选择都能重新判断是否需要提示
  if (isNewBatch) {
    fileSelectionBatchCount.value = null
  }

  // 记录批次开始时的文件数量（在检查超限之前）
  // 如果是新的一批文件选择（从未记录过），记录当前文件数量
  if (fileSelectionBatchCount.value === null) {
    fileSelectionBatchCount.value = currentFileCount
  }

  // 检查文件格式是否在支持的格式列表中（使用过滤后的格式列表，已排除 ofd）
  const fileExt = file.name.split('.').pop()
    ?.toLowerCase() || ''
  const limitMap = filteredFileFormats.value
  const maxSizeMb = limitMap[fileExt]

  // 如果文件格式不在过滤后的格式列表中，则拒绝
  if (!maxSizeMb) {
    const supportedFormats = Object.keys(limitMap).join(', ')
    message.error(proxy.$t('knowledge.import.valid1', {
      fileName: file.name,
      type: supportedFormats || proxy.$t('modules.knowledgeGraphStudio.defaultFileFormats')
    }))
    return
  }

  // 来自接口的限制，单位MB，需要转换为字节
  const maxSize = typeof maxSizeMb === 'number' ? maxSizeMb * 1024 * 1024 : undefined

  if (typeof maxSize === 'number' && file.size > maxSize) {
    message.error(proxy.$t('modules.kb.fileSizeExceeded', {
      fileName: file.name,
      fileExt,
      maxSize: maxSizeMb
    }))
    return
  }

  // 检查文件数量限制（使用上面已获取的numberLimit）
  if (currentFileCount >= numberLimit) {
    // 检查当前批次是否已经提示过
    // 如果批次开始时的文件数量 < 限制，说明是当前批次导致的超限，需要提示
    // 如果批次开始时的文件数量 >= 限制，且是新的批次（刚刚重置过），说明是在已有超限的基础上继续选择，也应该提示
    // 如果批次开始时的文件数量 >= 限制，但不是新批次，说明是同一批次中的后续文件，已在之前提示过，不重复提示
    const shouldShowError = (fileSelectionBatchCount.value !== null && fileSelectionBatchCount.value < numberLimit) ||
                            (isNewBatch && fileSelectionBatchCount.value >= numberLimit)

    if (shouldShowError) {
      message.error(proxy.$t('modules.kb.fileCountExceeded', { limit: numberLimit }))
      // 标记当前批次已经提示过（通过将批次数量设为限制值）
      fileSelectionBatchCount.value = numberLimit
    }
    return
  }

  // 添加到文件列表
  uploadedFiles.value.push({
    name: file.name,
    size: file.size,
    raw: file.raw
  })

  // 如果文件成功添加后，列表长度发生了变化，说明可能是新的批次，重置批次记录
  // 使用 nextTick 确保在 DOM 更新后检查
  // 但这个逻辑其实不需要，因为批次记录应该在文件数量小于限制且删除文件时重置
  // 这里不重置，保持批次记录直到文件数量降到限制以下或删除文件
}

function removeFile (index: number) {
  uploadedFiles.value.splice(index, 1)
  // 删除文件后，重置批次记录，允许下次选择时重新记录批次
  // 这样可以确保在删除文件后再次选择时，如果超限会重新提示
  fileSelectionBatchCount.value = null
}

function formatFileSize (bytes: number) {
  if (bytes === 0) {
    return '0 MB'
  }
  const mb = bytes / (1024 * 1024)
  return mb.toFixed(2)
}

// 获取文件大小限制提示信息
function getFileSizeLimitNotice (): string {
  const sizeNotices: string[] = []
  const sizeMap: Record<number, string> = {}
  const maxSizeMap = filteredFileFormats.value
  // 根据语言环境使用不同的文件扩展名分隔符
  const extSeparator = proxy.$i18n.locale === 'zh' ? '、' : ', '

  // 遍历对象，构建大小映射
  for (const [ext, size] of Object.entries(maxSizeMap)) {
    if (sizeMap[size]) {
      sizeMap[size] += `${extSeparator}${ext}` // 如果该大小已存在映射中，添加当前后缀名
    } else {
      sizeMap[size] = ext // 否则初始化映射
    }
  }

  // 将映射转换为提示信息数组
  for (const [size, exts] of Object.entries(sizeMap)) {
    sizeNotices.push(`${exts}${proxy.$t('knowledge.uploadFileTip9')}${size}MB`)
  }

  // 将提示信息数组连接为一个字符串
  return sizeNotices.join(proxy.$t('public.comma'))
}

// 格式化上传提示信息，将 | 替换为换行
function formatUploadTip (): string {
  const tip = proxy.$t('knowledge.uploadFileTip3_2', {
    fileSize: getFileSizeLimitNotice(),
    fileLimit: fileLimit.value?.number || 50,
    totalSize: TOTAL_UPLOAD_SIZE_MB
  })
  // 将 | 替换为 <br />
  return tip.replace(/\s*\|\s*/g, '<br />')
}

// 算子变化时的处理
function handleOperatorChange (value: string) {
  // 清空之前的选择
  step2Form.config.template = ''
  step2Form.config.llmModel = ''
  step2Form.config.prompt = ''
  Object.keys(dynamicParams).forEach(k => delete dynamicParams[k])

  // 根据选中算子的args加载对应的数据
  const op = operatorList.value.find((op: any) => op.id === value)
  const args = op?.args || []
  args.forEach((arg: any) => {
    // 对于数字类型的参数，将默认值转换为数字
    if (arg.argName === 'overlap' || arg.argName === 'chunkSize') {
      const defaultValue = arg.defaultValue || (arg.argName === 'chunkSize' ? '512' : '0')
      dynamicParams[arg.argName] = parseInt(defaultValue, 10) || 0
    } else {
      dynamicParams[arg.argName] = arg.defaultValue ?? ''
    }

    if (arg.argName === 'schemaId') {
      loadTemplateList()
    }
    if (arg.argName === 'llm') {
      loadLLMModels()
    }
  })
}

// 加载知识图谱模版列表
async function loadTemplateList () {
  try {
    const res = await knowledgeGraphTemplateListApi({}, {})
    const data = res || []
    templateList.value = Array.isArray(data) ? data : []
  } catch (error) {
    console.error('加载模版列表失败:', error)
    // message.error('加载模版列表失败')
  }
}

// 加载大模型列表
async function loadLLMModels () {
  try {
    const res = await getLlmListApi()
    const list = res || []
    // 接口约定使用 value 作为展示/取值
    llmModelList.value = Array.isArray(list) ? list : []
  } catch (error) {
    console.error('加载大模型列表失败:', error)
    // message.error('加载大模型列表失败')
  }
}

// 构建知识图谱
async function buildKnowledgeGraph () {
  // 组装表单数据：files + data(JSON字符串)
  const fd = new FormData()
  uploadedFiles.value.forEach((f: any) => {
    fd.append('file', f.raw || f)
  })

  const kwargs: Record<string, any> = { ...dynamicParams }
  // schemaId 单独作为顶层字段，且从 kwargs 中移除
  const payload: any = {
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

  const res = await extractKnowledgeGraphApi(fd)
  return res
}

// 步骤二：构建
async function handleBuild () {
  if (!canBuild.value) {
    message.warning(proxy.$t('modules.kb.pleaseCompleteRequiredFields'))
    return
  }

  buildLoading.value = true

  try {
    // 然后构建知识图谱
    await buildKnowledgeGraph()

    message.success(proxy.$t('modules.kb.buildKnowledgeGraphSuccess'))
    // 返回列表页
    // 图谱知识库是独立页面（/graph）
    router.push({ path: '/graph' })
  } catch (error: any) {
    console.error('构建失败:', error)
    // message.error(error.message || '知识图谱构建失败')
  } finally {
    buildLoading.value = false
  }
}

function handleCancel () {
  // 图谱知识库是独立页面（/graph）
  router.push({ path: '/graph' })
}
</script>

<style lang="less" scoped>
.create-knowledge-graph-page {
  // 与「新建文档知识库」页（docKnowledgeLibrary/CreateKnowledgeBaseUnified.vue）同一套视觉：
  // 扁平白底、无卡片外壳；控件/标签取值见本文件下半部分与 style/sync/createKb.less。
  background: transparent;
  min-height: 0;
  --el-text-color-placeholder: var(--rs-text-3);

  // 控件统一成「新建文档知识库」页的取值（与 sync/createKb.less 实测值一致）
  :deep(.el-input__wrapper) {
    padding: 0 8px;
  }

  :deep(.el-select__wrapper) {
    min-height: 32px;
    padding: 0 8px 0 0;
    line-height: 30px;
  }

  // 本页表单是 large 档：EP 只给 default 档留了选中区内距
  //（同 sync/createKb.less §3.1，别提到全局）
  :deep(.el-select--large .el-select__selection) {
    padding: 0 8px;
  }

  :deep(.el-textarea__inner) {
    min-height: 32px;
    padding: 6px 8px;
    border: 1px solid var(--rs-border);
    box-shadow: none;
  }

  :deep(.el-input__inner),
  :deep(.el-textarea__inner) {
    color: var(--rs-text-2);
  }
}

.breadcrumb {
  margin-bottom: 8px;
}

.step-content {
  //background: white;
  //border-radius: 8px;
  //box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  min-height: 78vh;
}

.step-form {
  padding: 8px 0px 0px 0px;
  position: relative;
  min-height: 78vh;

  .form-section {
    width: 30vw;
    margin: 0px 0px 0px 12vw;
  }

  .create-form {
    margin-top: 22px;

    .form-input,
    .form-textarea,
    .form-select {
      width: 100%;
    }
  }
}

.el-form {
    --el-form-label-font-size: 12px;
    margin-top: 8px;
}

.content-layout {
  padding: 8px;
  display: flex;
  gap: 20px;
  min-height: 90vh;

  .left-section {
    flex: 1 1 0;
    min-width: 0;
    padding: 0 12px 20px;

    .basic-form {
      margin-bottom: 8px;

      :deep(.el-form-item) {
        display: flex;
        align-items: center;
        margin-bottom: 16px;
      }

      :deep(.el-form-item__label) {
        font-weight: 400;
        color: var(--rs-text-2);
        font-size: 12px;
        // 英文标签最长 160px（Knowledge Graph Description）+ 右侧 16px 内距，
        // 标签列取 180；文档库新建页标签短，那里是 140。字号/颜色/行高两页一致。
        width: 180px !important;
        text-align: right;
        justify-content: flex-end;
        flex-shrink: 0;
        line-height: 18px;
        height: 32px;
        padding-right: 16px;
        white-space: nowrap;
        overflow: visible;
      }

      :deep(.el-form-item__content) {
        flex: 1;
        margin-left: 0 !important;
        display: flex;
        align-items: center;
      }

      .form-input,
      .form-textarea,
      .form-select {
        width: 100%;
      }

      // 描述行的 20px 字符计数预留改到表单项的 padding 上（见文件底部说明），
      // 这样标签仍按输入框本身（84px）居中。
      :deep(.description-form-item) {
        align-items: center;
        padding-bottom: 20px;
        margin-bottom: 8px;
      }
    }

    .upload-form {
      :deep(.el-form-item) {
        display: flex;
        align-items: center;
        margin-bottom: 16px;
      }

      :deep(.el-form-item__label) {
        font-weight: 400;
        color: var(--rs-text-2);
        font-size: 12px;
        // 英文标签最长 160px（Knowledge Graph Description）+ 右侧 16px 内距，
        // 标签列取 180；文档库新建页标签短，那里是 140。字号/颜色/行高两页一致。
        width: 180px !important;
        text-align: right;
        justify-content: flex-end;
        flex-shrink: 0;
        line-height: 18px;
        height: 32px;
        padding-right: 16px;
        white-space: nowrap;
        overflow: visible;
      }

      :deep(.el-form-item__content) {
        flex: 1;
        margin-left: 0 !important;
        display: flex;
        align-items: center;
      }
    }

    .upload-demo {
      width: 100%;

      :deep(.el-upload) {
        width: 100%;
      }

      // 与「新建文档知识库」页一致：1px 虚线 / 3px 圆角 / 内距 16px 10px，
      // hover 只换边框色（element-plus 的 padding 变量顺序是 vertical/horizontal）
      :deep(.el-upload-dragger) {
        width: 100%;
        --el-upload-dragger-padding-vertical: 16px;
        --el-upload-dragger-padding-horizontal: 10px;
        padding: var(--el-upload-dragger-padding-vertical) var(--el-upload-dragger-padding-horizontal);
        border: 1px dashed var(--rs-border);
        border-radius: 3px;
        background: var(--rs-bg-card);
        transition: all 0.3s ease;

        &:hover {
          border-color: var(--el-color-primary);
        }
      }
    }

    // 与「新建文档知识库」页一致：表格无圆角/无阴影；表头令牌走全局
    // 主题（`src/styles/theme.css` 的 --el-* 变量）。
    :deep(.el-table) {
      width: 100%;
      border-radius: 0;
      overflow: hidden;

      .el-button--text {
        color: var(--rs-danger);

        &:hover {
          color: var(--rs-danger);
          background: color-mix(in srgb, var(--rs-danger) 8%, transparent);
        }
      }
    }

    /* 禁止文件列表表格列宽拖动 */
    .file-list-table {
      // 表头高度/内距与「新建文档知识库」页同一个口径（表头 40px、cell 内距 0 4px）
      :deep(.el-table__header-wrapper) {
        .el-table__header {
          th {
            height: 40px !important;
            min-height: 40px !important;
            max-height: 40px !important;
            padding: 8px 0 !important;
            line-height: 24px !important;

            .cell {
              line-height: 24px !important;
              padding: 0 4px !important;
              cursor: default !important;
            }

            &::after {
              display: none !important;
            }
          }

          // `.cell` 是 inline-block，不补 vertical-align 会按 baseline 落位、撑高表头
          th.el-table__cell .cell {
            vertical-align: middle;
          }
        }
      }

      :deep(.el-table__body-wrapper) {
        border-bottom: 1px solid var(--el-table-border-color, var(--rs-border)) !important;
      }

      :deep(.el-table__empty-block) {
        border-bottom: 1px solid var(--el-table-border-color, var(--rs-border)) !important;
      }

      :deep(.el-table__body-wrapper) {
        .el-table__body {
          td {
            .cell {
              cursor: default !important;
            }
          }
        }
      }
    }

    .upload-icon {
      font-size: 28px;
      color: var(--rs-primary);
      margin-bottom: 4px;
      transition: transform 0.3s ease;

      &:hover {
        transform: scale(1.1);
      }
    }

    .upload-text {
      color: var(--rs-text);
      font-size: 13px;
      font-weight: 500;
      margin-bottom: 6px;
    }

    .upload-hint {
      color: var(--rs-text-3);
      font-size: 11px;
      line-height: 1.5;
    }

    // 移除重复的表格样式，已在上面统一定义
  }

  .right-section {
    flex: 1 1 0;
    min-width: 0;
    padding: 0 12px 20px;

    .config-form {
      :deep(.el-form-item) {
        display: flex;
        align-items: center;
        margin-bottom: 16px;
      }

      :deep(.el-form-item__error) {
        margin-top: 4px;
        line-height: 1.5;
        word-wrap: break-word;
      }

      :deep(.el-form-item__label) {
        font-weight: 400;
        color: var(--rs-text-2);
        font-size: 12px;
        // 同 basic-form：英文最长标签 160px + 16px 内距
        width: 180px !important;
        text-align: right;
        justify-content: flex-end;
        padding-right: 16px;
        white-space: nowrap;
        overflow: visible;
        flex-shrink: 0;
        line-height: 18px;
        height: 32px;
      }

      :deep(.el-form-item__content) {
        flex: 1;
        margin-left: 0 !important;
      }

      :deep(.el-select),
      :deep(.el-input),
      :deep(.el-textarea) {
        width: 100%;
      }

      // 底部操作按钮与「新建文档知识库」页同一套：32px / 3px 圆角 / 0 16px 内距
      // （尺寸与配色见全局组件样式 `src/styles/`），这里只补最小宽与按钮间距。
      :deep(.el-form-item:last-child) {
        margin-top: 32px;
        margin-bottom: 0;

        .el-button {
          min-width: 80px;
        }

        .el-button + .el-button {
          margin-left: 8px;
        }
      }
    }
  }
}

.limit-item {
  margin-right: 8px;
}

.action-buttons {
  display: flex;
  justify-content: center;
  gap: 12px;
  padding: 20px 0;
  border-top: 1px solid var(--rs-border-soft);
}

.question-icon {
  margin-left: 4px;
  color: var(--rs-text-3);
  cursor: help;
  font-size: 14px;
}

// 修改 textarea 字符计数显示位置，使其显示在输入框下方
:deep(.el-form-item) {
  // 确保表单项容器允许溢出显示
  overflow: visible !important;

  // 字符计数预留改到 `.description-form-item` 的 padding-bottom（20px）：
  // 留在这里会被 form-item 的 `align-items:center` 算进内容盒，32px 的标签
  // 会按 84+20px 居中、比输入框低 10px（同「新建文档知识库」页修过的问题）。
  .vn-textarea,
  .el-textarea {
    position: relative !important;
    margin-bottom: 0 !important;
    overflow: visible !important; // 确保字符计数可以显示在容器外

    // 字符计数样式 - 使用多种选择器确保覆盖
    .vn-input__count,
    .el-input__count {
      background: var(--el-fill-color-blank) !important;
      color: var(--el-input-count-color) !important;
      font-size: 12px !important;
      line-height: 14px !important;
      position: absolute !important;
      right: 8px !important;
      bottom: -19px !important;
      z-index: 10 !important;
    }
  }

  // 确保 el-input__wrapper 也允许溢出
  .vn-textarea .el-input__wrapper,
  .el-textarea .el-input__wrapper {
    overflow: visible !important;
  }
}

// 全局覆盖 Element Plus 的默认样式（针对 textarea）
:deep(.vn-textarea .vn-input__count),
:deep(.vn-textarea .el-input__count),
:deep(.el-textarea .vn-input__count),
:deep(.el-textarea .el-input__count) {
  bottom: -19px !important;
  right: 8px !important;
  position: absolute !important;
}

// 针对 el-form-item__content 容器
:deep(.el-form-item__content) {
  overflow: visible !important;

  .vn-textarea,
  .el-textarea {
    overflow: visible !important;
  }
}
</style>


<template>
  <el-dialog
    v-model="dialogVisible"
    :title="isEdit ? $t('modules.modelManagement.edit') : $t('modules.modelManagement.create')"
    width="680px"
    :append-to-body="true"
    :close-on-press-escape="false"
    :close-on-click-modal="false"
    :before-close="closeHandle"
  >
    <el-form
      ref="formRef"
      v-loading="loading"
      :model="formData"
      label-position="right"
      :rules="formRules"
      label-width="140px"
    >
      <el-form-item :label="$t('modules.modelManagement.formKind')" prop="modelKind">
        <el-select v-model="formData.modelKind" :disabled="isEdit" @change="kindChangeHandle">
          <el-option
            v-for="kind in MODEL_KINDS"
            :key="kind"
            :label="$t(KIND_LABEL_KEY[kind])"
            :value="kind"
          />
        </el-select>
      </el-form-item>

      <el-form-item :label="$t('modules.modelManagement.formName')" prop="modelName">
        <el-input
          v-model.trim="formData.modelName"
          :placeholder="$t('modules.modelManagement.formNamePlaceholder')"
          @blur="refreshThinkingCatalog"
        />
        <div class="model-form__tip">
          {{ $t('modules.modelManagement.formNameTip') }}
        </div>
      </el-form-item>

      <el-form-item :label="$t('modules.modelManagement.formDisplayName')" prop="displayName">
        <el-input v-model.trim="formData.displayName" :placeholder="$t('modules.modelManagement.formDisplayNamePlaceholder')" />
      </el-form-item>

      <el-form-item :label="$t('modules.modelManagement.formApiModel')" prop="apiModel">
        <el-input
          v-model.trim="formData.apiModel"
          :placeholder="$t('modules.modelManagement.formApiModelPlaceholder')"
          @blur="refreshThinkingCatalog"
        />
      </el-form-item>

      <el-form-item :label="$t('modules.modelManagement.formBaseUrl')" prop="baseUrl">
        <el-input
          v-model.trim="formData.baseUrl"
          :placeholder="$t('modules.modelManagement.formBaseUrlPlaceholder')"
          @blur="refreshThinkingCatalog"
        />
      </el-form-item>

      <el-form-item :label="$t('modules.modelManagement.formApiKey')" prop="apiKey">
        <el-input
          v-model.trim="formData.apiKey"
          type="password"
          show-password
          autocomplete="new-password"
          :placeholder="keyPlaceholder"
        />
        <div class="model-form__tip">
          {{ $t('modules.modelManagement.formApiKeyTip') }}
        </div>
        <el-checkbox v-if="isEdit && hasStoredKey" v-model="formData.clearApiKey">
          {{ $t('modules.modelManagement.formClearApiKey') }}
        </el-checkbox>
      </el-form-item>

      <el-form-item
        v-if="needsDimension(formData.modelKind)"
        :label="$t('modules.modelManagement.formDimension')"
        prop="dimension"
      >
        <el-input-number v-model="formData.dimension" :min="1" :max="65535" :controls="false" />
        <div class="model-form__tip">
          {{ $t('modules.modelManagement.formDimensionTip') }}
        </div>
      </el-form-item>

      <template v-if="formData.modelKind === 'llm'">
        <el-form-item :label="$t('modules.modelManagement.formMaxTokens')" prop="maxTokens">
          <el-input-number v-model="formData.maxTokens" :min="1" :controls="false" />
        </el-form-item>
        <el-form-item :label="$t('modules.modelManagement.formTemperature')" prop="temperature">
          <el-input-number v-model="formData.temperature" :min="0" :max="2" :step="0.1" :controls="false" />
        </el-form-item>
        <el-form-item :label="$t('modules.modelManagement.formReasoning')" prop="isReasoning">
          <el-switch v-model="formData.isReasoning" />
          <div class="model-form__tip">
            {{ $t('modules.modelManagement.formReasoningTip') }}
          </div>
        </el-form-item>
        <el-form-item :label="$t('modules.modelManagement.formThinkingMode')" prop="thinkingMode">
          <el-select
            v-model="formData.thinkingMode"
            class="model-form__thinking-mode"
            @change="thinkingModeChange"
          >
            <el-option
              v-for="mode in THINKING_MODES"
              :key="mode"
              :label="$t(THINKING_MODE_LABEL_KEY[mode])"
              :value="mode"
            />
          </el-select>
          <div class="model-form__tip">
            {{ $t('modules.modelManagement.formThinkingModeTip') }}
          </div>
          <div
            v-if="formData.thinkingMode === 'auto'"
            class="model-form__tip"
            :class="{ 'model-form__tip--warning': autoThinkingWarning }"
          >
            <template v-if="thinkingCatalogLoading">
              {{ $t('modules.modelManagement.thinkingPreviewLoading') }}
            </template>
            <template v-else-if="!formData.modelName && !formData.apiModel">
              {{ $t('modules.modelManagement.thinkingPreviewEmpty') }}
            </template>
            <template v-else-if="thinkingCatalogError">
              {{ $t('modules.modelManagement.thinkingPreviewFailed') }}
            </template>
            <template v-else-if="thinkingMatchedPreset">
              {{ $t('modules.modelManagement.thinkingPreviewMatched', { label: presetLabel(thinkingMatchedPreset) }) }}
            </template>
            <template v-else>
              {{ $t('modules.modelManagement.thinkingPreviewNoMatch') }}
            </template>
          </div>
        </el-form-item>

        <el-form-item
          v-if="formData.thinkingMode === 'preset'"
          :label="$t('modules.modelManagement.formThinkingPreset')"
          prop="thinkingPreset"
        >
          <el-select
            v-model="formData.thinkingPreset"
            class="model-form__thinking-preset"
            :placeholder="$t('modules.modelManagement.formThinkingPresetPlaceholder')"
          >
            <el-option
              v-for="preset in thinkingCatalog.presets"
              :key="preset.presetId"
              :label="presetLabel(preset)"
              :value="preset.presetId"
            />
          </el-select>
          <div v-if="selectedPreset" class="model-form__tip">
            {{ presetNote(selectedPreset) }}
          </div>
        </el-form-item>

        <el-form-item
          v-if="formData.thinkingMode === 'custom'"
          :label="$t('modules.modelManagement.formThinkingJson')"
          prop="thinkingCustomJson"
        >
          <el-input
            v-model="formData.thinkingCustomJson"
            class="model-form__thinking-json"
            type="textarea"
            :rows="4"
            :placeholder="$t('modules.modelManagement.formThinkingJsonPlaceholder')"
          />
          <div class="model-form__tip">
            {{ $t('modules.modelManagement.formThinkingJsonTip', { keys: thinkingCatalog.allowedPayloadKeys.join(' / ') }) }}
          </div>
        </el-form-item>

        <el-form-item
          v-if="formData.thinkingMode !== 'custom' && thinkingPreviewPayload"
          :label="$t('modules.modelManagement.thinkingPreviewTitle')"
        >
          <pre class="model-form__thinking-preview">{{ thinkingPreviewJson }}</pre>
        </el-form-item>
      </template>

      <el-form-item :label="$t('modules.modelManagement.formTimeout')" prop="timeout">
        <el-input-number v-model="formData.timeout" :min="1" :controls="false" />
      </el-form-item>

      <el-form-item :label="$t('modules.modelManagement.formDefault')" prop="isDefault">
        <el-switch v-model="formData.isDefault" />
      </el-form-item>

      <el-form-item :label="$t('modules.modelManagement.formEnabled')" prop="enabled">
        <el-switch v-model="formData.enabled" />
      </el-form-item>

      <el-form-item :label="$t('modules.modelManagement.formRemark')" prop="remark">
        <el-input v-model.trim="formData.remark" type="textarea" :rows="2" />
      </el-form-item>

      <!--
        路径覆盖默认收起：实测过不同实现路径确实不同（契约里三次踩坑），
        所以必须可配；但绝大多数端点用的是标准路径，摊开只会让人以为「必填」。
      -->
      <el-collapse-transition>
        <div v-show="advancedVisible">
          <el-form-item
            v-for="field in pathFields"
            :key="field"
            :label="$t(PATH_LABEL_KEY[field])"
            :prop="field"
          >
            <el-input v-model.trim="formData[field]" :placeholder="PATH_PLACEHOLDER[formData.modelKind][field] || ''" />
          </el-form-item>
        </div>
      </el-collapse-transition>
      <el-form-item>
        <el-button text @click="advancedVisible = !advancedVisible">
          {{ advancedVisible ? $t('modules.modelManagement.advancedHide') : $t('modules.modelManagement.advanced') }}
        </el-button>
        <span class="model-form__tip model-form__tip--inline">
          {{ $t('modules.modelManagement.advancedTip') }}
        </span>
      </el-form-item>

      <!-- 连接测试结果（表格）：行序、文案与列表行弹窗共用同一个组件 -->
      <div v-if="testResult" class="model-form__result">
        <ModelTestResultTable
          :result="testResult"
          :kind="formData.modelKind"
          :registered-dimension="formData.dimension"
        />
      </div>
    </el-form>

    <template #footer>
      <el-button :loading="testing" @click="testHandle">
        {{ testing ? $t('modules.modelManagement.testing') : $t('modules.modelManagement.test') }}
      </el-button>
      <el-button :disabled="saveDisabled" type="primary" @click="submitHandle">
        {{ $t('public.confirm') }}
      </el-button>
      <el-button plain @click="closeHandle">
        {{ $t('public.cancel') }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, getCurrentInstance, ref } from 'vue'
import {
  createModelApi,
  getThinkingPresetsApi,
  testModelConfigApi,
  testModelApi,
  updateModelApi
} from '@/features/model/api/model.js'
import {
  KIND_LABEL_KEY,
  MODEL_KINDS,
  ModelKind,
  ModelTestResult,
  needsDimension,
  PATH_PLACEHOLDER,
  THINKING_MODE_LABEL_KEY,
  THINKING_MODES,
  ThinkingCatalog,
  ThinkingMode,
  ThinkingPreset
} from './type'
import ModelTestResultTable from './ModelTestResultTable.vue'

const props = defineProps({
  /** 当前页签的类型：新建时的默认值 */
  kind: { type: String, default: 'llm' }
})

const emits = defineEmits(['refreshTableData'])
const { proxy } = getCurrentInstance() as any

const PATH_LABEL_KEY: Record<string, string> = {
  chatPath: 'modules.modelManagement.formChatPath',
  embeddingsPath: 'modules.modelManagement.formEmbeddingsPath',
  modelsPath: 'modules.modelManagement.formModelsPath',
  rerankPath: 'modules.modelManagement.formRerankPath'
}

/** 每类模型要显示哪几个路径输入框（与后端 supported_operations 对应；models 只有 LLM 有） */
const PATHS_BY_KIND: Record<ModelKind, string[]> = {
  llm: ['chatPath', 'modelsPath'],
  embedding: ['embeddingsPath'],
  rerank: ['rerankPath']
}

/** 表单模型：**只含可提交的字段**，列表行上的审计字段一概不进来（见 buildPayload） */
interface ModelForm {
  modelId: string
  modelKind: ModelKind
  modelName: string
  displayName: string
  apiModel: string
  baseUrl: string
  apiKey: string
  clearApiKey: boolean
  chatPath: string
  embeddingsPath: string
  modelsPath: string
  rerankPath: string
  dimension: number | null
  maxTokens: number | null
  temperature: number | null
  timeout: number | null
  isReasoning: boolean
  thinkingMode: ThinkingMode
  thinkingPreset: string
  thinkingPayload: Record<string, unknown> | null
  /** UI-only：自定义 JSON 文本框，不直接提交（提交的是解析后的 thinkingPayload） */
  thinkingCustomJson: string
  isDefault: boolean
  enabled: boolean
  remark: string
}

const SUBMITTABLE_FIELDS: (keyof ModelForm)[] = [
  'modelKind', 'modelName', 'displayName', 'apiModel', 'baseUrl', 'apiKey',
  'chatPath', 'embeddingsPath', 'modelsPath', 'rerankPath',
  'dimension', 'maxTokens', 'temperature', 'timeout',
  'isReasoning', 'thinkingMode', 'thinkingPreset', 'thinkingPayload',
  'isDefault', 'enabled', 'remark'
]

/**
 * 列表行 → 表单要拷的字段 = 可提交字段 + `modelId`。
 *
 * ⚠️ `modelId` **必须**在这份名单里：`isEdit` 全靠它判 ——
 * 弹窗标题、保存走 PUT 还是 POST、编辑态「连接测试」打哪条接口，三处分支都看它。
 * 缺了它 openDialog(row) 后 `formData.modelId` 恒空 → 编辑被当成新建
 * （POST 建出重复行、标题显示「新建模型」）。
 *
 * 但它**不进请求体**（PUT 的路径里已经带了），所以 buildPayload 仍只按 SUBMITTABLE_FIELDS
 * —— 两件事别合并回一张表。
 */
const ROW_COPY_FIELDS: (keyof ModelForm)[] = ['modelId', ...SUBMITTABLE_FIELDS]

function getInitFormData (): ModelForm {
  return {
    modelId: '',
    modelKind: 'llm',
    modelName: '',
    displayName: '',
    apiModel: '',
    baseUrl: '',
    apiKey: '',
    clearApiKey: false,
    chatPath: '',
    embeddingsPath: '',
    modelsPath: '',
    rerankPath: '',
    dimension: null,
    maxTokens: null,
    temperature: null,
    timeout: null,
    isReasoning: false,
    thinkingMode: 'auto',
    thinkingPreset: '',
    thinkingPayload: null,
    thinkingCustomJson: '',
    isDefault: false,
    enabled: true,
    remark: ''
  }
}

const dialogVisible = ref(false)
const loading = ref(false)
const testing = ref(false)
const saveDisabled = ref(false)
const advancedVisible = ref(false)
const testResult = ref<ModelTestResult | null>(null)
const hasStoredKey = ref(false)
/** 已保存密钥的脱敏值，**只用来做占位提示**（不回填输入框，见 openDialog） */
const storedKeyMask = ref('')
const formRef = ref()
const formData = ref(getInitFormData())

const isEdit = computed(() => Boolean(formData.value.modelId))
const pathFields = computed(() => PATHS_BY_KIND[formData.value.modelKind] || [])
// ⚠️ `storedKeyMask.value` 的 `.value` 不能省：computed 里返回**ref 本身**的话，
// 模板把 ref 对象字符串化 → placeholder 渲染成 `[object Object]`（B6 实拍，zh/en 均现）。
const keyPlaceholder = computed(() => (hasStoredKey.value ? storedKeyMask.value : ''))
// 结果标题/行文案在 ModelTestResultTable 里（状态行 + 表格行），这里不再保留。

const DEFAULT_THINKING_KEYS = [
  'chat_template_kwargs', 'thinking', 'reasoning_effort', 'enable_thinking', 'google'
]
const thinkingCatalog = ref<ThinkingCatalog>({
  presets: [],
  matchedPresetId: '',
  matchedBy: '',
  confidence: '',
  warning: '',
  allowedPayloadKeys: DEFAULT_THINKING_KEYS,
  maxPayloadBytes: 8192,
  modes: THINKING_MODES
})
const thinkingCatalogLoading = ref(false)
const thinkingCatalogError = ref(false)
const isZh = computed(() => String(proxy.$i18n?.locale || 'zh').startsWith('zh'))

function presetLabel (preset: ThinkingPreset | null): string {
  if (!preset) {
    return ''
  }
  return isZh.value ? preset.label : preset.labelEn
}

function presetNote (preset: ThinkingPreset | null): string {
  if (!preset) {
    return ''
  }
  const confidence = preset.confidence === 'verified'
    ? proxy.$t('modules.modelManagement.thinkingConfidenceVerified')
    : proxy.$t('modules.modelManagement.thinkingConfidenceStandard')
  const note = isZh.value ? preset.note : preset.noteEn
  return `${confidence} · ${note}`
}

const thinkingMatchedPreset = computed(() => (
  thinkingCatalog.value.presets.find(
    preset => preset.presetId === thinkingCatalog.value.matchedPresetId) || null
))
const selectedPreset = computed(() => (
  thinkingCatalog.value.presets.find(
    preset => preset.presetId === formData.value.thinkingPreset) || null
))
const autoThinkingWarning = computed(() => (
  formData.value.thinkingMode === 'auto'
  && Boolean(formData.value.modelName || formData.value.apiModel)
  && !thinkingCatalogLoading.value
  && !thinkingMatchedPreset.value
))
const thinkingPreviewPayload = computed(() => {
  if (formData.value.modelKind !== 'llm') {
    return null
  }
  if (formData.value.thinkingMode === 'auto') {
    return thinkingMatchedPreset.value?.payload || null
  }
  if (formData.value.thinkingMode === 'preset') {
    return selectedPreset.value?.payload || formData.value.thinkingPayload || null
  }
  return null
})
const thinkingPreviewJson = computed(() => (
  thinkingPreviewPayload.value ? JSON.stringify(thinkingPreviewPayload.value, null, 2) : ''
))

async function refreshThinkingCatalog () {
  if (formData.value.modelKind !== 'llm') {
    return
  }
  thinkingCatalogLoading.value = true
  thinkingCatalogError.value = false
  try {
    const response: any = await getThinkingPresetsApi({
      modelName: formData.value.modelName,
      apiModel: formData.value.apiModel,
      baseUrl: formData.value.baseUrl
    }, { skipErrorHandler: true })
    const data = response && typeof response === 'object' ? response : {}
    thinkingCatalog.value = {
      presets: Array.isArray(data.presets) ? data.presets : [],
      matchedPresetId: data.matchedPresetId || '',
      matchedBy: data.matchedBy || '',
      confidence: data.confidence || '',
      warning: data.warning || '',
      allowedPayloadKeys: Array.isArray(data.allowedPayloadKeys) && data.allowedPayloadKeys.length
        ? data.allowedPayloadKeys
        : DEFAULT_THINKING_KEYS,
      maxPayloadBytes: Number(data.maxPayloadBytes) || 8192,
      modes: Array.isArray(data.modes) && data.modes.length ? data.modes : THINKING_MODES
    }
  } catch (error) {
    thinkingCatalogError.value = true
    thinkingCatalog.value = {
      ...thinkingCatalog.value,
      presets: [],
      matchedPresetId: '',
      warning: ''
    }
  } finally {
    thinkingCatalogLoading.value = false
  }
}

function thinkingModeChange (mode: ThinkingMode) {
  if (mode === 'auto') {
    refreshThinkingCatalog()
  }
  if (mode === 'custom' && !formData.value.thinkingCustomJson
      && formData.value.thinkingPayload) {
    formData.value.thinkingCustomJson = JSON.stringify(formData.value.thinkingPayload, null, 2)
  }
}

/** 自定义 JSON → 对象；解析失败/非对象返回 null（表单校验会先拦住）。 */
function customThinkingPayload (): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(formData.value.thinkingCustomJson || '')
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return null
    }
    return parsed
  } catch (error) {
    return null
  }
}

const formRules = computed(() => ({
  modelName: [{ required: true, message: proxy.$t('modules.modelManagement.nameRequired'), trigger: 'blur' }],
  baseUrl: [
    { required: true, message: proxy.$t('modules.modelManagement.baseUrlRequired'), trigger: 'blur' },
    {
      validator: (_rule: any, value: string, callback: (error?: Error) => void) => {
        if (!value || /^https?:\/\//i.test(value)) {
          return callback()
        }
        callback(new Error(proxy.$t('modules.modelManagement.baseUrlInvalid')))
      },
      trigger: 'blur'
    }
  ],
  dimension: [
    {
      validator: (_rule: any, value: any, callback: (error?: Error) => void) => {
        if (!needsDimension(formData.value.modelKind)) {
          return callback()
        }
        if (value === null || value === undefined || value === '') {
          return callback(new Error(proxy.$t('modules.modelManagement.dimensionRequired')))
        }
        if (!Number.isInteger(Number(value)) || Number(value) <= 0) {
          return callback(new Error(proxy.$t('modules.modelManagement.dimensionInvalid')))
        }
        callback()
      },
      trigger: 'blur'
    }
  ],
  thinkingPreset: [
    {
      validator: (_rule: any, value: string, callback: (error?: Error) => void) => {
        if (formData.value.thinkingMode !== 'preset' || value) {
          return callback()
        }
        callback(new Error(proxy.$t('modules.modelManagement.thinkingPresetRequired')))
      },
      trigger: 'change'
    }
  ],
  thinkingCustomJson: [
    {
      validator: (_rule: any, value: string, callback: (error?: Error) => void) => {
        if (formData.value.thinkingMode !== 'custom') {
          return callback()
        }
        const text = (value || '').trim()
        if (!text) {
          return callback(new Error(proxy.$t('modules.modelManagement.thinkingJsonRequired')))
        }
        let parsed: any
        try {
          parsed = JSON.parse(text)
        } catch (error) {
          return callback(new Error(proxy.$t('modules.modelManagement.thinkingJsonInvalid')))
        }
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
          return callback(new Error(proxy.$t('modules.modelManagement.thinkingJsonMustBeObject')))
        }
        const keys = Object.keys(parsed)
        if (!keys.length) {
          return callback(new Error(proxy.$t('modules.modelManagement.thinkingJsonEmpty')))
        }
        const allowed = thinkingCatalog.value.allowedPayloadKeys || DEFAULT_THINKING_KEYS
        const unknown = keys.find(key => !allowed.includes(key))
        if (unknown) {
          return callback(new Error(proxy.$t(
            'modules.modelManagement.thinkingJsonKeyInvalid', { key: unknown })))
        }
        const size = new TextEncoder().encode(JSON.stringify(parsed)).length
        if (size > thinkingCatalog.value.maxPayloadBytes) {
          return callback(new Error(proxy.$t(
            'modules.modelManagement.thinkingJsonTooLarge',
            { max: thinkingCatalog.value.maxPayloadBytes })))
        }
        callback()
      },
      trigger: 'blur'
    }
  ]
}))

function kindChangeHandle () {
  // 换类型后之前那几个路径字段不再适用，清掉免得提交上去一个张冠李戴的覆盖值
  const allowed = PATHS_BY_KIND[formData.value.modelKind] || []
  for (const field of ['chatPath', 'embeddingsPath', 'modelsPath', 'rerankPath']) {
    if (!allowed.includes(field)) {
      formData.value[field] = ''
    }
  }
  // 思考配置只对 LLM 有意义：切走时清空，避免隐藏值被提交
  if (formData.value.modelKind !== 'llm') {
    formData.value.thinkingMode = 'none'
    formData.value.thinkingPreset = ''
    formData.value.thinkingPayload = null
    formData.value.thinkingCustomJson = ''
  }
}

function openDialog (row?: any) {
  closeHandle()
  dialogVisible.value = true
  if (row) {
    hasStoredKey.value = Boolean(row.hasApiKey)
    storedKeyMask.value = row.apiKeyMasked || ''
    const base: ModelForm = {
      ...getInitFormData(),
      ...pickRowFields(row),
      // 后端只回脱敏值，**不能**把它当明文放回输入框：留空 = 不改动库里那把
      apiKey: '',
      clearApiKey: false
    }
    let mode: ThinkingMode = base.thinkingMode
    if (base.modelKind !== 'llm') {
      mode = 'none'
    } else if (!mode) {
      mode = 'none'
    }
    const payload = base.thinkingPayload && typeof base.thinkingPayload === 'object'
      ? base.thinkingPayload
      : null
    formData.value = {
      ...base,
      thinkingMode: mode,
      thinkingPreset: mode === 'preset' ? (base.thinkingPreset || '') : '',
      thinkingPayload: payload,
      thinkingCustomJson: payload ? JSON.stringify(payload, null, 2) : ''
    }
  } else {
    const kind = (props.kind as ModelKind) || 'llm'
    formData.value = {
      ...getInitFormData(),
      modelKind: kind,
      // 新 LLM 默认自动匹配；其它类型没有思考配置
      thinkingMode: kind === 'llm' ? 'auto' : 'none'
    }
  }
  formRef.value?.clearValidate()
  if (formData.value.modelKind === 'llm') {
    refreshThinkingCatalog()
  }
}

/** 列表行 → 表单字段（**白名单**：行上还有 createTime/source/hasApiKey 等审计字段） */
function pickRowFields (row: any): Partial<ModelForm> {
  const picked: Record<string, any> = {}
  for (const field of ROW_COPY_FIELDS) {
    if (row[field] !== undefined && field !== 'apiKey' && field !== 'clearApiKey') {
      picked[field] = row[field]
    }
  }
  return picked
}

function closeHandle () {
  formData.value = getInitFormData()
  hasStoredKey.value = false
  storedKeyMask.value = ''
  testResult.value = null
  advancedVisible.value = false
  dialogVisible.value = false
}

/** 表单值 → 请求体。``clearApiKey`` 只在编辑且勾选时带上（后端按「缺省 = 保留」实现） */
function buildPayload () {
  const data: Record<string, any> = {}
  for (const field of SUBMITTABLE_FIELDS) {
    data[field] = formData.value[field]
  }
  if (formData.value.modelKind !== 'llm') {
    data.thinkingMode = 'none'
    data.thinkingPreset = ''
    data.thinkingPayload = null
  } else if (data.thinkingMode === 'custom') {
    data.thinkingPayload = customThinkingPayload()
    data.thinkingPreset = ''
  } else if (data.thinkingMode === 'preset') {
    // preset 由后端按目录快照，前端不传 payload
    data.thinkingPayload = null
  } else {
    data.thinkingPreset = ''
    data.thinkingPayload = null
  }
  if (!isEdit.value || !formData.value.clearApiKey) {
    delete data.clearApiKey
  }
  return data
}

function testHandle () {
  formRef.value.validate(async (valid: boolean) => {
    if (!valid) {
      return
    }
    testing.value = true
    testResult.value = null
    try {
      const payload = buildPayload()
      // 编辑态且没重填 key：让后端用库里那把测（前端根本拿不到明文）
      const result: any = isEdit.value && !payload.apiKey && hasStoredKey.value
        ? await testModelApi(formData.value.modelId, payload, { skipErrorHandler: true })
        : await testModelConfigApi(payload, { skipErrorHandler: true })
      testResult.value = result
    } catch (error: any) {
      testResult.value = {
        ok: false, probed: null, models: null, dimension: null,
        dimensionMatches: null, latencyMs: 0,
        message: error?.detail || error?.message || ''
      }
    } finally {
      testing.value = false
    }
  })
}

function submitHandle () {
  // 同步双击会在 Vue 把 `saveDisabled` 刷到 DOM 之前再次进入这里；
  // 只看按钮 disabled 挡不住（E2E RES-07 实测两次 POST），必须在入口再判一次。
  if (saveDisabled.value) {
    return
  }
  formRef.value.validate(async (valid: boolean) => {
    // 两次 click 都会进到这里；第一次的回调把 saveDisabled 置 true 后，
    // 第二次必须在这里被拦住（入口那一道拦不住同步双击）。
    if (!valid || saveDisabled.value) {
      return
    }
    saveDisabled.value = true
    try {
      const payload = buildPayload()
      if (isEdit.value) {
        await updateModelApi(formData.value.modelId, payload)
      } else {
        await createModelApi(payload)
      }
      proxy.$message.success(proxy.$t('modules.modelManagement.saveSuccess'))
      emits('refreshTableData')
      closeHandle()
    } catch (error) {
      // 错误提示由 axios 拦截器统一弹（除非调用方 skipErrorHandler）
    } finally {
      saveDisabled.value = false
    }
  })
}

defineExpose({ openDialog })
</script>

<style scoped lang="less">
.model-form__tip {
    // ⚠️ 别用 `--el-color-info-light-*` 当文字色：那是**边框/填充**色阶。
  // light-4 = #D9D9D9，压在 #E9EDF7 底上对比度约 **1.2:1**（AA 要 4.5:1），
  // 用户实测反馈「看不清」。`--el-text-color-regular`(#606266) 在这两个底色上
  // 分别是 5.2:1 / 6.1:1，都过 AA。
  color: var(--el-text-color-regular);
  font-size: 12px;
  line-height: 18px;
  margin-top: 2px;
}

.model-form__tip--inline {
  margin-left: 8px;
  display: inline-block;
}

.model-form__tip--warning {
  color: var(--el-color-warning);
}

.model-form__thinking-preview {
  width: 100%;
  max-height: 140px;
  margin: 0;
  padding: 8px 10px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 18px;
  color: var(--el-text-color-regular);
  background: var(--el-fill-color-light);
  border-radius: var(--el-border-radius-base);
}

.model-form__thinking-json :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.model-form__result {
  margin-bottom: 8px;
}
</style>

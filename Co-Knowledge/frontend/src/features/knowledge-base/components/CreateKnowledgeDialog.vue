<template>
  <el-dialog v-model="open" class="create-knowledge-dialog" width="800px" align-center append-to-body destroy-on-close :close-on-click-modal="false" :close-on-press-escape="!submitting" :show-close="!submitting" @opened="nameInput?.focus()">
    <template #header="{ titleId }">
      <div class="kb-dialog-heading">
        <span class="kb-heading-icon"><Collection/></span>
        <div><h2 :id="titleId">{{ graph ? $t('modules.studioDialogs.createKnowledge.titleGraph') : $t('modules.studioDialogs.createKnowledge.title') }}</h2><p class="text-secondary">{{ graph ? $t('modules.studioDialogs.createKnowledge.graphSubtitle') : $t('modules.studioDialogs.createKnowledge.subtitle') }}</p></div>
      </div>
    </template>

    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="kb-create-form" @submit.prevent="submit">
      <section class="kb-form-section" aria-labelledby="kb-basic-title">
        <div class="kb-section-heading"><span class="kb-section-number text-caption">01</span><h3 id="kb-basic-title" class="text-section-title">{{ $t('modules.studioDialogs.createKnowledge.sectionBasic') }}</h3><span class="text-caption kb-section-note">{{ graph ? $t('modules.studioDialogs.createKnowledge.graphBasicNote') : $t('modules.studioDialogs.createKnowledge.sectionBasicNote') }}</span></div>
        <div :class="['kb-field-grid', { 'kb-field-grid-single': graph }]">
          <el-form-item :label="$t('modules.studioDialogs.createKnowledge.name')" prop="name"><el-input ref="nameInput" v-model="form.name" :placeholder="$t('modules.studioDialogs.createKnowledge.namePlaceholder')" maxlength="30" show-word-limit autocomplete="off"/></el-form-item>
          <el-form-item v-if="!graph" :label="$t('modules.studioDialogs.createKnowledge.model')" prop="model">
            <el-select v-model="form.model" :aria-label="$t('modules.studioDialogs.createKnowledge.model')"><template #prefix><LayersIcon class="kb-model-icon"/></template><el-option v-for="model in modelOptions" :key="model.name" :label="model.name" :value="model.name"><span>{{ model.name }}</span><span v-if="model.recommended" class="kb-option-hint text-caption">{{ $t('modules.studioDialogs.createKnowledge.modelDefault') }}</span></el-option></el-select>
          </el-form-item>
        </div>
        <div v-if="!graph" class="kb-model-note text-caption"><InfoFilled/>{{ $t('modules.studioDialogs.createKnowledge.modelNote') }}</div>
        <el-form-item prop="description" :class="['kb-description', { 'kb-graph-description': graph }]"><template #label>{{ $t('modules.studioDialogs.createKnowledge.description') }} <span class="kb-optional text-caption">{{ $t('modules.studioDialogs.common.optional') }}</span></template><el-input v-model="form.description" type="textarea" :rows="2" resize="none" :placeholder="$t('modules.studioDialogs.createKnowledge.descriptionPlaceholder')" maxlength="1000" show-word-limit/></el-form-item>
      </section>

      <section v-if="graph" class="kb-form-section kb-graph-config" aria-labelledby="kb-graph-config-title">
        <div class="kb-section-heading"><span class="kb-section-number text-caption">02</span><h3 id="kb-graph-config-title" class="text-section-title">{{ $t('modules.studioDialogs.createKnowledge.sectionGraphConfig') }}</h3><span class="text-caption kb-section-note">{{ $t('modules.studioDialogs.createKnowledge.sectionGraphConfigNote') }}</span></div>
        <div class="kb-field-grid">
          <el-form-item :label="$t('modules.studioDialogs.createKnowledge.model')" prop="model">
            <el-select v-model="form.model" :aria-label="$t('modules.studioDialogs.createKnowledge.model')"><template #prefix><LayersIcon class="kb-model-icon"/></template><el-option v-for="model in modelOptions" :key="model.name" :label="model.name" :value="model.name"/></el-select>
          </el-form-item>
          <el-form-item :label="$t('modules.studioDialogs.createKnowledge.operator')" prop="operatorId">
            <el-select v-model="form.operatorId" :aria-label="$t('modules.studioDialogs.createKnowledge.operator')" :placeholder="$t('modules.studioDialogs.createKnowledge.operatorPlaceholder')" :loading="optionsLoading" clearable filterable @change="handleOperatorChange">
              <el-option v-for="operator in operators" :key="operator.id" :label="operatorLabel(operator)" :value="operator.id"/>
            </el-select>
          </el-form-item>
        </div>
        <p class="kb-model-note kb-config-note text-caption"><InfoFilled/>{{ selectedOperator?.description || operatorNoteFallback }}</p>
        <p v-if="optionsError" class="kb-options-error text-caption" role="alert">{{ optionsError }}</p>
        <div v-if="selectedOperator" class="kb-operator-fields">
          <template v-for="arg in operatorArgs" :key="arg.argName">
            <el-form-item v-if="arg.argName === 'schemaId'" :label="$t('modules.studioDialogs.createKnowledge.graphTemplate')" :error="argErrorText('schemaId')">
              <el-select v-model="params.schemaId" :aria-label="$t('modules.studioDialogs.createKnowledge.graphTemplate')" :placeholder="$t('modules.studioDialogs.createKnowledge.graphTemplatePlaceholder')" filterable clearable @change="clearArgError('schemaId')">
                <el-option v-for="template in templates" :key="template.schemaId || template.id" :label="template.schemaName || template.name" :value="template.schemaId || template.id"/>
              </el-select>
            </el-form-item>
            <el-form-item v-else-if="arg.argName === 'llm'" :label="$t('modules.studioDialogs.createKnowledge.llmModel')" :error="argErrorText('llm')">
              <el-select v-model="params.llm" :aria-label="$t('modules.studioDialogs.createKnowledge.llmModel')" :placeholder="$t('modules.studioDialogs.createKnowledge.llmPlaceholder')" filterable clearable @change="clearArgError('llm')">
                <el-option v-for="model in llmModels" :key="model.value || model.id || model" :label="model.label || model.name || model.value || model" :value="model.value || model.id || model"/>
              </el-select>
            </el-form-item>
            <el-form-item v-else-if="arg.argName === 'extractionProfile'" :label="$t('modules.kb.graphArgExtractionProfile')" :error="argErrorText('extractionProfile')">
              <el-select v-model="params.extractionProfile" :aria-label="$t('modules.kb.graphArgExtractionProfile')" @change="clearArgError('extractionProfile')">
                <el-option :label="$t('modules.kb.extractionProfileGeneral')" value="general"/>
                <el-option :label="$t('modules.kb.extractionProfileAttributes')" value="general_attributes"/>
              </el-select>
            </el-form-item>
            <el-form-item v-else-if="isIntegerArg(arg)" :label="argLabel(arg)" :error="argErrorText(arg.argName)">
              <el-input-number v-model="params[arg.argName]" :aria-label="argLabel(arg)" :min="numberMin(arg)" :max="numberMax(arg)" :precision="0" :step="1" controls-position="right" @change="clearArgError(arg.argName)"/>
            </el-form-item>
            <el-form-item v-else :label="argLabel(arg)" :error="argErrorText(arg.argName)">
              <el-input v-model="params[arg.argName]" :aria-label="argLabel(arg)" :placeholder="argPlaceholder(arg)" @input="clearArgError(arg.argName)"/>
            </el-form-item>
          </template>
        </div>
      </section>

      <section class="kb-form-section kb-documents" aria-labelledby="kb-documents-title">
        <div class="kb-section-heading"><span class="kb-section-number text-caption">{{ graph ? '03' : '02' }}</span><h3 id="kb-documents-title" class="text-section-title">{{ $t('modules.studioDialogs.createKnowledge.sectionDocuments') }}</h3><span class="text-caption kb-section-note">{{ $t('modules.studioDialogs.createKnowledge.sectionDocumentsNote') }}</span></div>
        <KnowledgeFilePicker v-model="files" :title="$t('modules.studioDialogs.createKnowledge.filesHeading')" :active-file-limits="activeFileLimits" :max-files="maxFiles" :max-total-bytes="maxTotalBytes"/>
      </section>
    </el-form>

    <template #footer>
      <div class="kb-dialog-footer">
        <!-- 提交失败的就地提示：
             服务端返回错误（如重名 409）时只有右上角一条 3 秒的 toast，弹窗本身
             没有任何变化，用户盯着表单会觉得「点了没反应」。这里把错误原因同时
             落到弹窗底部，直到下次提交或改字段才消失。 -->
        <p v-if="submitError" class="kb-submit-error" role="alert">
          <WarningFilled/>{{ submitError }}
        </p>
        <span class="kb-footer-hint text-caption"><InfoFilled/>{{ footerHint }}</span>
        <div class="kb-footer-actions">
          <el-button :disabled="submitting" @click="open = false">{{ $t('modules.studioDialogs.common.cancel') }}</el-button>
          <el-button type="primary" :loading="submitting" :disabled="!canSubmit" @click="submit"><Plus/>{{ graph ? $t('modules.studioDialogs.createKnowledge.graphSubmit') : $t('modules.studioDialogs.createKnowledge.createButton') }}</el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Collection, InfoFilled, Plus, WarningFilled } from '@element-plus/icons-vue'
import { $t } from '@/app/i18n/i18n.js'
import { LayersIcon } from '@/shared/ui/icons'
import KnowledgeFilePicker from './KnowledgeFilePicker.vue'
import { fileLimits, formatFileSize } from '../lib/knowledge-files'
import { getOperatorListApi, knowledgeGraphTemplateListApi, getLlmListApi, extractKnowledgeGraphApi } from '@/features/graph/api/knowledgeGraph'
import {
  buildGraphExtractPayload,
  defaultBuildParams,
  isIntegerArg,
  orderedOperatorArgs,
  validateBuildParams,
  CHUNK_SIZE_MIN,
  CHUNK_SIZE_MAX,
  OVERLAP_MIN,
  OVERLAP_MAX
} from '@/features/graph/lib/graph-build-config'

const open = defineModel({ type: Boolean, default: false })
const props = defineProps({
  graph: Boolean,
  template: { type: String, default: '' },
  existingNames: { type: Array, default: () => [] },
  /** 真实部署的向量模型（来自 /embedding/all）；为空时回落到两条演示值 */
  models: { type: Array, default: () => [] },
  /** 真实部署的文件上限（来自 GET /file/size_limit）；缺省使用固定值 */
  activeFileLimits: { type: Array, default: () => fileLimits },
  maxFiles: { type: Number, default: 50 },
  maxTotalBytes: { type: Number, default: 650 * 1024 ** 2 },
  /** 由父级注入的真实创建动作；返回 Promise 时才关闭弹窗（失败保持打开） */
  submitHandler: { type: Function, default: null }
})
const { t, locale } = useI18n()
const emit = defineEmits(['create'])
const formRef = ref()
const nameInput = ref()
const files = ref([])
const submitting = ref(false)
/** 提交失败的就地文案（服务端 detail 优先）；空串表示没有错误 */
const submitError = ref('')
let openSession = 0
const form = reactive({ name: '', model: '', description: '', operatorId: '' })

/* ── 建图配置（只有图谱入口才有） ─────────────────────────────── */
const operators = ref([])
const operatorArgs = ref([])
const templates = ref([])
const llmModels = ref([])
const params = reactive({})
const argErrors = ref({})
const optionsLoading = ref(false)
const optionsError = ref('')

const modelOptions = computed(() => props.models.filter(model => model && model.name))
const selectedOperator = computed(() => operators.value.find(operator => String(operator.id) === String(form.operatorId)) || null)
const operatorNoteFallback = computed(() => t('modules.studioDialogs.createKnowledge.operatorNote'))
const footerHint = computed(() => {
  if (props.graph) {
    return files.value.length
      ? t('modules.studioDialogs.createKnowledge.graphFooterSelected', { count: files.value.length, size: formatFileSize(totalBytes.value) })
      : t('modules.studioDialogs.createKnowledge.graphFooterHint')
  }
  return files.value.length
    ? t('modules.studioDialogs.createKnowledge.footerSelected', { count: files.value.length, size: formatFileSize(totalBytes.value) })
    : t('modules.studioDialogs.createKnowledge.footerHint')
})

function operatorLabel (operator) {
  const zh = locale.value === 'zh'
  return zh ? operator.name || operator.nameEn : operator.nameEn || operator.name
}

function argLabel (arg) {
  return arg.description || arg.argName
}

function argPlaceholder (arg) {
  return String(arg.defaultValue ?? '')
}

function numberMin (arg) {
  return arg.argName === 'chunkSize' ? CHUNK_SIZE_MIN : OVERLAP_MIN
}

function numberMax (arg) {
  return arg.argName === 'chunkSize' ? CHUNK_SIZE_MAX : OVERLAP_MAX
}

function argErrorText (name) {
  switch (argErrors.value[name]) {
    case 'required': return t('modules.studioDialogs.createKnowledge.argRequired')
    case 'integer': return t('modules.studioDialogs.createKnowledge.argInteger')
    case 'chunkSizeRange': return t('modules.studioDialogs.createKnowledge.argChunkSizeRange')
    case 'overlapRange': return t('modules.studioDialogs.createKnowledge.argOverlapRange')
    case 'overlapLessThanChunkSize': return t('modules.studioDialogs.createKnowledge.argOverlapLessThanChunkSize')
    default: return ''
  }
}

function clearArgError (name) {
  if (!name || !argErrors.value[name]) {
    return
  }
  const next = { ...argErrors.value }
  delete next[name]
  argErrors.value = next
}

/** 算子切换：清空旧参数，按新算子的 args 生成默认值与数据源。 */
async function handleOperatorChange () {
  const operator = selectedOperator.value
  operatorArgs.value = orderedOperatorArgs(operator?.args)
  Object.keys(params).forEach(key => delete params[key])
  Object.assign(params, defaultBuildParams(operatorArgs.value))
  argErrors.value = {}
  const names = operatorArgs.value.map(arg => arg.argName)
  if (names.includes('schemaId') && !templates.value.length) {
    await loadTemplates()
  }
  if (names.includes('llm') && !llmModels.value.length) {
    await loadLlmModels()
  }
}

async function loadTemplates () {
  try {
    const list = await knowledgeGraphTemplateListApi({}, {})
    templates.value = Array.isArray(list) ? list : []
  } catch (error) {
    templates.value = []
  }
}

async function loadLlmModels () {
  try {
    const list = await getLlmListApi()
    llmModels.value = Array.isArray(list) ? list : []
  } catch (error) {
    llmModels.value = []
  }
}

async function loadGraphOptions () {
  optionsLoading.value = true
  optionsError.value = ''
  try {
    operators.value = await getOperatorListApi('graph_extract')
  } catch (error) {
    operators.value = []
    optionsError.value = t('modules.studioDialogs.createKnowledge.graphOptionsFailed')
  } finally {
    optionsLoading.value = false
  }
  // 模板 / 大模型按算子参数按需加载；这里先并行取一次，避免切算子时下拉为空
  await Promise.all([loadTemplates(), loadLlmModels()])
}

const totalBytes = computed(() => files.value.reduce((sum, file) => sum + file.size, 0))

function graphNameError (name) {
  if (!name) {
    return t('modules.studioDialogs.createKnowledge.nameRequired')
  }
  if (name.length < 2 || name.length > 30) {
    return t('modules.studioDialogs.createKnowledge.graphNameValidation')
  }
  if (/^\s+$/.test(name) || !/^[\w一-龥.\-\s]+$/.test(name)) {
    return t('modules.studioDialogs.createKnowledge.graphNameValidation')
  }
  return ''
}

const rules = {
  name: [{
    required: true,
    validator: (_rule, value, callback) => {
      const name = (value || '').trim()
      const duplicate = props.existingNames.some(existing => String(existing).toLowerCase() === name.toLowerCase())
      if (props.graph) {
        const error = graphNameError(name)
        if (error) {
          callback(new Error(error))
          return
        }
      } else if (!name) {
        callback(new Error($t('modules.studioDialogs.createKnowledge.nameRequired')))
        return
      } else if (name.length < 2 || name.length > 30) {
        // 与后端 KbaseReqDTO.name 的 @Pattern（2~30）对齐：以前只有 maxlength=64，
        // 31~64 字的名字能填进来、到提交时才被服务端拒（且当时没有行内提示）。
        callback(new Error($t('modules.studioDialogs.createKnowledge.nameLength')))
        return
      }
      if (duplicate) {
        callback(new Error($t('modules.studioDialogs.createKnowledge.nameDuplicate')))
        return
      }
      callback()
    },
    trigger: 'blur'
  }],
  model: [{
    required: true,
    validator: (_rule, value, callback) => {
      if (!value) {
        callback(new Error($t('modules.studioDialogs.createKnowledge.modelRequired')))
      } else {
        callback()
      }
    },
    trigger: 'change'
  }],
  operatorId: [{
    required: true,
    validator: (_rule, _value, callback) => {
      if (props.graph && !selectedOperator.value) {
        callback(new Error(t('modules.studioDialogs.createKnowledge.operatorRequired')))
      } else {
        callback()
      }
    },
    trigger: 'change'
  }]
}

const canSubmit = computed(() => {
  if (!form.name.trim() || !files.value.length || !form.model) {
    return false
  }
  if (!props.graph) {
    return true
  }
  if (!selectedOperator.value) {
    return false
  }
  return Object.keys(validateBuildParams(operatorArgs.value, params)).length === 0
})

watch(open, value => {
  if (!value) {
    return
  }
  Object.assign(form, {
    name: props.template,
    model: modelOptions.value[0]?.name || '',
    description: props.template ? `${props.template}${$t('modules.studioDialogs.createKnowledge.templateSuffix')}` : '',
    operatorId: ''
  })
  openSession += 1
  files.value = []
  submitting.value = false
  submitError.value = ''
  argErrors.value = {}
  operatorArgs.value = []
  Object.keys(params).forEach(key => delete params[key])
  formRef.value?.clearValidate()
  if (props.graph) {
    loadGraphOptions()
  }
})
// 模型列表是异步取的：打开后列表到了再补默认选中（以及把已失效的选择换掉）
watch(modelOptions, list => {
  if (!list.some(model => model.name === form.model)) {
    form.model = list[0]?.name || ''
  }
})

function buildGraphFormData (payload) {
  const formData = new FormData()
  files.value.forEach(file => formData.append('file', file))
  formData.append('data', JSON.stringify(payload))
  return formData
}

function buildGraphData () {
  return buildGraphExtractPayload({
    name: form.name.trim(),
    description: form.description.trim(),
    embeddingModel: form.model,
    operatorId: form.operatorId,
    params
  })
}

async function createGraphDirectly () {
  const response = await extractKnowledgeGraphApi(buildGraphFormData(buildGraphData()))
  // 拦截器已处理 HTTP 错误；这里再挡一层业务失败（success === false）
  if (response && response.success === false) {
    throw new Error(response.message || 'graph extract failed')
  }
}

async function submit () {
  // 同步防重：双击时第二次必须在 validate 的 await 之前就被挡住
  if (submitting.value) {
    return
  }
  if (!files.value.length) {
    return
  }
  const session = openSession
  submitting.value = true
  submitError.value = ''
  try {
    if (!await formRef.value.validate().catch(() => false)) {
      return
    }
    if (props.graph) {
      argErrors.value = validateBuildParams(operatorArgs.value, params)
      if (Object.keys(argErrors.value).length) {
        return
      }
      if (!props.submitHandler) {
        await createGraphDirectly()
        if (session === openSession) {
          open.value = false
          emit('create', { created: true })
        }
        return
      }
    }
    const payload = {
      name: form.name.trim(),
      description: form.description.trim(),
      model: form.model,
      files: [...files.value],
      totalBytes: totalBytes.value
    }
    if (props.graph) {
      payload.operator = { ...selectedOperator.value }
      payload.buildConfig = { ...params }
    }
    if (!props.submitHandler) {
      emit('create', payload)
      if (session === openSession) {
        open.value = false
      }
      return
    }
    await props.submitHandler(payload)
    if (session === openSession) {
      open.value = false
    }
  } catch (error) {
    // 真实创建失败：留在弹窗里。拦截器那条 toast 只是「闪过一下」，这里同时把
    // 服务端给的原因（RFC 9457 的 detail）留在弹窗底部，用户回头还看得到。
    submitError.value = error?.detail || error?.title || $t('modules.studioDialogs.createKnowledge.createFailed')
  } finally {
    if (session === openSession) {
      submitting.value = false
    }
  }
}

</script>

<style>
.el-dialog.create-knowledge-dialog { --el-dialog-padding-primary: 0; width: min(800px, calc(100vw - 32px)); padding: 0; max-height: calc(100dvh - 48px); display: flex; flex-direction: column; overflow: hidden; border: 1px solid var(--rs-border); box-shadow: 0 24px 80px #0c153826; }
.create-knowledge-dialog .el-dialog__header { padding: 26px 32px 24px; margin: 0; border-bottom: 1px solid var(--rs-border-soft); }
.create-knowledge-dialog .el-dialog__headerbtn { top: 20px; right: 18px; width: 32px; height: 32px; }
.create-knowledge-dialog .el-dialog__body { overflow-y: auto; padding: 0 32px; color: var(--rs-text-2); }
.create-knowledge-dialog .el-dialog__footer { padding: 18px 32px; border-top: 1px solid var(--rs-border); background: var(--rs-bg-soft); }
.kb-dialog-heading { display: flex; align-items: center; gap: 14px; padding-right: 22px; }
.kb-heading-icon { display: flex; align-items: center; justify-content: center; width: 46px; height: 46px; border-radius: 12px; color: var(--rs-primary); background: var(--rs-bg-selected); flex-shrink: 0; }
.kb-heading-icon svg { width: 25px; height: 25px; }
.kb-dialog-heading h2 { margin: 0; font-size: var(--rs-font-size-workspace-title); line-height: 1.4; font-weight: 650; color: var(--rs-text); }
.kb-dialog-heading p { margin: 5px 0 0; color: var(--rs-text-3); }
.kb-form-section { padding: 24px 0; }
.kb-form-section + .kb-form-section { border-top: 1px solid var(--rs-border-soft); }
.kb-section-heading { display: flex; align-items: center; gap: 10px; margin-bottom: 20px; }
.kb-section-heading h3 { color: var(--rs-text); margin: 0; }
.kb-section-number { display: flex; align-items: center; justify-content: center; width: 26px; height: 26px; border-radius: 6px; color: var(--rs-primary); background: var(--rs-bg-selected); font-weight: 600; }
.kb-section-note { color: var(--rs-text-3); margin-left: auto; }
.kb-field-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.kb-field-grid-single { grid-template-columns: 1fr; }
.kb-create-form .kb-graph-description { margin-top: 18px; }
.kb-model-note.kb-config-note { margin-bottom: 0; align-items: flex-start; }
.kb-config-note svg { flex-shrink: 0; margin-top: 3px; }
.kb-operator-fields { display: grid; gap: 24px; margin-top: 22px; }
.kb-operator-fields .el-input-number { width: 100%; }
.kb-options-error { margin: 10px 0 0; color: var(--rs-danger); }
.kb-create-form .el-form-item { margin-bottom: 0; }
.kb-create-form .el-form-item__label { font-size: var(--rs-font-size-secondary); color: var(--rs-text); line-height: 20px; height: auto; padding: 0; margin-bottom: 8px; }
.kb-create-form .el-form-item.is-required .el-form-item__label:before { color: var(--rs-danger); }
.kb-create-form .el-input__wrapper, .kb-create-form .el-select__wrapper { min-height: 40px; }
.kb-create-form .el-input__wrapper.is-focus, .kb-create-form .el-select__wrapper.is-focused { box-shadow: 0 0 0 1px var(--rs-primary) inset !important; }
.kb-create-form .is-error .el-input__wrapper { box-shadow: 0 0 0 1px var(--rs-danger) inset !important; }
.kb-create-form .el-input__count-inner, .kb-create-form .el-input__count { color: var(--rs-text-3); font-size: var(--rs-font-size-caption); }
.kb-model-icon { width: 16px; height: 16px; color: var(--rs-primary); }
.kb-option-hint { float: right; margin-left: 16px; color: var(--rs-text-3); }
.kb-model-note { display: flex; gap: 6px; align-items: center; color: var(--rs-text-3); margin: 18px 0; }
.kb-model-note svg { width: 13px; height: 13px; }
.kb-optional { color: var(--rs-text-3); font-weight: 400; margin-left: 6px; }
.kb-description .el-textarea__inner { font-family: inherit; font-size: var(--rs-font-size-secondary); line-height: 1.7; padding: 10px 14px 20px; border-radius: 6px; background: var(--rs-bg-card); box-shadow: 0 0 0 1px var(--rs-border) inset; }
.kb-description .el-textarea__inner:focus { box-shadow: 0 0 0 1px var(--rs-primary) inset; }
.kb-description .el-textarea .el-input__count { bottom: 5px; right: 12px; background: var(--rs-bg-card); }
.kb-dialog-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
/* 提交失败时的就地提示：占满一行放在按钮上方，用危险色，直到下次提交/改字段才消失 */
.kb-submit-error { order: -1; flex-basis: 100%; display: flex; align-items: center; gap: 6px; margin: 0 0 10px; color: var(--rs-danger); font-size: var(--rs-font-size-secondary); }
.kb-submit-error svg { width: 14px; height: 14px; flex-shrink: 0; }
.kb-footer-hint { display: flex; align-items: center; gap: 6px; color: var(--rs-text-3); text-align: left; }
.kb-footer-hint svg { width: 13px; height: 13px; }
.kb-footer-actions { display: flex; gap: 10px; flex-shrink: 0; }
@media (max-width: 600px) {
  .el-dialog.create-knowledge-dialog { max-height: calc(100dvh - 24px); width: calc(100vw - 24px); }
  .create-knowledge-dialog .el-dialog__header { padding: 20px; }
  .create-knowledge-dialog .el-dialog__body { padding: 0 20px; }
  .create-knowledge-dialog .el-dialog__footer { padding: 14px 20px; }
  .kb-field-grid { grid-template-columns: 1fr; gap: 22px; }
  .kb-section-note { display: none; }
  .kb-dialog-footer { align-items: stretch; flex-direction: column; gap: 10px; }
  .kb-footer-actions { justify-content: flex-end; }
}
</style>

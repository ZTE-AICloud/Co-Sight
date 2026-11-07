<template>
  <StudioDialog v-model="open" dialog-class="model-editor-dialog" :busy="submitting || testing" width="800px" :title="editing ? $t('modules.studioDialogs.modelEditor.titleEdit') : $t('modules.studioDialogs.modelEditor.titleCreate')" :subtitle="$t('modules.studioDialogs.modelEditor.subtitle')" :icon="CubeIcon" :hint="$t('modules.studioDialogs.modelEditor.hint')" @opened="modelInput?.focus()">
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="studio-form" @submit.prevent="submit">
      <FormSection number="01" :title="$t('modules.studioDialogs.modelEditor.sectionBasic')" :note="$t('modules.studioDialogs.modelEditor.sectionBasicNote')">
        <el-form-item :label="$t('modules.studioDialogs.modelEditor.kind')" prop="kind"><div class="studio-choice-grid" role="radiogroup" :aria-label="$t('modules.studioDialogs.modelEditor.kind')"><button v-for="kind in kinds" :key="kind.id" type="button" role="radio" :aria-checked="form.kind === kind.id" :disabled="Boolean(editing)" :class="['studio-choice', { selected: form.kind === kind.id }]" @click="setKind(kind.id)"><span class="studio-choice-heading text-secondary"><component :is="kind.icon"/>{{ kind.name }}<CircleCheck v-if="form.kind === kind.id" class="studio-choice-check"/></span><span class="studio-choice-desc">{{ kind.description }}</span></button></div></el-form-item>
        <div class="studio-field-grid"><el-form-item :label="$t('modules.studioDialogs.modelEditor.name')" prop="internal"><el-input ref="modelInput" v-model="form.internal" :aria-label="$t('modules.studioDialogs.modelEditor.name')" :placeholder="$t('modules.studioDialogs.modelEditor.namePlaceholder')" maxlength="128" @blur="refreshThinkingCatalog"/><p class="studio-field-help text-caption">{{ $t('modules.studioDialogs.modelEditor.nameHelp') }}</p></el-form-item><el-form-item :label="$t('modules.studioDialogs.modelEditor.displayName')"><el-input v-model="form.name" :aria-label="$t('modules.studioDialogs.modelEditor.displayName')" :placeholder="$t('modules.studioDialogs.modelEditor.displayNamePlaceholder')" maxlength="128"/><p class="studio-field-help text-caption">{{ $t('modules.studioDialogs.modelEditor.displayNameHelp') }}</p></el-form-item></div>
      </FormSection>
      <FormSection number="02" :title="$t('modules.studioDialogs.modelEditor.sectionConnection')" :note="$t('modules.studioDialogs.modelEditor.sectionConnectionNote')">
        <el-form-item :label="$t('modules.studioDialogs.modelEditor.endpoint')" prop="endpoint"><el-input v-model="form.endpoint" :aria-label="$t('modules.studioDialogs.modelEditor.endpoint')" :placeholder="$t('modules.studioDialogs.modelEditor.endpointPlaceholder')" maxlength="1000" :prefix-icon="Link" autocomplete="off" @blur="refreshThinkingCatalog"/></el-form-item>
        <div class="studio-field-grid"><el-form-item :label="$t('modules.studioDialogs.modelEditor.endpointModel')"><el-input v-model="form.endpointModel" :aria-label="$t('modules.studioDialogs.modelEditor.endpointModel')" :placeholder="$t('modules.studioDialogs.modelEditor.endpointModelPlaceholder')" maxlength="255" @blur="refreshThinkingCatalog"/><p class="studio-field-help text-caption">{{ $t('modules.studioDialogs.modelEditor.endpointModelHelp') }}</p></el-form-item><el-form-item :label="$t('modules.studioDialogs.modelEditor.apiKey')"><el-input v-model="form.apiKey" :aria-label="$t('modules.studioDialogs.modelEditor.apiKey')" type="password" show-password maxlength="1400" :placeholder="editing ? $t('modules.studioDialogs.modelEditor.apiKeyPlaceholderEdit') : $t('modules.studioDialogs.modelEditor.apiKeyPlaceholderCreate')" autocomplete="new-password" :prefix-icon="Lock"/><p class="studio-field-help text-caption">{{ editing ? $t('modules.studioDialogs.modelEditor.apiKeyHelpEdit') : $t('modules.studioDialogs.modelEditor.apiKeyHelpCreate') }}</p><el-checkbox v-if="editing && hasStoredKey" v-model="form.clearApiKey">{{ $t('modules.modelManagement.formClearApiKey') }}</el-checkbox></el-form-item></div>
        <el-form-item v-if="form.kind === 'embedding'" :label="$t('modules.studioDialogs.modelEditor.dimension')" prop="dimension"><el-input-number v-model="form.dimension" :aria-label="$t('modules.studioDialogs.modelEditor.dimension')" :min="1" :max="65535" :precision="0" controls-position="right" :placeholder="$t('modules.studioDialogs.modelEditor.dimensionPlaceholder')"/><p class="studio-field-help text-caption">{{ $t('modules.studioDialogs.modelEditor.dimensionHelp') }}</p></el-form-item>
        <div class="studio-switch-grid"><div class="studio-switch-row"><div><strong class="text-secondary">{{ $t('modules.studioDialogs.modelEditor.enabled') }}</strong><p class="text-caption">{{ $t('modules.studioDialogs.modelEditor.enabledHint') }}</p></div><el-switch v-model="form.enabled" :aria-label="$t('modules.studioDialogs.modelEditor.enabled')"/></div><div class="studio-switch-row"><div><strong class="text-secondary">{{ $t('modules.studioDialogs.modelEditor.isDefault') }}</strong><p class="text-caption">{{ $t('modules.studioDialogs.modelEditor.isDefaultHint') }}</p></div><el-switch v-model="form.isDefault" :disabled="!form.enabled" :aria-label="$t('modules.studioDialogs.modelEditor.isDefault')"/></div></div>
        <div v-if="connectionResult" :class="['studio-callout', 'model-config-result', { 'is-error': !connectionResult.ok }]" role="status"><InfoFilled/><p>{{ connectionResult.ok ? $t('modules.studioDialogs.modelEditor.testPassed') : $t('modules.studioDialogs.modelEditor.testFailed', { message: connectionResult.message }) }}</p></div>
        <!-- 真实连接测试的明细（模型清单 / 维度 / 延迟）：
             在结论下方展示明细表，避免能力倒退。 -->
        <div v-if="connectionResult?.detail" class="model-config-result"><ModelTestResultTable :result="connectionResult.detail" :kind="form.kind" :registered-dimension="form.dimension"/></div>
      </FormSection>
      <details ref="advanced" class="studio-disclosure"><summary><Setting/><span class="text-secondary">{{ $t('modules.studioDialogs.modelEditor.advanced') }}</span><span class="studio-optional">{{ $t('modules.studioDialogs.modelEditor.advancedHint') }}</span><ArrowDown/></summary><div class="studio-disclosure-body">
        <template v-if="form.kind === 'llm'"><h4 class="text-secondary">{{ $t('modules.studioDialogs.modelEditor.generation') }}</h4><div class="studio-field-grid"><el-form-item :label="$t('modules.studioDialogs.modelEditor.maxTokens')" prop="maxTokens"><el-input-number v-model="form.maxTokens" :aria-label="$t('modules.studioDialogs.modelEditor.maxTokens')" :min="1" :precision="0" controls-position="right" :placeholder="$t('modules.studioDialogs.modelEditor.maxTokensPlaceholder')"/></el-form-item><el-form-item :label="$t('modules.studioDialogs.modelEditor.temperature')" prop="temperature"><el-input-number v-model="form.temperature" :aria-label="$t('modules.studioDialogs.modelEditor.temperature')" :min="0" :max="2" :step="0.1" controls-position="right" :placeholder="$t('modules.studioDialogs.modelEditor.maxTokensPlaceholder')"/></el-form-item></div><div class="studio-switch-row model-reasoning-toggle"><div><strong class="text-secondary">{{ $t('modules.studioDialogs.modelEditor.reasoning') }}</strong><p class="text-caption">{{ $t('modules.studioDialogs.modelEditor.reasoningHint') }}</p></div><el-switch v-model="form.reasoning" :aria-label="$t('modules.studioDialogs.modelEditor.reasoning')"/></div><el-form-item :label="$t('modules.studioDialogs.modelEditor.thinking')" class="model-thinking-field"><el-select v-model="form.thinking" :aria-label="$t('modules.studioDialogs.modelEditor.thinking')"><el-option v-for="option in thinkingOptions" :key="option.value" :value="option.value" :label="option.label"/></el-select><p class="studio-field-help text-caption">{{ $t('modules.studioDialogs.modelEditor.thinkingHelp') }}</p><p v-if="thinkingMatch" class="studio-field-help text-caption model-thinking-match">{{ $t(thinkingMatch.key, thinkingMatch.params) }}</p></el-form-item><el-form-item v-if="form.thinking === 'preset'" :label="$t('modules.studioDialogs.modelEditor.thinkingPresetField')" prop="thinkingPreset"><el-select v-model="form.thinkingPreset" :placeholder="$t('modules.studioDialogs.modelEditor.thinkingPresetPlaceholder')"><el-option v-for="preset in thinkingCatalog.presets" :key="preset.presetId" :label="presetLabel(preset)" :value="preset.presetId"/></el-select></el-form-item><el-form-item v-if="form.thinking === 'custom'" :label="$t('modules.studioDialogs.modelEditor.thinkingJson')" prop="thinkingCustomJson"><el-input v-model="form.thinkingCustomJson" type="textarea" :rows="4" :placeholder="$t('modules.studioDialogs.modelEditor.thinkingJsonPlaceholder')"/><p class="studio-field-help text-caption">{{ $t('modules.modelManagement.formThinkingJsonTip', { keys: thinkingCatalog.allowedPayloadKeys.join(' / ') }) }}</p></el-form-item></template>
        <h4 class="text-secondary">{{ $t('modules.studioDialogs.modelEditor.request') }}</h4><div class="studio-field-grid"><el-form-item :label="$t('modules.studioDialogs.modelEditor.timeout')" prop="timeout"><el-input-number v-model="form.timeout" :aria-label="$t('modules.studioDialogs.modelEditor.timeout')" :min="1" :precision="0" controls-position="right"/></el-form-item><el-form-item v-if="form.kind === 'llm'" :label="$t('modules.studioDialogs.modelEditor.modelsPath')" prop="modelsPath"><el-input v-model="form.modelsPath" :aria-label="$t('modules.studioDialogs.modelEditor.modelsPath')" :placeholder="$t('modules.studioDialogs.modelEditor.modelsPathPlaceholder')" maxlength="255"/></el-form-item></div><el-form-item :label="$t('modules.studioDialogs.modelEditor.requestPath')" prop="requestPath" class="model-path-field"><el-input v-model="form.requestPath" :aria-label="$t('modules.studioDialogs.modelEditor.requestPath')" :placeholder="requestPlaceholder" maxlength="255"/><p class="studio-field-help text-caption">{{ $t('modules.studioDialogs.modelEditor.requestPathHelp') }}</p></el-form-item>
        <el-form-item :label="$t('modules.studioDialogs.modelEditor.notes')"><el-input v-model="form.notes" :aria-label="$t('modules.studioDialogs.modelEditor.notes')" type="textarea" :rows="2" maxlength="500" show-word-limit resize="none" :placeholder="$t('modules.studioDialogs.modelEditor.notesPlaceholder')"/></el-form-item>
      </div></details>
    </el-form>
    <template #actions><el-button :loading="testing" :disabled="submitting" @click="checkConnection"><Connection/>{{ $t('modules.studioDialogs.modelEditor.test') }}</el-button><el-button :disabled="submitting" @click="open = false">{{ $t('modules.studioDialogs.common.cancel') }}</el-button><el-button type="primary" :loading="submitting" @click="submit"><Check/>{{ editing ? $t('modules.studioDialogs.modelEditor.saveButton') : $t('modules.studioDialogs.modelEditor.createButton') }}</el-button></template>
  </StudioDialog>
</template>
<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ChatDotRound, Histogram, CircleCheck, Link, Lock, InfoFilled, Setting, ArrowDown, Check, Connection } from '@element-plus/icons-vue'
import { $t, isGlobalZh } from '@/app/i18n/i18n.js'
import { CubeIcon, LayersIcon } from '@/shared/ui/icons'
import StudioDialog from '@/shared/ui/StudioDialog.vue'
import FormSection from '@/shared/ui/FormSection.vue'
import ModelTestResultTable from '@/features/model/ModelTestResultTable.vue'
import { isHttpEndpoint } from '@/shared/lib/form-validators'
import { getThinkingPresetsApi, testModelApi, testModelConfigApi } from '@/features/model/api/model.js'
import { THINKING_MODES } from '@/features/model/type'

const open = defineModel({ type: Boolean, default: false })
const props = defineProps({
  /** 编辑时的列表行；新建传 null */
  editing: { type: Object, default: null },
  /** 新建时当前页签的类型 */
  initialKind: { type: String, default: 'llm' },
  /** 全部模型（同名判重用；同 kind 内唯一） */
  existing: { type: Array, default: () => [] },
  submitHandler: { type: Function, default: null }
})
const emit = defineEmits(['save'])
const formRef = ref()
const modelInput = ref()
const advanced = ref()
const testing = ref(false)
const submitting = ref(false)
const hasStoredKey = ref(false)
const connectionResult = ref(null)
// 每次打开弹窗算一个会话；测试/保存的响应回来时会话变了就丢弃
let openSession = 0

const defaults = () => ({
  kind: props.initialKind,
  internal: '',
  name: '',
  endpoint: '',
  endpointModel: '',
  apiKey: '',
  clearApiKey: false,
  dimension: null,
  enabled: true,
  isDefault: false,
  maxTokens: null,
  temperature: null,
  reasoning: false,
  thinking: 'auto',
  thinkingPreset: '',
  thinkingCustomJson: '',
  timeout: 120,
  modelsPath: '',
  requestPath: '',
  notes: ''
})
const form = reactive(defaults())
const kinds = computed(() => ([
  { id: 'llm', name: $t('modules.studioDialogs.modelEditor.kindLlm'), description: $t('modules.studioDialogs.modelEditor.kindLlmDesc'), icon: ChatDotRound },
  { id: 'embedding', name: $t('modules.studioDialogs.modelEditor.kindEmbedding'), description: $t('modules.studioDialogs.modelEditor.kindEmbeddingDesc'), icon: LayersIcon },
  { id: 'rerank', name: $t('modules.studioDialogs.modelEditor.kindRerank'), description: $t('modules.studioDialogs.modelEditor.kindRerankDesc'), icon: Histogram }
]))
const THINKING_LABEL_KEY = {
  auto: 'modules.studioDialogs.modelEditor.thinkingAuto',
  none: 'modules.studioDialogs.modelEditor.thinkingOff',
  preset: 'modules.studioDialogs.modelEditor.thinkingPreset',
  custom: 'modules.studioDialogs.modelEditor.thinkingCustom'
}
const thinkingOptions = computed(() => THINKING_MODES.map(value => ({ value, label: $t(THINKING_LABEL_KEY[value]) })))
const REQUEST_PATH_FIELD = { llm: 'chatPath', embedding: 'embeddingsPath', rerank: 'rerankPath' }
const requestPlaceholder = computed(() => ({
  llm: $t('modules.studioDialogs.modelEditor.requestPathPlaceholderLlm'),
  embedding: $t('modules.studioDialogs.modelEditor.requestPathPlaceholderEmbedding'),
  rerank: $t('modules.studioDialogs.modelEditor.requestPathPlaceholderRerank')
}[form.kind]))
const thinkingCatalog = ref({
  presets: [],
  matchedPresetId: '',
  allowedPayloadKeys: ['chat_template_kwargs', 'thinking', 'reasoning_effort', 'enable_thinking', 'google']
})
const thinkingCatalogLoading = ref(false)

function presetLabel (preset) {
  return isGlobalZh ? preset.label : (preset.labelEn || preset.label)
}

/** auto 模式运行时会匹配到的预置；目录请求失败/无匹配时为 null。 */
const thinkingMatchedPreset = computed(() => (
  thinkingCatalog.value.presets.find(
    preset => preset.presetId === thinkingCatalog.value.matchedPresetId) || null
))

/** 「关闭思考」下的匹配结果提示：无匹配时必须说清「不会发送」，避免误以为已关闭。 */
const thinkingMatch = computed(() => {
  // 目录请求在飞时不要先闪一条「未匹配」的假提示。
  if (form.thinking !== 'auto' || thinkingCatalogLoading.value) {
    return null
  }
  if (thinkingMatchedPreset.value) {
    return {
      key: 'modules.modelManagement.thinkingPreviewMatched',
      params: { label: presetLabel(thinkingMatchedPreset.value) }
    }
  }
  return {
    key: (form.internal.trim() || form.endpointModel.trim())
      ? 'modules.modelManagement.thinkingPreviewNoMatch'
      : 'modules.modelManagement.thinkingPreviewEmpty',
    params: {}
  }
})

const optionalNumber = (min, max, integer = false) => ({
  trigger: 'change',
  validator: (_rule, value, done) => (
    value === null || value === undefined || (Number.isFinite(value) && value >= min && value <= max && (!integer || Number.isInteger(value)))
      ? done()
      : done(new Error($t('modules.studioDialogs.modelEditor.valueInvalid')))
  )
})
const pathRule = {
  trigger: 'blur',
  validator: (_rule, value, done) => (
    !value || /^\/[^\s?#]*$/.test(value)
      ? done()
      : done(new Error($t('modules.studioDialogs.modelEditor.pathInvalid')))
  )
}
const rules = {
  internal: [{
    required: true,
    trigger: 'blur',
    validator: (_rule, value, done) => {
      const name = String(value || '').trim()
      if (!name) {
        done(new Error($t('modules.studioDialogs.modelEditor.nameRequired')))
        return
      }
      const duplicate = props.existing.some(item => (
        item.modelId !== props.editing?.modelId &&
        item.modelKind === form.kind &&
        String(item.modelName || '').toLowerCase() === name.toLowerCase()
      ))
      done(duplicate ? new Error($t('modules.studioDialogs.modelEditor.nameDuplicate')) : undefined)
    }
  }],
  endpoint: [{
    required: true,
    trigger: 'blur',
    validator: (_rule, value, done) => (
      isHttpEndpoint(String(value || '').trim())
        ? done()
        : done(new Error($t('modules.studioDialogs.modelEditor.endpointInvalid')))
    )
  }],
  dimension: [{
    trigger: 'blur',
    validator: (_rule, value, done) => {
      if (form.kind !== 'embedding') {
        done()
        return
      }
      if (value === null || value === undefined || value === '') {
        done(new Error($t('modules.studioDialogs.modelEditor.dimensionRequired')))
        return
      }
      done(Number.isInteger(Number(value)) && Number(value) > 0
        ? undefined
        : new Error($t('modules.studioDialogs.modelEditor.valueInvalid')))
    }
  }],
  maxTokens: [optionalNumber(1, Number.MAX_SAFE_INTEGER, true)],
  temperature: [optionalNumber(0, 2)],
  timeout: [{ required: true, message: $t('modules.studioDialogs.modelEditor.timeoutRequired'), trigger: 'change' }, optionalNumber(1, Number.MAX_SAFE_INTEGER, true)],
  modelsPath: [pathRule],
  requestPath: [pathRule],
  thinkingPreset: [{
    trigger: 'change',
    validator: (_rule, value, done) => (
      form.kind !== 'llm' || form.thinking !== 'preset' || value
        ? done()
        : done(new Error($t('modules.modelManagement.thinkingPresetRequired')))
    )
  }],
  thinkingCustomJson: [{
    trigger: 'blur',
    validator: (_rule, value, done) => {
      if (form.kind !== 'llm' || form.thinking !== 'custom') {
        done()
        return
      }
      const text = String(value || '').trim()
      if (!text) {
        done(new Error($t('modules.modelManagement.thinkingJsonRequired')))
        return
      }
      let parsed
      try {
        parsed = JSON.parse(text)
      } catch (error) {
        done(new Error($t('modules.modelManagement.thinkingJsonInvalid')))
        return
      }
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed) || !Object.keys(parsed).length) {
        done(new Error($t('modules.modelManagement.thinkingJsonMustBeObject')))
        return
      }
      const allowed = thinkingCatalog.value.allowedPayloadKeys || []
      const unknown = Object.keys(parsed).find(key => !allowed.includes(key))
      done(unknown
        ? new Error($t('modules.modelManagement.thinkingJsonKeyInvalid', { key: unknown }))
        : undefined)
    }
  }]
}

watch(open, value => {
  if (!value) {
    return
  }
  const row = props.editing
  const initial = defaults()
  if (row) {
    const storedMode = row.thinkingMode || 'none'
    const mode = row.modelKind === 'llm' ? storedMode : 'none'
    Object.assign(initial, {
      kind: row.modelKind || props.initialKind,
      internal: row.modelName || '',
      name: row.displayName || '',
      endpoint: row.baseUrl || '',
      endpointModel: row.apiModel || '',
      apiKey: '',
      clearApiKey: false,
      dimension: row.dimension ?? null,
      enabled: row.enabled !== false,
      isDefault: Boolean(row.isDefault),
      maxTokens: row.maxTokens ?? null,
      temperature: row.temperature ?? null,
      reasoning: Boolean(row.isReasoning),
      thinking: mode,
      thinkingPreset: row.thinkingPreset || '',
      thinkingCustomJson: row.thinkingPayload ? JSON.stringify(row.thinkingPayload, null, 2) : '',
      timeout: row.timeout ?? 120,
      modelsPath: row.modelsPath || '',
      requestPath: row[REQUEST_PATH_FIELD[row.modelKind]] || '',
      notes: row.remark || ''
    })
    hasStoredKey.value = Boolean(row.hasApiKey)
  } else {
    hasStoredKey.value = false
  }
  openSession += 1
  testing.value = false
  submitting.value = false
  Object.assign(form, initial)
  connectionResult.value = null
  if (advanced.value) {
    advanced.value.open = false
  }
  formRef.value?.clearValidate()
  refreshThinkingCatalog()
})
watch(() => form.enabled, value => {
  if (!value) {
    form.isDefault = false
  }
})
watch(() => [form.kind, form.internal, form.endpoint, form.endpointModel, form.apiKey, form.modelsPath, form.requestPath], () => {
  connectionResult.value = null
})
watch(() => form.kind, () => {
  formRef.value?.clearValidate('internal')
})

function setKind (kind) {
  if (kind === form.kind) {
    return
  }
  form.kind = kind
  // 旧的请求路径属于上一个类型（chatPath/embeddingsPath/rerankPath 语义不同），清掉
  form.requestPath = ''
  if (kind !== 'llm') {
    form.thinking = 'none'
    form.thinkingPreset = ''
    form.thinkingCustomJson = ''
  } else if (form.thinking === 'none') {
    form.thinking = 'auto'
  }
}

async function refreshThinkingCatalog () {
  if (form.kind !== 'llm') {
    return
  }
  thinkingCatalogLoading.value = true
  try {
    const response = await getThinkingPresetsApi({
      modelName: form.internal,
      apiModel: form.endpointModel,
      baseUrl: form.endpoint
    }, { skipErrorHandler: true })
    const data = response && typeof response === 'object' ? response : {}
    thinkingCatalog.value = {
      presets: Array.isArray(data.presets) ? data.presets : [],
      matchedPresetId: data.matchedPresetId || '',
      allowedPayloadKeys: Array.isArray(data.allowedPayloadKeys) && data.allowedPayloadKeys.length
        ? data.allowedPayloadKeys
        : thinkingCatalog.value.allowedPayloadKeys
    }
  } catch {
    // 目录只是辅助；失败不影响手填，但要把旧匹配清掉，避免提示与实际不符。
    thinkingCatalog.value = {
      ...thinkingCatalog.value,
      presets: [],
      matchedPresetId: ''
    }
  } finally {
    thinkingCatalogLoading.value = false
  }
}

function customThinkingPayload () {
  try {
    const parsed = JSON.parse(form.thinkingCustomJson || '')
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null
  } catch (error) {
    return null
  }
}

function buildValues () {
  const values = {
    modelKind: form.kind,
    modelName: form.internal.trim(),
    displayName: form.name.trim() || form.internal.trim(),
    apiModel: form.endpointModel.trim(),
    baseUrl: form.endpoint.trim().replace(/\/+$/, ''),
    apiKey: form.apiKey,
    dimension: form.kind === 'embedding' ? form.dimension : null,
    enabled: form.enabled,
    isDefault: form.isDefault,
    maxTokens: form.kind === 'llm' ? form.maxTokens : null,
    temperature: form.kind === 'llm' ? form.temperature : null,
    isReasoning: form.kind === 'llm' ? form.reasoning : false,
    thinkingMode: form.kind === 'llm' ? form.thinking : 'none',
    thinkingPreset: '',
    thinkingPayload: null,
    timeout: form.timeout,
    modelsPath: form.modelsPath.trim(),
    remark: form.notes.trim()
  }
  values[REQUEST_PATH_FIELD[form.kind]] = form.requestPath.trim()
  if (form.kind === 'llm' && form.thinking === 'preset') {
    values.thinkingPreset = form.thinkingPreset
  } else if (form.kind === 'llm' && form.thinking === 'custom') {
    values.thinkingPayload = customThinkingPayload()
  }
  if (props.editing && !values.apiKey && !form.clearApiKey) {
    delete values.apiKey
  }
  if (props.editing && form.clearApiKey) {
    values.clearApiKey = true
  }
  return values
}

async function checkConnection () {
  // 同步置位，避免双击发起两次探测
  if (testing.value || submitting.value) {
    return
  }
  const session = openSession
  testing.value = true
  connectionResult.value = null
  try {
    if (!await formRef.value.validate().catch(() => false)) {
      if (advanced.value) {
        advanced.value.open = true
      }
      return
    }
    const values = buildValues()
    const result = props.editing
      ? await testModelApi(props.editing.modelId, values, { skipErrorHandler: true })
      : await testModelConfigApi(values, { skipErrorHandler: true })
    if (session !== openSession) {
      return
    }
    connectionResult.value = {
      ok: Boolean(result?.ok),
      message: result?.message || result?.chatError || '',
      detail: result && typeof result === 'object' ? result : null
    }
  } catch (error) {
    if (session === openSession) {
      connectionResult.value = { ok: false, message: error?.detail || error?.message || '' }
    }
  } finally {
    if (session === openSession) {
      testing.value = false
    }
  }
}

async function submit () {
  // 同步防重（原因同 CreateWorkflowDialog）
  if (submitting.value || testing.value) {
    return
  }
  const session = openSession
  submitting.value = true
  try {
    if (!await formRef.value.validate().catch(() => false)) {
      if (advanced.value) {
        advanced.value.open = true
      }
      return
    }
    const values = buildValues()
    if (!props.submitHandler) {
      emit('save', values)
      if (session === openSession) {
        open.value = false
      }
      return
    }
    await props.submitHandler(values)
    if (session === openSession) {
      open.value = false
    }
  } catch (error) {
    // 保存失败保持弹窗
  } finally {
    if (session === openSession) {
      submitting.value = false
    }
  }
}
</script>
<style>
.model-config-result { margin-top: 14px; }
.model-config-result.is-error { border-color: color-mix(in srgb, var(--rs-danger) 40%, var(--rs-border)); background: color-mix(in srgb, var(--rs-danger) 6%, var(--rs-bg-card)); color: var(--rs-text-2); }
.model-config-result.is-error > svg { color: var(--rs-danger); }
.model-reasoning-toggle, .model-thinking-field, .model-path-field { margin-top: 20px; }
.model-thinking-match { margin-top: -6px; }
</style>

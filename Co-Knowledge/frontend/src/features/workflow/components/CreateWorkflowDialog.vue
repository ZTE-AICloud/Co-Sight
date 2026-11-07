<template>
  <StudioDialog v-model="open" dialog-class="create-workflow-dialog" :busy="submitting" :title="$t('modules.studioDialogs.createWorkflow.title')" :subtitle="$t('modules.studioDialogs.createWorkflow.subtitle')" :icon="WorkflowIcon" :hint="footerHint" @opened="nameInput?.focus()">
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="studio-form" @submit.prevent="submit">
      <FormSection number="01" :title="$t('modules.studioDialogs.createWorkflow.sectionBasic')" :note="$t('modules.studioDialogs.createWorkflow.sectionBasicNote')">
        <div class="studio-field-grid"><el-form-item :label="$t('modules.studioDialogs.createWorkflow.name')" prop="name"><el-input ref="nameInput" v-model="form.name" :aria-label="$t('modules.studioDialogs.createWorkflow.name')" :placeholder="$t('modules.studioDialogs.createWorkflow.namePlaceholder')" maxlength="50" show-word-limit/></el-form-item><el-form-item :label="$t('modules.studioDialogs.createWorkflow.description')"><el-input v-model="form.description" :aria-label="$t('modules.studioDialogs.createWorkflow.description')" maxlength="1000" :placeholder="$t('modules.studioDialogs.createWorkflow.descriptionPlaceholder')"/></el-form-item></div>
      </FormSection>
      <FormSection number="02" :title="$t('modules.studioDialogs.createWorkflow.sectionSource')" :note="$t('modules.studioDialogs.createWorkflow.sectionSourceNote')">
        <el-form-item :label="$t('modules.studioDialogs.createWorkflow.sourceTypeLabel')" prop="sourceType">
          <div class="studio-choice-grid workflow-source-types" role="radiogroup" :aria-label="$t('modules.studioDialogs.createWorkflow.sourceTypeLabel')">
            <button v-for="(source, index) in sourceTypes" :key="source.id" type="button" role="radio" :aria-checked="form.sourceType === source.id" :tabindex="form.sourceType === source.id ? 0 : -1" :class="['studio-choice', { selected: form.sourceType === source.id }]" @click="setSourceType(source.id)" @keydown="moveChoice($event, index, sourceTypes.map(item => item.id), setSourceType)"><span class="studio-choice-heading text-secondary"><component :is="source.icon"/>{{ source.name }}<CircleCheck v-if="form.sourceType === source.id" class="studio-choice-check"/></span><span class="studio-choice-desc">{{ source.description }}</span></button>
          </div>
        </el-form-item>
        <el-form-item :key="form.sourceType" :label="kind.name" prop="sourceIds" required>
          <RetrievalSourceSelect v-model="form.sourceIds" :source-type="form.sourceType" :options="sourceOptions" />
        </el-form-item>
        <p v-if="sourceNotice && !form.sourceIds.length" class="workflow-source-notice text-caption" role="status"><InfoFilled/>{{ sourceNotice }}</p>
      </FormSection>
      <FormSection number="03" :title="$t('modules.studioDialogs.createWorkflow.sectionFlow')" :note="$t('modules.studioDialogs.createWorkflow.sectionFlowNote')">
        <p class="workflow-type-explanation text-caption">{{ typeExplanation }}</p>
        <el-form-item :label="$t('modules.studioDialogs.createWorkflow.template')" prop="template">
          <div :class="['studio-choice-grid', { 'workflow-single-template': templateOptions.length === 1 }]" role="radiogroup" :aria-label="$t('modules.studioDialogs.createWorkflow.template')">
            <button v-for="(template, index) in templateOptions" :key="template.value" type="button" role="radio" :aria-checked="form.template === template.value" :tabindex="form.template === template.value ? 0 : -1" :class="['studio-choice', { selected: form.template === template.value }]" @click="form.template = template.value" @keydown="moveChoice($event, index, templateOptions.map(item => item.value), value => form.template = value)"><span class="studio-choice-heading text-secondary"><component :is="template.icon"/>{{ template.name }}<CircleCheck v-if="form.template === template.value" class="studio-choice-check"/></span><span class="studio-choice-desc">{{ template.description }}</span></button>
          </div>
        </el-form-item>
        <div class="workflow-template-preview" :aria-label="$t('modules.studioDialogs.createWorkflow.preview')"><span class="text-caption">{{ $t('modules.studioDialogs.createWorkflow.preview') }}</span><div class="workflow-preview-steps text-caption"><span><ChatDotRound/>{{ $t('modules.studioDialogs.createWorkflow.stepQuestion') }}</span><template v-for="(step, index) in previewSteps" :key="index"><ArrowRight/><span :class="{ 'workflow-retrieval-step': step.retrieval }"><component :is="step.icon"/>{{ step.label }}</span></template></div><p v-if="showSequentialNote" class="workflow-preview-note text-caption">{{ sequentialNote }}</p></div>
      </FormSection>
    </el-form>
    <template #actions><el-button :disabled="submitting" @click="open = false">{{ $t('modules.studioDialogs.common.cancel') }}</el-button><el-button type="primary" :loading="submitting" @click="submit"><ArrowRight/>{{ $t('modules.studioDialogs.createWorkflow.submit') }}</el-button></template>
  </StudioDialog>
</template>
<script setup>
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Document, Share, Coin, CircleCheck, Connection, Sort, Filter, ArrowRight, ChatDotRound, InfoFilled } from '@element-plus/icons-vue'
import { $t } from '@/app/i18n/i18n.js'
import { WorkflowIcon } from '@/shared/ui/icons'
import StudioDialog from '@/shared/ui/StudioDialog.vue'
import FormSection from '@/shared/ui/FormSection.vue'
import RetrievalSourceSelect from './RetrievalSourceSelect.vue'
import { uniqueNameRule } from '@/shared/lib/form-validators'
import { sourceKindMeta } from '@/features/workflow/lib/retrievalSources'

const open = defineModel({ type: Boolean, default: false })
const props = defineProps({
  /** 列表里的全部工作流（名称判重用） */
  existing: { type: Array, default: () => [] },
  /** 真实知识库下拉：{ id, name, statusLabel, disabled, isGraph, isStruct } */
  knowledgeOptions: { type: Array, default: () => [] },
  /** 数据库下拉（演示配置；没有可用的结构化数据源） */
  databaseOptions: { type: Array, default: () => [{ id: 'db-demo-business', name: '业务数据库（演示）' }] },
  submitHandler: { type: Function, default: null }
})
const emit = defineEmits(['create'])
const formRef = ref()
const nameInput = ref()
const submitting = ref(false)
const sourceNotice = ref('')
// 弹窗每次打开/关闭算一个会话：异步请求回来时如果会话已经换了，结果直接丢弃
let openSession = 0
const form = reactive({ name: '', description: '', sourceType: 'knowledge', template: 'Blended', sourceIds: [] })
// 数据库（结构化知识库）类型暂时没有可用能力：没有结构化数据源，选中也只能走到「不可用」提示。
// 先把入口屏蔽；能力补齐后把开关改回 true，其余 database 分支保持原样。
const DATABASE_SOURCE_ENABLED = false
const sourceTypes = computed(() => {
  const types = [
    { id: 'knowledge', name: $t('modules.studioDialogs.createWorkflow.typeKnowledge'), description: $t('modules.studioDialogs.createWorkflow.typeKnowledgeDesc'), icon: Document },
    { id: 'graph', name: $t('modules.studioDialogs.createWorkflow.typeGraph'), description: $t('modules.studioDialogs.createWorkflow.typeGraphDesc'), icon: Share }
  ]
  if (DATABASE_SOURCE_ENABLED) {
    types.push({ id: 'database', name: $t('modules.studioDialogs.createWorkflow.typeDatabase'), description: $t('modules.studioDialogs.createWorkflow.typeDatabaseDesc'), icon: Coin })
  }
  return types
})
const kind = computed(() => {
  const meta = sourceKindMeta(form.sourceType)
  return {
    ...meta,
    name: $t(meta.labelKey),
    templates: form.sourceType === 'database' ? ['Conditional'] : meta.templates
  }
})
const templateOptions = computed(() => {
  if (form.sourceType === 'graph') {
    return [{ value: 'Blended', name: $t('modules.studioDialogs.createWorkflow.templateGraph'), description: $t('modules.studioDialogs.createWorkflow.templateGraphDesc'), icon: Share }]
  }
  return [
    { value: 'Blended', name: $t('modules.studioDialogs.createWorkflow.templateBlended'), description: $t('modules.studioDialogs.createWorkflow.templateBlendedDesc'), icon: Connection },
    { value: 'Sequential', name: $t('modules.studioDialogs.createWorkflow.templateSequential'), description: $t('modules.studioDialogs.createWorkflow.templateSequentialDesc'), icon: Sort },
    { value: 'Conditional', name: $t('modules.studioDialogs.createWorkflow.templateConditional'), description: $t('modules.studioDialogs.createWorkflow.templateConditionalDesc'), icon: Filter }
  ]
})
const templateName = computed(() => templateOptions.value.find(item => item.value === form.template)?.name || '')
const typeExplanation = computed(() => ({
  knowledge: $t('modules.studioDialogs.createWorkflow.typeExplanationKnowledge'),
  graph: $t('modules.studioDialogs.createWorkflow.typeExplanationGraph'),
  database: $t('modules.studioDialogs.createWorkflow.typeExplanationDatabase')
}[form.sourceType]))
// 来源下拉只列当前类型可用的库：图谱库不再混在文档库里（选错会静默切成图谱画布）。
const sourceOptions = computed(() => {
  if (form.sourceType === 'database') {
    return props.databaseOptions.map(option => ({ ...option, disabled: Boolean(option.disabled) }))
  }
  return props.knowledgeOptions
    .filter(option => (form.sourceType === 'graph' ? option.isGraph : !option.isGraph && !option.isStruct))
    .map(option => ({ ...option, disabled: Boolean(option.disabled) }))
})
const previewSteps = computed(() => {
  const step = (key, icon, retrieval = false) => ({ label: $t(`modules.studioDialogs.createWorkflow.${key}`), icon, retrieval })
  if (form.sourceType === 'database') {
    return [step('stepFilter', Filter), step('stepDatabase', Coin, true), step('stepDirect', Document)]
  }
  if (form.sourceType === 'graph') {
    return [step('stepProcess', ChatDotRound), step('stepGraph', Share, true), step('stepRerank', Sort), step('stepAnswer', Document)]
  }
  if (form.template === 'Sequential') {
    return [step('stepProcess', ChatDotRound), step('stepSequential', Sort, true), step('stepRerank', Sort), step('stepAnswer', Document)]
  }
  if (form.template === 'Conditional') {
    return [step('stepFilter', Filter), step('stepBlended', Connection, true), step('stepRerank', Sort), step('stepAnswer', Document)]
  }
  return [step('stepProcess', ChatDotRound), step('stepBlended', Connection, true), step('stepRerank', Sort), step('stepAnswer', Document)]
})
const showSequentialNote = computed(() => form.sourceType === 'knowledge' && form.template === 'Sequential')
const sequentialNote = computed(() => {
  const names = form.sourceIds.map(id => sourceOptions.value.find(option => option.id === id)?.name).filter(Boolean)
  return names.length
    ? names.join(' → ')
    : $t('modules.studioDialogs.createWorkflow.previewSequentialNote')
})
function sourceSelectionError (ids = []) {
  const kindName = kind.value.name
  if (!ids.length) {
    return $t('modules.studioDialogs.createWorkflow.sourceMissing', { kind: kindName })
  }
  for (const id of ids) {
    const option = sourceOptions.value.find(item => item.id === id)
    if (!option) {
      return $t('modules.studioDialogs.createWorkflow.sourceUnavailableItem', { name: id, kind: kindName })
    }
    if (option.disabled) {
      return $t('modules.studioDialogs.createWorkflow.sourceUnavailableItem', { name: option.name, kind: kindName })
    }
  }
  return ''
}
const footerHint = computed(() => (
  form.sourceIds.length
    ? $t('modules.studioDialogs.createWorkflow.hintSelected', {
      count: form.sourceIds.length,
      type: kind.value.name,
      template: templateName.value
    })
    : $t('modules.studioDialogs.createWorkflow.hintEmpty')
))
const rules = {
  name: [uniqueNameRule(() => props.existing, $t('modules.studioDialogs.createWorkflow.name'))],
  sourceIds: [{
    validator: (_rule, value, done) => {
      const error = sourceSelectionError(value)
      done(error ? new Error(error) : undefined)
    },
    trigger: 'change'
  }],
  template: [{
    validator: (_rule, value, done) => {
      done(kind.value.templates.includes(value) ? undefined : new Error($t('modules.studioDialogs.createWorkflow.templateHint')))
    },
    trigger: 'change'
  }]
}
watch(open, value => {
  if (!value) {
    return
  }
  openSession += 1
  submitting.value = false
  sourceNotice.value = ''
  Object.assign(form, { name: '', description: '', sourceType: 'knowledge', template: 'Blended', sourceIds: [] })
  formRef.value?.clearValidate()
})
// 模板被类型收窄（例如接口回填了不允许的模板）时回落到该类型的第一个模板
watch(() => form.template, value => {
  if (!kind.value.templates.includes(value)) {
    form.template = kind.value.templates[0]
  }
})
function setSourceType (type) {
  if (type === form.sourceType) {
    return
  }
  const previous = kind.value.name
  const count = form.sourceIds.length
  form.sourceType = type
  form.sourceIds = []
  form.template = kind.value.templates[0]
  sourceNotice.value = count
    ? $t('modules.studioDialogs.createWorkflow.sourceNotice', {
      kind: kind.value.name,
      count,
      previous,
      template: templateName.value
    })
    : ''
  nextTick(() => formRef.value?.clearValidate(['sourceIds', 'template']))
}
function moveChoice (event, index, choices, select) {
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) {
    return
  }
  event.preventDefault()
  const next = event.key === 'Home'
    ? 0
    : event.key === 'End'
      ? choices.length - 1
      : (index + (['ArrowRight', 'ArrowDown'].includes(event.key) ? 1 : -1) + choices.length) % choices.length
  select(choices[next])
  event.currentTarget.parentElement.querySelectorAll('[role="radio"]')[next].focus()
}
async function submit () {
  // 防重必须**同步**置位：放在 await validate() 之后，双击会两次进入
  // （与旧 ModelFormDialog 的 E2E RES-07 同一个坑）。
  if (submitting.value) {
    return
  }
  if (form.sourceType === 'database') {
    // 没有可用的结构化数据源：保持界面完整，但不伪造创建成功
    ElMessage.warning($t('modules.studioDialogs.createWorkflow.databaseUnavailable'))
    return
  }
  const session = openSession
  submitting.value = true
  try {
    if (!await formRef.value.validate().catch(() => false)) {
      return
    }
    const payload = {
      ...form,
      name: form.name.trim(),
      description: form.description.trim(),
      sourceIds: [...form.sourceIds],
      sourceNames: form.sourceIds.map(id => sourceOptions.value.find(item => item.id === id)?.name)
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
    // 创建失败保持弹窗
  } finally {
    if (session === openSession) {
      submitting.value = false
    }
  }
}
</script>
<style>
.create-workflow-dialog .studio-form-section { padding: 18px 0; }
.create-workflow-dialog .studio-section-heading { margin-bottom: 14px; }
.create-workflow-dialog .workflow-source-types .studio-choice { padding: 12px 14px; }
.workflow-source-notice { display: flex; align-items: flex-start; gap: 6px; color: var(--rs-text-2); margin: 8px 0 0; line-height: 1.6; }
.workflow-source-notice svg { width: 14px; height: 14px; margin-top: 3px; color: var(--rs-primary); }
.workflow-type-explanation { line-height: 1.7; margin: 0 0 14px; color: var(--rs-text-2); }
.create-workflow-dialog .workflow-single-template { grid-template-columns: minmax(0, 1fr); }
.create-workflow-dialog .workflow-single-template .studio-choice { padding: 10px 14px; }
.workflow-template-preview { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px; border-radius: 8px; padding: 12px 14px; background: var(--rs-bg-soft); border: 1px solid var(--rs-border-soft); color: var(--rs-text-3); }
.workflow-preview-steps { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; color: var(--rs-text-2); }
.workflow-preview-steps > span { display: flex; align-items: center; gap: 6px; padding: 5px 8px; border: 1px solid var(--rs-border); border-radius: 4px; background: var(--rs-bg-card); }
.workflow-preview-steps .workflow-retrieval-step { border-color: var(--rs-primary-border); color: var(--rs-primary); }
.workflow-preview-steps svg { width: 13px; height: 13px; color: var(--rs-primary); }
.workflow-preview-steps > svg { color: var(--rs-text-3); width: 12px; }
.workflow-preview-note { width: 100%; margin: 0; line-height: 1.7; overflow-wrap: anywhere; }
@media (max-width: 600px) { .create-workflow-dialog .workflow-source-types { grid-template-columns: 1fr; }.create-workflow-dialog .workflow-source-types .studio-choice { gap: 4px; padding: 12px; } }
</style>

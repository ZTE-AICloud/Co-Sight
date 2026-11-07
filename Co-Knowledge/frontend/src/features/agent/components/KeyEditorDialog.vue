<template>
  <StudioDialog v-model="open" dialog-class="key-editor-dialog" :busy="submitting" :title="editing ? $t('modules.studioDialogs.keyEditor.titleEdit') : $t('modules.studioDialogs.keyEditor.titleCreate')" :subtitle="$t('modules.studioDialogs.keyEditor.subtitle')" :icon="Key" :hint="footerHint" @opened="nameInput?.focus()">
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="studio-form" @submit.prevent="submit">
      <FormSection number="01" :title="$t('modules.studioDialogs.keyEditor.sectionBasic')" :note="$t('modules.studioDialogs.keyEditor.sectionBasicNote')"><div class="studio-field-grid"><el-form-item :label="$t('modules.studioDialogs.keyEditor.name')" prop="name"><el-input ref="nameInput" v-model="form.name" :aria-label="$t('modules.studioDialogs.keyEditor.name')" :placeholder="$t('modules.studioDialogs.keyEditor.namePlaceholder')" maxlength="128" show-word-limit/></el-form-item><el-form-item :label="$t('modules.studioDialogs.keyEditor.desc')"><el-input v-model="form.desc" :aria-label="$t('modules.studioDialogs.keyEditor.desc')" :placeholder="$t('modules.studioDialogs.keyEditor.descPlaceholder')" maxlength="200"/></el-form-item></div></FormSection>
      <FormSection number="02" :title="$t('modules.studioDialogs.keyEditor.sectionPermissions')" :note="$t('modules.studioDialogs.keyEditor.sectionPermissionsNote')">
        <el-form-item :label="$t('modules.studioDialogs.keyEditor.perms')" prop="perms"><div class="studio-choice-grid" role="group" :aria-label="$t('modules.studioDialogs.keyEditor.perms')"><button v-for="permission in permissions" :key="permission.code" type="button" role="checkbox" :aria-checked="form.perms.includes(permission.code)" :class="['studio-choice key-permission-card', { selected: form.perms.includes(permission.code) }]" @click="togglePermission(permission.code)"><span class="studio-choice-heading text-secondary"><component :is="permission.icon"/>{{ permission.name }}<span class="key-permission-check"><Check v-if="form.perms.includes(permission.code)"/></span></span><code class="text-code text-caption">{{ permission.code }}</code><span class="studio-choice-desc">{{ permission.description }}</span></button></div><p class="studio-field-help text-caption">{{ $t('modules.studioDialogs.keyEditor.permsHelp') }}</p></el-form-item>
        <el-form-item :label="$t('modules.studioDialogs.keyEditor.whitelist')"><el-select v-model="form.whitelistIds" multiple clearable filterable collapse-tags :max-collapse-tags="2" :aria-label="$t('modules.studioDialogs.keyEditor.whitelist')" :placeholder="$t('modules.studioDialogs.keyEditor.whitelistPlaceholder')"><el-option v-for="knowledge in knowledgeOptions" :key="knowledge.id" :label="knowledge.name" :value="knowledge.id"/></el-select><p class="studio-field-help text-caption">{{ $t('modules.studioDialogs.keyEditor.whitelistHelp') }}</p></el-form-item>
      </FormSection>
      <FormSection number="03" :title="$t('modules.studioDialogs.keyEditor.sectionLimits')" :note="$t('modules.studioDialogs.keyEditor.sectionLimitsNote')"><div class="studio-field-grid"><el-form-item :label="$t('modules.studioDialogs.keyEditor.limit')" prop="limit"><el-input-number v-model="form.limit" :aria-label="$t('modules.studioDialogs.keyEditor.limit')" :min="0" :precision="0" controls-position="right"/><p class="studio-field-help text-caption">{{ $t('modules.studioDialogs.keyEditor.limitHelp') }}</p></el-form-item><el-form-item :label="$t('modules.studioDialogs.keyEditor.expiry')" prop="expiryDate"><el-date-picker v-model="form.expiryDate" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" :disabled-date="disabledDate" clearable :aria-label="$t('modules.studioDialogs.keyEditor.expiry')" :placeholder="$t('modules.studioDialogs.keyEditor.expiryPlaceholder')"/><p class="studio-field-help text-caption">{{ $t('modules.studioDialogs.keyEditor.expiryHelp') }}</p></el-form-item></div></FormSection>
    </el-form>
    <template #actions><el-button :disabled="submitting" @click="open = false">{{ $t('modules.studioDialogs.common.cancel') }}</el-button><el-button type="primary" :loading="submitting" @click="submit"><Check v-if="editing"/><Plus v-else/>{{ editing ? $t('modules.studioDialogs.keyEditor.saveButton') : $t('modules.studioDialogs.keyEditor.createButton') }}</el-button></template>
  </StudioDialog>
</template>
<script setup>
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { Key, Document, Search, ChatDotRound, Files, VideoPlay, Check, Plus } from '@element-plus/icons-vue'
import { $t } from '@/app/i18n/i18n.js'
import StudioDialog from '@/shared/ui/StudioDialog.vue'
import FormSection from '@/shared/ui/FormSection.vue'
import { uniqueNameRule, expiryDateToUTC, isValidExpiryDate } from '@/shared/lib/form-validators'

const open = defineModel({ type: Boolean, default: false })
const props = defineProps({
  /** 编辑时的列表行；新建传 null */
  editing: { type: Object, default: null },
  /** 全部密钥行（名称判重） */
  existing: { type: Array, default: () => [] },
  /** 文档知识库下拉：{ id, name } */
  knowledgeOptions: { type: Array, default: () => [] },
  /** 后端支持的 scope 码；缺省为四条标准权限 + 运行工作流 */
  scopeOptions: { type: Array, default: () => ['kb:list', 'kb:search', 'kb:answer', 'workflow:read', 'workflow:run'] },
  submitHandler: { type: Function, default: null }
})
const emit = defineEmits(['save'])
const formRef = ref()
const nameInput = ref()
const submitting = ref(false)
let openSession = 0
const defaults = () => ({ name: '', desc: '', perms: ['kb:list', 'kb:search'], whitelistIds: [], limit: 60, expiryDate: '' })
const form = reactive(defaults())
const permissions = computed(() => {
  const catalog = [
    { code: 'kb:list', name: $t('modules.studioDialogs.keyEditor.permList'), description: $t('modules.studioDialogs.keyEditor.permListDesc'), icon: Document },
    { code: 'kb:search', name: $t('modules.studioDialogs.keyEditor.permSearch'), description: $t('modules.studioDialogs.keyEditor.permSearchDesc'), icon: Search },
    { code: 'kb:answer', name: $t('modules.studioDialogs.keyEditor.permAnswer'), description: $t('modules.studioDialogs.keyEditor.permAnswerDesc'), icon: ChatDotRound },
    { code: 'workflow:read', name: $t('modules.studioDialogs.keyEditor.permWorkflowRead'), description: $t('modules.studioDialogs.keyEditor.permWorkflowReadDesc'), icon: Files },
    { code: 'workflow:run', name: $t('modules.studioDialogs.keyEditor.permWorkflowRun'), description: $t('modules.studioDialogs.keyEditor.permWorkflowRunDesc'), icon: VideoPlay }
  ]
  return catalog.filter(item => props.scopeOptions.includes(item.code))
})
// 编辑一条已过期的 Key 时，日期没改就不该被「必须晚于今天」的规则拦住
// （helpers.buildPatchPayload 对「没改」的日期本来就不发）。
const originalExpiryDate = computed(() => (
  props.editing?.expiresAt ? String(props.editing.expiresAt).slice(0, 10) : ''
))
const footerHint = computed(() => {
  const scope = form.whitelistIds.length
    ? $t('modules.studioDialogs.keyEditor.hintScoped', { count: form.whitelistIds.length })
    : $t('modules.studioDialogs.keyEditor.hintAll')
  return $t('modules.studioDialogs.keyEditor.hint', { count: form.perms.length, scope })
})
const rules = {
  name: [uniqueNameRule(() => props.existing, $t('modules.studioDialogs.keyEditor.name'), () => props.editing)],
  perms: [{ type: 'array', required: true, min: 1, message: $t('modules.studioDialogs.keyEditor.permsRequired'), trigger: 'change' }],
  limit: [{
    required: true,
    trigger: 'change',
    validator: (_rule, value, done) => (
      Number.isSafeInteger(value) && value >= 0
        ? done()
        : done(new Error($t('modules.studioDialogs.keyEditor.limitInvalid')))
    )
  }],
  expiryDate: [{
    trigger: 'change',
    validator: (_rule, value, done) => (
      !value || value === originalExpiryDate.value || isValidExpiryDate(value)
        ? done()
        : done(new Error($t('modules.studioDialogs.keyEditor.expiryInvalid')))
    )
  }]
}
watch(open, value => {
  if (!value) {
    return
  }
  openSession += 1
  submitting.value = false
  const row = props.editing
  Object.assign(form, row
    ? {
      name: row.name,
      desc: row.description ?? row.desc ?? '',
      perms: [...(row.scopes || row.perms || [])],
      whitelistIds: [...(row.kbIds || row.whitelistIds || [])],
      limit: Number.parseInt(row.rateLimitPerMin ?? row.limit) || 0,
      expiryDate: row.expiresAt ? String(row.expiresAt).slice(0, 10) : ''
    }
    : defaults())
  formRef.value?.clearValidate()
})
function disabledDate (date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return !isValidExpiryDate(`${year}-${month}-${day}`)
}
async function togglePermission (code) {
  form.perms = form.perms.includes(code)
    ? form.perms.filter(permission => permission !== code)
    : [...form.perms, code]
  await nextTick()
  formRef.value?.validateField('perms').catch(() => {})
}
async function submit () {
  // 同步防重（原因同 CreateWorkflowDialog）
  if (submitting.value) {
    return
  }
  const session = openSession
  submitting.value = true
  try {
    if (!await formRef.value.validate().catch(() => false)) {
      return
    }
    const values = {
      name: form.name.trim(),
      desc: form.desc.trim(),
      scopes: [...form.perms],
      kbIds: [...form.whitelistIds],
      rateLimitPerMin: form.limit,
      expiresAt: expiryDateToUTC(form.expiryDate)
    }
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
.key-permission-card code { color: var(--rs-text-2); }
.key-permission-card.selected code { color: var(--rs-primary); }
.key-permission-check { display: flex; align-items: center; justify-content: center; width: 15px; height: 15px; margin-left: auto; border: 1px solid var(--rs-border); border-radius: 3px; background: var(--rs-bg-card); }
.key-permission-card.selected .key-permission-check { color: var(--rs-bg-card); background: var(--rs-primary); border-color: var(--rs-primary); }
.key-permission-check svg { width: 11px; height: 11px; }
</style>

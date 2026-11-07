<template>
  <el-drawer
    :model-value="modelValue"
    class="graph-entity-drawer"
    size="min(640px, 100vw)"
    append-to-body
    destroy-on-close
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="ge-header">
        <span :class="['ge-symbol', entityType.tone]"><Edit /></span>
        <div>
          <h2 class="text-section-title">{{ t('modules.kb.entityDrawerTitle') }}</h2>
          <p class="text-secondary">{{ displayName }}</p>
        </div>
        <span :class="['tag-soft', entityType.tone]">{{ entityType.name }}</span>
      </div>
    </template>

    <div v-if="entity && draft" class="ge-form" @keydown.ctrl.enter.prevent="save">
      <details class="ge-section" open>
        <summary>
          <span class="ge-section-number text-caption">01</span>
          <h3 class="text-section-title">{{ t('modules.kb.basicInfo') }}</h3>
          <ArrowDown />
        </summary>
        <div class="ge-section-body">
          <div class="ge-identity">
            <div>
              <span class="text-caption muted">{{ t('modules.kb.entityDrawerEntityId') }}</span>
              <div class="ge-readonly">
                <code>{{ entity.entity_id || entity.id }}</code>
                <button
                  type="button"
                  class="icon-button copy"
                  :aria-label="t('modules.kb.entityDrawerCopyEntityId')"
                  @click="copyText(entity.entity_id || entity.id)"
                >
                  <CopyDocument />
                </button>
              </div>
            </div>
            <div>
              <span class="text-caption muted">{{ t('modules.kb.entityType') }}</span>
              <div class="ge-readonly"><span>{{ entityType.name }}</span><Lock /></div>
            </div>
          </div>
          <el-form label-position="top" class="ge-basics" @submit.prevent>
            <el-form-item :label="t('modules.kb.entityDrawerEntityName')" :error="nameErrorText">
              <el-input
                ref="nameInputRef"
                v-model="draft.name"
                :aria-label="t('modules.kb.entityDrawerEntityName')"
                maxlength="128"
                show-word-limit
                :disabled="!draft.hasName"
                @input="nameError = ''"
              />
            </el-form-item>
            <el-form-item :label="t('modules.kb.entityDrawerEntityDescription')">
              <el-input
                v-model="draft.description"
                :aria-label="t('modules.kb.entityDrawerEntityDescription')"
                type="textarea"
                :autosize="{ minRows: 2, maxRows: 6 }"
                resize="vertical"
                :disabled="!draft.hasDescription"
                :placeholder="t('modules.kb.entityDrawerDescriptionPlaceholder')"
              />
            </el-form-item>
          </el-form>
          <div class="ge-source text-caption">
            <Document />
            <span>{{ t('modules.kb.entityDrawerSource', { source: entitySource }) }}</span>
          </div>
        </div>
      </details>

      <details ref="propertySection" class="ge-section" open>
        <summary>
          <span class="ge-section-number text-caption">02</span>
          <h3 class="text-section-title">
            {{ t('modules.kb.propertyInfo') }}
            <span class="ge-count text-caption">{{ draft.properties.length }}</span>
          </h3>
          <ArrowDown />
        </summary>
        <div class="ge-section-body">
          <el-input
            v-if="draft.properties.length > 5"
            v-model="search"
            :prefix-icon="Search"
            clearable
            :placeholder="t('modules.kb.entityDrawerSearchProperty')"
            :aria-label="t('modules.kb.entityDrawerSearchProperty')"
            class="ge-property-search"
          />
          <div v-if="Object.keys(errors).length" class="ge-error-summary text-secondary" role="alert">
            <WarningFilled />
            {{ t('modules.kb.entityDrawerErrorsSummary', { count: Object.keys(errors).length }) }}
          </div>
          <div
            v-for="field in visibleProperties"
            :key="field.key"
            :class="['ge-property', { 'is-json': field.kind === 'json' }]"
          >
            <div class="ge-property-heading">
              <label :for="fieldId(field.key)" class="text-secondary">{{ field.key }}</label>
              <span class="ge-kind text-caption">{{ kindNames[field.kind] || kindNames.string }}</span>
              <div v-if="field.kind === 'json'" class="ge-json-actions">
                <button
                  type="button"
                  class="ge-text-action text-caption"
                  :aria-label="t('modules.kb.entityDrawerFormatJsonFor', { name: field.key })"
                  @click="format(field)"
                >
                  {{ t('modules.kb.entityDrawerFormatJson') }}
                </button>
                <button
                  type="button"
                  class="icon-button copy"
                  :aria-label="t('modules.kb.entityDrawerCopyProperty', { name: field.key })"
                  @click="copyText(String(field.value))"
                >
                  <CopyDocument />
                </button>
              </div>
            </div>
            <el-switch
              v-if="field.kind === 'boolean'"
              :id="fieldId(field.key)"
              v-model="field.value"
              :aria-label="field.key"
              active-text="true"
              inactive-text="false"
            />
            <el-input
              v-else
              :id="fieldId(field.key)"
              v-model="field.value"
              :aria-label="field.key"
              :aria-invalid="!!errors[field.key]"
              :aria-describedby="errors[field.key] ? fieldId(field.key) + '-error' : undefined"
              :type="field.kind === 'json' || String(field.value).length > 80 || String(field.value).includes('\n') ? 'textarea' : 'text'"
              :autosize="field.kind === 'json' ? { minRows: 5, maxRows: 12 } : { minRows: 2, maxRows: 6 }"
              resize="vertical"
              :class="{ 'ge-field-error': errors[field.key] }"
              @input="delete errors[field.key]"
            />
            <p v-if="errors[field.key]" :id="fieldId(field.key) + '-error'" class="ge-field-message text-caption">
              {{ errorText(field.key) }}
            </p>
          </div>
          <div v-if="!visibleProperties.length" class="ge-empty text-secondary">
            {{ draft.properties.length ? t('modules.kb.entityDrawerNoMatchingProperties') : t('modules.kb.entityDrawerNoProperties') }}
          </div>
        </div>
      </details>

      <details class="ge-section ge-relations">
        <summary>
          <span class="ge-section-number text-caption">03</span>
          <h3 class="text-section-title">
            {{ t('modules.kb.entityDrawerRelations') }}
            <span class="ge-count text-caption">{{ relations.length }}</span>
          </h3>
          <ArrowDown />
        </summary>
        <div class="ge-section-body">
          <p v-if="dirty" class="text-caption muted">{{ t('modules.kb.entityDrawerDirtyRelationsHint') }}</p>
          <el-button class="button-compact ge-add-relation" :disabled="dirty || saving" @click="emit('add-relation')">
            <Plus />{{ t('modules.kb.addRelationship') }}
          </el-button>
          <ul class="workspace-panel-list">
            <li v-for="relation in relations" :key="relation.id">
              <button
                type="button"
                class="ge-relation"
                :disabled="dirty"
                @click="emit('select', relation.peer)"
              >
                <span class="text-caption muted">{{ relation.direction }} · {{ relation.label }}</span>
                <span class="text-secondary">{{ relation.peer.name }}<ArrowRight /></span>
              </button>
            </li>
          </ul>
          <p v-if="!relations.length" class="ge-empty text-secondary">{{ t('modules.kb.entityDrawerNoRelations') }}</p>
        </div>
      </details>
    </div>

    <template #footer>
      <div class="ge-footer">
        <p class="ge-session text-caption"><InfoFilled />{{ t('modules.kb.entityDrawerSaveHint') }}</p>
        <div class="ge-footer-actions">
          <el-button class="button-compact ge-locate" :disabled="dirty || saving" @click="emit('locate')">
            <Aim />{{ t('modules.kb.entityDrawerLocate') }}
          </el-button>
          <el-button class="button-compact" :disabled="saving" @click="emit('update:modelValue', false)">
            {{ t('modules.kb.cancel') }}
          </el-button>
          <el-button class="button-compact" type="primary" :loading="saving" @click="save">
            {{ t('modules.kb.entityDrawerSave') }}
          </el-button>
        </div>
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { ref, computed, watch, nextTick, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Edit,
  Lock,
  CopyDocument,
  ArrowDown,
  ArrowRight,
  Search,
  InfoFilled,
  Document,
  Aim,
  WarningFilled,
  Plus
} from '@element-plus/icons-vue'
import { copyTextWithToast } from '@/shared/lib/copy-with-toast'
import { createEntityDraft, parseEntityDraft } from '../lib/entity-draft'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  entity: { type: Object, default: null },
  entityType: { type: Object, required: true },
  propertyDefs: { type: Object, default: () => ({}) },
  relations: { type: Array, default: () => [] },
  saving: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'save', 'select', 'locate', 'add-relation'])
const { t } = useI18n()

const draft = ref(null)
const original = ref('')
const search = ref('')
const errors = ref({})
const nameError = ref('')
const nameInputRef = ref(null)
const propertySection = ref(null)
const prefix = useId()
const fieldId = (key) => `${prefix}-${encodeURIComponent(key)}`

const kindNames = computed(() => ({
  string: t('modules.kb.entityDrawerKindString'),
  number: t('modules.kb.entityDrawerKindNumber'),
  boolean: t('modules.kb.entityDrawerKindBoolean'),
  json: t('modules.kb.entityDrawerKindJson')
}))

const displayName = computed(() =>
  draft.value?.name || props.entity?.entity_name || props.entity?.entity_id || props.entity?.id || ''
)

const entitySource = computed(() => {
  const entity = props.entity || {}
  const propsObj = entity.properties && typeof entity.properties === 'object' ? entity.properties : {}
  return entity.source || propsObj.source || t('modules.kb.graphInfoNoSource')
})

const visibleProperties = computed(() => {
  const term = search.value.trim().toLowerCase()
  if (!draft.value) {
    return []
  }
  return term
    ? draft.value.properties.filter((field) => field.key.toLowerCase().includes(term))
    : draft.value.properties
})

const dirty = computed(() => !!draft.value && JSON.stringify(draft.value) !== original.value)

const nameErrorText = computed(() =>
  nameError.value ? t('modules.kb.entityDrawerNameRequired') : ''
)

const errorText = (key) => {
  const code = errors.value[key]
  if (code === 'json') {
    return t('modules.kb.entityDrawerJsonError')
  }
  if (code === 'jsonType') {
    return t('modules.kb.entityDrawerJsonTypeError')
  }
  if (code === 'integer') {
    return t('modules.kb.entityDrawerIntegerError')
  }
  if (code === 'number') {
    return t('modules.kb.entityDrawerNumberError')
  }
  return ''
}

function resetDraft () {
  if (!props.entity) {
    draft.value = null
    original.value = ''
    return
  }
  draft.value = createEntityDraft(props.entity, props.propertyDefs)
  original.value = JSON.stringify(draft.value)
  search.value = ''
  errors.value = {}
  nameError.value = ''
}

watch(
  () => [props.modelValue, props.entity?.entity_id || props.entity?.id],
  () => {
    if (!props.modelValue || !props.entity) {
      return
    }
    resetDraft()
  },
  { immediate: true }
)

/** 复制并提示结果（成功/失败都要有反馈，见 copy-with-toast.js）。 */
function copyText (text) {
  return copyTextWithToast(text)
}

function format (field) {
  try {
    field.value = JSON.stringify(JSON.parse(String(field.value)), null, 2)
    delete errors.value[field.key]
  } catch {
    errors.value[field.key] = 'json'
  }
}

async function save () {
  if (!draft.value || props.saving) {
    return
  }
  const parsed = parseEntityDraft(draft.value, props.propertyDefs)
  nameError.value = parsed.nameError
  errors.value = parsed.errors
  if (parsed.nameError || Object.keys(parsed.errors).length) {
    search.value = ''
    if (parsed.nameError) {
      await nextTick()
      nameInputRef.value?.focus?.()
    } else {
      if (propertySection.value) {
        propertySection.value.open = true
      }
      await nextTick()
      document.getElementById(fieldId(Object.keys(errors.value)[0]))?.focus()
    }
    return
  }
  emit('save', parsed.value)
}
</script>

<style>
/* 抽屉 teleport 到 body，样式保持全局作用域，统一加 .graph-entity-drawer 前缀 */
.graph-entity-drawer { border-left: 1px solid var(--rs-border); background: var(--rs-bg-card); }
.graph-entity-drawer .el-drawer__header { margin: 0; padding: 24px; border-bottom: 1px solid var(--rs-border); }
.graph-entity-drawer .el-drawer__body { padding: 0 24px; min-width: 0; overflow: auto; }
.graph-entity-drawer .el-drawer__footer { padding: 16px 24px; border-top: 1px solid var(--rs-border); }
.ge-header { display: flex; gap: 12px; align-items: center; min-width: 0; padding-right: 12px; }
.ge-header > div { flex: 1; min-width: 0; }
.ge-header h2 { margin: 0; color: var(--rs-text); }
.ge-header p { margin: 4px 0 0; color: var(--rs-text-3); overflow-wrap: anywhere; }
.ge-symbol { width: 40px; height: 40px; border-radius: 10px; display: flex; align-items: center; justify-content: center; background: var(--tint); color: var(--tone); flex-shrink: 0; }
.ge-section { padding: 22px 0; }
.ge-section + .ge-section { border-top: 1px solid var(--rs-border-soft); }
.ge-section summary { display: flex; align-items: center; gap: 10px; cursor: pointer; list-style: none; }
.ge-section summary::-webkit-details-marker { display: none; }
.ge-section summary > svg { width: 14px; height: 14px; margin-left: auto; color: var(--rs-text-3); transition: transform .15s; }
.ge-section[open] > summary > svg { transform: rotate(180deg); }
.ge-section summary:focus-visible { outline: 2px solid var(--rs-primary); outline-offset: 4px; }
.ge-section h3 { margin: 0; color: var(--rs-text); }
.ge-section-number { display: grid; place-items: center; width: 26px; height: 26px; border-radius: 6px; background: var(--rs-bg-selected); color: var(--rs-primary); font-weight: 600; }
.ge-section-body { padding-top: 20px; }
.ge-count { margin-left: 5px; color: var(--rs-text-3); font-weight: 400; }
.ge-identity { display: grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap: 16px; margin-bottom: 20px; }
.ge-readonly { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; margin-top: 7px; padding: 10px 12px; border-radius: 6px; border: 1px solid var(--rs-border-soft); background: var(--rs-bg-soft); color: var(--rs-text-2); min-height: 42px; overflow-wrap: anywhere; }
.ge-readonly code { font-size: var(--rs-font-size-code); min-width: 0; }
.ge-readonly > svg { width: 14px; height: 14px; color: var(--rs-text-3); margin-top: 3px; }
.ge-readonly button { flex-shrink: 0; }
.ge-basics .el-form-item { margin-bottom: 18px; }
.ge-basics .el-form-item__label { color: var(--rs-text-2); font-size: var(--rs-font-size-secondary); }
.ge-form .el-input__inner, .ge-form .el-textarea__inner { font-size: var(--rs-font-size-secondary); }
.ge-form .el-textarea__inner { line-height: 1.7; overflow-wrap: anywhere; padding: 10px 12px; }
.ge-source { display: flex; gap: 6px; align-items: flex-start; color: var(--rs-text-3); overflow-wrap: anywhere; }
.ge-source svg { width: 14px; height: 14px; margin-top: 2px; }
.ge-property-search { margin-bottom: 20px; }
.ge-property + .ge-property { margin-top: 20px; }
.ge-property-heading { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; min-height: 24px; }
.ge-property-heading label { color: var(--rs-text); overflow-wrap: anywhere; min-width: 0; font-family: var(--rs-font-family-mono); }
.ge-kind { color: var(--rs-text-3); background: var(--rs-bg-soft); padding: 1px 6px; border-radius: 4px; white-space: nowrap; }
.ge-json-actions { display: flex; align-items: center; gap: 8px; margin-left: auto; flex-shrink: 0; }
.ge-text-action { border: 0; background: transparent; padding: 0; color: var(--rs-primary); }
.ge-text-action:hover { text-decoration: underline; }
.ge-property.is-json .el-textarea__inner { font-family: var(--rs-font-family-mono); font-size: var(--rs-font-size-code); background: var(--rs-bg-soft); tab-size: 2; }
.ge-field-error .el-textarea__inner, .ge-field-error .el-input__wrapper { box-shadow: 0 0 0 1px var(--rs-danger) inset !important; }
.ge-field-message { color: var(--rs-danger); margin: 6px 0 0; }
.ge-error-summary { display: flex; gap: 8px; align-items: flex-start; color: var(--rs-danger); padding: 12px; margin-bottom: 18px; border-radius: 6px; background: color-mix(in srgb, var(--rs-danger) 7%, var(--rs-bg-card)); }
.ge-error-summary svg { width: 16px; height: 16px; margin-top: 3px; }
.ge-empty { text-align: center; padding: 20px 12px; margin: 0; color: var(--rs-text-3); background: var(--rs-bg-soft); border-radius: 6px; }
.ge-add-relation { margin-bottom: 12px; }
.ge-relation { display: flex; flex-direction: column; width: 100%; gap: 7px; border: 0; padding: 0; background: transparent; text-align: left; }
.ge-relation > span:last-child { display: flex; justify-content: space-between; gap: 12px; color: var(--rs-primary); }
.ge-relation:disabled { opacity: .5; cursor: not-allowed; }
.ge-relation svg { width: 14px; height: 14px; }
.ge-footer { display: flex; align-items: center; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
.ge-session { margin: 0; display: flex; gap: 6px; align-items: center; color: var(--rs-text-3); }
.ge-session svg { width: 13px; height: 13px; }
.ge-footer-actions { display: flex; gap: 8px; margin-left: auto; }
@media (max-width: 600px) {
  .graph-entity-drawer .el-drawer__header { padding: 20px 16px; }
  .graph-entity-drawer .el-drawer__body { padding: 0 16px; }
  .graph-entity-drawer .el-drawer__footer { padding: 14px 16px; }
  .ge-identity { grid-template-columns: minmax(0,1fr); gap: 12px; }
  .ge-header > .tag-soft { display: none; }
  .ge-section { padding: 20px 0; }
  .ge-footer { gap: 10px; }
  .ge-footer-actions { width: 100%; }
  .ge-locate { margin-right: auto; }
}
</style>

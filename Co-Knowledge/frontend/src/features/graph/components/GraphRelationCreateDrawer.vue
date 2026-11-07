<template>
  <el-drawer :model-value="modelValue" class="graph-relation-drawer" size="min(600px, 100vw)" append-to-body destroy-on-close :close-on-click-modal="false" @update:model-value="emit('update:modelValue', $event)">
    <template #header>
      <div class="gr-header">
        <span class="gr-header-icon"><Connection/></span>
        <div>
          <h2 class="text-section-title">{{ t('modules.kb.relationDrawerTitle') }}</h2>
          <p class="text-secondary">{{ t('modules.kb.relationDrawerSubtitle') }}</p>
        </div>
      </div>
    </template>

    <div class="gr-form" @keydown.ctrl.enter.prevent="save">
      <section class="gr-preview" :aria-label="t('modules.kb.relationPreview')" aria-live="polite">
        <div class="gr-preview-heading text-caption"><span>{{ t('modules.kb.relationPreview') }}</span><span class="gr-direction">{{ t('modules.kb.relationPreviewDirection') }}</span></div>
        <div class="gr-preview-diagram">
          <div v-for="(node, index) in [source, target]" :key="index" :class="['gr-preview-node', { 'is-empty': !node }]" :style="{gridColumn: index ? 3 : 1, gridRow: 1}">
            <span :class="['gr-avatar', node ? toneOf(node) : '']">{{ node ? nameOf(node).slice(0, 1) : '?' }}</span>
            <strong class="text-secondary">{{ node ? nameOf(node) : (index ? t('modules.kb.relationTargetPlaceholder') : t('modules.kb.relationSourcePlaceholder')) }}</strong>
            <span class="text-caption">{{ node ? typeOf(node) : t('modules.kb.relationNotSelected') }}</span>
          </div>
          <div :class="['gr-preview-connection', { 'is-ready': ready }]">
            <span class="text-caption">{{ draft.edgeType || t('modules.kb.relationTypePlaceholder') }}</span>
            <div><i/><Right/></div>
          </div>
        </div>
      </section>

      <section class="gr-section">
        <div class="gr-section-heading">
          <h3 class="text-section-title">{{ t('modules.kb.relationSectionConnect') }}</h3>
          <el-button text class="button-compact gr-swap" :disabled="!draft.source && !draft.target" @click="swap"><Sort/>{{ t('modules.kb.relationSwap') }}</el-button>
        </div>
        <div class="gr-endpoints">
          <div v-for="(endpoint, index) in endpoints" :key="endpoint.key" class="gr-endpoint">
            <span :class="['gr-endpoint-marker', { target: index }]">{{ index ? t('modules.kb.relationEndpointEnd') : t('modules.kb.relationEndpointStart') }}</span>
            <div class="gr-endpoint-field">
              <label :for="`${prefix}-${endpoint.key}`" class="text-secondary">{{ endpoint.label }}<span class="gr-required">*</span></label>
              <el-select
                :id="`${prefix}-${endpoint.key}`"
                v-model="draft[endpoint.key]"
                :aria-label="endpoint.label"
                filterable
                clearable
                :filter-method="query => entitySearch[endpoint.key] = query"
                :placeholder="endpoint.placeholder"
                popper-class="gr-entity-options"
                :class="{ 'gr-invalid': submitted && validation.errors[endpoint.key] }"
                @visible-change="entitySearch[endpoint.key] = ''"
              >
                <template #label="{ value, label }">
                  <span class="gr-selected-entity">
                    <i :style="{ background: toneColor(findNode(value)) }"/>
                    <span class="gr-selected-name" :title="label">{{ label }}</span>
                    <span class="gr-selected-type text-caption">{{ typeOf(findNode(value)) }}</span>
                  </span>
                </template>
                <el-option v-for="node in filteredNodes(endpoint.key)" :key="entityIdOf(node)" :label="nameOf(node)" :value="entityIdOf(node)" :disabled="entityIdOf(node) === draft[index ? 'source' : 'target']">
                  <div class="gr-option">
                    <span :class="['gr-option-avatar', toneOf(node)]">{{ nameOf(node).slice(0, 1) }}</span>
                    <div>
                      <div class="gr-option-name"><span>{{ nameOf(node) }}</span><span class="text-caption">{{ typeOf(node) }}</span></div>
                      <code>{{ entityIdOf(node) }}</code>
                    </div>
                  </div>
                </el-option>
                <template #empty><p class="gr-option-empty text-secondary">{{ t('modules.kb.relationNoMatch') }}</p></template>
              </el-select>
              <p v-if="submitted && validation.errors[endpoint.key]" class="gr-error text-caption" role="alert">{{ errorText(validation.errors[endpoint.key]) }}</p>
              <p v-else class="gr-entity-id text-caption">{{ findNode(draft[endpoint.key]) ? entityIdOf(findNode(draft[endpoint.key])) : t('modules.kb.relationSearchHint') }}</p>
            </div>
          </div>
        </div>
      </section>

      <section class="gr-section gr-type-section">
        <h3 class="text-section-title">{{ t('modules.kb.relationSectionDefine') }}</h3>
        <el-form label-position="top" @submit.prevent>
          <el-form-item :label="t('modules.kb.relationshipType')" required :error="submitted ? errorText(validation.errors.edgeType) : ''">
            <el-select v-model="draft.edgeType" :aria-label="t('modules.kb.relationshipType')" :placeholder="t('modules.kb.relationTypeSelectPlaceholder')" filterable popper-class="gr-type-options" :disabled="!source || !target">
              <el-option v-for="item in edgeOptions" :key="item.edge_type" :value="item.edge_type" :label="item.edge_type">
                <span>{{ item.edge_type }}</span><span class="gr-type-description text-caption">{{ item.edge_desc }}</span>
              </el-option>
            </el-select>
          </el-form-item>
        </el-form>
        <p v-if="validation.errors.duplicate" class="gr-duplicate text-secondary" role="alert"><WarningFilled/>{{ errorText(validation.errors.duplicate) }}</p>
        <p v-else-if="source && target && !edgeOptions.length" class="gr-duplicate text-secondary" role="alert"><WarningFilled/>{{ t('modules.kb.noAvailableEdgeTypes') }}</p>
        <p v-else class="gr-type-help text-caption"><InfoFilled/>{{ t('modules.kb.relationDirectionHelp') }}</p>
      </section>

      <details v-if="propertyDefs.length" class="gr-extra">
        <summary>
          <span class="text-secondary">{{ t('modules.kb.relationshipPropertyInfo') }}<span class="gr-optional text-caption">{{ t('modules.studioDialogs.common.optional') }}</span></span>
          <span class="gr-attribute-count text-caption">{{ t('modules.kb.relationPropertyCount', { count: propertyDefs.length }) }}</span>
          <ArrowDown/>
        </summary>
        <div class="gr-extra-body">
          <div v-for="definition in propertyDefs" :key="relationPropertyName(definition)" class="gr-attribute-row">
            <span class="gr-property-label text-secondary">{{ relationPropertyName(definition) }}</span>
            <template v-if="relationPropertyKind(definition) === 'boolean'">
              <el-select v-model="draft.properties[relationPropertyName(definition)]" :aria-label="relationPropertyName(definition)" class="gr-property-value">
                <el-option label="true" value="true"/>
                <el-option label="false" value="false"/>
              </el-select>
            </template>
            <el-input v-else v-model="draft.properties[relationPropertyName(definition)]" :aria-label="relationPropertyName(definition)" :placeholder="definition.desc || relationPropertyName(definition)" class="gr-property-value"/>
          </div>
          <p v-if="firstPropertyError" class="gr-error text-caption" role="alert">{{ errorText(firstPropertyError) }}</p>
          <p class="gr-auto-id text-caption"><Lock/>{{ t('modules.kb.relationIdNote') }}</p>
        </div>
      </details>
    </div>

    <template #footer>
      <div class="gr-footer">
        <span class="text-caption">{{ ready ? t('modules.kb.relationFooterReady') : t('modules.kb.relationFooterHint') }}</span>
        <div>
          <el-button class="button-compact" :disabled="saving" @click="emit('update:modelValue', false)">{{ $t('public.cancel') }}</el-button>
          <el-button type="primary" class="button-compact" :loading="saving" :disabled="!!validation.errors.duplicate" @click="save"><Plus/>{{ t('modules.kb.relationSubmit') }}</el-button>
        </div>
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { computed, nextTick, reactive, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Connection, Sort, Right, ArrowDown, Plus, InfoFilled, WarningFilled, Lock } from '@element-plus/icons-vue'
import { entityIdOf, entityTypeOf } from '../lib/entity-create-draft'
import {
  parseRelationDraft,
  relationEdgeOptions,
  relationPropertyDefs,
  relationPropertyKind,
  relationPropertyName
} from '../lib/relation-draft'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  sourceId: { type: String, default: '' },
  targetId: { type: String, default: '' },
  nodes: { type: Array, default: () => [] },
  edges: { type: Array, default: () => [] },
  typeTones: { type: Object, default: () => ({}) },
  edgeTypesFor: { type: Function, required: true },
  saving: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue', 'save'])
const { t } = useI18n()
const prefix = useId()
const submitted = ref(false)
const entitySearch = reactive({ source: '', target: '' })
const draft = reactive({ source: '', target: '', edgeType: '', properties: {} })

const endpoints = computed(() => [
  { key: 'source', label: t('modules.kb.relationSourceLabel'), placeholder: t('modules.kb.relationSourcePlaceholder') },
  { key: 'target', label: t('modules.kb.relationTargetLabel'), placeholder: t('modules.kb.relationTargetPlaceholder') }
])

function findNode (id) {
  return props.nodes.find(node => entityIdOf(node) === String(id || ''))
}
function nameOf (node) {
  return String(node?.properties?.name ?? node?.entity_name ?? entityIdOf(node))
}
function typeOf (node) {
  return entityTypeOf(node) || t('modules.kb.unknownType')
}
function toneOf (node) {
  return props.typeTones?.[entityTypeOf(node)] || 'blue'
}
function toneColor (node) {
  return node ? `var(--rs-tone-${toneOf(node)})` : 'var(--rs-border)'
}

const source = computed(() => findNode(draft.source))
const target = computed(() => findNode(draft.target))
const edgeOptions = computed(() => relationEdgeOptions(
  entityTypeOf(source.value),
  entityTypeOf(target.value),
  props.edgeTypesFor
))
const selectedOption = computed(() => edgeOptions.value.find(edge => edge.edge_type === draft.edgeType) || null)
const propertyDefs = computed(() => relationPropertyDefs(selectedOption.value))
const ready = computed(() => Boolean(source.value && target.value && draft.edgeType))

const validation = computed(() => parseRelationDraft({
  source: draft.source,
  target: draft.target,
  edgeType: draft.edgeType,
  properties: draft.properties
}, {
  nodes: props.nodes,
  edges: props.edges,
  edgeTypesFor: props.edgeTypesFor
}))

const firstPropertyError = computed(() => {
  const errors = validation.value.errors.properties || {}
  const key = Object.keys(errors).find(name => Boolean(errors[name]))
  return key ? errors[key] : ''
})

function filteredNodes (key) {
  const query = String(entitySearch[key] || '').trim().toLowerCase()
  return props.nodes.filter((node) => {
    const text = `${nameOf(node)} ${entityIdOf(node)} ${typeOf(node)}`.toLowerCase()
    return text.includes(query)
  })
}

function errorText (code) {
  switch (code) {
    case 'sourceRequired': return t('modules.kb.relationSourceRequired')
    case 'targetRequired': return t('modules.kb.relationTargetRequired')
    case 'selfLoop': return t('modules.kb.relationSelfLoop')
    case 'edgeTypeRequired': return t('modules.kb.relationEdgeTypeRequired')
    case 'duplicate': return t('modules.kb.relationDuplicate')
    case 'json': return t('modules.kb.entityDrawerJsonError')
    case 'jsonType': return t('modules.kb.entityDrawerJsonTypeError')
    case 'number': return t('modules.kb.entityDrawerNumberError')
    case 'integer': return t('modules.kb.entityDrawerIntegerError')
    default: return ''
  }
}

function swap () {
  const previousSource = draft.source
  draft.source = draft.target
  draft.target = previousSource
}

watch(() => props.modelValue, (open) => {
  if (!open) {
    return
  }
  draft.source = props.sourceId || ''
  draft.target = props.targetId || ''
  draft.edgeType = ''
  draft.properties = {}
  submitted.value = false
  entitySearch.source = ''
  entitySearch.target = ''
})

// 起点 / 终点变化后，原关系类型可能不再可用：清空选择与属性默认值
watch(() => [draft.source, draft.target], () => {
  if (draft.edgeType && !edgeOptions.value.some(edge => edge.edge_type === draft.edgeType)) {
    draft.edgeType = ''
  }
  draft.properties = {}
})

// 关系类型切换：按模板声明预填布尔默认值
watch(() => draft.edgeType, () => {
  const defaults = {}
  propertyDefs.value.forEach((definition) => {
    const name = relationPropertyName(definition)
    if (relationPropertyKind(definition) === 'boolean') {
      defaults[name] = 'false'
    }
  })
  draft.properties = defaults
})

async function save () {
  submitted.value = true
  if (!validation.value.valid) {
    await nextTick()
    const target = document.querySelector('.graph-relation-drawer .gr-invalid input, .graph-relation-drawer .is-error input, .graph-relation-drawer .gr-error')
    target?.scrollIntoView({ block: 'center' })
    target?.focus?.({ preventScroll: true })
    return
  }
  emit('save', validation.value.value)
}
</script>

<style>
.graph-relation-drawer { background: var(--rs-bg-card); border-left: 1px solid var(--rs-border); }
.graph-relation-drawer .el-drawer__header { padding: 24px; margin: 0; border-bottom: 1px solid var(--rs-border); }
.graph-relation-drawer .el-drawer__body { padding: 24px; min-width: 0; }
.graph-relation-drawer .el-drawer__footer { padding: 18px 24px; border-top: 1px solid var(--rs-border); }
.gr-header { display: flex; align-items: center; gap: 12px; padding-right: 12px; }
.gr-header-icon { width: 42px; height: 42px; display: grid; place-items: center; color: var(--rs-primary); background: var(--rs-bg-selected); border-radius: 11px; flex-shrink: 0; }
.gr-header-icon svg { width: 22px; height: 22px; }
.gr-header h2 { margin: 0; color: var(--rs-text); }
.gr-header p { margin: 4px 0 0; color: var(--rs-text-3); }
.gr-preview { padding: 16px 20px 20px; border: 1px solid var(--rs-border); border-radius: 10px; background: linear-gradient(135deg, var(--rs-bg-hover), var(--rs-bg-soft)); }
.gr-preview-heading { display: flex; justify-content: space-between; color: var(--rs-text-2); }
.gr-direction { color: var(--rs-text-3); }
.gr-preview-diagram { display: grid; grid-template-columns: minmax(0,1fr) minmax(80px,.85fr) minmax(0,1fr); align-items: start; margin-top: 22px; gap: 10px; }
.gr-preview-node { display: flex; align-items: center; flex-direction: column; gap: 7px; min-width: 0; }
.gr-preview-node:last-of-type { grid-column: 3; }
.gr-preview-node strong { font-weight: 550; color: var(--rs-text); text-align: center; overflow-wrap: anywhere; }
.gr-preview-node > .text-caption { color: var(--rs-text-3); }
.gr-avatar { display: grid; place-items: center; width: 46px; height: 46px; background: var(--rs-bg-card); color: var(--rs-tone-blue); border: 1px solid color-mix(in srgb, currentColor 45%, transparent); border-radius: 50%; font-weight: 600; }
.gr-avatar[class*="blue"] { color: var(--rs-tone-blue); background: var(--rs-tint-blue); }
.gr-avatar[class*="purple"] { color: var(--rs-tone-purple); background: var(--rs-tint-purple); }
.gr-avatar[class*="green"] { color: var(--rs-tone-green); background: var(--rs-tint-green); }
.gr-avatar[class*="orange"] { color: var(--rs-tone-orange); background: var(--rs-tint-orange); }
.gr-avatar[class*="red"] { color: var(--rs-tone-red); background: var(--rs-tint-red); }
.gr-preview-node.is-empty .gr-avatar { border: 1px dashed var(--rs-primary-border); background: transparent; color: var(--rs-text-3); }
.gr-preview-node.is-empty strong { color: var(--rs-text-3); font-weight: 400; }
.gr-preview-connection { grid-column: 2; grid-row: 1; padding-top: 1px; text-align: center; color: var(--rs-text-3); }
.gr-preview-connection > span { display: inline-block; background: var(--rs-bg-card); padding: 2px 9px; border: 1px solid var(--rs-border); border-radius: 5px; max-width: 100%; overflow-wrap: anywhere; }
.gr-preview-connection > div { display: flex; align-items: center; margin-top: 7px; }
.gr-preview-connection i { flex: 1; border-top: 1px dashed var(--rs-primary-border); }
.gr-preview-connection svg { width: 14px; height: 14px; margin-left: -7px; color: var(--rs-primary-border); }
.gr-preview-connection.is-ready { color: var(--rs-primary); }
.gr-preview-connection.is-ready > span { border-color: var(--rs-primary-border); }
.gr-preview-connection.is-ready i { border-color: var(--rs-primary); border-top-style: solid; }
.gr-preview-connection.is-ready svg { color: var(--rs-primary); }
.gr-section { padding: 24px 0; border-bottom: 1px solid var(--rs-border-soft); }
.gr-section-heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; gap: 10px; }
.gr-section h3 { margin: 0; color: var(--rs-text); }
.gr-swap.el-button { color: var(--rs-primary); padding-right: 0; }
.gr-swap svg { width: 14px; height: 14px; }
.gr-endpoints { position: relative; display: flex; flex-direction: column; gap: 20px; }
.gr-endpoints::before { content: ''; position: absolute; top: 23px; bottom: 72px; left: 13px; border-left: 1px dashed var(--rs-border); }
.gr-endpoint { display: flex; align-items: flex-start; gap: 14px; position: relative; }
.gr-endpoint-marker { display: grid; place-items: center; width: 27px; height: 27px; flex-shrink: 0; background: var(--rs-bg-selected); color: var(--rs-primary); font-size: var(--rs-font-size-caption); border-radius: 7px; border: 1px solid var(--rs-primary-border); }
.gr-endpoint-marker.target { background: var(--rs-tint-purple); color: var(--rs-tone-purple); border-color: color-mix(in srgb, var(--rs-tone-purple) 30%, var(--rs-border)); }
.gr-endpoint-field { flex: 1; min-width: 0; }
.gr-endpoint-field > label { display: block; color: var(--rs-text-2); margin-bottom: 9px; line-height: 27px; }
.gr-required { color: var(--rs-danger); margin-left: 4px; }
.gr-selected-entity { display: flex; align-items: center; gap: 8px; min-width: 0; }
.gr-selected-entity > i { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.gr-selected-entity > span { color: var(--rs-text-3); margin-left: auto; padding-left: 8px; }
.gr-entity-id { color: var(--rs-text-3); margin: 7px 0 0; overflow-wrap: anywhere; font-family: var(--rs-font-family-mono); font-size: var(--rs-font-size-code); }
.gr-invalid :deep(.el-select__wrapper) { box-shadow: 0 0 0 1px var(--rs-danger) inset; }
.gr-error { color: var(--rs-danger); margin: 6px 0 0; }
.gr-entity-options .el-select-dropdown__item { height: auto; padding: 10px 16px; line-height: 1.5; }
.gr-option { display: flex; align-items: center; gap: 10px; }
.gr-option-avatar { width: 32px; height: 32px; border-radius: 8px; display: grid; place-items: center; flex-shrink: 0; color: var(--rs-tone-blue); background: var(--rs-tint-blue); }
.gr-option-avatar.blue { color: var(--rs-tone-blue); background: var(--rs-tint-blue); }
.gr-option-avatar.purple { color: var(--rs-tone-purple); background: var(--rs-tint-purple); }
.gr-option-avatar.green { color: var(--rs-tone-green); background: var(--rs-tint-green); }
.gr-option-avatar.orange { color: var(--rs-tone-orange); background: var(--rs-tint-orange); }
.gr-option-avatar.red { color: var(--rs-tone-red); background: var(--rs-tint-red); }
.gr-option > div { flex: 1; min-width: 0; }
.gr-option-name { display: flex; justify-content: space-between; gap: 12px; }
.gr-option-name > span:first-child { overflow: hidden; text-overflow: ellipsis; }
.gr-option-name .text-caption { color: var(--rs-text-3); font-weight: 400; flex-shrink: 0; }
.gr-option code { display: block; font-size: var(--rs-font-size-code); color: var(--rs-text-3); font-weight: 400; white-space: normal; overflow-wrap: anywhere; }
.gr-option-empty { padding: 16px; color: var(--rs-text-3); text-align: center; }
.gr-type-section h3 { margin-bottom: 20px; }
.gr-type-section .el-form-item { margin-bottom: 12px; }
.gr-type-section .el-form-item__label { font-size: var(--rs-font-size-secondary); color: var(--rs-text-2); }
.gr-type-description { color: var(--rs-text-3); margin-left: 18px; float: right; font-weight: 400; }
.gr-type-options .el-select-dropdown__item { height: auto; min-height: 36px; white-space: normal; }
.gr-type-help, .gr-duplicate { display: flex; align-items: flex-start; gap: 6px; margin: 10px 0 0; color: var(--rs-text-3); }
.gr-type-help svg, .gr-duplicate svg { width: 14px; height: 14px; margin-top: 2px; }
.gr-duplicate { padding: 10px 12px; border-radius: 6px; color: var(--rs-warning); background: color-mix(in srgb, var(--rs-warning) 8%, var(--rs-bg-card)); }
.gr-extra { padding: 20px 0 0; }
.gr-extra summary { display: flex; align-items: center; gap: 10px; cursor: pointer; list-style: none; color: var(--rs-text-2); }
.gr-extra summary::-webkit-details-marker { display: none; }
.gr-extra summary > svg { width: 14px; height: 14px; color: var(--rs-text-3); margin-left: auto; transition: transform .15s; }
.gr-extra[open] summary > svg { transform: rotate(180deg); }
.gr-extra summary:focus-visible { outline: 2px solid var(--rs-primary); outline-offset: 4px; }
.gr-optional { margin-left: 8px; padding: 2px 6px; border-radius: 4px; color: var(--rs-text-3); background: var(--rs-bg-soft); }
.gr-attribute-count { color: var(--rs-text-3); }
.gr-extra-body { padding-top: 20px; }
.gr-attribute-row { display: grid; grid-template-columns: minmax(0, 0.8fr) minmax(0, 1.4fr); gap: 8px; align-items: center; margin-top: 10px; }
.gr-property-label { color: var(--rs-text-2); overflow-wrap: anywhere; }
.gr-property-value { min-width: 0; }
.gr-auto-id { display: flex; gap: 6px; align-items: center; margin: 20px 0 0; color: var(--rs-text-3); }
.gr-auto-id svg { width: 12px; height: 12px; }
.gr-footer { display: flex; flex-wrap: wrap; gap: 14px; align-items: center; justify-content: space-between; }
.gr-footer > span { color: var(--rs-text-3); }
.gr-footer > div { display: flex; gap: 8px; margin-left: auto; }
.gr-footer .el-button + .el-button { margin-left: 0; }
.gr-selected-entity > .gr-selected-name { min-width: 0; margin: 0; padding: 0; overflow: hidden; text-overflow: ellipsis; color: var(--rs-text); }
.gr-selected-entity > .gr-selected-type { flex-shrink: 0; }
@media (max-width: 600px) {
  .graph-relation-drawer .el-drawer__header { padding: 20px 16px; }
  .graph-relation-drawer .el-drawer__body { padding: 20px 16px; }
  .graph-relation-drawer .el-drawer__footer { padding: 14px 16px; }
  .gr-preview { padding: 14px 12px 18px; }
  .gr-preview-diagram { gap: 6px; }
  .gr-endpoint { gap: 10px; }
  .gr-preview-connection > span { padding: 2px 5px; }
  .gr-footer { gap: 10px; }
  .gr-footer > div { width: 100%; justify-content: flex-end; }
}
</style>

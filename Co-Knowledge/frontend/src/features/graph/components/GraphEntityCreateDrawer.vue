<template>
  <el-drawer
    :model-value="modelValue"
    class="graph-create-drawer"
    size="min(640px, 100vw)"
    append-to-body
    destroy-on-close
    :close-on-click-modal="false"
    :before-close="handleBeforeClose"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="studio-dialog-heading">
        <span class="studio-dialog-icon"><Plus /></span>
        <div>
          <h2>{{ t('modules.kb.createEntityTitle') }}</h2>
          <p class="text-secondary">{{ t('modules.kb.createEntitySubtitle', { graph: graphName || '—' }) }}</p>
        </div>
      </div>
    </template>

    <el-form
      v-if="draft"
      class="studio-form gc-form"
      label-position="top"
      @submit.prevent
      @keydown.ctrl.enter.prevent="submit"
    >
      <FormSection number="01" :title="t('modules.kb.createEntitySectionBasic')">
        <el-form-item :label="nameFieldLabel" required :error="errorText(errors.name)">
          <el-input
            ref="nameInputRef"
            v-model="draft.name"
            :aria-label="t('modules.kb.createEntityName')"
            :placeholder="t('modules.kb.createEntityNamePlaceholder')"
            maxlength="128"
            show-word-limit
            @input="errors.name = ''"
          />
        </el-form-item>
        <el-form-item :label="t('modules.kb.createEntityType')" required :error="errorText(errors.type)">
          <el-select
            v-model="draft.type"
            filterable
            :aria-label="t('modules.kb.createEntityType')"
            :placeholder="t('modules.kb.createEntityTypePlaceholder')"
            @change="handleTypeChange"
          >
            <el-option v-for="item in entityTypes" :key="item" :label="item" :value="item">
              <span class="gc-type-option"><i :style="{ background: toneColor(item) }" />{{ item }}</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item v-if="descriptionSupported" :label="t('modules.kb.createEntityDescription')">
          <el-input
            v-model="draft.description"
            :aria-label="t('modules.kb.createEntityDescription')"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 5 }"
            maxlength="1000"
            show-word-limit
            resize="vertical"
            :placeholder="t('modules.kb.createEntityDescriptionPlaceholder')"
          />
        </el-form-item>
        <p v-else class="studio-inline-note text-caption">
          <InfoFilled />{{ t('modules.kb.createEntityNoDescription') }}
        </p>
        <p class="studio-inline-note text-caption">
          <InfoFilled />{{ t('modules.kb.createEntityIdNote') }}
        </p>
      </FormSection>

      <FormSection
        number="02"
        :title="t('modules.kb.createEntitySectionProperties')"
        :note="t('modules.kb.createEntityOptional')"
      >
        <p class="gc-intro text-secondary">{{ propertiesIntro }}</p>
        <div v-for="(field, index) in draft.properties" :key="field.uid" class="gc-property">
          <div class="gc-property-head">
            <span class="text-caption muted">{{ t('modules.kb.createEntityPropertyIndex', { index: index + 1 }) }}</span>
            <button
              type="button"
              class="icon-button danger-icon"
              :aria-label="t('modules.kb.createEntityRemoveProperty', { index: index + 1 })"
              @click="removeProperty(index)"
            >
              <Delete />
            </button>
          </div>
          <div class="gc-property-fields">
            <el-form-item
              :label="t('modules.kb.createEntityPropertyName')"
              :error="errorText(errors.properties[index]?.key)"
            >
              <el-select
                v-if="schemaDeclared"
                v-model="field.key"
                filterable
                :aria-label="t('modules.kb.createEntityPropertyNameFor', { index: index + 1 })"
                :placeholder="t('modules.kb.createEntityPropertyNamePlaceholder')"
                @change="handlePropertyKeyChange(field, index)"
              >
                <el-option
                  v-for="item in availablePropertyOptions(index)"
                  :key="item.name"
                  :label="item.name"
                  :value="item.name"
                >
                  <span>{{ item.name }}</span>
                  <span class="gc-option-id text-caption">{{ kindLabelForDef(item) }}</span>
                </el-option>
              </el-select>
              <el-input
                v-else
                v-model="field.key"
                :aria-label="t('modules.kb.createEntityPropertyNameFor', { index: index + 1 })"
                :placeholder="t('modules.kb.createEntityPropertyKeyPlaceholder')"
                maxlength="64"
                @input="clearPropertyError(index)"
              />
            </el-form-item>
            <el-form-item :label="t('modules.kb.createEntityPropertyType')">
              <el-select
                v-if="!schemaDeclared"
                v-model="field.kind"
                :aria-label="t('modules.kb.createEntityPropertyKindFor', { index: index + 1 })"
                @change="handlePropertyKindChange(field, index)"
              >
                <el-option v-for="option in kindOptions" :key="option.value" :label="option.label" :value="option.value" />
              </el-select>
              <span v-else class="gc-kind">{{ kindLabel(rowKind(field)) }}</span>
            </el-form-item>
          </div>
          <el-form-item
            :label="t('modules.kb.createEntityPropertyValue')"
            :error="errorText(errors.properties[index]?.value)"
          >
            <el-switch
              v-if="rowKind(field) === 'boolean'"
              v-model="field.value"
              :aria-label="t('modules.kb.createEntityPropertyValueFor', { index: index + 1 })"
              active-text="true"
              inactive-text="false"
            />
            <el-input
              v-else
              v-model="field.value"
              :aria-label="t('modules.kb.createEntityPropertyValueFor', { index: index + 1 })"
              :type="rowKind(field) === 'json' ? 'textarea' : 'text'"
              :autosize="{ minRows: 3, maxRows: 8 }"
              :placeholder="valuePlaceholder(field)"
              :class="{ 'gc-json': rowKind(field) === 'json' }"
              @input="clearPropertyError(index)"
            />
          </el-form-item>
        </div>
        <el-button
          class="button-compact"
          :disabled="schemaDeclared && !availablePropertyOptions(draft.properties.length).length"
          @click="addProperty"
        >
          <Plus />{{ t('modules.kb.createEntityAddProperty') }}
        </el-button>
      </FormSection>

      <FormSection
        number="03"
        :title="t('modules.kb.createEntitySectionRelation')"
        :note="t('modules.kb.createEntityOptional')"
      >
        <div class="studio-switch-row">
          <div>
            <strong class="text-secondary">{{ t('modules.kb.createEntityRelationToggle') }}</strong>
            <p class="text-caption">{{ t('modules.kb.createEntityRelationHint') }}</p>
          </div>
          <el-switch
            v-model="draft.relation.enabled"
            :aria-label="t('modules.kb.createEntityRelationToggle')"
            :disabled="!entities.length"
            @change="handleRelationToggle"
          />
        </div>
        <p v-if="!entities.length" class="studio-field-help text-caption">
          {{ t('modules.kb.createEntityRelationEmpty') }}
        </p>
        <div v-if="draft.relation.enabled" class="gc-relation-fields">
          <el-form-item :label="t('modules.kb.createEntityPeer')" required :error="errorText(errors.peer)">
            <el-select
              v-model="draft.relation.peer"
              filterable
              :aria-label="t('modules.kb.createEntityPeer')"
              :placeholder="t('modules.kb.createEntityPeerPlaceholder')"
              @change="handlePeerChange"
            >
              <el-option
                v-for="item in entities"
                :key="entityIdOf(item)"
                :label="entityNameOf(item)"
                :value="entityIdOf(item)"
              >
                <span>{{ entityNameOf(item) }}</span>
                <span class="gc-option-id text-caption">{{ entityIdOf(item) }}</span>
              </el-option>
            </el-select>
          </el-form-item>
          <div class="studio-field-grid">
            <el-form-item
              :label="t('modules.kb.createEntityEdgeType')"
              required
              :error="errorText(errors.edgeType)"
            >
              <el-select
                v-model="draft.relation.edgeType"
                :aria-label="t('modules.kb.createEntityEdgeType')"
                :placeholder="t('modules.kb.createEntityEdgeTypePlaceholder')"
                :disabled="!relationEdgeOptions.length"
                @change="errors.edgeType = ''"
              >
                <el-option
                  v-for="item in relationEdgeOptions"
                  :key="item.edge_type"
                  :label="item.edge_type"
                  :value="item.edge_type"
                />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('modules.kb.createEntityDirection')">
              <el-select
                v-model="draft.relation.direction"
                :aria-label="t('modules.kb.createEntityDirection')"
                @change="handleDirectionChange"
              >
                <el-option
                  :label="t('modules.kb.createEntityDirectionOutgoing')"
                  value="newToPeer"
                />
                <el-option
                  :label="t('modules.kb.createEntityDirectionIncoming')"
                  value="peerToNew"
                />
              </el-select>
            </el-form-item>
          </div>
          <p v-if="peerEntity && !relationEdgeOptions.length" class="studio-field-help text-caption">
            {{ t('modules.kb.createEntityNoEdgeType') }}
          </p>
        </div>
      </FormSection>
    </el-form>

    <template #footer>
      <div class="studio-dialog-footer">
        <span class="studio-footer-hint text-caption">
          <InfoFilled />{{ t('modules.kb.createEntityFooterHint') }}
        </span>
        <div class="studio-footer-actions">
          <el-button @click="close">{{ t('public.cancel') }}</el-button>
          <!-- 名称或类型没填时**直接禁用**，与文档知识库「新建知识库」向导
               （必填未满足 → 禁用提交）保持一致。
               按钮恒可点、点下去只在表单项下方出现一行内联红字，
               在窄屏/长表单里很容易被当成「点了没反应」。 -->
          <el-button
            type="primary"
            :loading="saving"
            :disabled="!canSubmit"
            @click="submit"
          >
            <Plus v-if="!saving" />{{ t('modules.kb.createEntitySubmit') }}
          </el-button>
        </div>
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Plus, Delete, InfoFilled } from '@element-plus/icons-vue'
import FormSection from '@/shared/ui/FormSection.vue'
import { kindFromSchemaType } from '../lib/entity-draft'
import {
  compatibleEdgeOptions,
  entityIdOf,
  entityNameOf,
  entityTypeOf,
  kindForProperty,
  parseCreateEntityDraft,
  propertiesForType,
  resolveDescriptionProperty,
  resolveDisplayProperty
} from '../lib/entity-create-draft'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  graphName: { type: String, default: '' },
  entityTypes: { type: Array, default: () => [] },
  typeTones: { type: Object, default: () => ({}) },
  entities: { type: Array, default: () => [] },
  propertyDefs: { type: Object, default: () => ({}) },
  edgeTypesFor: { type: Function, required: true },
  saving: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'create'])
const { t } = useI18n()

const draft = ref(null)
const errors = ref(blankErrors())
const nameInputRef = ref(null)

const kindOptions = computed(() => [
  { value: 'string', label: t('modules.kb.entityDrawerKindString') },
  { value: 'number', label: t('modules.kb.entityDrawerKindNumber') },
  { value: 'boolean', label: t('modules.kb.entityDrawerKindBoolean') },
  { value: 'json', label: t('modules.kb.entityDrawerKindJson') }
])

const schemaProperties = computed(() => (
  draft.value ? propertiesForType(draft.value.type, props.propertyDefs) : []
))
const schemaDeclared = computed(() => schemaProperties.value.length > 0)
const displayProperty = computed(() => (
  draft.value ? resolveDisplayProperty(draft.value.type, props.propertyDefs) : null
))
const descriptionProperty = computed(() => (
  draft.value ? resolveDescriptionProperty(draft.value.type, props.propertyDefs) : null
))
const descriptionSupported = computed(() => !schemaDeclared.value || Boolean(descriptionProperty.value))

const propertiesIntro = computed(() => {
  if (!draft.value?.type) {
    return t('modules.kb.createEntityPropertiesIntro')
  }
  return schemaDeclared.value
    ? t('modules.kb.createEntityPropertiesIntro')
    : t('modules.kb.createEntityPropertiesIntroFree')
})

const nameFieldLabel = computed(() => {
  const property = displayProperty.value
  if (!property?.name || property.name === 'name') {
    return t('modules.kb.createEntityName')
  }
  return t('modules.kb.createEntityNameWithProperty', { property: property.name })
})

const peerEntity = computed(() => {
  if (!draft.value?.relation?.peer) {
    return null
  }
  return props.entities.find((item) => entityIdOf(item) === draft.value.relation.peer) || null
})

const relationEdgeOptions = computed(() => {
  if (!draft.value?.relation?.enabled || !draft.value.type || !peerEntity.value) {
    return []
  }
  return compatibleEdgeOptions(
    draft.value.type,
    entityTypeOf(peerEntity.value),
    draft.value.relation.direction,
    props.edgeTypesFor
  )
})

/**
 * 提交按钮的启用条件：**名称与类型都填了**。
 *
 * 只挡这两项（实体的最小身份）；属性/关联边的完整性仍由 ``submit`` 里的
 * ``parseCreateEntityDraft`` 行内报错处理 —— 那些提示需要按钮点得动才会出现，
 * 全部禁用反而让人不知道差在哪。
 */
const canSubmit = computed(() => (
  Boolean(String(draft.value?.name ?? '').trim()) && Boolean(draft.value?.type)
))

function blankErrors () {
  return { name: '', type: '', properties: [], peer: '', edgeType: '' }
}

function emptyDraft () {
  return {
    name: '',
    type: '',
    description: '',
    properties: [],
    relation: { enabled: false, peer: '', edgeType: '', direction: 'newToPeer' }
  }
}

function toneColor (type) {
  const tone = props.typeTones?.[type]
  return tone ? `var(--rs-tone-${tone})` : 'var(--rs-primary)'
}

function kindLabel (kind) {
  const option = kindOptions.value.find((item) => item.value === kind)
  return option ? option.label : kind
}

function kindLabelForDef (def) {
  return kindLabel(kindFromSchemaType(def?.type) || 'string')
}

function rowKind (field) {
  if (!schemaDeclared.value) {
    return field.kind
  }
  return field.key ? kindForProperty(draft.value.type, field.key, props.propertyDefs) : 'string'
}

function valuePlaceholder (field) {
  const kind = rowKind(field)
  if (kind === 'json') {
    return t('modules.kb.createEntityPropertyValueJsonPlaceholder')
  }
  if (kind === 'number') {
    return t('modules.kb.createEntityPropertyValueNumberPlaceholder')
  }
  return t('modules.kb.createEntityPropertyValuePlaceholder')
}

function availablePropertyOptions (index) {
  const excluded = new Set(
    [displayProperty.value?.name, descriptionProperty.value?.name].filter(Boolean)
  )
  draft.value?.properties.forEach((field, fieldIndex) => {
    if (fieldIndex !== index && field.key) {
      excluded.add(field.key)
    }
  })
  return schemaProperties.value.filter((item) => !excluded.has(item.name))
}

function handleTypeChange () {
  draft.value.properties = []
  errors.value = blankErrors()
  if (!descriptionSupported.value) {
    draft.value.description = ''
  }
  syncEdgeType()
}

function handleRelationToggle (enabled) {
  errors.value.peer = ''
  errors.value.edgeType = ''
  if (enabled) {
    syncEdgeType()
  }
}

function handlePeerChange () {
  errors.value.peer = ''
  errors.value.edgeType = ''
  syncEdgeType()
}

function handleDirectionChange () {
  errors.value.edgeType = ''
  syncEdgeType()
}

function syncEdgeType () {
  if (!draft.value?.relation?.enabled) {
    return
  }
  const options = relationEdgeOptions.value
  if (!options.some((item) => item.edge_type === draft.value.relation.edgeType)) {
    draft.value.relation.edgeType = options[0]?.edge_type || ''
  }
}

function addProperty () {
  if (!draft.value) {
    return
  }
  draft.value.properties.push({
    uid: `row-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    key: '',
    kind: 'string',
    value: ''
  })
  errors.value.properties.push({})
}

function removeProperty (index) {
  draft.value.properties.splice(index, 1)
  errors.value.properties.splice(index, 1)
}

function handlePropertyKeyChange (field, index) {
  const kind = rowKind(field)
  field.kind = kind
  field.value = kind === 'boolean' ? false : ''
  clearPropertyError(index)
}

function handlePropertyKindChange (field, index) {
  field.value = field.kind === 'boolean' ? false : ''
  clearPropertyError(index)
}

function clearPropertyError (index) {
  errors.value.properties[index] = {}
}

function errorText (code) {
  switch (code) {
    case 'nameRequired': return t('modules.kb.createEntityNameRequired')
    case 'typeRequired': return t('modules.kb.createEntityTypeRequired')
    case 'peerRequired': return t('modules.kb.createEntityPeerRequired')
    case 'edgeTypeRequired': return t('modules.kb.createEntityEdgeTypeRequired')
    case 'keyRequired': return t('modules.kb.createEntityPropertyKeyRequired')
    case 'duplicate': return t('modules.kb.createEntityPropertyDuplicate')
    case 'notDefined': return t('modules.kb.createEntityPropertyNotDefined')
    case 'json': return t('modules.kb.entityDrawerJsonError')
    case 'jsonType': return t('modules.kb.entityDrawerJsonTypeError')
    case 'number': return t('modules.kb.entityDrawerNumberError')
    case 'integer': return t('modules.kb.entityDrawerIntegerError')
    default: return ''
  }
}

async function submit () {
  // 抽屉关闭后 footer 节点仍在 DOM 里（Element Plus 的 destroy-on-close 只销毁 body），
  // 不能再提交上一轮草稿。
  if (!props.modelValue || !draft.value || props.saving) {
    return
  }
  const parsed = parseCreateEntityDraft(draft.value, {
    entityTypes: props.entityTypes,
    propertyDefs: props.propertyDefs,
    entities: props.entities,
    edgeTypesFor: props.edgeTypesFor
  })
  errors.value = parsed.errors
  if (!parsed.valid) {
    await nextTick()
    const item = document.querySelector('.graph-create-drawer .is-error')
    item?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    item?.querySelector('input,textarea')?.focus()
    return
  }
  emit('create', parsed.value)
}

function close () {
  if (props.saving) {
    return
  }
  emit('update:modelValue', false)
}

function handleBeforeClose (done) {
  if (props.saving) {
    return
  }
  done()
}

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) {
      draft.value = null
      errors.value = blankErrors()
      return
    }
    draft.value = emptyDraft()
    errors.value = blankErrors()
    await nextTick()
    nameInputRef.value?.focus?.()
  },
  { immediate: true }
)
</script>

<style>
.graph-create-drawer { border-left: 1px solid var(--rs-border); background: var(--rs-bg-card); }
.graph-create-drawer .el-drawer__header { margin: 0; padding: 24px; border-bottom: 1px solid var(--rs-border-soft); }
.graph-create-drawer .el-drawer__body { padding: 0 24px; min-width: 0; overflow: auto; }
.graph-create-drawer .el-drawer__footer { padding: 18px 24px; border-top: 1px solid var(--rs-border); background: var(--rs-bg-soft); }
.graph-create-drawer .studio-dialog-heading { min-width: 0; }
.graph-create-drawer .studio-dialog-heading > div { min-width: 0; }
.graph-create-drawer .studio-dialog-heading p { overflow-wrap: anywhere; }
.gc-intro { margin: 0 0 16px; color: var(--rs-text-3); }
.gc-property { padding: 14px; margin-bottom: 14px; border: 1px solid var(--rs-border); border-radius: 8px; }
.gc-property-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.gc-property-fields { display: grid; grid-template-columns: minmax(0, 1fr) 136px; gap: 12px; }
.gc-property .el-form-item { margin-bottom: 18px; }
.gc-property-fields > .el-form-item { min-width: 0; }
.gc-form .gc-json .el-textarea__inner { font-family: var(--rs-font-family-mono); background: var(--rs-bg-soft); }
.gc-relation-fields { margin-top: 20px; }
.gc-type-option { display: inline-flex; align-items: center; gap: 8px; }
.gc-type-option i { width: 8px; height: 8px; border-radius: 50%; }
.gc-option-id { margin-left: 12px; color: var(--rs-text-3); }
.gc-kind { display: flex; align-items: center; width: 100%; min-height: 40px; padding: 0 12px; box-sizing: border-box; border: 1px solid var(--rs-border); border-radius: 6px; background: var(--rs-bg-soft); color: var(--rs-text-2); }
@media (max-width: 600px) {
  .graph-create-drawer .el-drawer__header { padding: 20px 16px; }
  .graph-create-drawer .el-drawer__body { padding: 0 16px; }
  .graph-create-drawer .el-drawer__footer { padding: 14px 16px; }
  .gc-property-fields { grid-template-columns: minmax(0, 1fr); }
  .graph-create-drawer .studio-dialog-heading { gap: 10px; }
  .graph-create-drawer .studio-dialog-icon { width: 40px; height: 40px; }
}
</style>

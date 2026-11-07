<template>
  <el-drawer
    :key="drawerKey"
    ref="drawerRef"
    v-model="drawer"
    :class="['flow-config-drawer', { 'is-fixed': fixed }]"
    size="min(680px, 100vw)"
    append-to-body
    destroy-on-close
    :close-on-click-modal="false"
    :close-on-press-escape="true"
    :wrapper-closable="false"
    @closed="handleClosed"
  >
    <template #header>
      <div v-if="!fixed" class="fc-header">
        <span :class="['module-icon', tone || 'blue']"><Setting /></span>
        <div>
          <h2 class="text-section-title">{{ $t('modules.workflow.nodeConfig') }}</h2>
          <p class="text-caption">
            {{ title }}<code>{{ nodeLabel }}</code>
          </p>
        </div>
        <span class="tag-soft blue">
          {{ $t('modules.workflow.operatorCountBadge', { count: operatorCount }) }}
        </span>
      </div>
      <div v-else class="fc-header">
        <span :class="['module-icon', tone || 'blue']"><InfoFilled /></span>
        <div>
          <h2 class="text-section-title">{{ $t('modules.workflow.nodeInfo') }}</h2>
          <p class="text-caption">
            {{ title }}<code>{{ nodeLabel }}</code>
          </p>
        </div>
      </div>
    </template>

    <dl v-if="fixed" class="workspace-properties text-secondary">
      <div><dt>{{ $t('modules.workflow.nodeType') }}</dt><dd>{{ title }}</dd></div>
      <div>
        <dt>{{ fixedDirection }}</dt>
        <dd>{{ fixedField }}</dd>
      </div>
      <div><dt>{{ $t('modules.workflow.description') }}</dt><dd>{{ $t('modules.workflow.fixedNodeHint') }}</dd></div>
    </dl>

    <template v-else>
      <details ref="basicsRef" class="fc-basics" @toggle="onBasicsToggle">
        <summary>
          <h3 class="text-secondary">{{ $t('modules.workflow.basicInfoConnections') }}</h3>
          <span class="text-caption">
            {{ title }} · {{ $t('modules.workflow.upstreamCount', { count: upstreams.length }) }}
          </span>
          <ArrowDown />
        </summary>
        <el-form label-position="top" class="fc-grid" @submit.prevent>
          <el-form-item :label="$t('modules.workflow.nodeName')">
            <el-input
              :model-value="nodeLabel"
              maxlength="40"
              :aria-label="$t('modules.workflow.nodeName')"
              @update:model-value="$emit('update:nodeLabel', $event)"
            />
          </el-form-item>
          <el-form-item :label="$t('modules.workflow.upstreamNodes')">
            <el-select
              :model-value="upstreams"
              multiple
              collapse-tags
              collapse-tags-tooltip
              :max-collapse-tags="2"
              :placeholder="$t('modules.workflow.selectUpstream')"
              :aria-label="$t('modules.workflow.upstreamNodes')"
              @update:model-value="$emit('update:upstreams', $event)"
            >
              <el-option
                v-for="option in upstreamOptions"
                :key="option.id"
                :label="option.label"
                :value="option.id"
              />
            </el-select>
          </el-form-item>
        </el-form>
      </details>

      <slot />
    </template>

    <template #footer>
      <div v-if="!fixed" class="fc-footer">
        <p v-if="error" class="fc-error text-secondary" role="alert">{{ error }}</p>
        <button type="button" class="danger-action text-secondary" @click="$emit('delete')">
          <Delete />{{ $t('modules.workflow.deleteNode') }}
        </button>
        <div class="fc-footer-actions">
          <el-button class="button-compact" @click="cancelHandle">{{ $t('public.cancel') }}</el-button>
          <el-button class="button-compact" type="primary" @click="submitHandle">
            {{ $t('modules.workflow.applyNodeConfig') }}
          </el-button>
        </div>
        <p class="text-caption">{{ $t('modules.workflow.applyAfterHint') }}</p>
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { nextTick, ref } from 'vue'
import { ArrowDown, Delete, InfoFilled, Setting } from '@/shared/lib/icons'

const aipVueInstance = window.aipVueInstance

const props = defineProps({
  title: { type: String, default: '' },
  nodeLabel: { type: String, default: '' },
  operatorCount: { type: Number, default: 0 },
  tone: { type: String, default: 'blue' },
  fixed: { type: Boolean, default: false },
  fixedDirection: { type: String, default: '' },
  fixedField: { type: String, default: '' },
  upstreams: { type: Array, default: () => [] },
  upstreamOptions: { type: Array, default: () => [] }
})

const emit = defineEmits(['submitHandle', 'cancelHandle', 'closed', 'delete', 'update:nodeLabel', 'update:upstreams'])

const drawer = ref(false)
// 关闭动画未结束时再次打开：ElDrawer 的 afterLeave 会补发 update:modelValue(false)，
// 把新打开的抽屉又关掉。换 key 强制重建，旧实例的离场事件就落不到新实例上。
const drawerKey = ref(0)
const basicsRef = ref(null)
const basicsOpen = ref(false)
const error = ref('')

function openDrawer () {
  error.value = ''
  basicsOpen.value = false
  drawerKey.value += 1
  drawer.value = true
  nextTick(() => {
    drawerRef.value?.$el?.querySelector?.('.el-drawer__body')?.scrollTo?.({ top: 0 })
  })
}

function closeDrawer () {
  drawer.value = false
}

const drawerRef = ref(null)

function submitHandle () {
  const message = validateBasics()
  if (message) {
    showError(message)
    return
  }
  emit('submitHandle')
}

function cancelHandle () {
  emit('cancelHandle')
  drawer.value = false
}

function validateBasics () {
  if (props.fixed) {
    return ''
  }
  if (!props.nodeLabel?.trim()) {
    openBasics()
    return aipVueInstance.$t('modules.workflow.nodeNameRequired')
  }
  if (!props.upstreams?.length) {
    openBasics()
    return aipVueInstance.$t('modules.workflow.needUpstream')
  }
  return ''
}

function onBasicsToggle (event) {
  basicsOpen.value = !!event.target.open
}

function openBasics () {
  basicsOpen.value = true
  basicsRef.value && (basicsRef.value.open = true)
  nextTick(() => {
    basicsRef.value?.scrollIntoView?.({ block: 'start', behavior: 'smooth' })
  })
}

function showError (message) {
  error.value = message || ''
  if (error.value) {
    drawerRef.value?.$el?.querySelector?.('.el-drawer__body')?.scrollTo?.({ top: 0 })
  }
}

function clearError () {
  error.value = ''
}

function handleClosed () {
  error.value = ''
  basicsOpen.value = false
  emit('closed')
}

defineExpose({
  openDrawer,
  closeDrawer,
  showError,
  clearError
})
</script>

<style>
.flow-config-drawer {
  background: var(--rs-bg-card);
  border-left: 1px solid var(--rs-border);
}
.flow-config-drawer .el-drawer__header {
  margin: 0;
  padding: 18px 24px;
  border-bottom: 1px solid var(--rs-border);
}
.flow-config-drawer .el-drawer__body {
  padding: 0 24px;
  overflow: auto;
  min-width: 0;
}
.flow-config-drawer .el-drawer__footer {
  padding: 12px 24px;
  border-top: 1px solid var(--rs-border);
}
.flow-config-drawer.is-fixed .el-drawer__footer {
  display: none;
}
.fc-header {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding-right: 10px;
}
.fc-header > div {
  flex: 1;
  min-width: 0;
}
.fc-header h2 {
  color: var(--rs-text);
  margin: 0;
}
.fc-header p {
  margin: 5px 0 0;
  color: var(--rs-text-3);
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.fc-header code {
  font-size: var(--rs-font-size-code);
  overflow-wrap: anywhere;
}
.fc-header .module-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  color: var(--tone);
  background: var(--tint);
  flex-shrink: 0;
}
.fc-header .module-icon svg {
  width: 20px;
  height: 20px;
}
.fc-basics {
  border-bottom: 1px solid var(--rs-border-soft);
}
.fc-basics summary {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 54px;
  cursor: pointer;
  list-style: none;
}
.fc-basics summary::-webkit-details-marker {
  display: none;
}
.fc-basics summary > span {
  color: var(--rs-text-3);
  margin-left: auto;
}
.fc-basics summary svg {
  width: 13px;
  height: 13px;
  color: var(--rs-text-3);
}
.fc-basics[open] summary svg {
  transform: rotate(180deg);
}
.fc-basics h3 {
  margin: 0;
  color: var(--rs-text);
  font-weight: 600;
}
.fc-basics > .el-form {
  padding-top: 6px;
}
.fc-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
}
.fc-grid > * {
  min-width: 0;
}
.fc-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.fc-footer-actions {
  display: flex;
  gap: 8px;
  margin-left: auto;
}
.fc-footer p {
  width: 100%;
  margin: 0;
  text-align: right;
  color: var(--rs-text-3);
}
.fc-error {
  color: var(--rs-danger) !important;
  margin: 0;
  text-align: left !important;
}
.fc-error-banner {
  margin: 14px 0 0;
  padding: 8px 12px;
  border-radius: 6px;
  color: var(--rs-danger);
  background: color-mix(in srgb, var(--rs-danger) 8%, transparent);
  font-size: var(--rs-font-size-secondary);
}
/* .fc-text-action / svg 由全局 styles/flow-config.css 提供，不再复制。 */
.fc-delete {
  color: var(--rs-danger) !important;
}
@media (max-width: 540px) {
  .flow-config-drawer .el-drawer__header {
    padding: 18px 16px;
  }
  .flow-config-drawer .el-drawer__body {
    padding: 0 16px;
  }
  .flow-config-drawer .el-drawer__footer {
    padding: 14px 16px;
  }
  .fc-grid {
    grid-template-columns: minmax(0, 1fr);
    gap: 0;
  }
  .fc-header > .tag-soft {
    display: none;
  }
  .fc-footer p {
    text-align: left;
  }
}
</style>

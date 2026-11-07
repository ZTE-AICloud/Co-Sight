<template>
  <div
    class="ai-card-frame"
    :class="[`ai-card-frame--${toneClass}`, { 'highlight': highlightNode }]"
  >
    <header :class="['flow-node-heading', toneClass]" :title="tip || title">
      <span class="flow-node-icon" aria-hidden="true">
        <slot name="icon">
          <i v-if="icon" class="card-frame-header__glyph" :style="iconStyle" />
        </slot>
      </span>
      <div class="flow-node-title">
        <strong class="text-secondary">{{ title }}</strong>
        <code class="text-caption">{{ label }}</code>
      </div>
      <Lock v-if="fixed" class="node-lock" />
      <button
        v-else-if="showEditButton !== false"
        type="button"
        class="icon-button"
        :aria-label="aipVueInstance.$t('modules.workflow.configureNode', { name: title })"
        :title="aipVueInstance.$t('modules.workflow.configureNode', { name: title })"
        @pointerdown.stop
        @mousedown.stop
        @click.stop="editHandle"
      >
        <Setting />
      </button>
    </header>

    <div
      v-if="fixed"
      class="flow-fixed-body"
      role="button"
      tabindex="0"
      :aria-label="aipVueInstance.$t('modules.workflow.viewNodeConfig', { name: title })"
      @pointerdown.stop
      @mousedown.stop
      @click.stop="editHandle"
      @keydown.enter.prevent="editHandle"
      @keydown.space.prevent="editHandle"
    >
      <span class="text-caption">{{ fixedDirection }}</span>
      <span class="flow-fixed-field flow-io-row text-secondary">{{ fixedField }}</span>
    </div>

    <div
      v-else
      class="flow-node-contents"
      role="button"
      tabindex="0"
      :aria-label="aipVueInstance.$t('modules.workflow.viewNodeConfig', { name: title })"
      @pointerdown.stop
      @mousedown.stop
      @click.stop="editHandle"
      @keydown.enter.prevent="editHandle"
      @keydown.space.prevent="editHandle"
    >
      <div class="flow-operators">
        <div class="flow-section-label text-caption">
          <span>{{ aipVueInstance.$t('modules.workflow.operators') }}</span>
          <span>{{ operators.length }}</span>
        </div>
        <div
          v-for="(operator, index) in operators"
          :key="operator.key || index"
          class="flow-operator-row"
        >
          <span class="text-caption">{{ String(index + 1).padStart(2, '0') }}</span>
          <span class="text-secondary">{{ operator.name }}</span>
        </div>
        <div v-if="!operators.length" class="flow-operator-row text-caption muted">
          {{ aipVueInstance.$t('modules.workflow.noOperators') }}
        </div>
        <div
          v-if="sourceSummary && sourceSummary.text"
          class="flow-source-summary text-caption"
          :title="sourceSummary.title || sourceSummary.text"
        >
          {{ sourceSummary.text }}
        </div>
      </div>

      <div class="flow-io">
        <div class="flow-section-label text-caption">
          {{ aipVueInstance.$t('modules.workflow.inputs') }}
        </div>
        <div
          v-for="input in inputs"
          :key="input.id"
          class="flow-io-row text-caption"
        >
          <span :class="['flow-input-dot', input.tone || 'blue']" />
          <span>{{ input.title }}</span>
          <code>{{ input.label }}</code>
        </div>
        <div v-if="!inputs.length" class="flow-io-row text-caption muted">
          {{ aipVueInstance.$t('modules.workflow.noUpstream') }}
        </div>
      </div>

      <div class="flow-io">
        <div class="flow-section-label text-caption">
          {{ aipVueInstance.$t('modules.workflow.output') }}
        </div>
        <div class="flow-output-row text-caption">
          <code>{{ outputField }}</code>
          <span>→</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Setting, Lock } from '@/shared/lib/icons'

const aipVueInstance = window.aipVueInstance

interface Props {
  theme?: 'primary' | 'orange' | 'purple' | 'green' | 'gray' | ''
  icon?: string
  title?: string
  label?: string
  tip?: string
  fixed?: boolean
  highlightNode?: boolean
  showEditButton?: boolean
  operators?: Array<{ key?: string | number, name: string }>
  inputs?: Array<{ id: string, title: string, label: string, tone?: string }>
  outputField?: string
  sourceSummary?: { text: string, title?: string } | null
  fixedDirection?: string
  fixedField?: string
}

const props = withDefaults(defineProps<Props>(), {
  theme: 'primary',
  icon: '',
  title: '',
  label: '',
  tip: '',
  fixed: false,
  highlightNode: false,
  showEditButton: true,
  operators: () => [],
  inputs: () => [],
  outputField: '',
  sourceSummary: null,
  fixedDirection: '',
  fixedField: ''
})

const toneClass = computed(() => {
  const theme = props.theme || 'primary'
  return ['primary', 'gray', ''].includes(theme) ? 'blue' : theme
})

// 用图标字形的 tone 色；SVG 资源本身带固定填色，这里用 mask 取形状、
// 再用 --tone 上色，四类节点只用 --tone/--tint 两个变量。
const iconStyle = computed(() => (
  props.icon
    ? { '--card-frame-icon': `url("${props.icon}")` }
    : {}
))

const emit = defineEmits<{
  (e: 'editCardHandle'): void,
  (e: 'deleteCardHandle'): void
}>()

function editHandle () {
  emit('editCardHandle')
}
</script>

<style lang="less" scoped>
.ai-card-frame {
  --card-item-tone: var(--rs-tone-blue, #1677ff);
  --card-item-tint: var(--rs-tint-blue, #edf5ff);
  /* 卡片宽 264，白卡、10px 圆角、1px 描边、极轻投影。
     高度由 X6 节点尺寸给定（nodeGeometry.frameHeight），这里铺满。 */
  width: 100%;
  height: 100%;
  box-sizing: border-box;
  border: 1px solid var(--rs-border, #e5ebf4);
  border-radius: 10px;
  background: var(--rs-bg-card, #ffffff);
  box-shadow: 0 4px 14px #19264c06;
  color: var(--rs-text, #0c1538);
  overflow: hidden;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  user-select: none;

  &:hover {
    border-color: var(--rs-primary-border, #a4c8ff);
    box-shadow: 0 8px 20px #19264c12;
  }

  &.highlight {
    border-color: var(--rs-success, #09b34c);
    box-shadow:
      0 0 0 2px color-mix(in srgb, var(--rs-success, #09b34c) 18%, transparent),
      0 8px 20px #19264c12;
  }
}

.flow-node-heading {
  display: flex;
  align-items: center;
  gap: 9px;
  height: 52px;
  padding: 7px 12px;
  box-sizing: border-box;
  border-bottom: 1px solid var(--rs-border-soft);
  cursor: move;
  touch-action: none;
  background: color-mix(in srgb, var(--tint) 60%, var(--rs-bg-card));
}

.flow-node-title {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;

  strong {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--tone);
    font-size: 13px;
    font-weight: 600;
    line-height: 18px;
  }

  code {
    color: var(--rs-text-3);
    font-size: 10px;
    line-height: 14px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.flow-node-heading .icon-button {
  width: 24px;
  height: 26px;
  flex-shrink: 0;
  cursor: pointer;
}

.flow-node-heading .icon-button svg,
.node-lock {
  width: 14px;
  height: 14px;
  color: var(--rs-text-3);
}

.flow-node-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 7px;
  flex-shrink: 0;
  color: var(--tone);
  background: var(--tint);

  svg {
    width: 16px;
    height: 16px;
  }
}

.flow-node-contents {
  outline: none;
  cursor: pointer;
}

.flow-fixed-body {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  height: 86px;
  padding: 14px;
  box-sizing: border-box;
  width: 100%;
  text-align: left;
  color: var(--rs-text);
  outline: none;
  cursor: pointer;

  > span:first-child {
    height: 18px;
    line-height: 18px;
    color: var(--rs-text-2);
    font-weight: 600;
  }
}

.flow-fixed-field {
  width: 100%;
  flex-shrink: 0;
  background: var(--rs-bg-soft);
}

.flow-operators {
  padding: 14px 14px 0;
  margin-bottom: 14px;
}

.flow-section-label {
  height: 18px;
  line-height: 18px;
  margin-bottom: 8px;
  display: flex;
  justify-content: space-between;
  color: var(--rs-text-2);
  font-weight: 600;

  > span:last-child {
    font-family: var(--rs-font-family-mono);
    color: var(--rs-text-3);
    font-weight: 400;
  }
}

.flow-operator-row {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid var(--rs-border-soft);
  background: var(--rs-bg-soft);
  padding: 0 10px;
  height: 32px;
  box-sizing: border-box;
  border-radius: 5px;
  text-align: left;
  color: var(--rs-text);

  + .flow-operator-row {
    margin-top: 6px;
  }

  > span:first-child {
    color: var(--rs-text-3);
    font-family: var(--rs-font-family-mono);
    flex-shrink: 0;
  }

  > span:last-child {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.flow-operator-row:hover {
  border-color: var(--rs-primary-border);
  background: var(--rs-bg-hover);
}

.flow-source-summary {
  height: 20px;
  line-height: 20px;
  margin-top: 8px;
  color: var(--rs-text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.flow-io {
  padding: 0 14px 14px;
}

.flow-io-row {
  height: 32px;
  padding: 0 10px;
  box-sizing: border-box;
  border: 1px solid var(--rs-border-soft);
  border-radius: 5px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--rs-text-2);

  + .flow-io-row {
    margin-top: 6px;
  }

  > span:nth-child(2) {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
  }

  code {
    margin-left: auto;
    font-size: 10px;
    color: var(--rs-text-3);
    white-space: nowrap;
    max-width: 85px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
}

.flow-io-row.muted {
  color: var(--rs-text-3);
}

.flow-input-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--tone);
  flex-shrink: 0;
}

.flow-output-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 28px;
  padding: 0 10px;
  box-sizing: border-box;
  background: var(--rs-bg-soft);
  border-radius: 4px;
  color: var(--rs-text-2);
}

.card-frame-header__glyph {
  display: block;
  width: 16px;
  height: 16px;
  background: var(--tone);
  -webkit-mask: var(--card-frame-icon) center / contain no-repeat;
  mask: var(--card-frame-icon) center / contain no-repeat;
}
</style>

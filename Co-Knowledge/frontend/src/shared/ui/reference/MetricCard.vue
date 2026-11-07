<!--
  概览指标卡。
  结构与 class 必须保持现状（.metric-card / .metric-icon / .metric-body /
  .metric-label / .metric-bottom / .metric-value / .metric-change / .metric-delta /
  .metric-foot），样式全部来自 src/styles/management.css。
-->
<template>
  <div class="metric-card">
    <div :class="['metric-icon', tone]">
      <component :is="icon" />
    </div>
    <div class="metric-body">
      <div class="metric-label">
        {{ label }}
      </div>
      <div class="metric-bottom">
        <span class="metric-value">{{ value }}</span>
        <div v-if="delta" class="metric-change">
          <span
            :class="['metric-delta', { muted: muted || delta.includes('→') }]"
            :title="deltaTitle || undefined"
            :aria-label="deltaTitle || undefined"
          >{{ delta }}</span>
          <span class="metric-foot">{{ foot }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  label: { type: String, default: '' },
  value: { type: [String, Number], default: '' },
  delta: { type: String, default: '' },
  /** Unavailable/neutral delta (no historical trend API) */
  muted: { type: Boolean, default: false },
  /** Explains why the delta is unavailable; also exposes the real current count */
  deltaTitle: { type: String, default: '' },
  foot: { type: String, default: '较上周' },
  tone: { type: String, default: 'blue' },
  icon: { type: [Object, Function], default: null }
})
</script>

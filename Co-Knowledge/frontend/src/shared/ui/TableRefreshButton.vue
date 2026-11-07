<template>
  <div
    class="table-refresh-control"
    :class="{ 'has-compact-feedback': !inlineFeedback }"
    :aria-busy="refreshing"
  >
    <el-button
      :class="{ 'button-compact': compact }"
      :loading="refreshing"
      :aria-label="label"
      :title="inlineFeedback ? undefined : feedbackTitle"
      native-type="button"
      @click="refresh"
    >
      <Warning v-if="!refreshing && !inlineFeedback && refreshError" class="table-refresh-failure" />
      <CircleCheck v-else-if="!refreshing && !inlineFeedback && refreshedAt" class="table-refresh-success" />
      <Refresh v-else-if="!refreshing" />
      {{ refreshing && inlineFeedback ? $t('public.tableRefresh.refreshing') : $t('public.tableRefresh.action') }}
    </el-button>
    <span v-if="refreshError" class="table-refresh-error text-caption" role="alert">
      {{ $t('public.tableRefresh.failed') }}
    </span>
    <span
      v-else-if="refreshedAt"
      :key="refreshedAt.getTime()"
      class="table-refresh-status text-caption"
      role="status"
      :title="fullTime"
    >
      <CircleCheck />{{ $t('public.tableRefresh.done', { time }) }}
    </span>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Refresh, CircleCheck, Warning } from '@element-plus/icons-vue'
import { useTableRefresh } from '@/shared/composables/tableRefresh'
import { isGlobalZh } from '@/app/i18n/i18n.js'

const { t } = useI18n()

const props = defineProps({
  refresh: { type: Function, required: true },
  label: { type: String, default: '' },
  compact: Boolean,
  /** 0.1.12：浮层内不展示行内「已刷新 HH:MM」，改用按钮图标 + title，避免撑开浮层。 */
  inlineFeedback: { type: Boolean, default: true }
})

const { refreshing, refreshedAt, refreshError, refresh } = useTableRefresh(() => props.refresh())
const time = computed(() => refreshedAt.value?.toLocaleTimeString(isGlobalZh ? 'zh-CN' : 'en-US', {
  hour12: false,
  timeZone: 'Asia/Shanghai'
}))
const fullTime = computed(() => refreshedAt.value?.toLocaleString(isGlobalZh ? 'zh-CN' : 'en-US', {
  hour12: false,
  timeZone: 'Asia/Shanghai'
}))
const feedbackTitle = computed(() => {
  if (refreshError.value) {
    return t('public.tableRefresh.failed')
  }
  return refreshedAt.value
    ? t('public.tableRefresh.done', { time: fullTime.value })
    : undefined
})
</script>

<style scoped>
.table-refresh-control { display:inline-flex;align-items:center;flex-wrap:wrap;gap:6px 10px;min-width:0;max-width:100%; }
.table-refresh-control > .el-button { flex-shrink:0; }
.table-refresh-status { display:inline-flex;align-items:center;gap:4px;color:var(--rs-text-3);white-space:nowrap;animation:table-refresh-reveal .3s ease-out; }
.table-refresh-status svg { width:13px;height:13px;color:var(--rs-success); }
.table-refresh-error { color:var(--rs-danger-ink); }
.has-compact-feedback > .el-button { min-width:78px; }
.table-refresh-success { color:var(--rs-success); }
.table-refresh-failure { color:var(--rs-danger-ink); }
.has-compact-feedback .table-refresh-status,
.has-compact-feedback .table-refresh-error {
  position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
  clip:rect(0,0,0,0);white-space:nowrap;border:0;
}
@keyframes table-refresh-reveal { from { opacity:.2; } to { opacity:1; } }
@media(prefers-reduced-motion:reduce){.table-refresh-status{animation:none}}
</style>

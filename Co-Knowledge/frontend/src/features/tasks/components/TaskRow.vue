<template>
  <tr :class="{ 'task-child-row': child }">
    <td :class="{ 'task-title-cell': child }">
      <div class="entity">
        <div class="tinted-icon blue">
          <component :is="taskIcon" />
        </div>
        <div class="task-identity">
          <div class="entity-title task-title" :title="primaryTitle">
            {{ primaryTitle }}
          </div>
          <div class="entity-sub">
            <span v-if="task.fileName" class="task-short-id">{{ shortId(task.id) }}</span>
            <span class="tag-soft">{{ typeLabel(task.taskType, t) }}</span>
            <span class="tag-soft blue">{{ task.lane }}</span>
          </div>
        </div>
      </div>
    </td>
    <td>
      <div class="task-status-cell">
        <StatusText :type="statusTone(task.status)" :text="statusLabel(task.status, t)" />
        <span
          v-if="task.cancelRequested && task.status === 'RUNNING'"
          class="tag-soft orange"
        >
          {{ $t('modules.taskManagement.detailCancelRequested') }}
        </span>
      </div>
    </td>
    <td>
      <div class="task-progress">
        <el-progress
          :percentage="Number(task.progress) || 0"
          :stroke-width="6"
          :show-text="false"
        />
        <span>{{ Number(task.progress) || 0 }}%</span>
      </div>
    </td>
    <td>{{ task.priority }}</td>
    <td>
      {{ $t('modules.taskManagement.attemptValue', {
        attempt: task.attempt, max: task.maxAttempts
      }) }}
    </td>
    <td class="nowrap">
      <template v-if="showKbase">
        <div v-if="task.kbaseName" class="task-kbase-cell">
          <span class="task-kbase-name" :title="task.kbaseName">{{ task.kbaseName }}</span>
          <span class="task-short-id">{{ task.kbaseId }}</span>
        </div>
        <span v-else>{{ task.kbaseId || '—' }}</span>
      </template>
      <span v-else>—</span>
    </td>
    <td class="nowrap">
      {{ formatDateTime(task.createdAt) }}
    </td>
    <td>
      <div class="row-actions task-actions">
        <el-button link type="primary" @click="emit('detail', task)">
          {{ $t('modules.taskManagement.detail') }}
        </el-button>
        <el-button
          v-if="canCancel(task)"
          link
          type="warning"
          :loading="cancelling"
          @click="emit('cancel', task)"
        >
          {{ $t('modules.taskManagement.cancel') }}
        </el-button>
        <el-button
          v-if="canRetry(task)"
          link
          type="primary"
          :loading="retrying"
          @click="emit('retry', task)"
        >
          {{ $t('modules.taskManagement.retry') }}
        </el-button>
        <el-button v-if="canPrioritize(task)" link @click="emit('priority', task)">
          {{ $t('modules.taskManagement.priority') }}
        </el-button>
      </div>
    </td>
  </tr>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Coin, Document, Share } from '@element-plus/icons-vue'

import StatusText from '@/shared/ui/StatusText.vue'
import {
  canCancel, canPrioritize, canRetry, formatDateTime, shortId,
  statusLabel, statusTone, typeLabel
} from '@/features/tasks/lib/display'

const props = defineProps({
  task: { type: Object, required: true },
  child: { type: Boolean, default: false },
  showKbase: { type: Boolean, default: true },
  cancelling: { type: Boolean, default: false },
  retrying: { type: Boolean, default: false }
})

const emit = defineEmits(['detail', 'cancel', 'retry', 'priority'])
const { t } = useI18n()

const TASK_ICONS = { FILE_IMPORT: Document, T2S_INDEX: Coin }

const taskIcon = computed(() => TASK_ICONS[props.task.taskType] || Share)

const primaryTitle = computed(() => (
  props.task.fileName || shortId(props.task.id)
))
</script>

<style scoped>
.task-identity { min-width: 0; }
.task-title { max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-short-id { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; color: var(--rs-text-3); font-size: var(--rs-table-secondary-font-size); }
.task-kbase-cell { display: flex; flex-direction: column; gap: 2px; }
.task-kbase-name { max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--rs-text); }
.task-status-cell { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; }
.task-progress { display: flex; align-items: center; gap: 10px; min-width: 130px; }
.task-progress :deep(.el-progress) { flex: 1; }
.task-progress span { color: var(--rs-text-3); font-size: var(--rs-table-secondary-font-size); min-width: 34px; text-align: right; }
.task-actions { flex-wrap: wrap; gap: 12px; }
.task-child-row .task-title-cell { padding-left: 48px; }
</style>

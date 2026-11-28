<template>
  <el-drawer
    :model-value="modelValue"
    :title="$t('modules.taskManagement.detailTitle')"
    size="min(680px, 92vw)"
    class="task-detail-drawer"
    @update:model-value="value => emit('update:modelValue', value)"
    @closed="emit('closed')"
  >
    <div v-if="task" v-loading="loading" class="task-detail">
      <div class="task-detail-actions">
        <el-button
          v-if="canCancel(task)"
          type="warning"
          plain
          :loading="cancellingId === task.id"
          @click="emit('cancel', task)"
        >
          {{ $t('modules.taskManagement.cancel') }}
        </el-button>
        <el-button
          v-if="canRetry(task)"
          type="primary"
          plain
          :loading="retryingId === task.id"
          @click="emit('retry', task)"
        >
          {{ $t('modules.taskManagement.retry') }}
        </el-button>
        <el-button
          v-if="canPrioritize(task)"
          plain
          @click="emit('priority', task)"
        >
          {{ $t('modules.taskManagement.priority') }}
        </el-button>
        <TableRefreshButton
          :label="$t('modules.taskManagement.refresh')"
          :refresh="() => emit('refresh', task.id)"
        />
      </div>

      <dl class="task-detail-summary">
        <div>
          <dt>{{ $t('modules.taskManagement.detailTaskId') }}</dt>
          <dd class="task-detail-id">
            {{ task.id }}
          </dd>
        </div>
        <div v-if="task.fileName">
          <dt>{{ $t('modules.taskManagement.detailFileName') }}</dt>
          <dd class="task-detail-file">
            {{ task.fileName }}
          </dd>
        </div>
        <div>
          <dt>{{ $t('modules.taskManagement.detailType') }}</dt>
          <dd>{{ typeLabel(task.taskType, t) }}</dd>
        </div>
        <div>
          <dt>{{ $t('modules.taskManagement.detailLane') }}</dt>
          <dd>{{ task.lane }}</dd>
        </div>
        <div>
          <dt>{{ $t('modules.taskManagement.detailStatus') }}</dt>
          <dd>
            <StatusText :type="statusTone(task.status)" :text="statusLabel(task.status, t)" />
          </dd>
        </div>
        <div>
          <dt>{{ $t('modules.taskManagement.detailKbase') }}</dt>
          <dd>
            <template v-if="task.kbaseName">
              <div>{{ task.kbaseName }}</div>
              <span class="task-detail-sub">{{ task.kbaseId }}</span>
            </template>
            <span v-else>{{ task.kbaseId || '—' }}</span>
          </dd>
        </div>
        <div>
          <dt>{{ $t('modules.taskManagement.detailPriority') }}</dt>
          <dd>{{ task.priority }}</dd>
        </div>
        <div>
          <dt>{{ $t('modules.taskManagement.detailAttempt') }}</dt>
          <dd>
            {{ $t('modules.taskManagement.attemptValue', {
              attempt: task.attempt, max: task.maxAttempts
            }) }}
          </dd>
        </div>
        <div>
          <dt>{{ $t('modules.taskManagement.detailCreated') }}</dt>
          <dd>{{ formatDateTime(task.createdAt) || '—' }}</dd>
        </div>
        <div>
          <dt>{{ $t('modules.taskManagement.detailStarted') }}</dt>
          <dd>{{ formatDateTime(task.startTime) || '—' }}</dd>
        </div>
        <div>
          <dt>{{ $t('modules.taskManagement.detailFinished') }}</dt>
          <dd>{{ formatDateTime(task.finishTime) || '—' }}</dd>
        </div>
        <div>
          <dt>{{ $t('modules.taskManagement.detailWorker') }}</dt>
          <dd>{{ task.lockedBy || '—' }}</dd>
        </div>
        <div>
          <dt>{{ $t('modules.taskManagement.detailError') }}</dt>
          <dd class="task-detail-error">
            {{ task.errorMessage || '—' }}
          </dd>
        </div>
      </dl>

      <el-tabs v-model="activeTab">
        <el-tab-pane :label="$t('modules.taskManagement.detailPayload')" name="payload">
          <pre class="task-detail-json">{{ prettyJson(task.payload) }}</pre>
        </el-tab-pane>
        <el-tab-pane :label="$t('modules.taskManagement.detailExtra')" name="extra">
          <section v-if="extraFacts.length" class="task-result">
            <div class="task-result-title">
              {{ $t('modules.taskManagement.detailResultSummary') }}
            </div>
            <dl class="task-result-grid">
              <div v-for="fact in extraFacts" :key="fact.label">
                <dt>{{ fact.label }}</dt>
                <dd>{{ fact.value }}</dd>
              </div>
            </dl>
          </section>
          <div v-if="extraFacts.length" class="task-result-title">
            {{ $t('modules.taskManagement.detailRawJson') }}
          </div>
          <pre class="task-detail-json">{{ prettyJson(task.extra) }}</pre>
        </el-tab-pane>
        <el-tab-pane
          :label="$t('modules.taskManagement.detailAttempts')"
          name="attempts"
        >
          <table v-if="task.attempts?.length" class="list-table attempts-table">
            <thead>
              <tr>
                <th>#</th>
                <th>{{ $t('modules.taskManagement.attemptStatus') }}</th>
                <th>{{ $t('modules.taskManagement.attemptWorker') }}</th>
                <th>{{ $t('modules.taskManagement.attemptStarted') }}</th>
                <th>{{ $t('modules.taskManagement.attemptDuration') }}</th>
                <th>{{ $t('modules.taskManagement.detailError') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(attempt, index) in task.attempts" :key="`${attempt.attempt}-${index}`">
                <td>{{ attempt.attempt }}</td>
                <td>
                  <StatusText
                    :type="attemptTone(attempt.status)"
                    :text="attemptLabel(attempt.status, t)"
                  />
                </td>
                <td class="nowrap">
                  {{ attempt.workerId || '—' }}
                </td>
                <td class="nowrap">
                  {{ formatDateTime(attempt.startedAt) || '—' }}
                </td>
                <td>{{ formatDuration(attempt.durationMs) }}</td>
                <td class="task-detail-error">
                  {{ attempt.errorMessage || '—' }}
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else class="task-detail-empty">
            {{ $t('modules.taskManagement.attemptsEmpty') }}
          </p>
        </el-tab-pane>
      </el-tabs>
    </div>
  </el-drawer>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import StatusText from '@/shared/ui/StatusText.vue'
import TableRefreshButton from '@/shared/ui/TableRefreshButton.vue'
import {
  attemptLabel, attemptTone, canCancel, canPrioritize, canRetry,
  formatDateTime, formatDuration, prettyJson, resultFacts, statusLabel,
  statusTone, typeLabel
} from '@/features/tasks/lib/display'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  task: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  cancellingId: { type: String, default: '' },
  retryingId: { type: String, default: '' }
})

const emit = defineEmits(['update:modelValue', 'closed', 'cancel', 'retry', 'priority', 'refresh'])

const { t } = useI18n()
const activeTab = ref('payload')
const extraFacts = computed(() => resultFacts(props.task, t))

watch(() => props.modelValue, value => {
  if (value) {
    activeTab.value = 'payload'
  }
})
</script>

<style scoped>
.task-detail { display: flex; flex-direction: column; gap: 20px; }
.task-detail-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.task-detail-summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 24px; margin: 0; padding: 18px; border: 1px solid var(--rs-border); border-radius: var(--rs-radius); background: var(--rs-bg-card); }
.task-detail-summary div { min-width: 0; }
.task-detail-summary dt { color: var(--rs-text-3); font-size: var(--rs-font-size-caption); margin-bottom: 4px; }
.task-detail-summary dd { margin: 0; color: var(--rs-text); overflow-wrap: anywhere; }
.task-detail-id { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.task-detail-file { color: var(--rs-text); overflow-wrap: anywhere; }
.task-detail-sub { color: var(--rs-text-3); font-size: var(--rs-table-secondary-font-size); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.task-detail-error { color: var(--rs-text-2); overflow-wrap: anywhere; max-width: 260px; }
.task-detail-json { margin: 0; padding: 14px; border-radius: var(--rs-radius); border: 1px solid var(--rs-border); background: var(--rs-bg-soft); color: var(--rs-text-2); font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-all; max-height: 420px; overflow: auto; }
.task-result { margin-bottom: 18px; }
.task-result-title { margin-bottom: 10px; color: var(--rs-text-3); font-size: var(--rs-font-size-caption); }
.task-result-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px 20px; margin: 0 0 16px; padding: 16px; border: 1px solid var(--rs-border); border-radius: var(--rs-radius); background: var(--rs-bg-soft); }
.task-result-grid div { min-width: 0; }
.task-result-grid dt { color: var(--rs-text-3); font-size: var(--rs-font-size-caption); margin-bottom: 4px; }
.task-result-grid dd { margin: 0; color: var(--rs-text); overflow-wrap: anywhere; }
.task-detail-empty { color: var(--rs-text-3); margin: 12px 0; }
.attempts-table { min-width: 0; }
.attempts-table th, .attempts-table td { padding-left: 10px; padding-right: 10px; }
@media (max-width: 900px) {
  .task-detail-summary,
  .task-result-grid { grid-template-columns: 1fr; }
}
</style>

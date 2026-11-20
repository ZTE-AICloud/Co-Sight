<template>
  <div v-loading="loading" class="table-card">
    <table class="list-table tasks-table">
      <thead>
        <tr>
          <th>{{ $t('modules.taskManagement.columnTask') }}</th>
          <th>{{ $t('modules.taskManagement.columnStatus') }}</th>
          <th>{{ $t('modules.taskManagement.columnProgress') }}</th>
          <th>{{ $t('modules.taskManagement.columnPriority') }}</th>
          <th>{{ $t('modules.taskManagement.columnAttempt') }}</th>
          <th>{{ $t('modules.taskManagement.columnKbase') }}</th>
          <th>{{ $t('modules.taskManagement.columnCreated') }}</th>
          <th>{{ $t('modules.taskManagement.columnActions') }}</th>
        </tr>
      </thead>
      <tbody>
        <template v-if="viewMode === 'tree'">
          <template v-for="group in groups" :key="groupKey(group)">
            <tr class="task-group-row" @click="emit('toggle-group', group)">
              <td>
                <div class="task-group-title">
                  <button
                    type="button"
                    class="icon-button task-group-toggle"
                    :aria-label="$t(expanded[groupKey(group)]
                      ? 'modules.taskManagement.collapseGroup'
                      : 'modules.taskManagement.expandGroup')"
                    :aria-expanded="Boolean(expanded[groupKey(group)])"
                    @click.stop="emit('toggle-group', group)"
                  >
                    <CaretBottom v-if="expanded[groupKey(group)]" />
                    <CaretRight v-else />
                  </button>
                  <div class="tinted-icon task-group-icon">
                    <Collection />
                  </div>
                  <div class="task-identity">
                    <div class="entity-title task-group-name" :title="groupTitle(group)">
                      {{ groupTitle(group) }}
                    </div>
                    <div class="entity-sub">
                      <span class="tag-soft green">
                        {{ $t('modules.taskManagement.groupTaskCount', {
                          count: group.total
                        }) }}
                      </span>
                      <span v-if="group.kbaseId" class="task-short-id">
                        {{ group.kbaseId }}
                      </span>
                    </div>
                  </div>
                </div>
              </td>
              <td>
                <div class="task-group-status">
                  <span
                    v-for="tag in groupStatusTags(group)"
                    :key="tag.status"
                    :class="['tag-soft', tag.className]"
                  >
                    {{ tag.label }} {{ tag.count }}
                  </span>
                </div>
              </td>
              <td>—</td>
              <td>—</td>
              <td>—</td>
              <td>—</td>
              <td class="nowrap">
                {{ formatDateTime(group.latestCreatedAt) }}
              </td>
              <td>
                <el-button link type="primary" @click.stop="emit('toggle-group', group)">
                  {{ $t(expanded[groupKey(group)]
                    ? 'modules.taskManagement.collapseGroup'
                    : 'modules.taskManagement.expandGroup') }}
                </el-button>
              </td>
            </tr>

            <template v-if="expanded[groupKey(group)]">
              <TaskRow
                v-for="task in groupState(group).items"
                :key="task.id"
                :task="task"
                child
                :show-kbase="false"
                :cancelling="cancellingId === task.id"
                :retrying="retryingId === task.id"
                @detail="task => emit('detail', task)"
                @cancel="task => emit('cancel', task)"
                @retry="task => emit('retry', task)"
                @priority="task => emit('priority', task)"
              />
              <tr v-if="groupState(group).loading && !groupState(group).items.length">
                <td colspan="8" class="empty-row">
                  {{ $t('modules.taskManagement.loading') }}
                </td>
              </tr>
              <tr
                v-else-if="!groupState(group).loading && !groupState(group).items.length"
              >
                <td colspan="8" class="empty-row">
                  {{ $t('modules.taskManagement.empty') }}
                </td>
              </tr>
              <tr
                v-else-if="groupState(group).items.length < group.total"
                class="task-group-more"
              >
                <td colspan="8">
                  <el-button
                    link
                    type="primary"
                    :loading="groupState(group).loading"
                    @click="emit('load-more', group)"
                  >
                    {{ $t('modules.taskManagement.groupLoadMore') }}
                  </el-button>
                  <span class="task-group-more-hint">
                    {{ groupState(group).items.length }} / {{ group.total }}
                  </span>
                </td>
              </tr>
            </template>
          </template>
        </template>

        <template v-else>
          <TaskRow
            v-for="task in rows"
            :key="task.id"
            :task="task"
            :cancelling="cancellingId === task.id"
            :retrying="retryingId === task.id"
            @detail="task => emit('detail', task)"
            @cancel="task => emit('cancel', task)"
            @retry="task => emit('retry', task)"
            @priority="task => emit('priority', task)"
          />
        </template>

        <tr v-if="isEmpty">
          <td colspan="8" class="empty-row">
            {{ loading ? $t('modules.taskManagement.loading')
              : $t('modules.taskManagement.empty') }}
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { CaretBottom, CaretRight, Collection } from '@element-plus/icons-vue'

import TaskRow from '@/features/tasks/components/TaskRow.vue'
import {
  STATUSES, STATUS_TONES, formatDateTime, statusLabel
} from '@/features/tasks/lib/display'

const props = defineProps({
  viewMode: { type: String, default: 'tree' },
  rows: { type: Array, default: () => [] },
  groups: { type: Array, default: () => [] },
  expanded: { type: Object, default: () => ({}) },
  groupTasks: { type: Object, default: () => ({}) },
  loading: { type: Boolean, default: false },
  cancellingId: { type: String, default: '' },
  retryingId: { type: String, default: '' }
})

const emit = defineEmits([
  'toggle-group', 'load-more', 'detail', 'cancel', 'retry', 'priority'
])
const { t } = useI18n()

const isEmpty = computed(() => (
  props.viewMode === 'tree' ? props.groups.length === 0 : props.rows.length === 0
))

function groupKey (group) {
  return group.kbaseId || '__none__'
}

function groupTitle (group) {
  return group.kbaseName || group.kbaseId || t('modules.taskManagement.groupUnassigned')
}

function groupState (group) {
  return props.groupTasks[groupKey(group)] || { items: [], loading: false }
}

const TAG_CLASS = {
  info: '',
  success: 'green',
  warning: 'orange',
  error: 'orange'
}

function groupStatusTags (group) {
  return STATUSES
    .filter(status => Number(group.byStatus?.[status]) > 0)
    .map(status => ({
      status,
      label: statusLabel(status, t),
      count: Number(group.byStatus?.[status]) || 0,
      className: TAG_CLASS[STATUS_TONES[status]] || ''
    }))
}
</script>

<style scoped>
.tasks-table { min-width: 1120px; }
.task-group-row { cursor: pointer; }
.task-group-row td { border-bottom: 1px solid var(--rs-border); }
.task-group-title { display: flex; align-items: center; gap: 10px; }
.task-group-icon { background: var(--rs-primary); color: #fff; }
.task-group-icon svg { color: #fff; stroke: #fff; }
.task-group-toggle { padding: 0; width: 22px; height: 22px; color: var(--rs-primary); }
.task-group-toggle svg { width: 14px; height: 14px; }
.task-group-name { max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-group-status { display: flex; flex-wrap: wrap; gap: 6px; max-width: 280px; }
.task-group-more-hint { margin-left: 10px; color: var(--rs-text-3); font-size: var(--rs-table-secondary-font-size); }
.task-identity { min-width: 0; }
.task-short-id { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; color: var(--rs-text-3); font-size: var(--rs-table-secondary-font-size); }
</style>

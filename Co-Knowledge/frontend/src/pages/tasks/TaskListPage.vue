<template>
  <AppPage class="management-page tasks-page">
    <div class="page-inner">
      <PageHeader
        :title="$t('modules.taskManagement.pageTitle')"
        :subtitle="$t('modules.taskManagement.pageSubtitle')"
        :icon="List"
      />

      <div class="metric-grid">
        <MetricCard
          :label="$t('modules.taskManagement.metricQueueDepth')"
          :value="stats.queueDepth"
          delta="—"
          muted
          :foot="$t('modules.taskManagement.metricQueueDepthFoot')"
          :icon="Clock"
          tone="blue"
        />
        <MetricCard
          :label="$t('modules.taskManagement.metricRunning')"
          :value="stats.running"
          delta="—"
          muted
          :foot="$t('modules.taskManagement.metricRunningFoot')"
          :icon="VideoPlay"
          tone="green"
        />
        <MetricCard
          :label="$t('modules.taskManagement.metricFailed')"
          :value="stats.failed"
          delta="—"
          muted
          :foot="$t('modules.taskManagement.metricFailedFoot')"
          :icon="CircleClose"
          tone="orange"
        />
        <MetricCard
          :label="$t('modules.taskManagement.metricOldestPending')"
          :value="stats.oldestPending"
          delta="—"
          muted
          :foot="$t('modules.taskManagement.metricOldestPendingFoot')"
          :icon="Timer"
          tone="purple"
        />
      </div>

      <section class="tasks-main management-main">
        <div class="toolbar">
          <div class="toolbar-left">
            <el-select
              v-model="filters.type"
              class="task-filter"
              :aria-label="$t('modules.taskManagement.filterType')"
              @change="reloadFirstPage"
            >
              <el-option :label="$t('modules.taskManagement.filterAllTypes')" value="all" />
              <el-option
                v-for="type in TASK_TYPES"
                :key="type"
                :label="$t(`modules.taskManagement.${TYPE_KEYS[type]}`)"
                :value="type"
              />
            </el-select>
            <el-select
              v-model="filters.status"
              class="task-filter"
              :aria-label="$t('modules.taskManagement.filterStatus')"
              @change="reloadFirstPage"
            >
              <el-option :label="$t('modules.taskManagement.filterAllStatuses')" value="all" />
              <el-option
                v-for="status in STATUSES"
                :key="status"
                :label="$t(`modules.taskManagement.${STATUS_KEYS[status]}`)"
                :value="status"
              />
            </el-select>
            <el-input
              v-model.trim="filters.keyword"
              class="search-field task-search"
              maxlength="100"
              clearable
              :placeholder="viewMode === 'tree'
                ? $t('modules.taskManagement.searchPlaceholderGroup')
                : $t('modules.taskManagement.searchPlaceholder')"
              :prefix-icon="Search"
              @input="scheduleSearch"
              @clear="reloadFirstPage"
            />
          </div>
          <div class="toolbar-right">
            <el-radio-group
              v-model="viewMode"
              class="task-view-mode"
              @change="onViewModeChange"
            >
              <el-radio-button value="tree">
                {{ $t('modules.taskManagement.viewTree') }}
              </el-radio-button>
              <el-radio-button value="flat">
                {{ $t('modules.taskManagement.viewFlat') }}
              </el-radio-button>
            </el-radio-group>
            <TableRefreshButton
              :label="$t('modules.taskManagement.refreshList')"
              :refresh="refreshAll"
            />
          </div>
        </div>

        <TaskTable
          :view-mode="viewMode"
          :rows="rows"
          :groups="groups"
          :expanded="expandedGroups"
          :group-tasks="groupTasks"
          :loading="loading"
          :cancelling-id="cancellingId"
          :retrying-id="retryingId"
          @toggle-group="toggleGroup"
          @load-more="loadMoreGroup"
          @detail="openDetail"
          @cancel="cancelRow"
          @retry="retryRow"
          @priority="changePriority"
        />

        <p v-if="viewMode === 'tree'" class="task-group-summary">
          {{ $t('modules.taskManagement.groupTaskSummary', {
            groups: total, tasks: groupsTaskTotal
          }) }}
        </p>
        <TablePagination
          :total="total"
          :page="page"
          :size="size"
          @change="onPaginationChange"
        />
      </section>

      <TaskDetailDrawer
        v-model="detailOpen"
        :task="detailTask"
        :loading="detailLoading"
        :cancelling-id="cancellingId"
        :retrying-id="retryingId"
        @closed="detailTask = null"
        @cancel="cancelRow"
        @retry="retryRow"
        @priority="changePriority"
        @refresh="refreshDetail"
      />
    </div>
  </AppPage>
</template>

<script setup>
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  CircleClose, Clock, List, Search, Timer, VideoPlay
} from '@element-plus/icons-vue'

import AppPage from '@/shared/ui/AppPage.vue'
import PageHeader from '@/shared/ui/reference/PageHeader.vue'
import MetricCard from '@/shared/ui/reference/MetricCard.vue'
import TablePagination from '@/shared/ui/reference/TablePagination.vue'
import TableRefreshButton from '@/shared/ui/TableRefreshButton.vue'
import TaskDetailDrawer from '@/features/tasks/components/TaskDetailDrawer.vue'
import TaskTable from '@/features/tasks/components/TaskTable.vue'
import {
  cancelTask, getTask, getTaskStats, listTaskGroups, listTasks, retryTask,
  updateTaskPriority
} from '@/features/tasks/api/tasks'
import {
  STATUSES, STATUS_KEYS, TASK_TYPES, TYPE_KEYS, formatAge, shortId
} from '@/features/tasks/lib/display'

const { t } = useI18n()

const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(false)
const stats = ref({
  queueDepth: 0, running: 0, failed: 0, oldestPending: '—'
})
const filters = reactive({ type: 'all', status: 'all', keyword: '' })

const VIEW_MODE_KEY = 'tasks-view-mode'
const viewMode = ref(localStorage.getItem(VIEW_MODE_KEY) === 'flat' ? 'flat' : 'tree')
const groups = ref([])
const groupsTaskTotal = ref(0)
const expandedGroups = reactive({})
const groupTasks = reactive({})
const GROUP_TASK_SIZE = 50

function groupKey (group) {
  return group.kbaseId || '__none__'
}

const detailOpen = ref(false)
const detailTask = ref(null)
const detailLoading = ref(false)
const cancellingId = ref('')
const retryingId = ref('')

function updateMetrics (data) {
  const byStatus = data?.byStatus || {}
  stats.value = {
    ...data,
    queueDepth: Number(data?.queueDepth) || 0,
    running: Number(byStatus.RUNNING) || 0,
    failed: Number(byStatus.FAILED) || 0,
    oldestPending: formatAge(
      data?.oldestPendingAgeSeconds,
      t('modules.taskManagement.metricAgeEmpty'))
  }
}

let listSeq = 0
async function loadTasks ({ silent = false } = {}) {
  const seq = ++listSeq
  loading.value = !silent
  try {
    const data = await listTasks({
      task_type: filters.type === 'all' ? '' : filters.type,
      status: filters.status === 'all' ? '' : filters.status,
      keyword: filters.keyword,
      page: page.value,
      size: size.value
    })
    if (seq !== listSeq) {
      return
    }
    rows.value = Array.isArray(data?.items) ? data.items : []
    total.value = Number(data?.total) || 0
  } catch (error) {
    // axios 客户端已弹全局提示；保留上一次成功列表，避免整页闪空。
    if (seq === listSeq && !rows.value.length) {
      total.value = 0
    }
  } finally {
    if (seq === listSeq) {
      loading.value = false
    }
  }
}

let groupsSeq = 0
async function loadGroups ({ silent = false } = {}) {
  const seq = ++groupsSeq
  loading.value = !silent
  try {
    const data = await listTaskGroups({
      task_type: filters.type === 'all' ? '' : filters.type,
      status: filters.status === 'all' ? '' : filters.status,
      keyword: filters.keyword,
      page: page.value,
      size: size.value
    })
    if (seq !== groupsSeq) {
      return
    }
    groups.value = Array.isArray(data?.items) ? data.items : []
    total.value = Number(data?.total) || 0
    groupsTaskTotal.value = Number(data?.taskTotal) || 0
    const visibleKeys = new Set(groups.value.map(groupKey))
    Object.keys(expandedGroups).forEach(key => {
      if (!visibleKeys.has(key)) {
        delete expandedGroups[key]
        delete groupTasks[key]
      }
    })
  } catch (error) {
    if (seq === groupsSeq && !groups.value.length) {
      total.value = 0
      groupsTaskTotal.value = 0
    }
  } finally {
    if (seq === groupsSeq) {
      loading.value = false
    }
  }
}

async function loadGroupTasks (group, pageNo = 1, append = false) {
  const key = groupKey(group)
  const current = groupTasks[key] || { items: [], page: 0, loading: false }
  groupTasks[key] = { ...current, loading: true }
  try {
    const data = await listTasks({
      task_type: filters.type === 'all' ? '' : filters.type,
      status: filters.status === 'all' ? '' : filters.status,
      kbase_id: group.kbaseId || '__none__',
      page: pageNo,
      size: GROUP_TASK_SIZE
    })
    const items = Array.isArray(data?.items) ? data.items : []
    groupTasks[key] = {
      items: append ? [...current.items, ...items] : items,
      total: Number(data?.total) || group.total,
      page: pageNo,
      loading: false
    }
  } catch (error) {
    groupTasks[key] = { ...current, loading: false }
  }
}

function toggleGroup (group) {
  const key = groupKey(group)
  if (expandedGroups[key]) {
    delete expandedGroups[key]
    return
  }
  expandedGroups[key] = true
  if (!groupTasks[key] || !groupTasks[key].page) {
    loadGroupTasks(group, 1)
  }
}

function loadMoreGroup (group) {
  const key = groupKey(group)
  const state = groupTasks[key]
  if (!state || state.loading) {
    return
  }
  loadGroupTasks(group, (state.page || 1) + 1, true)
}

function onViewModeChange () {
  localStorage.setItem(VIEW_MODE_KEY, viewMode.value)
  // 两种模式的搜索语义不同（任务/文件 vs 知识库），切换时清空避免误解。
  filters.keyword = ''
  page.value = 1
  rows.value = []
  groups.value = []
  total.value = 0
  groupsTaskTotal.value = 0
  Object.keys(expandedGroups).forEach(key => {
    delete expandedGroups[key]
  })
  Object.keys(groupTasks).forEach(key => {
    delete groupTasks[key]
  })
  loadAll()
}

let statsSeq = 0
async function loadStats () {
  const seq = ++statsSeq
  try {
    const data = await getTaskStats()
    if (seq === statsSeq) {
      updateMetrics(data)
    }
  } catch (error) {
    // 指标失败不拖垮列表
  }
}

async function loadAll ({ silent = false } = {}) {
  const list = viewMode.value === 'tree'
    ? loadGroups({ silent })
    : loadTasks({ silent })
  await Promise.all([list, loadStats()])
}

function reloadFirstPage () {
  page.value = 1
  loadAll()
}

let searchTimer = null
function scheduleSearch () {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(reloadFirstPage, 300)
}

function onPaginationChange ({ page: nextPage, size: nextSize }) {
  page.value = nextPage
  size.value = nextSize
  if (viewMode.value === 'tree') {
    loadGroups()
  } else {
    loadTasks()
  }
}

async function refreshAll () {
  await loadAll()
  if (viewMode.value === 'tree') {
    await Promise.all(groups.value
      .filter(group => expandedGroups[groupKey(group)])
      .map(group => loadGroupTasks(group, 1)))
  }
  if (detailOpen.value && detailTask.value) {
    await refreshDetail(detailTask.value.id)
  }
  return true
}

async function openDetail (row) {
  detailOpen.value = true
  await refreshDetail(row.id)
}

async function refreshDetail (taskId) {
  if (!taskId) {
    return
  }
  detailLoading.value = true
  try {
    detailTask.value = await getTask(taskId)
  } catch (error) {
    // 全局 toast 已提示
  } finally {
    detailLoading.value = false
  }
}

async function cancelRow (row) {
  try {
    await ElMessageBox.confirm(
      t('modules.taskManagement.cancelConfirmMessage', { id: shortId(row.id) }),
      t('modules.taskManagement.cancelConfirmTitle'),
      {
        type: 'warning',
        confirmButtonText: t('public.confirm'),
        cancelButtonText: t('public.cancel')
      }
    )
  } catch (error) {
    return
  }
  cancellingId.value = row.id
  try {
    const updated = await cancelTask(row.id)
    ElMessage.success(
      updated?.status === 'CANCELLED'
        ? t('modules.taskManagement.cancelDone')
        : t('modules.taskManagement.cancelRequested')
    )
    await loadAll({ silent: true })
    if (detailOpen.value && detailTask.value?.id === row.id) {
      await refreshDetail(row.id)
    }
  } catch (error) {
    // 全局 toast 已提示
  } finally {
    cancellingId.value = ''
  }
}

async function retryRow (row) {
  retryingId.value = row.id
  try {
    await retryTask(row.id)
    ElMessage.success(t('modules.taskManagement.retryDone'))
    await loadAll({ silent: true })
    if (detailOpen.value && detailTask.value?.id === row.id) {
      await refreshDetail(row.id)
    }
  } catch (error) {
    // 全局 toast 已提示
  } finally {
    retryingId.value = ''
  }
}

async function changePriority (row) {
  let result
  try {
    result = await ElMessageBox.prompt(
      t('modules.taskManagement.priorityMessage'),
      t('modules.taskManagement.priorityTitle'),
      {
        inputValue: String(row.priority ?? 0),
        inputPattern: /^-?\d+$/,
        inputErrorMessage: t('modules.taskManagement.priorityInvalid'),
        confirmButtonText: t('public.confirm'),
        cancelButtonText: t('public.cancel')
      }
    )
  } catch (error) {
    return
  }
  const priority = Number(result.value)
  if (!Number.isInteger(priority) || priority < -1000 || priority > 1000) {
    ElMessage.warning(t('modules.taskManagement.priorityInvalid'))
    return
  }
  try {
    await updateTaskPriority(row.id, priority)
    ElMessage.success(t('modules.taskManagement.priorityDone'))
    await loadAll({ silent: true })
    if (detailOpen.value && detailTask.value?.id === row.id) {
      await refreshDetail(row.id)
    }
  } catch (error) {
    // 全局 toast 已提示
  }
}

let pollTimer = null
function stopPolling () {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}
function startPolling () {
  stopPolling()
  pollTimer = window.setInterval(() => {
    if (document.hidden) {
      return
    }
    loadAll({ silent: true })
    if (detailOpen.value && detailTask.value) {
      refreshDetail(detailTask.value.id)
    }
  }, 5000)
}

function onVisibilityChange () {
  if (!document.hidden) {
    loadAll({ silent: true })
  }
}

onMounted(() => {
  loadAll()
  startPolling()
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onBeforeUnmount(() => {
  stopPolling()
  window.clearTimeout(searchTimer)
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<style scoped>
.tasks-main { min-width: 0; }
.task-filter { width: 160px; }
.task-search { width: 240px; }
.task-view-mode { margin-right: 8px; }
.task-view-mode :deep(.el-radio-button__inner) {
  height: var(--el-component-size);
  padding: 0 16px;
  display: inline-flex;
  align-items: center;
  font-size: var(--el-font-size-base);
}
.task-group-summary { margin: 10px 0 0; color: var(--rs-text-3); font-size: var(--rs-table-secondary-font-size); }
</style>

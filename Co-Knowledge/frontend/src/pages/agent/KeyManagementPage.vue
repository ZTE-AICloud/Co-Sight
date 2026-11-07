<template>
  <div class="key-management">
    <el-alert
      v-if="blocked && status && !status.adminEnabled"
      class="key-management__alert"
      type="warning"
      :closable="false"
      show-icon
    >
      {{ $t('modules.remoteAccess.warningAdminDisabled') }}
    </el-alert>
    <el-alert
      v-if="blocked && status && !status.keyStoreAvailable"
      class="key-management__alert"
      type="error"
      :closable="false"
      show-icon
    >
      {{ $t('modules.remoteAccess.warningStoreUnavailable') }}
    </el-alert>
    <el-alert
      v-if="!blocked && status && !status.pepperConfigured"
      class="key-management__alert"
      type="warning"
      :closable="false"
      show-icon
    >
      {{ $t('modules.remoteAccess.warningPepperMissingCreate') }}
    </el-alert>

    <div class="metric-grid">
      <MetricCard
        :label="$t('modules.remoteAccess.metricEnabledKeys')"
        :value="summary.enabled"
        delta="—"
        muted
        :delta-title="$t('modules.remoteAccess.metricEnabledFoot') + ' ' + summary.enabled + ' · ' + $t('modules.kb.metricTrendUnavailable')"
        :foot="$t('modules.kb.metricFoot')"
        :icon="Key"
        tone="blue"
      />
      <MetricCard
        :label="$t('modules.remoteAccess.metricCallTotal')"
        :value="callTotalValue"
        delta="—"
        muted
        :delta-title="callTotalTitle"
        :foot="callTotalFoot"
        :icon="Histogram"
        tone="purple"
      />
      <MetricCard
        :label="$t('modules.remoteAccess.metricAccessibleKbs')"
        :value="summary.allKbs ? $t('modules.remoteAccess.metricAllKbs') : summary.kbCount"
        delta="—"
        muted
        :delta-title="(summary.allKbs ? $t('modules.remoteAccess.metricKbReachAll') : $t('modules.remoteAccess.metricKbReachScoped')) + ' · ' + $t('modules.kb.metricTrendUnavailable')"
        :foot="$t('modules.kb.metricFoot')"
        :icon="Coin"
        tone="green"
      />
      <MetricCard
        :label="$t('modules.remoteAccess.metricRequests7d')"
        :value="requests7dValue"
        delta="—"
        muted
        :delta-title="requests7dTitle"
        :foot="requests7dFoot"
        :icon="TrendCharts"
        tone="orange"
      />
    </div>

    <AppEmpty
      v-if="blocked"
      state="empty"
      :description="$t('modules.remoteAccess.keysBlocked')"
    />

    <template v-else>
      <div class="toolbar">
        <div class="toolbar-left">
          <el-tooltip
            :disabled="createEnabled"
            :content="$t('modules.remoteAccess.createDisabledTip')"
            placement="top"
          >
            <span>
              <el-button type="primary" :disabled="!createEnabled" @click="createHandle">
                <Plus />
                {{ $t('modules.remoteAccess.create') }}
              </el-button>
            </span>
          </el-tooltip>
        </div>
        <div class="toolbar-right">
          <TableRefreshButton :label="$t('modules.remoteAccess.refreshList')" :refresh="refreshList" />
          <el-input
            v-model.trim="searchKey"
            :placeholder="$t('modules.remoteAccess.searchPlaceholder')"
            class="search-field"
            :prefix-icon="Search"
            clearable
            @input="search"
          />
          <el-dropdown trigger="click" @command="setEnabledFilter">
            <el-button>
              <Filter />
              {{ $t('modules.kb.filterStatus') }}
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="all">
                  {{ $t('modules.remoteAccess.allStatus') }}
                </el-dropdown-item>
                <el-dropdown-item command="enabled">
                  {{ $t('modules.remoteAccess.enabled') }}
                </el-dropdown-item>
                <el-dropdown-item command="disabled">
                  {{ $t('modules.remoteAccess.disabled') }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>

      <ListSelectionBar :count="selectedRows.length" @clear="clearSelection">
        <el-button link type="primary" @click="batchKeys('enable')">
          {{ $t('modules.remoteAccess.batchEnable') }}
        </el-button>
        <el-button link @click="batchKeys('disable')">
          {{ $t('modules.remoteAccess.batchDisable') }}
        </el-button>
        <el-button class="danger-action" link type="danger" @click="batchKeys('delete')">
          <Delete />{{ $t('modules.remoteAccess.batchDelete') }}
        </el-button>
      </ListSelectionBar>

      <div v-loading="loading" class="table-card">
        <table class="list-table keys-table">
          <thead>
            <tr>
              <th class="check-cell">
                <input
                  type="checkbox"
                  :aria-label="$t('modules.remoteAccess.selectAllPage')"
                  :checked="allSelected"
                  @change="toggleAll($event.target.checked)"
                >
              </th>
              <th :aria-sort="sortState('name')">
                <button type="button" class="table-sort-button" :aria-label="$t('modules.remoteAccess.sortBy', { field: $t('modules.remoteAccess.columnName') })" @click="sortColumn('name')">
                  {{ $t('modules.remoteAccess.columnName') }}
                  <ArrowUp v-if="sortField === 'name' && sortDirection === 1" />
                  <ArrowDown v-else-if="sortField === 'name'" />
                  <DCaret v-else />
                </button>
              </th>
              <th :aria-sort="sortState('keyPrefix')">
                <button type="button" class="table-sort-button" :aria-label="$t('modules.remoteAccess.sortBy', { field: $t('modules.remoteAccess.columnPrefix') })" @click="sortColumn('keyPrefix')">
                  {{ $t('modules.remoteAccess.columnPrefix') }}
                  <ArrowUp v-if="sortField === 'keyPrefix' && sortDirection === 1" />
                  <ArrowDown v-else-if="sortField === 'keyPrefix'" />
                  <DCaret v-else />
                </button>
              </th>
              <th>{{ $t('modules.remoteAccess.columnScopes') }}</th>
              <th>{{ $t('modules.remoteAccess.columnKbIds') }}</th>
              <th>{{ $t('modules.remoteAccess.columnRateLimit') }}</th>
              <th>{{ $t('modules.remoteAccess.columnEnabled') }}</th>
              <th :aria-sort="sortState('expiresAt')">
                <button type="button" class="table-sort-button" :aria-label="$t('modules.remoteAccess.sortBy', { field: $t('modules.remoteAccess.columnExpiresAt') })" @click="sortColumn('expiresAt')">
                  {{ $t('modules.remoteAccess.columnExpiresAt') }}
                  <ArrowUp v-if="sortField === 'expiresAt' && sortDirection === 1" />
                  <ArrowDown v-else-if="sortField === 'expiresAt'" />
                  <DCaret v-else />
                </button>
              </th>
              <th :aria-sort="sortState('lastUsedAt')">
                <button type="button" class="table-sort-button" :aria-label="$t('modules.remoteAccess.sortBy', { field: $t('modules.remoteAccess.columnLastUsedAt') })" @click="sortColumn('lastUsedAt')">
                  {{ $t('modules.remoteAccess.columnLastUsedAt') }}
                  <ArrowUp v-if="sortField === 'lastUsedAt' && sortDirection === 1" />
                  <ArrowDown v-else-if="sortField === 'lastUsedAt'" />
                  <DCaret v-else />
                </button>
              </th>
              <th>{{ $t('public.creator') }}</th>
              <th>{{ $t('public.operate') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in rows" :key="row.keyPrefix">
              <td class="check-cell">
                <input
                  type="checkbox"
                  :checked="isSelected(row)"
                  :aria-label="$t('modules.remoteAccess.selectKey', { name: row.name })"
                  @change="toggleRow(row, $event.target.checked)"
                >
              </td>
              <td>
                <div class="entity">
                  <div :class="['avatar-square', avatarTone(index)]">
                    {{ initialOf(row.name) }}
                  </div>
                  <div>
                    <div class="entity-title">
                      {{ row.name }}
                    </div>
                    <div class="entity-sub">
                      {{ row.createdBy || '--' }} · {{ formatDateTime(row.createdAt) || '--' }}
                    </div>
                    <div v-if="row.description" class="entity-sub">
                      {{ row.description }}
                    </div>
                  </div>
                </div>
              </td>
              <td class="nowrap">
                {{ row.keyPrefix }}
                <button
                  class="icon-button copy"
                  :aria-label="$t('modules.remoteAccess.copy')"
                  :title="$t('modules.remoteAccess.copy')"
                  @click="copyPrefix(row)"
                >
                  <CopyDocument />
                </button>
              </td>
              <td class="permission-cell">
                <span
                  v-for="scope in row.scopes"
                  :key="scope"
                  class="tag-soft"
                >{{ $t(scopeLabelKey(scope)) }}</span>
              </td>
              <td :title="kbTooltip(row)">
                {{ row.kbIds && row.kbIds.length
                  ? $t('modules.remoteAccess.kbCount', { count: row.kbIds.length })
                  : $t('modules.remoteAccess.allKbs') }}
              </td>
              <td class="nowrap">
                {{ row.rateLimitPerMin === 0
                  ? $t('modules.remoteAccess.unlimited')
                  : $t('modules.remoteAccess.ratePerMin', { count: row.rateLimitPerMin }) }}
              </td>
              <td class="nowrap">
                <div class="table-status">
                  <el-switch
                    :model-value="row.enabled"
                    :loading="Boolean(toggling[row.keyPrefix])"
                    :aria-label="$t('modules.remoteAccess.toggleKey', { name: row.name })"
                    @change="value => toggleEnabled(row, value)"
                  />
                  <span>{{ row.enabled ? $t('modules.remoteAccess.enabled') : $t('modules.remoteAccess.disabled') }}</span>
                </div>
              </td>
              <td class="nowrap">
                {{ formatDateUTC(row.expiresAt) || $t('modules.remoteAccess.neverExpires') }}
                <div v-if="row.expiresAt" class="entity-sub">
                  {{ $t('modules.remoteAccess.expiryUtc') }}
                </div>
                <span v-if="row.expired || isExpired(row.expiresAt)" class="tag-soft orange">
                  {{ $t('modules.remoteAccess.expired') }}
                </span>
              </td>
              <td class="table-time">
                <template v-if="usedDate(row)">
                  <span>{{ usedDate(row) }}</span><br>
                  {{ usedTime(row) }}
                </template>
                <template v-else>
                  {{ $t('modules.remoteAccess.neverUsed') }}
                </template>
              </td>
              <td>{{ row.createdBy || '--' }}</td>
              <td>
                <div class="row-actions">
                  <el-button link type="primary" @click="editClickHandle(row)">
                    {{ $t('public.edit') }}
                  </el-button>
                  <el-button class="danger-action" link type="danger" @click="deleteClickHandle(row)">
                    <Delete />{{ $t('public.delete') }}
                  </el-button>
                  <el-dropdown
                    trigger="click"
                    @command="toggleEnabled(row, !row.enabled)"
                  >
                    <button class="icon-button" :aria-label="row.name + ' ' + $t('public.operate')">
                      <MoreFilled class="more-icon" />
                    </button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="toggle">
                          {{ row.enabled ? $t('modules.remoteAccess.disabled') : $t('modules.remoteAccess.enabled') }}
                        </el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </div>
              </td>
            </tr>
            <tr v-if="!rows.length">
              <td colspan="11" class="empty-row">
                {{ $t('modules.remoteAccess.keysEmpty') }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <TablePagination
        :total="total"
        :page="currentPage"
        :size="pageSize"
        @change="onPaginationChange"
      />
    </template>

    <KeyEditorDialog
      v-model="editorOpen"
      :editing="editingRow"
      :existing="rows"
      :knowledge-options="kbOptions"
      :scope-options="scopeOptions"
      :submit-handler="saveKey"
    />

    <KeyRevealDialog ref="revealDialogRef" />

  </div>
</template>

<script setup>
import { computed, getCurrentInstance, onMounted, reactive, ref } from 'vue'
import { debounce } from 'lodash'
import { Search, Filter, Key, Histogram, Coin, TrendCharts, CopyDocument, DCaret, MoreFilled, Plus, ArrowUp, ArrowDown, Delete } from '@/shared/lib/icons'
import MetricCard from '@/shared/ui/reference/MetricCard.vue'
import TablePagination from '@/shared/ui/reference/TablePagination.vue'
import TableRefreshButton from '@/shared/ui/TableRefreshButton.vue'
import ListSelectionBar from '@/shared/ui/ListSelectionBar.vue'
import message from '@/shared/lib/message'
import { requestDeletion } from '@/shared/composables/deletion'
import AppEmpty from '@/shared/ui/AppEmpty.vue'
import { DEBOUNCETIME } from '@/shared/constants/index.js'
import { copyText } from '@/shared/lib/clipboard'
import {
  createAgentKeyApi,
  deleteAgentKeyApi,
  getAgentKeyStatsApi,
  queryAgentKeysApi,
  searchDocumentKbasesApi,
  updateAgentKeyApi
} from '@/features/agent/api/remoteAccess'

import KeyEditorDialog from '@/features/agent/components/KeyEditorDialog.vue'
import KeyRevealDialog from '@/features/agent/components/KeyRevealDialog.vue'
import { buildPatchPayload, formatCount, formatDateUTC, formatDateTime, isExpired, scopeLabelKey } from '@/features/agent/lib/helpers'

const props = defineProps({
  status: {
    type: Object,
    default: null
  }
})

const { proxy } = getCurrentInstance()
const editorOpen = ref(false)
const editingRow = ref(null)
const scopeOptions = computed(() => (
  props.status?.scopes?.length ? props.status.scopes : ['kb:list', 'kb:search', 'kb:answer', 'workflow:read', 'workflow:run']
))
const revealDialogRef = ref(null)
const searchKey = ref('')
const toggling = ref({})
const kbNameMap = ref({})
const kbOptions = ref([])

/* ── 概览指标（真实 Key 列表） ───────────────────────────────────── */
const summary = reactive({
  total: 0,
  enabled: 0,
  rateLimited: 0,
  kbScoped: 0,
  kbCount: 0,
  allKbs: false
})

/**
 * 调用量指标（后端 `/agent-keys/stats`）：null = 还没取到 / 接口不可用，
 * 卡片显示「—」；取到后显示千分位数字。刷新失败保留上次值。
 */
const usage = reactive({
  totalCalls: null,
  requests7d: null
})

function usageValue (value) {
  return value === null ? '—' : formatCount(value)
}

function usageTitle (labelKey, hintKey, value) {
  const hint = value === null
    ? proxy.$t('modules.remoteAccess.metricUnavailable')
    : proxy.$t(`modules.remoteAccess.${hintKey}`)
  return `${proxy.$t(`modules.remoteAccess.${labelKey}`)} · ${hint}`
}

function usageFoot (footKey, value) {
  return value === null
    ? proxy.$t('modules.kb.metricFoot')
    : proxy.$t(`modules.remoteAccess.${footKey}`)
}

const callTotalValue = computed(() => usageValue(usage.totalCalls))
const callTotalTitle = computed(() => usageTitle('metricCallTotal', 'metricCallHint', usage.totalCalls))
const callTotalFoot = computed(() => usageFoot('metricCallFoot', usage.totalCalls))
const requests7dValue = computed(() => usageValue(usage.requests7d))
const requests7dTitle = computed(() => usageTitle('metricRequests7d', 'metricRequests7dHint', usage.requests7d))
const requests7dFoot = computed(() => usageFoot('metricRequests7dFoot', usage.requests7d))

const enabledFilter = ref('all')

/* ── 表格状态 ───────────────────────────────────────────────────── */
const rows = ref([])
const currentPage = ref(1)
const pageSize = ref(10)
const total = ref(0)
const loading = ref(false)
const selectedMap = reactive(new Map())
const selectedRows = computed(() => Array.from(selectedMap.values()))
const allSelected = computed(() => rows.value.length > 0 && rows.value.every(row => selectedMap.has(row.keyPrefix)))
const sortField = ref('')
const sortDirection = ref(1)

function isSelected (row) {
  return Boolean(row?.keyPrefix) && selectedMap.has(row.keyPrefix)
}

function toggleRow (row, checked) {
  if (!row?.keyPrefix) {
    return
  }
  if (checked) {
    selectedMap.set(row.keyPrefix, { ...row })
  } else {
    selectedMap.delete(row.keyPrefix)
  }
}

function toggleAll (checked) {
  rows.value.forEach(row => {
    if (checked) {
      selectedMap.set(row.keyPrefix, { ...row })
    } else {
      selectedMap.delete(row.keyPrefix)
    }
  })
}

function clearSelection () {
  selectedMap.clear()
}

function syncSelectedRows (data) {
  data.forEach(row => {
    if (row?.keyPrefix && selectedMap.has(row.keyPrefix)) {
      selectedMap.set(row.keyPrefix, { ...row })
    }
  })
}

function sortColumn (field) {
  if (sortField.value === field) {
    sortDirection.value *= -1
  } else {
    sortField.value = field
    sortDirection.value = 1
  }
  currentPage.value = 1
  clearSelection()
  loadRows()
}

function sortState (field) {
  if (sortField.value !== field) {
    return 'none'
  }
  return sortDirection.value === 1 ? 'ascending' : 'descending'
}

function setEnabledFilter (value) {
  enabledFilter.value = value
  clearSelection()
  refreshTableData('initPage')
}

/**
 * 概览指标：Key 计数与调用量都来自 `GET /agent-keys/stats`。
 *
 * 以前四张卡靠一次 `pageSize=500` 的列表全量在本地数 —— 后端列表页大小上限是 100，
 * 超过 100 把 Key 时会静默少算；聚合放到后端后不再受分页上限影响，也少一条大请求。
 * 失败时保留上次值（调用量首次仍显示「—」）。
 */
async function loadSummary () {
  try {
    const result = await getAgentKeyStatsApi({ skipErrorHandler: true })
    const total = Number(result?.totalCalls)
    usage.totalCalls = Number.isFinite(total) ? total : null
    const recent = Number(result?.requests7d)
    usage.requests7d = Number.isFinite(recent) ? recent : null
    const keys = result?.keySummary
    if (keys) {
      summary.total = Number(keys.total) || 0
      summary.enabled = Number(keys.enabled) || 0
      summary.rateLimited = Number(keys.rateLimited) || 0
      summary.kbScoped = Number(keys.kbScoped) || 0
      summary.kbCount = Number(keys.kbCount) || 0
      summary.allKbs = Boolean(keys.allKbs)
    }
  } catch {
    // 统计只是辅助信息；不弹错误提示
  }
}

const AVATAR_TONES = ['av-blue', 'av-purple', 'av-green', 'av-orange']

function initialOf (name) {
  return String(name || '?').charAt(0)
    .toUpperCase()
}

/** 按行序轮换头像色（蓝/紫/绿/橙）。 */
function avatarTone (index) {
  return AVATAR_TONES[index % AVATAR_TONES.length]
}

const blocked = computed(() => Boolean(
  props.status && (!props.status.adminEnabled || !props.status.keyStoreAvailable)
))
const createEnabled = computed(() => Boolean(
  !props.status || (props.status.adminEnabled && props.status.pepperConfigured)
))

function getTableDataApi (params, config) {
  const query = {
    ...params,
    keyword: searchKey.value || ''
  }
  // 启用/停用筛选与排序都下推服务端，分页总数与顺序才是全量口径。
  if (enabledFilter.value !== 'all') {
    query.enabled = enabledFilter.value === 'enabled'
  }
  if (sortField.value) {
    query.sortBy = sortField.value
    query.sortOrder = sortDirection.value === 1 ? 'asc' : 'desc'
  }
  return queryAgentKeysApi(query, config)
}

async function loadRows () {
  loading.value = true
  try {
    const result = await getTableDataApi(
      { currentPage: currentPage.value, pageSize: pageSize.value },
      {}
    )
    const data = result?.items ?? (Array.isArray(result) ? result : [])
    syncSelectedRows(data)
    rows.value = data
    total.value = Number(result?.total ?? data.length) || data.length
    // 只有列表里真的出现「限定知识库」的 Key 时才需要 id→名称映射
    if (data.some(row => Array.isArray(row.kbIds) && row.kbIds.length)) {
      loadKbNames()
    }
    return true
  } catch {
    // 错误提示由拦截器统一弹；表格保持上一屏数据
    return false
  } finally {
    loading.value = false
  }
}

/** 刷新：保留搜索 / 筛选 / 排序 / 页码 / 勾选；失败保留原列表。 */
async function refreshList () {
  let ok = await loadRows()
  const maxPage = Math.max(1, Math.ceil(total.value / pageSize.value))
  if (ok && currentPage.value > maxPage) {
    currentPage.value = maxPage
    ok = await loadRows()
  }
  if (!ok) {
    throw new Error('refresh failed')
  }
}

function refreshTableData (initPage = '') {
  if (initPage) {
    currentPage.value = 1
  }
  return loadRows()
}

function onPaginationChange ({ page, size }) {
  currentPage.value = page
  pageSize.value = size
  loadRows()
}

const search = debounce(() => {
  clearSelection()
  refreshTableData('initPage')
}, DEBOUNCETIME)

function createHandle () {
  editingRow.value = null
  editorOpen.value = true
  // 弹窗的「可访问知识库」选项：第一次打开时才拉
  loadKbNames()
}

function editClickHandle (row) {
  editingRow.value = row
  editorOpen.value = true
  loadKbNames()
}

/**
 * 弹窗提交：新建走 POST，编辑走 PATCH 的**差量**载荷
 * （只发真正变化的字段，理由见 helpers.buildPatchPayload）。
 */
async function saveKey (values) {
  const dateOnly = values.expiresAt ? String(values.expiresAt).slice(0, 10) : ''
  try {
    if (editingRow.value) {
      const payload = buildPatchPayload(editingRow.value, {
        name: values.name,
        description: values.desc,
        scopes: values.scopes,
        kbIds: values.kbIds,
        rateLimitPerMin: values.rateLimitPerMin,
        expiresAt: dateOnly
      })
      if (!Object.keys(payload).length) {
        message.info(proxy.$t('modules.remoteAccess.noChanges'))
        return
      }
      await updateAgentKeyApi(editingRow.value.keyPrefix, payload)
      message.success(proxy.$t('modules.remoteAccess.updateSuccess'))
      refreshTableData()
      loadSummary()
      return
    }
    const created = await createAgentKeyApi({
      name: values.name,
      description: values.desc,
      scopes: values.scopes,
      kbIds: values.kbIds,
      rateLimitPerMin: values.rateLimitPerMin,
      expiresAt: dateOnly || null
    })
    message.success(proxy.$t('modules.remoteAccess.createSuccess'))
    createdHandle(created)
  } catch {
    // 错误提示由拦截器统一弹；弹窗保持打开
    throw new Error('save failed')
  }
}

function createdHandle (result) {
  refreshTableData('initPage')
  loadSummary()
  revealDialogRef.value?.open(result)
}

async function copyPrefix (row) {
  const ok = await copyText(row.keyPrefix)
  if (ok) {
    message.success(proxy.$t('modules.remoteAccess.copied'))
  } else {
    message.error(proxy.$t('modules.remoteAccess.copyFailed'))
  }
}

function toggleEnabled (row, value) {
  if (toggling.value[row.keyPrefix]) {
    return
  }
  toggling.value = { ...toggling.value, [row.keyPrefix]: true }
  updateAgentKeyApi(row.keyPrefix, { enabled: value })
    .then(() => {
      message.success(value
        ? proxy.$t('modules.remoteAccess.toggleOnSuccess')
        : proxy.$t('modules.remoteAccess.toggleOffSuccess'))
      refreshTableData()
      loadSummary()
    })
    .catch(() => {
      // 开关用的是 `:model-value`，没有本地乐观写入，失败时自然停留在原状态。
    })
    .finally(() => {
      const next = { ...toggling.value }
      delete next[row.keyPrefix]
      toggling.value = next
    })
}

function deleteItem (row) {
  return {
    id: row.keyPrefix,
    name: row.name,
    meta: row.keyPrefix,
    letter: initialOf(row.name),
    av: avatarTone(Math.max(0, rows.value.indexOf(row))),
    tag: proxy.$t('modules.remoteAccess.columnPrefix')
  }
}

async function deleteClickHandle (row) {
  const confirmed = await requestDeletion({
    resourceType: proxy.$t('public.deleteConfirm.resourceKey'),
    warning: proxy.$t('modules.remoteAccess.deleteWarning'),
    description: proxy.$t('modules.remoteAccess.deleteDescription'),
    items: [deleteItem(row)],
    detail: proxy.$t('modules.remoteAccess.deleteDetail'),
    hint: proxy.$t('modules.remoteAccess.deleteHint')
  })
  if (!confirmed) {
    return
  }
  try {
    await deleteAgentKeyApi(row.keyPrefix)
    selectedMap.delete(row.keyPrefix)
    message.success(proxy.$t('modules.remoteAccess.deleteSuccess'))
    await refreshAfterDelete(1)
    loadSummary()
  } catch {
    // 拦截器已提示
  }
}

async function refreshAfterDelete (deletedCount) {
  const remaining = Math.max(0, total.value - deletedCount)
  const maxPage = Math.max(1, Math.ceil(remaining / pageSize.value))
  if (currentPage.value > maxPage) {
    currentPage.value = maxPage
  }
  await loadRows()
}

async function batchKeys (command) {
  const targets = [...selectedRows.value]
  if (!targets.length) {
    return
  }
  if (command === 'delete') {
    const confirmed = await requestDeletion({
      resourceType: proxy.$t('public.deleteConfirm.resourceKey'),
      title: proxy.$t('modules.remoteAccess.batchDeleteTitle'),
      warning: proxy.$t('modules.remoteAccess.deleteWarning'),
      description: proxy.$t('modules.remoteAccess.deleteDescription'),
      items: targets.map(deleteItem),
      detail: proxy.$t('modules.remoteAccess.batchDeleteDetail', { count: targets.length }),
      hint: proxy.$t('modules.remoteAccess.deleteHint')
    })
    if (!confirmed) {
      return
    }
    const results = await Promise.allSettled(targets.map(row => deleteAgentKeyApi(row.keyPrefix)))
    const success = results.filter(result => result.status === 'fulfilled').length
    const failed = targets.length - success
    results.forEach((result, index) => {
      if (result.status === 'fulfilled') {
        selectedMap.delete(targets[index].keyPrefix)
      }
    })
    if (success) {
      message.success(proxy.$t('modules.remoteAccess.batchUpdated', { count: success }))
    }
    if (failed) {
      message.error(proxy.$t('modules.remoteAccess.batchPartial', { success, failed }))
    }
    await refreshAfterDelete(success)
    loadSummary()
    return
  }
  const enabled = command === 'enable'
  const results = await Promise.allSettled(targets.map(row => updateAgentKeyApi(row.keyPrefix, { enabled })))
  const success = results.filter(result => result.status === 'fulfilled').length
  const failed = targets.length - success
  clearSelection()
  if (success) {
    message.success(proxy.$t('modules.remoteAccess.batchUpdated', { count: success }))
  }
  if (failed) {
    message.error(proxy.$t('modules.remoteAccess.batchPartial', { success, failed }))
  }
  await loadRows()
  loadSummary()
}

function kbTooltip (row) {
  if (!row.kbIds || !row.kbIds.length) {
    return proxy.$t('modules.remoteAccess.allKbsTip')
  }
  return row.kbIds.map(id => kbNameMap.value[id] || id).join('\n')
}

/** 「最近使用」拆成日期 + 时间两行。 */
function usedParts (row) {
  const text = formatDateTime(row.lastUsedAt)
  if (!text) {
    return null
  }
  const index = text.indexOf(' ')
  return index === -1
    ? [text, '']
    : [text.slice(0, index), text.slice(index + 1)]
}

function usedDate (row) {
  const parts = usedParts(row)
  return parts ? parts[0] : ''
}

function usedTime (row) {
  const parts = usedParts(row)
  return parts ? parts[1] : ''
}

/**
 * 知识库名称映射 / 弹窗选项：进页面不拉，等真正用到再取 ——
 * 列表里出现限定白名单的 Key（tooltip 要显示库名）或打开新建/编辑弹窗时。
 */
let kbNamesLoading = false
let kbNamesLoaded = false

async function loadKbNames () {
  if (kbNamesLoading || kbNamesLoaded) {
    return
  }
  kbNamesLoading = true
  try {
    const result = await searchDocumentKbasesApi(
      { pageSize: 200 },
      { skipErrorHandler: true }
    )
    const rows = result?.items ?? (Array.isArray(result) ? result : [])
    const map = {}
    for (const row of rows || []) {
      if (row && row.id) {
        map[row.id] = row.name || row.id
      }
    }
    kbNameMap.value = map
    kbOptions.value = (rows || [])
      .filter(row => row && row.id)
      .map(row => ({ id: row.id, name: row.name || row.id }))
    kbNamesLoaded = true
  } catch {
    // 名称映射只是锦上添花；失败时表格回落显示原始 id（下次用到再重试）。
  } finally {
    kbNamesLoading = false
  }
}

onMounted(() => {
  loadSummary()
  refreshTableData('initPage')
})

</script>

<style scoped>
.keys-table { min-width: 1320px; table-layout: auto; }
.keys-table .entity-title { white-space: nowrap; }
.keys-table .entity-sub { max-width: 200px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.keys-table th:nth-child(2) { width: 20%; }
.keys-table .permission-cell { white-space: nowrap; }

.key-management__alert { margin-bottom: 16px; }
</style>

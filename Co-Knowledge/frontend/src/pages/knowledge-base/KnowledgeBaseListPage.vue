<template>
  <AppPage class="management-page knowledge-page">
    <div class="page-inner">
      <PageHeader
        :title="$t('modules.kb.kb')"
        :subtitle="$t('modules.kb.pageSubtitle')"
        :icon="Document"
      />

      <div class="metric-grid">
        <MetricCard
          :label="$t('modules.kb.metricKbTotal')"
          :value="overview.kbTotal"
          delta="—"
          muted
          :delta-title="$t('modules.kb.metricReadyCount', { count: overview.ready }) + ' · ' + $t('modules.kb.metricTrendUnavailable')"
          :foot="$t('modules.kb.metricFoot')"
          :icon="Document"
          tone="blue"
        />
        <MetricCard
          :label="$t('modules.kb.metricDocTotal')"
          :value="overview.docTotal"
          delta="—"
          muted
          :delta-title="$t('modules.kb.metricAvgDocs', { count: overview.avgDocs }) + ' · ' + $t('modules.kb.metricTrendUnavailable')"
          :foot="$t('modules.kb.metricFoot')"
          :icon="Document"
          tone="green"
        />
        <MetricCard
          :label="$t('modules.kb.metricGraphTotal')"
          :value="overview.graphTotal"
          delta="—"
          muted
          :delta-title="$t('modules.kb.metricGraphReady', { count: overview.graphReady }) + ' · ' + $t('modules.kb.metricTrendUnavailable')"
          :foot="$t('modules.kb.metricFoot')"
          :icon="Share"
          tone="purple"
        />
        <MetricCard
          :label="$t('modules.kb.metricHealth')"
          :value="readyPercent"
          delta="—"
          muted
          :delta-title="$t('modules.kb.metricReadyRatio', { ready: overview.ready, total: overview.kbTotal }) + ' · ' + $t('modules.kb.metricTrendUnavailable')"
          :foot="$t('modules.kb.metricFoot')"
          :icon="ActivityIcon"
          tone="orange"
        />
      </div>

      <section class="knowledge-main management-main">
        <div class="toolbar">
          <div class="toolbar-left">
            <el-button type="primary" @click="addKbaseHandle">
              <Plus />
              {{ $t('modules.kb.createDockb') }}
            </el-button>
            <el-button :disabled="!canImport" @click="openImport()">
              <Upload />
              {{ $t('public.import') }}
            </el-button>
            <el-dropdown
              trigger="click"
              @command="createFromTemplate"
            >
              <el-button>
                <Collection />
                {{ $t('modules.kb.templateButton') }}
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="document">
                    {{ $t('modules.kb.templateDocument') }}
                  </el-dropdown-item>
                  <el-dropdown-item command="graph">
                    {{ $t('modules.kb.templateGraph') }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-dropdown
              trigger="click"
              @command="openPanel"
            >
              <el-button
                class="knowledge-more"
                :title="$t('app.more')"
                :aria-label="$t('modules.kb.moreActions')"
              >
                <MoreFilled />
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="pipeline">
                    {{ $t('modules.kb.pipelineMenu') }}
                  </el-dropdown-item>
                  <el-dropdown-item command="monitor">
                    {{ $t('modules.kb.monitorMenu') }}
                  </el-dropdown-item>
                  <el-dropdown-item command="docs" divided>
                    {{ $t('modules.kb.viewDocs') }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
          <div class="toolbar-right">
            <TableRefreshButton :key="'knowledge'" :label="$t('modules.kb.refreshList')" :refresh="refreshList" />
            <el-input
              v-model.trim="searchKey"
              class="search-field"
              maxlength="200"
              :placeholder="$t('modules.kb.searchKbaseName')"
              :prefix-icon="Search"
              clearable
              @input="handleSearchInput"
              @change="handleSearchInput"
              @clear="handleSearchInput"
            />
            <el-dropdown
              trigger="click"
              @command="setStatusFilter"
            >
              <el-button :class="{ 'filter-active': statusFilter !== ALL_STATUS_FILTER }">
                <Filter />
                {{ $t('modules.kb.filterStatus') }}
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="all">
                    {{ $t('modules.kb.filterAllStatus') }}
                  </el-dropdown-item>
                  <!-- 选项由状态目录生成：与状态列同一份文案，不再各写各的 -->
                  <el-dropdown-item
                    v-for="option in statusOptions"
                    :key="option.value"
                    :command="option.value"
                  >
                    {{ $t(option.labelKey) }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>

        <KnowledgeImportDialog
          v-model="importOpen"
          :entries="importEntries"
          :initial-id="importTarget"
          :submit-handler="submitImport"
        />
        <ListSelectionBar :count="selectedRows.length" @clear="clearSelection">
          <el-button class="danger-action" link type="danger" @click="removeSelectedKbs">
            <Delete />{{ $t('modules.kb.batchDelete') }}
          </el-button>
        </ListSelectionBar>

        <div class="table-card">
          <table class="list-table knowledge-table">
            <thead>
              <tr>
                <th class="check-cell">
                  <input
                    type="checkbox"
                    :aria-label="$t('modules.kb.selectAllPage')"
                    :checked="allSelected"
                    @change="toggleAll($event.target.checked)"
                  >
                </th>
                <th>{{ $t('modules.kb.kbInfoColumn') }}</th>
                <th>{{ $t('modules.kb.typeColumn') }}</th>
                <th>{{ $t('modules.kb.fileCount') }}</th>
                <th>{{ $t('modules.kb.status') }}</th>
                <th>{{ $t('modules.kb.updateTimeColumn') }}</th>
                <th>{{ $t('public.creator') }}</th>
                <th>{{ $t('public.operate') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in rows" :key="row.id || row.name">
                <td class="check-cell">
                  <input
                    type="checkbox"
                    :checked="isSelected(row)"
                    :aria-label="$t('modules.kb.selectKb', { name: row.name || '' })"
                    @change="toggleRow(row, $event.target.checked)"
                  >
                </td>
                <td>
                  <div class="entity">
                    <div :class="['avatar-square', row.__avatarTone || avatarTone(index)]">
                      {{ initialOf(row.name) }}
                    </div>
                    <div>
                      <a
                        :key="`${row.id}-${row.name}`"
                        class="entity-title entity-link"
                        @click="detailHandle(row)"
                      >{{ row.name || '--' }}</a>
                      <div class="entity-sub entity-desc" :title="row.description || ''">
                        {{ row.description || '--' }}
                      </div>
                      <div class="table-tags">
                        <span v-if="row.embeddingModel" class="tag-soft">{{ row.embeddingModel }}</span>
                        <span class="tag-soft" :title="$t('modules.kb.tagUncategorized')">{{ $t('modules.kb.tagUncategorized') }}</span>
                      </div>
                    </div>
                  </div>
                </td>
                <td>
                  <span class="tag-soft blue">
                    <Document />
                    {{ $t('modules.kb.tagDocument') }}
                  </span>
                </td>
                <td class="nowrap">
                  <b>{{ docCountLabel(row.currentFileCount || 0) }}</b>
                  <div class="entity-sub" :title="$t('modules.kb.sizeUnavailable')">
                    —
                  </div>
                </td>
                <td class="nowrap">
                  <span :class="['status-dot', statusMeta(row).tone]" />
                  <b>{{ statusMeta(row).text }}</b>
                  <div class="entity-sub status-sub" :title="row.failReason || ''">
                    {{ statusSub(row) }}
                  </div>
                </td>
                <td class="nowrap" :title="row.updatedDate ? '' : $t('modules.kb.dateCreatedFallback')">
                  {{ formatDateShort(row.updatedDate || row.createdDate) }}
                  <div class="entity-sub">
                    {{ relativeTime(row.updatedDate || row.createdDate) }}
                  </div>
                </td>
                <td>{{ creatorOf(row) }}</td>
                <td>
                  <el-dropdown trigger="click">
                    <button
                      class="icon-button"
                      :aria-label="(row.name || '') + ' ' + $t('public.operate')"
                    >
                      <MoreFilled class="more-icon" />
                    </button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <!-- 列表行直接进「分块 / 文档管理」两个视图 -->
                        <el-dropdown-item @click="openDetail(row)">
                          <Document />
                          {{ $t('modules.studioDialogs.knowledgeDetail.viewChunks') }}
                        </el-dropdown-item>
                        <el-dropdown-item @click="openDocuments(row)">
                          <FolderOpened />
                          {{ $t('modules.studioDialogs.knowledgeDetail.documents') }}
                        </el-dropdown-item>
                        <el-dropdown-item
                          :disabled="isRowLocked(row) || !isDocKbModifyEnabled(toNum(row.status))"
                          @click="moreHandleCommand('modifyKbase', row)"
                        >
                          <Edit />
                          {{ $t('public.rename') }}
                        </el-dropdown-item>
                        <el-dropdown-item
                          :disabled="isRowLocked(row)"
                          @click="openDocuments(row, true)"
                        >
                          <Upload />
                          {{ $t('modules.kb.importHintTitle') }}
                        </el-dropdown-item>
                        <el-dropdown-item
                          divided
                          class="danger-menu-item"
                          :disabled="isRowLocked(row)"
                          @click="moreHandleCommand('deleteKbase', row)"
                        >
                          <Delete />
                          {{ $t('public.delete') }}
                        </el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </td>
              </tr>
              <tr v-if="!rows.length">
                <td colspan="8" class="empty-row">
                  <template v-if="listState === 'loading'">
                    {{ $t('public.loading') }}
                  </template>
                  <template v-else-if="listState === 'error'">
                    <span>{{ $t('public.loadFailedTip') }}</span>
                    <el-button link type="primary" @click="refreshTableData()">
                      {{ $t('public.retry') }}
                    </el-button>
                  </template>
                  <template v-else>
                    {{ $t('public.noData') }}
                  </template>
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
      </section>

      <!-- 处理流程 / 检索监控从工具条「更多」打开抽屉，不常驻右栏。 -->
      <el-drawer v-model="panelOpen" size="min(440px, 100vw)" append-to-body destroy-on-close>
        <template #header>
          <h2 class="panel-title text-section-title">
            {{ panel === 'pipeline' ? $t('modules.kb.pipelineTitle') : $t('modules.kb.monitorTitle') }}
          </h2>
        </template>
        <template v-if="panel === 'pipeline'">
          <p class="panel-description text-secondary">
            {{ $t('modules.kb.pipelineDrawerDesc') }}
          </p>
          <ol class="pipeline-steps">
            <li v-for="step in pipelineSteps" :key="step.name" class="pipeline-step">
              <span :class="['pipeline-icon', step.tone]">
                <component :is="step.icon" />
              </span>
              <div>
                <h3 class="text-body text-label">
                  {{ step.name }}
                </h3>
                <p class="text-secondary">
                  {{ step.desc }}
                </p>
              </div>
            </li>
          </ol>
          <RouterLink to="/access" class="panel-link text-secondary" @click="panelOpen = false">
            {{ $t('modules.kb.pipelineLearnMore') }}<ArrowRight />
          </RouterLink>
        </template>
        <template v-else>
          <div class="monitor-heading">
            <p class="panel-description text-secondary">
              {{ $t('modules.kb.monitorDrawerDesc') }}
            </p>
            <el-select
              v-model="monitorPeriod"
              :aria-label="$t('modules.kb.monitorRange')"
              style="width: 112px"
            >
              <el-option :label="$t('modules.kb.monitor7Days')" value="7" />
              <el-option :label="$t('modules.kb.monitor30Days')" value="30" />
            </el-select>
          </div>
          <dl class="monitor-list">
            <div v-for="metric in monitoring" :key="metric.name" class="monitor-item">
              <dt class="text-secondary">
                <span :class="['pipeline-icon', metric.tone]">
                  <component :is="metric.icon" />
                </span>
                {{ metric.name }}
              </dt>
              <dd>
                <span class="text-section-title">{{ metric.value }}</span>
                <span class="monitor-delta text-caption">{{ metric.delta }}</span>
              </dd>
            </div>
          </dl>
        </template>
      </el-drawer>
    </div>

    <!-- 新建知识库弹窗（名称 / 向量模型 / 描述 / 文件）。
         文档库：弹窗内直接建库 + 上传；图谱库：弹窗收第一步，随后带着草稿进
         整页建图流程补齐算子与 schema。 -->
    <CreateKnowledgeDialog
      v-model="createOpen"
      :graph="createGraph"
      :template="createTemplate"
      :existing-names="existingNames"
      :models="embeddingModels"
      :active-file-limits="uploadLimits.groups"
      :max-files="uploadLimits.maxFiles"
      :max-total-bytes="uploadLimits.maxTotalBytes"
      :submit-handler="saveKnowledgeDialog"
    />
    <CreateKbaseDialog ref="createKbaseDialogRef" @refreshTableData="refreshTableData" />
  </AppPage>
</template>

<script lang="ts" setup>
import { computed, reactive, ref, watch, getCurrentInstance, onMounted, onUnmounted } from 'vue';
import { ElMessageBox } from 'element-plus';
import { debounce } from 'lodash';
import { DEBOUNCETIME, EDIT } from '@/shared/constants/index.js';
import CreateKbaseDialog from '@/features/knowledge-base/components/CreateKbaseDialog.vue';
import CreateKnowledgeDialog from '@/features/knowledge-base/components/CreateKnowledgeDialog.vue';
import KnowledgeImportDialog from '@/features/knowledge-base/components/KnowledgeImportDialog.vue';
import TableRefreshButton from '@/shared/ui/TableRefreshButton.vue';
import ListSelectionBar from '@/shared/ui/ListSelectionBar.vue';
import { requestDeletion } from '@/shared/composables/deletion';
import { deleteKnowledgeBase } from '@/features/knowledge-base/api/knowledgeBase';
import { getModelList as getEmbeddingModelListApi } from '@/features/model/api/models';
import {
  createKnowledgeBaseWithFiles,
  fallbackUploadLimits,
  loadUploadLimits,
  uploadFilesToKbase
} from '@/features/knowledge-base/lib/quick-create';
import AppPage from '@/shared/ui/AppPage.vue';
import PageHeader from '@/shared/ui/reference/PageHeader.vue';
import TablePagination from '@/shared/ui/reference/TablePagination.vue';
import {
  Search,
  Document,
  Plus,
  Collection,
  ArrowRight,
  Filter,
  Share,
  Upload,
  Aim,
  Clock,
  Histogram,
  Coin,
  MoreFilled,
  Edit,
  Delete,
  FolderOpened
} from '@/shared/lib/icons';
import { SplitIcon, LayersIcon, SparkleIcon, ActivityIcon } from '@/shared/ui/icons';
import MetricCard from '@/shared/ui/reference/MetricCard.vue';
import { knowledgeBaseStatsApi, knowledgeGraphListApi } from '@/features/graph/api/knowledgeGraph';
import {
  FAILED_STATUSES,
  normalizeStatsResponse,
  overviewFor,
  PENDING_STATUSES,
  READY_STATUSES
} from '@/features/knowledge-base/lib/overview-stats';
import {
  isValidGraphQuickName,
  loadGraphCreateOptions,
  setGraphQuickDraft
} from '@/features/graph/lib/graph-quick-create';
import { isRequestCanceled } from '@/shared/lib/requestCancel.js';
// 状态码：与知识图谱列表页共用同一份实现（状态列与「修改/删除」闸门都读这一份）
import { KB_STATUS, toNum, isDocKbModifyEnabled } from '@/features/knowledge-base/lib/list-status';
// 状态列文案与筛选分桶的唯一来源：两处读同一份目录，避免「列里有、筛选里没有」
import {
  ALL_STATUS_FILTER,
  DOC_KB_STATUS_DEFINITIONS,
  DOC_KB_STATUS_FILTERS,
  findStatusDefinition,
  findStatusFilterOption
} from '@/features/knowledge-base/lib/status-catalog';
// 自动刷新（定时器 + 「用户输入中暂停」）与知识图谱列表页共用；
// 节拍常量也给下面 syncOnResume 的「切回前台补刷」复用
import { useListAutoRefresh, AUTO_REFRESH_INTERVAL } from '@/shared/composables/useListAutoRefresh';
import { docCountLabel } from '@/shared/lib/utils';
// 表格高度自适应（写死高度会把分页条挤出可视区），与图谱两个列表共用

const { proxy } = getCurrentInstance() as any;

// 上次静默刷新的时刻：轮询与「切回前台补刷」共用同一个节拍，避免来回切窗口连打请求
let lastSilentRefreshAt = 0

// 自动刷新（定时器 + 「用户输入中暂停」）抽到 useListAutoRefresh，与知识图谱列表页共用同一份实现；
// 文档知识库特有的闸门（前台 / 有没有进行中的行）以 shouldRefresh 注入。
const listAutoRefresh = useListAutoRefresh({
  // 用户正在输入由 composable 先拦一道，这里只管「这一拍值不值得发请求」
  shouldRefresh: () => {
    // 页面在前台、且列表里有「进行中」的行才发请求
    if (document.hidden) {
      return false;
    }
    // 列表里没有「进行中」的行：界面本来就是静止的，这一拍不发请求
    return hasPendingKbaseRows();
  },
  // 自动刷新不重置分页，保持当前页面状态
  onRefresh: () => refreshTableDataSilently()
});

// 用户输入状态：用户正在输入时不打断（标记输入与 1 秒后恢复都在 composable 里）
const { isUserTyping } = listAutoRefresh;

onMounted(() => {
  // 刚挂载就已经取过列表：把「上次静默刷新」对齐到此刻。
  // 否则初值 0 会让进入页面时的 window focus / visibilitychange 立刻补刷一次，
  // 首屏出现两条一模一样的列表请求。
  lastSilentRefreshAt = Date.now();

  // 每次进入知识库页面时取一次列表
  refreshTableData();

  // 启动自动刷新（闸门见上面 shouldRefresh）
  startAutoRefresh();

  // 概览指标（与列表分开取一次全量，不参与轮询）
  loadOverviewStats();

  // 回到前台/切回本窗口时补一次静默刷新
  document.addEventListener('visibilitychange', syncOnResume);
  window.addEventListener('focus', syncOnResume);
});

onUnmounted(() => {
  // 清理事件监听器
  document.removeEventListener('visibilitychange', syncOnResume);
  window.removeEventListener('focus', syncOnResume);

  // 清理自动刷新定时器与「用户停止输入」计时器（composable 的 stop + 输入计时器一起清）
  listAutoRefresh.dispose();

  // 摘掉表格高度的 ResizeObserver（不摘会一直盯着一个已卸载的 DOM）
});

// 列表里是否还有「进行中」的知识库：解析/切分/生成/入库/发布都算
// （`PENDING_STATUSES` 与指标卡的「进行中」口径同一份，见 overview-stats.ts）。
// 全是对地状态时数据不会自己变，这一拍就不必发请求。
function hasPendingKbaseRows (): boolean {
  return rows.value.some((row: any) => PENDING_STATUSES.includes(toNum(row.status)))
}

// 静默刷新一次列表：不挂转圈、数据没变就不动表格（见列表的静默刷新模式）
function refreshTableDataSilently () {
  lastSilentRefreshAt = Date.now()
  refreshTableData('', true)
}

// 从别的标签页/窗口切回来时补一次静默刷新（离开的这段时间列表可能已经变了），
// 与轮询共用 AUTO_REFRESH_INTERVAL 节拍，防止来回切换窗口连打请求
function syncOnResume () {
  if (document.hidden) {
    return
  }
  if (Date.now() - lastSilentRefreshAt < AUTO_REFRESH_INTERVAL) {
    return
  }
  refreshTableDataSilently()
}

// 启动自动刷新：定时器生命周期、10 秒节拍与「用户输入暂停」都在 useListAutoRefresh 里，
// 文档知识库的闸门在上面创建时以 shouldRefresh 注入
function startAutoRefresh () {
  listAutoRefresh.start();
}

/* 列表状态：用原生 table + 本地分页（不经过 el-table）。
   选择跨页保留：selectedMap 存 id → 行快照，当前页只负责渲染勾选状态。 */
const rows = ref<any[]>([])
const currentPage = ref(1)
const pageSize = ref(10)
const total = ref(0)
/** 列表态：loading / ready / error；失败时保留已有行，不伪造空列表。 */
const listState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const selectedMap = reactive(new Map<string, any>())

const selectedRows = computed(() => Array.from(selectedMap.values()))
const allSelected = computed(() => rows.value.length > 0 && rows.value.every(row => selectedMap.has(row.id)))

function isSelected (row: any): boolean {
  return Boolean(row?.id) && selectedMap.has(row.id)
}

function toggleRow (row: any, checked: boolean) {
  if (!row?.id) {
    return
  }
  if (checked) {
    selectedMap.set(row.id, { ...row })
  } else {
    selectedMap.delete(row.id)
  }
}

function toggleAll (checked: boolean) {
  rows.value.forEach(row => {
    if (checked) {
      selectedMap.set(row.id, { ...row })
    } else {
      selectedMap.delete(row.id)
    }
  })
}

function clearSelection () {
  selectedMap.clear()
}

/** 刷新 / 翻页后：把仍在当前页的已选项同步成最新行数据，避免展示旧的文件数。 */
function syncSelectedRows (data: any[]) {
  data.forEach(row => {
    if (row?.id && selectedMap.has(row.id)) {
      selectedMap.set(row.id, { ...row })
    }
  })
}

async function loadRows (): Promise<boolean> {
  if (!rows.value.length) {
    listState.value = 'loading'
  }
  try {
    const result = await getTableDataApi(
      { currentPage: currentPage.value, pageSize: pageSize.value },
      {}
    )
    const data = Array.isArray(result?.items) ? result.items : []
    const mapped = data.map((row: any, index: number) => ({
      ...row,
      __avatarTone: avatarTone(index)
    }))
    syncSelectedRows(mapped)
    rows.value = mapped
    total.value = Number(result?.total) || data.length
    listState.value = 'ready'
    return true
  } catch (error) {
    if (isRequestCanceled(error)) {
      // 被新请求顶掉不是故障，刷新按钮也不该显示失败。
      return true
    }
    // Keep the last successful rows; only surface the error when the table is empty.
    listState.value = 'error'
    console.error('获取文档知识库列表失败:', error)
    return false
  }
}

/** 刷新按钮：保留搜索 / 筛选 / 页码 / 勾选；失败时保留原列表并让按钮显示重试。 */
async function refreshList (): Promise<void> {
  let ok = await loadRows()
  // 外部删除 / 数据变少时，当前页可能已越界；回落到最后一个有效页再取一次。
  const maxPage = Math.max(1, Math.ceil(total.value / pageSize.value))
  if (ok && currentPage.value > maxPage) {
    currentPage.value = maxPage
    ok = await loadRows()
  }
  await loadOverviewStats()
  if (!ok) {
    throw new Error('refresh failed')
  }
}

function onPaginationChange ({ page, size }: { page: number, size: number }) {
  currentPage.value = page
  pageSize.value = size
  refreshTableData()
}

async function getTableDataApi (params: any, config: any) {
  try {
    // 构建请求参数 - 按照接口文档规范
    const requestParams = {
      categories: [1], // 知识库类别：1=文档知识库
      currentPage: params.currentPage || params.pageNum || 1, // 当前页，必须是正整数
      pageSize: params.pageSize || 10, // 一页多少条，必须是正整数
      keyword: searchKey.value || '', // 关键字，非必填
      orderList: orderList.value || [], // 排序列表，非必填
      ...params
    }

    // 状态筛选：后端搜索契约没有 status 字段，这里取整份结果集（≤500）后
    // 在本地过滤再按请求的分页切片 —— 分页总数仍是「筛选后的真实总数」，
    // 不会出现「当前页筛完只剩两行、总数却还是 300」的假象。
    if (statusFilter.value !== 'all') {
      const allResponse = await knowledgeGraphListApi(
        { ...requestParams, currentPage: 1, pageSize: STATS_PAGE_SIZE },
        config
      )
      let rows = extractRows(allResponse).filter(matchesStatusFilter)
      const sort = orderList.value && orderList.value[0]
      if (sort && sort.key) {
        const direction = sort.ascending === 'desc' ? -1 : 1
        rows = rows.slice().sort((a, b) => {
          const left = a[sort.key]
          const right = b[sort.key]
          if (left === right) {
            return 0
          }
          return (String(left ?? '') > String(right ?? '') ? 1 : -1) * direction
        })
      }
      const page = Number(requestParams.currentPage) || 1
      const size = Number(requestParams.pageSize) || 10
      const start = (page - 1) * size
      return {
        items: rows.slice(start, start + size),
        total: rows.length,
        page,
        pageSize: size
      }
    }

    // 调用真实接口
    const response = await knowledgeGraphListApi(requestParams, config)

    // 列表响应为 { items, total, page, pageSize }
    const data = Array.isArray(response)
      ? response
      : (Array.isArray(response?.items) ? response.items : [])
    const total = Array.isArray(response)
      ? data.length
      : Number(response?.total ?? data.length)

    return { items: data, total }
  } catch (error) {
    // 取数被后一次请求顶掉（列表每次取数都会 abort 上一次），
    // 这是正常的新旧替换，不是故障：既不该打错误日志，也不该伪造一个空列表返回
    // —— 那会把还在进行中的新请求的结果覆盖掉。交给列表取数的 catch 兜底即可。
    if (isRequestCanceled(error)) {
      throw error
    }
    console.error('获取文档知识库列表失败:', error)
    // 不要伪造「空列表」当成功返回：那会被当成真数据写进表格，
    // 后台轮询一旦失败就把列表清空；而「有没有进行中的行」的闸门看到空列表会关掉，
    // 于是再也轮询、错误永远自愈不了。抛出即可 —— 列表取数的 catch 里
    // 前台刷新清表、后台刷新保留原数据（见列表 getTableData）。
    throw error
  }
}

/** 「查看使用文档」：静态上手步骤（不发请求）。 */
function openUsageDocs () {
  ElMessageBox.alert(
    proxy.$t('modules.kb.docsBody'),
    proxy.$t('modules.kb.docsTitle'),
    {
      confirmButtonText: proxy.$t('modules.kb.docsConfirm'),
      customStyle: { whiteSpace: 'pre-line' }
    }
  )
}

/* ── 工具条「更多」抽屉 ───────────────────────────────────────── */
const panelOpen = ref(false)
const panel = ref<'pipeline' | 'monitor'>('pipeline')
const monitorPeriod = ref('7')

const monitoring = computed(() => ([
  { name: proxy.$t('modules.kb.monitorP95'), value: '—', delta: proxy.$t('modules.kb.monitorUnavailable'), icon: Clock, tone: 'blue' },
  { name: 'Recall@10', value: '—', delta: proxy.$t('modules.kb.monitorUnavailable'), icon: Aim, tone: 'purple' },
  { name: proxy.$t('modules.kb.monitorHitRate'), value: '—', delta: proxy.$t('modules.kb.monitorUnavailable'), icon: Histogram, tone: 'green' },
  { name: proxy.$t('modules.kb.monitorFreshness'), value: '—', delta: proxy.$t('modules.kb.monitorUnavailable'), icon: Coin, tone: 'blue' }
]))

function openPanel (command: string) {
  if (command === 'docs') {
    openUsageDocs()
    return
  }
  panel.value = command === 'monitor' ? 'monitor' : 'pipeline'
  panelOpen.value = true
}

/* ── 顶部「导入」：先选目标知识库，再上传文件 ───────────────────── */
const importOpen = ref(false)
const importTarget = ref('')
const importEntries = ref<{ id: string, name: string }[]>([])

async function openImport (row?: any) {
  importTarget.value = row?.id || ''
  importEntries.value = rows.value
    .map(item => ({ id: item.id, name: item.name }))
    .filter(item => item.id && item.name)
  importOpen.value = true
  // 目标下拉要覆盖所有知识库，而不是只有当前页。
  try {
    const response = await knowledgeGraphListApi(
      { categories: [1], currentPage: 1, pageSize: STATS_PAGE_SIZE },
      { skipErrorHandler: true }
    )
    const entries = extractRows(response)
      .map((item: any) => ({ id: item?.id, name: item?.name }))
      .filter(item => item.id && item.name)
    if (entries.length) {
      importEntries.value = entries
    }
  } catch {
    // 拉全量失败就保留当前页选项，不挡导入主流程
  }
}

async function submitImport ({ target, files }: { target: any, files: File[] }, options: { coverFlag?: boolean } = {}) {
  // 同名冲突由弹窗弹「是否覆盖」确认，确认后带 coverFlag 重发一次
  await uploadFilesToKbase(target.id, files, {
    skipErrorHandler: true,
    coverFlag: Boolean(options.coverFlag)
  })
  proxy.$message.success(proxy.$t('modules.kb.importSuccess'))
  await loadRows()
  loadOverviewStats()
}

/* ── 概览指标 / 右侧面板 ─────────────────────────────────────────
 * 数值来自真实列表接口：知识库列表（category=1）与图谱列表（category=10）
 * 各取一次全量（≤500），在本地求和/计数。没有「较上周」历史数据，所以卡片
 * 右侧显示的是当前结构（可用数 / 平均文档数 / 就绪占比），不是编造的涨幅。
 */
const overview = reactive({
  kbTotal: 0,
  docTotal: 0,
  graphTotal: 0,
  graphReady: 0,
  ready: 0,
  pending: 0,
  failed: 0,
  avgDocs: '0'
})

const canImport = computed(() => overview.kbTotal > 0 || total.value > 0)

// 接口上限：新建弹窗的「同名提示」需要一次拿到足够多的库名，仍走列表端点。
// 指标卡已改用 GET /knowledge-bases/stats，不再需要全量拉列表。
const STATS_PAGE_SIZE = 500

function extractRows (response: any): any[] {
  if (!response) {
    return []
  }
  if (Array.isArray(response)) {
    return response
  }
  if (Array.isArray(response.items)) {
    return response.items
  }
  if (response.data && Array.isArray(response.data.items)) {
    return response.data.items
  }
  return []
}

async function loadOverviewStats () {
  try {
    // 一个聚合端点返回 total / fileTotal / statusCounts，避免拉全量列表：
    // 后端按分类返回，状态分类仍在前端做。
    const response = await knowledgeBaseStatsApi(
      { categories: [1, 10] },
      { skipErrorHandler: true }
    )
    const stats = normalizeStatsResponse(response)
    const docStats = overviewFor(stats, 1) // 1=文档知识库
    const graphStats = overviewFor(stats, 10) // 10=知识图谱

    overview.kbTotal = docStats.total
    overview.docTotal = docStats.fileTotal
    overview.graphTotal = graphStats.total
    overview.graphReady = graphStats.ready
    overview.ready = docStats.ready
    overview.pending = docStats.pending
    overview.failed = docStats.failed
    overview.avgDocs = overview.kbTotal
      ? (overview.docTotal / overview.kbTotal).toFixed(1)
      : '0'
  } catch {
    // 指标只是概览；取不到时保持 0，不挡列表主流程
  }
}

const readyPercent = computed(() => {
  if (!overview.kbTotal) {
    return '0%'
  }
  return `${Math.round((overview.ready / overview.kbTotal) * 100)}%`
})

/** 左侧 RAG 流程（说明性内容，与真实链路一致）。 */
const pipelineSteps = computed(() => [
  { name: proxy.$t('modules.kb.pipelineDocSource'), desc: proxy.$t('modules.kb.pipelineDocSourceDesc'), icon: Document, tone: 'blue' },
  { name: proxy.$t('modules.kb.pipelineSplit'), desc: proxy.$t('modules.kb.pipelineSplitDesc'), icon: SplitIcon, tone: 'purple' },
  { name: proxy.$t('modules.kb.pipelineVector'), desc: proxy.$t('modules.kb.pipelineVectorDesc'), icon: LayersIcon, tone: 'green' },
  { name: proxy.$t('modules.kb.pipelineRetrieve'), desc: proxy.$t('modules.kb.pipelineRetrieveDesc'), icon: Search, tone: 'orange' },
  { name: proxy.$t('modules.kb.pipelineAnswer'), desc: proxy.$t('modules.kb.pipelineAnswerDesc'), icon: SparkleIcon, tone: 'blue' }
])

/**
 * 状态筛选（全部 / 已就绪 / 处理中 / 失败）。作用在整份结果集上，见 getTableDataApi。
 *
 * 分桶在状态目录里定义：每个状态码恰好落在一个桶，状态列能显示的状态都能被筛到。
 * 空库（0 篇文档）不单列，按状态列文案归到「已就绪」。
 */
const statusFilter = ref(ALL_STATUS_FILTER)
const statusOptions = DOC_KB_STATUS_FILTERS

function setStatusFilter (value: string) {
  statusFilter.value = value
  refreshTableData('initPage')
}

function matchesStatusFilter (row: any): boolean {
  const option = findStatusFilterOption(statusOptions, statusFilter.value)
  return !option || option.codes.includes(toNum(row.status))
}

/* ── 单元格展示辅助（.avatar-square / .status-dot / .entity-sub） ── */
const AVATAR_TONES = ['av-blue', 'av-purple', 'av-green', 'av-orange']

function initialOf (name: string): string {
  return String(name || '?').charAt(0)
    .toUpperCase()
}

/** 按行顺序取色：blue → purple → green → orange。 */
function avatarTone (index: number): string {
  return AVATAR_TONES[index % AVATAR_TONES.length]
}

/** 状态码 → 圆点色 + 文案：文案来自状态目录，与筛选选项同一份。 */
function statusMeta (row: any): { tone: string, text: string } {
  const definition = findStatusDefinition(DOC_KB_STATUS_DEFINITIONS, toNum(row.status))
  if (!definition) {
    return { tone: 'muted', text: proxy.$t('modules.kb.statusUnknown') }
  }
  return { tone: definition.tone, text: proxy.$t(definition.labelKey) }
}

/** 行级鉴权标记：`action === 'c'` 时整行操作禁用（与 DocKbRowActions 同语义）。 */
function isRowLocked (row: any): boolean {
  return Boolean(row?.action && row.action === 'c')
}

function creatorOf (row: any): string {
  const name = (proxy.$globalZh ? row?.fullName : row?.fullNameEn) || ''
  const account = row?.createdBy || ''
  return [name, account].filter(Boolean).join(' ') || '--'
}

function statusSub (row: any): string {
  const status = toNum(row.status)
  if (status === KB_STATUS.PUBLISHED_MODIFIED) {
    return proxy.$t('modules.kb.statusPublishedModifiedSub')
  }
  if (status === KB_STATUS.PUBLISH_FAILED) {
    return proxy.$t('modules.kb.statusPublishFailedSub')
  }
  if (READY_STATUSES.includes(status)) {
    return proxy.$t('modules.kb.metricReadyFoot')
  }
  if (FAILED_STATUSES.includes(status)) {
    // 状态副文案固定为「请检查数据格式」；详细失败原因放到 title 里，
    // 避免长文案把表格「状态」列撑宽（列宽由内容决定）。
    return proxy.$t('modules.kb.statusCheckDataFormat')
  }
  if (PENDING_STATUSES.includes(status)) {
    return proxy.$t('modules.kb.dataProcessing')
  }
  return proxy.$t('modules.kb.statusUnknownSub')
}

function formatDateShort (value: string): string {
  return value ? String(value).replace('T', ' ')
    .slice(0, 16) : '--'
}

/** 「2 小时前」：只用于列表的辅助行，取不到/乱码时回落原值。 */
function relativeTime (value: string): string {
  if (!value) {
    return ''
  }
  const timestamp = new Date(String(value).replace(/-/g, '/')).getTime()
  if (!Number.isFinite(timestamp)) {
    return ''
  }
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60000))
  if (minutes < 1) {
    return proxy.$t('public.justNow')
  }
  if (minutes < 60) {
    return proxy.$t('public.minutesAgo', { count: minutes })
  }
  const hours = Math.floor(minutes / 60)
  if (hours < 24) {
    return proxy.$t('public.hoursAgo', { count: hours })
  }
  const days = Math.floor(hours / 24)
  return proxy.$t('public.daysAgo', { count: days })
}

function createFromTemplate (command: string) {
  if (command === 'graph') {
    // 图谱模板也走同一个新建弹窗（graph 分支），
    // 提交后带着草稿进整页补齐抽图算子与 schema。
    openCreateDialog('', true)
    return
  }
  openCreateDialog(command === 'document' ? proxy.$t('modules.kb.templateDocument') : '')
}

/* ── 新建知识库弹窗 ──────────────────────────────────────────────
 * 弹窗需要三份真实数据：向量模型、同名列表、文件上限。
 * - 模型：/embedding/all（与整页创建页同一个接口）
 * - 同名：/kbase/search 取前 500 条（接口上限），只用于 blur 时的即时提示；
 *   最终判重仍由后端在建库时做。
 * - 文件上限：GET /file/size_limit；取不到回落到静态缺省值。
 */
const createOpen = ref(false)
const createTemplate = ref('')
const createGraph = ref(false)
const existingNames = ref<string[]>([])
const embeddingModels = ref<{ name: string, recommended?: boolean }[]>([])
const uploadLimits = ref(fallbackUploadLimits())

async function loadCreateOptions () {
  const tasks: Promise<any>[] = []
  tasks.push(getEmbeddingModelListApi()
    .then((response: any) => {
      const list = Array.isArray(response) ? response : []
      embeddingModels.value = list
        .map((item: any) => (typeof item === 'string' ? { name: item } : { name: item?.modelName || item?.name }))
        .filter(item => item.name)
    })
    .catch(() => {
      embeddingModels.value = []
    }))
  tasks.push(knowledgeGraphListApi(
    { categories: [1], currentPage: 1, pageSize: STATS_PAGE_SIZE },
    { skipErrorHandler: true }
  )
    .then(response => {
      existingNames.value = extractRows(response)
        .map((row: any) => row?.name)
        .filter(Boolean)
    })
    .catch(() => {
      existingNames.value = []
    }))
  tasks.push(loadUploadLimits().then(limits => {
    uploadLimits.value = limits
  }))
  await Promise.all(tasks)
}

async function openCreateDialog (template = '', graph = false) {
  createTemplate.value = graph ? '' : template
  createGraph.value = graph
  // 先取模型 / 同名 / 文件上限，再打开弹窗 —— 避免弹窗先渲染出空模型列表
  if (graph) {
    const options = await loadGraphCreateOptions()
    embeddingModels.value = options.models
    existingNames.value = options.existingNames
    uploadLimits.value = options.limits
  } else {
    await loadCreateOptions()
  }
  createOpen.value = true
}

/**
 * 弹窗提交分流：
 * - 图谱：把表单交给整页建图流程（还缺算子/schema），不在这里建库；
 * - 文档：真实建库 + 上传（见 `createKnowledgeWithFiles`）。
 */
async function saveKnowledgeDialog (payload: {
  name: string,
  description: string,
  model: string,
  files: File[]
}) {
  if (!createGraph.value) {
    await createKnowledgeWithFiles(payload)
    return
  }
  const name = payload.name.trim()
  if (!isValidGraphQuickName(name)) {
    proxy.$message.error(proxy.$t('modules.kb.knowledgeGraphNameValidation'))
    // 抛回弹窗：保持打开，让用户就地改名
    throw new Error('invalid graph knowledge base name')
  }
  setGraphQuickDraft({ ...payload, name })
  proxy.$router.push({ name: 'graph-create' })
}

/**
 * 弹窗提交：真实建库 + 上传。
 *
 * - 建库失败（没有 kbId）：抛回弹窗，用户改名/重试；
 * - 建库成功但上传失败：**不再抛回弹窗**（重试会再建一个库），提示后把人带到
 *   新库的文档页，那里可以重新导入。
 */
async function createKnowledgeWithFiles (payload: {
  name: string,
  description: string,
  model: string,
  files: File[]
}) {
  try {
    const result = await createKnowledgeBaseWithFiles(payload)
    proxy.$message.success(proxy.$t('modules.studioDialogs.createKnowledge.createSuccess'))
    refreshTableData('initPage')
    loadOverviewStats()
    proxy.$router.push({ name: 'knowledge-documents', params: { id: result.kbId } })
  } catch (error: any) {
    if (error?.kbId) {
      proxy.$message.error(proxy.$t('modules.studioDialogs.createKnowledge.uploadFailed'))
      refreshTableData('initPage')
      loadOverviewStats()
      proxy.$router.push({ name: 'knowledge-documents', params: { id: error.kbId } })
      return
    }
    throw error
  }
}

const searchKey = ref('');

// 切换筛选（含搜索）清除勾选，避免把看不见的行带进批量删除。
watch([searchKey, statusFilter], () => {
  clearSelection()
})

// 处理用户输入 - 标记用户正在操作
function handleSearchInput () {
  // 标记用户正在输入，1 秒无输入后自动恢复轮询（计时器在 useListAutoRefresh 里）
  listAutoRefresh.noteTypingInput()

  // 触发搜索（带防抖）
  search()
}

const search = debounce(() => {
  isUserTyping.value = false // 搜索完成后标记用户停止输入
  refreshTableData('initPage');
}, DEBOUNCETIME)

const orderList = ref<any[]>([]);

function refreshTableData (initPage: string | any[] = '', background = false) {
  if (Array.isArray(initPage)) {
    orderList.value = initPage;
  }
  if (initPage) {
    currentPage.value = 1;
  }
  return loadRows(background);
};

const createKbaseDialogRef = ref();

function addKbaseHandle () {
  openCreateDialog()
}

function detailHandle (row: any) {
  // 库名进入新的「分块」详情页（数据集 + 基本信息）。
  openDetail(row)
}

function openDetail (row: any) {
  proxy.$router.push({
    name: 'knowledge-detail',
    params: { id: row.id }
  })
}

function openDocuments (row: any, importNow = false) {
  proxy.$router.push({
    name: 'knowledge-documents',
    params: { id: row.id },
    query: importNow ? { import: '1' } : {}
  })
}


function modifyKbaseHandle (row: any) {
  createKbaseDialogRef.value.openDialog({
    mode: EDIT,
    id: row.id
  });
}

/** 单条删除走统一确认弹窗（影响说明 + 对象信息 + 验证码）。 */
async function deleteKbaseHandle (row: any) {
  // 列表行已带 currentFileCount，不再单独打一次判空接口；后端 DELETE 仍会兜底。
  if (Number(row.currentFileCount) > 0) {
    proxy.$message.warning(proxy.$t('knowledge.deleteKnowledgeBaseNotEmpty'));
    return;
  }
  const confirmed = await requestDeletion({
    resourceType: proxy.$t('modules.kb.resourceKb'),
    warning: proxy.$t('modules.kb.deleteWarning'),
    description: proxy.$t('modules.kb.deleteDescription'),
    items: [{
      id: row.id,
      name: row.name,
      meta: row.id,
      letter: initialOf(row.name),
      av: row.__avatarTone,
      tag: proxy.$t('modules.kb.resourceKb')
    }],
    detail: proxy.$t('modules.kb.deleteDetail', { docs: Number(row.currentFileCount) || 0 }),
    hint: proxy.$t('modules.kb.deleteHint')
  })
  if (!confirmed) {
    return
  }
  try {
    await deleteKnowledgeBase(row.id)
    selectedMap.delete(row.id)
    proxy.$message.success(proxy.$t('public.deleteSuccess'))
    await refreshAfterDeletes(1)
  } catch (error: any) {
    // 冒号已并入词条值（zh '删除失败：' / en 'Delete failed: '），这里只拼接。
    proxy.$message.error(`${proxy.$t('public.deletefail')}${error?.detail || error?.message || proxy.$t('public.noData')}`)
  }
}

/** 批量删除：先剔除「非空 / 无权删除」的行，再走同一个确认弹窗。 */
async function removeSelectedKbs () {
  const targets = selectedRows.value.filter(row => !isRowLocked(row) && Number(row.currentFileCount) === 0)
  const skipped = selectedRows.value.length - targets.length
  if (!targets.length) {
    proxy.$message.warning(proxy.$t('modules.kb.deleteBatchBlocked'))
    return
  }
  if (skipped > 0) {
    proxy.$message.warning(proxy.$t('modules.kb.deleteBatchSkipped', { count: skipped }))
  }
  const confirmed = await requestDeletion({
    resourceType: proxy.$t('modules.kb.resourceKb'),
    title: proxy.$t('modules.kb.deleteBatchTitle'),
    warning: proxy.$t('modules.kb.deleteWarning'),
    description: proxy.$t('modules.kb.deleteDescription'),
    items: targets.map(row => ({
      id: row.id,
      name: row.name,
      meta: row.id,
      letter: initialOf(row.name),
      av: row.__avatarTone,
      tag: proxy.$t('modules.kb.resourceKb')
    })),
    detail: proxy.$t('modules.kb.deleteDetail', {
      docs: targets.reduce((sum, row) => sum + (Number(row.currentFileCount) || 0), 0)
    }),
    hint: proxy.$t('modules.kb.deleteHint')
  })
  if (!confirmed) {
    return
  }
  const results = await Promise.allSettled(targets.map(row => deleteKnowledgeBase(row.id)))
  let success = 0
  results.forEach((result, index) => {
    if (result.status === 'fulfilled') {
      success += 1
      selectedMap.delete(targets[index].id)
    }
  })
  const failed = targets.length - success
  if (success) {
    proxy.$message.success(proxy.$t('modules.kb.deleteBatchSuccess', { count: success }))
  }
  if (failed) {
    proxy.$message.error(proxy.$t('modules.kb.deleteBatchPartial', { success, failed }))
  }
  await refreshAfterDeletes(success)
}

/** 删除后回到有效页：末页被删空时向前回落。 */
async function refreshAfterDeletes (deletedCount: number) {
  const remaining = Math.max(0, total.value - deletedCount)
  const maxPage = Math.max(1, Math.ceil(remaining / pageSize.value))
  if (currentPage.value > maxPage) {
    currentPage.value = maxPage
  }
  await refreshTableData()
  loadOverviewStats()
}

const kbaseMoreDropdown = {
  modifyKbase: modifyKbaseHandle,
  deleteKbase: deleteKbaseHandle
}

function moreHandleCommand (command:keyof typeof kbaseMoreDropdown, row: any) {
  kbaseMoreDropdown[command](row);
}

</script>

<style scoped>
  .knowledge-main { min-width: 0; }
  .knowledge-more { width: 40px; padding: 10px; }
  .knowledge-table { min-width: 960px; }
  .knowledge-table .entity-title { white-space: nowrap; }
  .filter-active { color: var(--rs-primary); border-color: var(--rs-primary-border); }
  .panel-title { margin: 0; color: var(--rs-text); }
  .panel-description { color: var(--rs-text-2); margin: 0 0 24px; }
  .pipeline-steps { list-style: none; padding: 0; margin: 0; }
  .pipeline-step { display: flex; align-items: flex-start; gap: 16px; position: relative; padding-bottom: 32px; }
  .pipeline-step:not(:last-child)::after { content: ''; position: absolute; left: 21px; top: 50px; bottom: 8px; border-left: 1px dashed var(--rs-border); }
  .pipeline-step h3 { margin: 0 0 6px; color: var(--rs-text); }
  .pipeline-step p { margin: 0; color: var(--rs-text-2); overflow-wrap: anywhere; }
  .pipeline-icon { display: flex; align-items: center; justify-content: center; width: 44px; height: 44px; flex-shrink: 0; border-radius: 10px; background: var(--tint); color: var(--tone); }
  .pipeline-icon svg { width: 22px; height: 22px; }
  .panel-link { display: flex; align-items: center; gap: 6px; border-top: 1px solid var(--rs-border); padding-top: 20px; }
  .panel-link svg { width: 14px; height: 14px; }
  .monitor-heading { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 20px; }
  .monitor-heading .panel-description { margin: 0; }
  .monitor-list { margin: 0; }
  .monitor-item { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 14px; padding: 24px 0; border-bottom: 1px solid var(--rs-border-soft); }
  .monitor-item dt { display: flex; align-items: center; gap: 14px; color: var(--rs-text-2); }
  .monitor-item dd { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; margin: 0; color: var(--rs-text); }
  /* Values are unavailable until the monitoring API exists; do not use the
     success green from the prototype's real-trend state. */
  .monitor-delta { color: var(--rs-text-3); }
</style>

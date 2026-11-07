<template>
  <div class="graph-list-page">
    <input
      ref="importFileInput"
      type="file"
      accept=".zip"
      style="display: none"
      @change="onImportFileChange"
    >

    <div class="metric-grid">
      <MetricCard
        :label="$t('modules.kb.metricKbTotal')"
        :value="overview.graphTotal"
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
        :delta-title="$t('modules.kb.metricGraphReady', { count: overview.ready }) + ' · ' + $t('modules.kb.metricTrendUnavailable')"
        :foot="$t('modules.kb.metricFoot')"
        :icon="Share"
        tone="purple"
      />
      <MetricCard
        :label="$t('modules.kb.metricHealth')"
        :value="readyPercent"
        delta="—"
        muted
        :delta-title="$t('modules.kb.metricReadyRatio', { ready: overview.ready, total: overview.graphTotal }) + ' · ' + $t('modules.kb.metricTrendUnavailable')"
        :foot="$t('modules.kb.metricFoot')"
        :icon="ActivityIcon"
        tone="orange"
      />
    </div>

    <section class="knowledge-main management-main">
      <div class="toolbar">
        <div class="toolbar-left">
          <el-button type="primary" @click="handleCreateKnowledgeGraph">
            <Plus />
            {{ $t('modules.kb.createGraphKnowledgeBase') }}
          </el-button>
          <el-button @click="handleImportKnowledgeGraph">
            <Upload />
            {{ $t('public.import') }}
          </el-button>
          <el-dropdown
            trigger="click"
            @command="handleTemplateCommand"
          >
            <el-button>
              <Collection />
              {{ $t('modules.kb.templateButton') }}
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="download">
                  <Download />
                  {{ $t('modules.kb.downloadTemplate') }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <!-- 图谱模版从「更多」菜单提到工具条：专业图谱必须先建模版，入口不宜再藏两层。 -->
          <el-button @click="openTemplateList">
            <Notebook />
            {{ $t('modules.kb.knowledgeGraphTemplate') }}
          </el-button>
          <el-dropdown trigger="click" @command="openPanel">
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
                  {{ $t('modules.kb.pipelineTitle') }}
                </el-dropdown-item>
                <el-dropdown-item command="monitor">
                  {{ $t('modules.kb.monitorTitle') }}
                </el-dropdown-item>
                <el-dropdown-item command="docs" divided>
                  {{ $t('modules.kb.viewDocs') }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <div class="toolbar-right">
          <TableRefreshButton :label="$t('modules.kb.refreshGraphList')" :refresh="refreshList" />
          <el-input
            v-model.trim="searchKey"
            class="search-field"
            maxlength="200"
            :placeholder="$t('modules.kb.searchKnowledgeGraphName')"
            :prefix-icon="Search"
            clearable
            @input="handleSearchInput"
            @change="handleSearchInput"
            @clear="handleSearchInput"
          />
          <el-dropdown trigger="click" @command="setStatusFilter">
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

      <ListSelectionBar :count="selectedRows.length" @clear="clearSelection">
        <el-button class="danger-action" link type="danger" @click="removeSelectedGraphs">
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
                  <div :class="['avatar-square', avatarTone(index)]">
                    {{ initialOf(row.name) }}
                  </div>
                  <div>
                    <a
                      :key="`${row.id}-${row.name}`"
                      class="entity-title entity-link"
                      @click="handleNameClick(row)"
                    >{{ row.name || '--' }}</a>
                    <div class="entity-sub entity-desc" :title="row.description || ''">
                      {{ row.description || '--' }}
                    </div>
                    <div class="table-tags">
                      <span v-if="row.embeddingModel" class="tag-soft">{{ row.embeddingModel }}</span>
                      <span class="tag-soft purple">{{ $t('modules.kb.knowledgeGraph') }}</span>
                    </div>
                  </div>
                </div>
              </td>
              <td>
                <span class="tag-soft purple">
                  <Share />
                  {{ $t('modules.kb.tagGraph') }}
                </span>
              </td>
              <td class="nowrap">
                <b>{{ docCountLabel(row.currentFileCount || 0) }}</b>
                <div class="entity-sub">
                  {{ graphCountSub(row) }}
                </div>
              </td>
              <td class="nowrap">
                <span :class="['status-dot', statusMeta(row).tone]" />
                <b>{{ statusMeta(row).text }}</b>
                <div class="entity-sub status-sub" :title="row.failReason || ''">
                  {{ graphStatusSub(row) }}
                </div>
              </td>
              <td class="nowrap">
                {{ formatDateShort(row.createdDate) }}
                <div class="entity-sub">
                  {{ relativeTime(row.createdDate) }}
                </div>
              </td>
              <td>{{ row.createdBy || '--' }}</td>
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
                      <el-dropdown-item
                        :disabled="!isModifyEnabled(toNum(row.status))"
                        @click="handleModify(row)"
                      >
                        <Edit />
                        {{ $t('public.modify') }}
                      </el-dropdown-item>
                      <el-dropdown-item @click="handleExportGraph(row)">
                        <Download />
                        {{ $t('modules.kb.exportGraph') }}
                      </el-dropdown-item>
                      <el-dropdown-item
                        divided
                        class="danger-menu-item"
                        :disabled="!isDeleteEnabled(toNum(row.status))"
                        @click="deleteKnowledgeGraphHandle(row)"
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
                {{ $t('public.noData') }}
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

    <el-drawer v-model="panelOpen" size="min(440px, 100vw)" destroy-on-close>
      <template #header>
        <h2 class="panel-title text-section-title">
          {{ panel === 'pipeline' ? $t('modules.kb.pipelineTitle') : $t('modules.kb.monitorTitle') }}
        </h2>
      </template>
      <template v-if="panel === 'pipeline'">
        <p class="panel-description text-secondary">
          {{ $t('modules.kb.pipelineGraphDrawerDesc') }}
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


    <el-dialog
      v-model="importChoiceDialogVisible"
      :title="$t('modules.kb.importDialogTitle')"
      width="500px"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      class="import-choice-dialog"
    >
      <div class="dialog-content">
        <p class="dialog-message">
          {{ $t('modules.kb.importChoiceMessage') }}
        </p>
        <div class="radio-group-container">
          <el-radio-group v-model="importChoiceValue" class="import-radio-group">
            <el-radio value="update" size="large" class="import-radio">
              <span>{{ $t('modules.kb.incrementalUpdate') }}</span>
              <el-tooltip
                :content="$t('modules.kb.incrementalUpdateTip')"
                placement="top"
                effect="light"
              >
                <i class="plx-ico-help-tip-20 import-radio-tip-icon" />
              </el-tooltip>
            </el-radio>
            <el-radio value="overwrite" size="large" class="import-radio">
              <span>{{ $t('modules.kb.fullOverwrite') }}</span>
              <el-tooltip
                :content="$t('modules.kb.fullOverwriteTip')"
                placement="top"
                effect="light"
              >
                <i class="plx-ico-help-tip-20 import-radio-tip-icon" />
              </el-tooltip>
            </el-radio>
          </el-radio-group>
        </div>
      </div>
      <template #footer>
        <div class="dialog-footer">
          <el-button type="primary" @click="handleImportChoiceConfirm">
            {{ $t('modules.kb.importButton') }}
          </el-button>
          <el-button @click="handleImportChoiceCancel">
            {{ $t('public.cancel') }}
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 图谱库也走同一个新建弹窗；弹窗内直接收集
         算子 / 模板 / LLM / 切分参数并提交建图，不跳整页补配置。 -->
    <CreateKnowledgeDialog
      v-model="createOpen"
      graph
      :existing-names="createExistingNames"
      :models="createModels"
      :active-file-limits="createLimits.groups"
      :max-files="createLimits.maxFiles"
      :max-total-bytes="createLimits.maxTotalBytes"
      @create="handleGraphCreated"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, getCurrentInstance, onMounted, onUnmounted, watch, inject } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import {
  ArrowRight,
  Coin,
  Collection,
  Document,
  Download,
  Edit,
  Delete,
  Filter,
  MoreFilled,
  Notebook,
  Plus,
  Search,
  Upload
} from '@element-plus/icons-vue'
import { Share, Aim, Clock, Histogram } from '@/shared/lib/icons'
import { SplitIcon, LayersIcon, SparkleIcon, ActivityIcon } from '@/shared/ui/icons'
import MetricCard from '@/shared/ui/reference/MetricCard.vue'
import TablePagination from '@/shared/ui/reference/TablePagination.vue'
import TableRefreshButton from '@/shared/ui/TableRefreshButton.vue'
import ListSelectionBar from '@/shared/ui/ListSelectionBar.vue'
import { requestDeletion } from '@/shared/composables/deletion'
import { knowledgeGraphListApi, knowledgeBaseStatsApi, deleteKnowledgeGraphApi, importKnowledgeGraphApi, getKnowledgeGraphBasicInfoApi, exportGraphKnowledgeBaseApi } from '@/features/graph/api/knowledgeGraph'
import CreateKnowledgeDialog from '@/features/knowledge-base/components/CreateKnowledgeDialog.vue'
import { loadGraphCreateOptions } from './lib/graph-quick-create'
import { fallbackUploadLimits } from '@/features/knowledge-base/lib/quick-create'
import JSZip from 'jszip'
// 状态闸门与状态码：与文档知识库列表页共用同一份实现（模板里用的 isModifyEnabled /
// isDeleteEnabled 就是这两个别名；图谱页的允许集合与文档知识库
// **不同**，在 lib 里逐条注明）
import {
  KB_STATUS,
  toNum,
  isGraphModifyEnabled as isModifyEnabled,
  isGraphDeleteEnabled as isDeleteEnabled
} from '@/features/knowledge-base/lib/list-status'
// 指标卡数据整形：与文档知识库列表页共用同一份实现，口径（三类状态集合）由本页传入
import { normalizeStatsResponse, overviewFor } from '@/features/knowledge-base/lib/overview-stats'
// 状态列文案与筛选分桶的唯一来源：两处读同一份目录，避免「列里有、筛选里没有」
import {
  ALL_STATUS_FILTER,
  findStatusDefinition,
  findStatusFilterOption,
  GRAPH_STATUS_DEFINITIONS,
  GRAPH_STATUS_FILTERS
} from '@/features/knowledge-base/lib/status-catalog'
// 自动刷新（定时器 + 「用户输入中暂停」）与文档知识库列表页共用
import { useListAutoRefresh } from '@/shared/composables/useListAutoRefresh'
import { docCountLabel } from '@/shared/lib/utils'
// 表格高度自适应（写死高度会把分页条挤出可视区），与文档知识库列表页共用

interface KnowledgeGraphItem {
  id: string
  name: string
  description: string
  embeddingModel: string
  schemaId: string
  templateName: string
  createdDate: string
  createdBy: string
  status: number
  failReason?: string
}

const { proxy } = getCurrentInstance() as any
const router = useRouter()
// toNum / isModifyEnabled / isDeleteEnabled 位于
// @/features/knowledge-base/lib/list-status.ts，模板使用文件头 import 的这几个函数。

// 搜索关键词
const searchKey = ref('')

/* ── 概览指标 / 右侧面板 ─────────────────────────────────────────
 * 数值来自 GET /knowledge-bases/stats（后端按分类聚合 total / fileTotal /
 * statusCounts），不再把 ≤500 行列表拉回来自己数；与列表请求分开，不参与轮询。
 */
const overview = reactive({
  graphTotal: 0,
  docTotal: 0,
  avgDocs: 0,
  ready: 0,
  pending: 0,
  failed: 0
})

const readyPercent = computed(() => {
  if (!overview.graphTotal) {
    return '0%'
  }
  return `${Math.round((overview.ready / overview.graphTotal) * 100)}%`
})

// 指标卡的「就绪 / 进行中 / 异常」三桶（0=已创建、5=已就绪），与文档知识库页的集合不同。
// 状态筛选是另一套口径：逐条对应状态列的文案，见 lib/status-catalog。
const READY_STATUSES = [5]
const PENDING_STATUSES = [0, 1, 2, 3, 4, 6]
const FAILED_STATUSES = [101, 102, 103, 104, 106]
const GRAPH_STATUS_BUCKETS = {
  ready: READY_STATUSES,
  pending: PENDING_STATUSES,
  failed: FAILED_STATUSES
}

/**
 * 「构建中」状态：这些行会自己往下走，列表才有必要轮询。
 * 0=已创建/等待生成不会自动变化（要用户触发），5=已就绪，都不触发轮询。
 */
const BUILDING_STATUSES = [
  KB_STATUS.PARSING,
  KB_STATUS.SPLITTING,
  KB_STATUS.GENERATING,
  KB_STATUS.INDEXING
]

/** 状态筛选的本地过滤仍要一次取全量（接口上限） */
const STATS_PAGE_SIZE = 500

/**
 * 状态筛选：已就绪 / 已创建 / 处理中 / 失败，分桶定义在状态目录里。
 * 每个状态码恰好落在一个桶，状态列能显示的状态都能被筛到；目录外的状态码
 * 只出现在「全部状态」。
 */
const statusFilter = ref(ALL_STATUS_FILTER)
const statusOptions = GRAPH_STATUS_FILTERS

function setStatusFilter (value: string) {
  statusFilter.value = value
  clearSelection()
  refreshTableData('initPage')
}

function matchesStatusFilter (row: any): boolean {
  const option = findStatusFilterOption(statusOptions, statusFilter.value)
  return !option || option.codes.includes(toNum(row.status))
}

function extractRows (response: any): any[] {
  if (!response) {
    return []
  }
  if (Array.isArray(response)) {
    return response
  }
  if (Array.isArray(response.data)) {
    return response.data
  }
  if (response.data && Array.isArray(response.data.data)) {
    return response.data.data
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
    // 聚合端点：一次请求拿到总数/文档数/状态分布，不拉全量列表
    const response = await knowledgeBaseStatsApi(
      { categories: [10] },
      { skipErrorHandler: true }
    )
    const stats = normalizeStatsResponse(response, GRAPH_STATUS_BUCKETS)
    const graphStats = overviewFor(stats, 10) // 10=知识图谱
    overview.graphTotal = graphStats.total
    overview.docTotal = graphStats.fileTotal
    overview.avgDocs = overview.graphTotal
      ? Math.round((overview.docTotal / overview.graphTotal) * 10) / 10
      : 0
    overview.ready = graphStats.ready
    overview.pending = graphStats.pending
    overview.failed = graphStats.failed
  } catch {
    // 指标只是概览；失败时保持 0，不影响列表
  }
}

// 图谱库的处理链路与文档库不同：没有「向量化」，中间多了实体关系抽取与图谱构建。
const pipelineSteps = computed(() => [
  { name: proxy.$t('modules.kb.pipelineDocSource'), desc: proxy.$t('modules.kb.pipelineDocSourceDesc'), icon: Document, tone: 'blue' },
  { name: proxy.$t('modules.kb.pipelineSplit'), desc: proxy.$t('modules.kb.pipelineSplitDesc'), icon: SplitIcon, tone: 'purple' },
  { name: proxy.$t('modules.kb.pipelineGraphExtract'), desc: proxy.$t('modules.kb.pipelineGraphExtractDesc'), icon: Share, tone: 'green' },
  { name: proxy.$t('modules.kb.pipelineGraphBuild'), desc: proxy.$t('modules.kb.pipelineGraphBuildDesc'), icon: LayersIcon, tone: 'orange' },
  { name: proxy.$t('modules.kb.pipelineGraphRetrieve'), desc: proxy.$t('modules.kb.pipelineGraphRetrieveDesc'), icon: Aim, tone: 'blue' },
  { name: proxy.$t('modules.kb.pipelineAnswer'), desc: proxy.$t('modules.kb.pipelineAnswerDesc'), icon: SparkleIcon, tone: 'purple' }
])

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

function showDocs () {
  ElMessageBox.alert(
    proxy.$t('modules.kb.docsBody'),
    proxy.$t('modules.kb.docsTitle'),
    {
      confirmButtonText: proxy.$t('modules.kb.docsConfirm'),
      customStyle: { whiteSpace: 'pre-line' }
    }
  )
}

function openTemplateList () {
  router.push({ path: '/graph', query: { subTab: 'knowledgeGraphTemplate' } })
}

function openPanel (command: string) {
  if (command === 'docs') {
    showDocs()
    return
  }
  panel.value = command === 'monitor' ? 'monitor' : 'pipeline'
  panelOpen.value = true
}

function handleTemplateCommand (command: string) {
  if (command === 'download') {
    handleDownloadTemplate()
  }
}

const AVATAR_TONES = ['av-blue', 'av-purple', 'av-green', 'av-orange']

function initialOf (name: string): string {
  return String(name || '?').charAt(0)
    .toUpperCase()
}

function avatarTone (index: number): string {
  return AVATAR_TONES[index % AVATAR_TONES.length]
}

/** 图谱状态码 → 圆点色 + 文案（0 为「已创建」，5 为「已就绪」）：文案来自状态目录。 */
function statusMeta (row: any): { tone: string, text: string } {
  const definition = findStatusDefinition(GRAPH_STATUS_DEFINITIONS, toNum(row.status))
  if (!definition) {
    return { tone: 'muted', text: '--' }
  }
  return { tone: definition.tone, text: proxy.$t(definition.labelKey) }
}

function graphStatusSub (row: any): string {
  const status = toNum(row.status)
  if (status === 5) {
    return proxy.$t('modules.kb.metricReadyFoot')
  }
  if (FAILED_STATUSES.includes(status)) {
    // 状态副文案固定为「请检查数据格式」；详细失败原因放在 title 里，
    // 避免长文案撑宽状态列。
    return proxy.$t('modules.kb.statusCheckDataFormat')
  }
  if (status === 0) {
    return proxy.$t('modules.kb.graphStatusCreatedSub')
  }
  return proxy.$t('modules.kb.dataProcessing')
}

function graphCountSub (row: any): string {
  return Number(row.currentFileCount)
    ? proxy.$t('modules.kb.metricReadyFoot')
    : proxy.$t('modules.kb.statusNoData')
}

function formatDateShort (value: string): string {
  return value ? String(value).slice(0, 16) : '--'
}

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
  return proxy.$t('public.daysAgo', { count: Math.floor(hours / 24) })
}

// 表格高度自适应在原生 table 下不再需要（内容自然高度，整页滚动）。

// 导入文件输入框引用
const importFileInput = ref()


// 排序列表
const orderList = ref<any[]>([])

// 删除对话框引用

// 导入选择对话框相关
const importChoiceDialogVisible = ref(false)
const importChoiceValue = ref<'update' | 'overwrite'>('update') // 默认选择增量更新
// eslint-disable-next-line no-unused-vars -- 函数类型里的形参名不参与运行
let importChoiceResolve: ((choice: 'cancel' | 'overwrite' | 'update') => void) | null = null

// 自动刷新（定时器 + 「用户输入中暂停」）抽到 useListAutoRefresh，与文档知识库列表页共用；
// 这一拍该不该发请求 = 页面可见（窗口在前台 + 两层页签都停在本页）且列表里有构建中的行，
// 与文档知识库列表页的 hasPendingKbaseRows 同一思路：静止时不打空请求。
const listAutoRefresh = useListAutoRefresh({
  shouldRefresh: () => isSurfaceVisible() && hasBuildingGraphRows(),
  // 自动刷新不重置分页，保持当前页面状态；后台静默刷新，不挂转圈。
  // 指标卡也随构建进度更新：状态分布（就绪/进行中/失败）只在指标卡上体现，
  // 只刷列表会出现「卡片永远显示构建中」的陈旧数据。
  onRefresh: async () => {
    await refreshTableData('', true)
    loadOverviewStats()
  }
})

// 用户输入状态：用户正在输入时不打断（标记输入与 1 秒后恢复都在 composable 里）
const { isUserTyping } = listAutoRefresh

/* 列表状态：用原生 table + 本地分页（不经过 el-table）。 */
const rows = ref<any[]>([])
const currentPage = ref(1)
const pageSize = ref(10)
const total = ref(0)
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

function clearSelection () {
  selectedMap.clear()
}

function syncSelectedRows (data: any[]) {
  data.forEach(row => {
    if (row?.id && selectedMap.has(row.id)) {
      selectedMap.set(row.id, { ...row })
    }
  })
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

async function loadRows (): Promise<boolean> {
  try {
    const result = await getTableDataApi(
      { currentPage: currentPage.value, pageSize: pageSize.value }
    )
    const data = Array.isArray(result?.items) ? result.items : []
    syncSelectedRows(data)
    rows.value = data
    total.value = Number(result?.total) || data.length
    return true
  } catch (error) {
    console.error('获取知识图谱列表失败:', error)
    return false
  }
}

/** 刷新：保留搜索 / 筛选 / 页码 / 勾选；失败保留原列表。 */
async function refreshList (): Promise<void> {
  let ok = await loadRows()
  const maxPage = Math.max(1, Math.ceil(total.value / pageSize.value))
  if (ok && currentPage.value > maxPage) {
    currentPage.value = maxPage
    ok = await loadRows()
  }
  loadOverviewStats()
  if (!ok) {
    throw new Error('refresh failed')
  }
}

function onPaginationChange ({ page, size }: { page: number, size: number }) {
  currentPage.value = page
  pageSize.value = size
  refreshTableData()
}

// 搜索功能 - 立即执行，无防抖
function search () {
  isUserTyping.value = false // 搜索完成后标记用户停止输入
  clearSelection()
  refreshTableData('initPage')
}

// 处理用户输入 - 标记用户正在操作
function handleSearchInput () {
  // 标记用户正在输入，1 秒无输入后自动恢复轮询（计时器在 useListAutoRefresh 里）
  listAutoRefresh.noteTypingInput()
}

// 页签头删除后容器按 subTab 二选一渲染：本组件只在「图谱面」挂载，
// subTab 闸门平时恒通过。保留注入与判断是为了 document.hidden
// （拿不到注入值时按「可见」处理，而不是把刷新掐死）。
const outerTab = inject<any>('kbaseActiveTab', null)
const subTab = inject<any>('activeTabName', null)
function isSurfaceVisible (): boolean {
  if (document.hidden) {
    return false
  }
  if (outerTab && outerTab.value !== 'knowledgeGraph') {
    return false
  }
  if (subTab && subTab.value !== 'knowledgeGraph') {
    return false
  }
  return true
}

/**
 * 当前页列表里是否有正在构建的图谱。
 *
 * 只有构建中的行会自己往下走，才值得按 10 秒补刷；全静止时停在界面上不发请求。
 * 计数来自当前页数据（与文档知识库列表页 hasPendingKbaseRows 同口径），
 * 构建中的行在其他页时这一拍不刷，靠翻页/手动刷新兜底。
 */
function hasBuildingGraphRows (): boolean {
  return rows.value.some(row => BUILDING_STATUSES.includes(toNum(row.status)))
}

// 启动自动刷新：定时器生命周期、10 秒节拍与「用户输入暂停」都在 useListAutoRefresh 里，
// 页签可见性闸门在上面创建时以 shouldRefresh 注入
function startAutoRefresh () {
  listAutoRefresh.start()
}

// 停止自动刷新
function stopAutoRefresh () {
  listAutoRefresh.stop()
}

// 获取表格数据的API函数
async function getTableDataApi (params: any) {
  try {
    // 构建请求参数 - 按照接口文档规范
    const requestParams = {
      categories: [10], // 知识库类别：10=知识图谱 // eslint-disable-line no-magic-numbers
      currentPage: params.currentPage || params.pageNum || 1, // 当前页，必须是正整数
      pageSize: params.pageSize || 10, // 一页多少条，必须是正整数 // eslint-disable-line no-magic-numbers
      keyword: searchKey.value || '', // 关键字，非必填
      orderList: orderList.value || [], // 排序列表，非必填
      ...params
    }

    // 状态筛选：后端搜索契约没有 status 字段，取整份结果集后在本地过滤再分页，
    // 保证分页总数是筛选后的真实总数（理由同 Kbase.vue）。
    if (statusFilter.value !== 'all') {
      const allResponse = await knowledgeGraphListApi({
        ...requestParams,
        currentPage: 1,
        pageSize: STATS_PAGE_SIZE
      })
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
    const response = await knowledgeGraphListApi(requestParams)

    // 列表响应为 { items, total, page, pageSize }
    const data = Array.isArray(response)
      ? response
      : (Array.isArray(response?.items) ? response.items : [])
    const total = Array.isArray(response)
      ? data.length
      : Number(response?.total ?? data.length)

    return { items: data, total }
  } catch (error) {
    console.error('获取知识图谱列表失败:', error)
    // proxy.$message.error(`获取知识图谱列表失败: ${error.message || '未知错误'}`)
    // 同 Kbase.vue：不要把失败伪装成「空列表」的成功返回，后台刷新时会误清表。
    // 抛给列表刷新逻辑：前台刷新清表、后台刷新保留原数据。
    throw error
  }
}

// 刷新表格数据。background=true 是后台静默刷新（不改变当前页）。
function refreshTableData (initPage: string | any[] = '', background = false) {
  if (Array.isArray(initPage)) {
    orderList.value = initPage
  }
  if (initPage) {
    currentPage.value = 1
  }
  return loadRows(background)
}

// 新建知识图谱：先走弹窗，提交后带着草稿进整页配置算子/schema
const createOpen = ref(false)
const createModels = ref<{ name: string }[]>([])
const createExistingNames = ref<string[]>([])
const createLimits = ref(fallbackUploadLimits())
let createOptionsLoading = false

async function handleCreateKnowledgeGraph () {
  // 取选项期间按钮可能被连点：同步闸门，避免两次都打开同一个弹窗
  if (createOptionsLoading) {
    return
  }
  createOptionsLoading = true
  try {
    const options = await loadGraphCreateOptions()
    createModels.value = options.models
    createExistingNames.value = options.existingNames
    createLimits.value = options.limits
    createOpen.value = true
  } finally {
    createOptionsLoading = false
  }
}

/** 弹窗内直接建图成功：提示并刷新列表（不再跳整页建图）。 */
function handleGraphCreated () {
  proxy.$message.success(proxy.$t('modules.kb.buildKnowledgeGraphSuccess'))
  refreshTableData('initPage')
  // 指标卡（总数/文档数/健康度）与列表是两条请求，新建后必须一起刷；
  // 只刷列表会出现「列表 1 条、指标卡还是 0」的矛盾显示。
  loadOverviewStats()
}

// 导入知识图谱
function handleImportKnowledgeGraph () {
  if (importFileInput.value) {
    importFileInput.value.click()
  }
}

// 下载模板文件（从 assets/template 目录，根据语言选择对应的模板）
async function handleDownloadTemplate () {
  try {
    // 根据当前语言环境选择模板文件
    const isZh = proxy.$i18n.locale === 'zh'
    const fileName = isZh ? 'import_graph_template_ZH.zip' : 'import_graph_template_EN.zip'

    // 使用 new URL 配合 import.meta.url 获取静态资源文件路径
    // 从当前文件位置（knowledgeGraphTab）到 assets/template 的相对路径
    const templateUrl = new URL(`../../assets/template/${fileName}`, import.meta.url)

    // 使用 fetch 获取文件
    const response = await fetch(templateUrl)
    if (!response.ok) {
      throw new Error('Failed to fetch template file')
    }

    // 将响应转换为 Blob
    const blob = await response.blob()

    // 创建一个临时的 <a> 标签来触发下载
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = fileName
    // 将链接添加到 DOM，触发点击，然后移除
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)

    // 释放 URL 对象
    URL.revokeObjectURL(link.href)
  } catch (error) {
    console.error('下载模板文件失败:', error)
    proxy.$message({
      message: proxy.$t('modules.kb.downloadTemplateFailed'),
      type: 'error'
    })
  }
}

// 处理导入文件选择
async function onImportFileChange (event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) {
    return
  }

  // 验证文件格式
  if (!file.name.toLowerCase().endsWith('.zip')) {
    proxy.$message.error(proxy.$t('modules.kb.invalidFileFormat'))
    return
  }

  // 验证文件大小 (500MB = 500 * 1024 * 1024 bytes)
  const maxSize = 500 * 1024 * 1024
  if (file.size > maxSize) {
    proxy.$message.error(proxy.$t('modules.kb.fileSizeExceededshort'))
    return
  }

  // 解析ZIP文件并处理导入流程
  try {
    await processImportFile(file)
  } catch (error: any) {
    console.error('处理导入文件失败:', error)
    proxy.$message.error(error.message || proxy.$t('modules.kb.importFailed'))
  } finally {
    // 清空文件输入框
    if (importFileInput.value) {
      importFileInput.value.value = ''
    }
  }
}

// 解析ZIP文件并处理导入流程
async function processImportFile (file: File) {
  let loadingInstance = null

  try {
    // 显示加载状态 - 统一使用"数据处理中..."
    loadingInstance = proxy.$loading({
      lock: true,
      text: proxy.$t('modules.kb.dataProcessing'),
      background: 'rgba(0, 0, 0, 0.7)',
      customClass: 'graph-import-loading'
    })

    // 解析ZIP文件
    const zip = new JSZip()
    const zipContent = await zip.loadAsync(file)

    // 检查是否存在desc.json文件
    if (!zipContent.files['desc.json'] && !zipContent.files['desc.json/']) {
      throw new Error(proxy.$t('modules.kb.missingDescJson'))
    }

    // 读取desc.json文件内容
    const descFile = zipContent.files['desc.json'] || zipContent.files['desc.json/']
    const descContent = await descFile.async('string')
    let descData: any = {}

    try {
      descData = JSON.parse(descContent)
    } catch (parseError) {
      throw new Error(proxy.$t('modules.kb.invalidDescJsonFormat'))
    }

    // 不关闭加载状态，继续使用同一个 loading 直到导入完成

    // 检查desc.json中是否存在id字段
    if (!descData.id) {
      // 没有id，直接调用导入接口（传入已有的 loadingInstance）
      await importKnowledgeGraphFile(file, loadingInstance)
      return
    }

    // 有id，处理id：去掉 graph_ 前缀
    let kbId = descData.id
    if (kbId.startsWith('graph_')) {
      kbId = kbId.substring(6) // 去掉 'graph_' 前缀（6个字符）
    }

    // 查询知识库是否存在（继续使用同一个 loading，不重新创建）
    let kbExists = false

    try {
      // skipErrorHandler：成功 resolve 纯 JSON，失败 reject ApiError
      try {
        await getKnowledgeGraphBasicInfoApi(kbId)
        kbExists = true
      } catch (error: any) {
        // 查询失败时按「不存在」处理并继续导入
        kbExists = false
      }
    } catch (error: any) {
      // 如果是0005错误，已经显示错误消息并重新抛出，这里会捕获并终止流程
      if (loadingInstance) {
        loadingInstance.close()
        loadingInstance = null
      }
      throw error
    }

    if (!kbExists) {
      // 知识库不存在，直接调用导入接口（传入已有的 loadingInstance）
      await importKnowledgeGraphFile(file, loadingInstance)
      return
    }

    // 知识库存在，弹出选择框（先关闭 loading，等用户选择后再显示）
    if (loadingInstance) {
      loadingInstance.close()
      loadingInstance = null
    }

    importChoiceValue.value = 'update' // 重置为默认值
    const userChoice = await showImportChoiceDialog()

    // 根据用户选择执行相应操作
    if (userChoice === 'cancel') {
      // 用户取消，结束流程
      return
    } else if (userChoice === 'overwrite') {
      // 全量覆盖：先删除现有知识库，然后导入
      await handleOverwriteImport(file, kbId)
    } else if (userChoice === 'update') {
      // 增量更新：直接调用导入接口
      await importKnowledgeGraphFile(file)
    }

  } catch (error: any) {
    if (loadingInstance) {
      loadingInstance.close()
    }
    throw error
  }
}

// 显示导入选择对话框
function showImportChoiceDialog (): Promise<'cancel' | 'overwrite' | 'update'> {
  return new Promise(resolve => {
    importChoiceResolve = resolve
    importChoiceDialogVisible.value = true
  })
}

// 处理导入选择：取消
function handleImportChoiceCancel () {
  importChoiceDialogVisible.value = false
  if (importChoiceResolve) {
    importChoiceResolve('cancel')
    importChoiceResolve = null
  }
}

// 处理导入选择：确定
function handleImportChoiceConfirm () {
  importChoiceDialogVisible.value = false
  if (importChoiceResolve) {
    // 根据单选框的值返回对应的选择
    importChoiceResolve(importChoiceValue.value)
    importChoiceResolve = null
  }
  // 注意：不在这里清理临时变量，因为实际的导入操作在 processImportFile 中执行
}

// 处理全量覆盖导入
async function handleOverwriteImport (file: File, kbId: string) {
  let loadingInstance = null

  try {
    // 统一使用"数据处理中..."提示
    loadingInstance = proxy.$loading({
      lock: true,
      text: proxy.$t('modules.kb.dataProcessing'),
      background: 'rgba(0, 0, 0, 0.7)',
      customClass: 'graph-import-loading'
    })

    // 先删除现有知识库
    await deleteKnowledgeGraphApi(kbId)

    // 不关闭 loading，继续使用同一个 loading 直到导入完成
    // 然后导入（传入已有的 loadingInstance）
    await importKnowledgeGraphFile(file, loadingInstance)
  } catch (error: any) {
    if (loadingInstance) {
      loadingInstance.close()
    }
    console.error('全量覆盖导入失败:', error)
    const errorMsg = error?.detail || error?.message || proxy.$t('modules.kb.importFailed')
    // 冒号在 overwriteImportFailed 词条值里（zh '：'/ en ': '），此处不再拼「：」
    proxy.$message.error(`${proxy.$t('modules.kb.overwriteImportFailed')}${errorMsg}`)
  }
}

// 执行导入操作
async function importKnowledgeGraphFile (file: File, existingLoadingInstance?: any) {
  let loadingInstance = existingLoadingInstance

  try {
    // 如果没有传入已有的 loadingInstance，则创建新的
    if (!loadingInstance) {
      loadingInstance = proxy.$loading({
        lock: true,
        text: proxy.$t('modules.kb.dataProcessing'),
        background: 'rgba(0, 0, 0, 0.7)',
        customClass: 'graph-import-loading'
      })
    }

    // 调用导入接口
    await importKnowledgeGraphApi(file)

    // 2xx 即成功；错误由拦截器 reject 并提示
    proxy.$message.success(proxy.$t('modules.kb.importSuccess'))
    refreshTableData()
    // 导入受理后 kb_kbase 行已同步创建（状态=入库中），列表与指标卡都要立刻刷；
    // 后续状态由 useListAutoRefresh 的「有构建中行」闸门继续跟进。
    loadOverviewStats()
  } catch (error) {
    console.error('导入知识图谱失败:', error)
  } finally {
    // 确保关闭加载状态
    if (loadingInstance) {
      loadingInstance.close()
    }

    // 清空文件输入框
    if (importFileInput.value) {
      importFileInput.value.value = ''
    }
  }
}

// 知识图谱名称点击
function handleNameClick (row: KnowledgeGraphItem) {
  proxy.$router.push({
    name: 'graph-detail',
    params: {
      id: row.id
    }
  })
}

// 修改
function handleModify (row: KnowledgeGraphItem) {
  router.push({
    name: 'graph-edit',
    params: {
      id: row.id
    }
  })
}

// 导出知识图谱
async function handleExportGraph (row: KnowledgeGraphItem) {
  let loadingInstance: any = null
  try {
    loadingInstance = proxy.$loading({
      lock: true,
      text: proxy.$t('modules.kb.exportingGraph'),
      background: 'rgba(0, 0, 0, 0.6)',
      body: true
    })

    // 调用导出接口
    // axios 拦截器会处理 blob 响应：
    // - 如果 res.data.type === 'application/json'，会解析为 JSON 并返回 res.data
    // - 否则直接返回 res 对象（res.data 是 Blob）
    const response = await exportGraphKnowledgeBaseApi(row.id)

    // 拦截器对 blob 成功直接返回 Blob；错误（problem+json）会 reject 到 catch
    const blobData = response instanceof Blob
      ? response
      : (response?.data instanceof Blob ? response.data : null)
    if (!blobData) {
      throw new Error(proxy.$t('modules.kb.exportGraphFailed'))
    }

    // 创建下载链接
    const url = URL.createObjectURL(blobData)
    const link = document.createElement('a')
    link.href = url

    // 设置文件名：graph_{kbId}_{timestamp}.zip
    const timestamp = new Date().getTime()
    const fileName = `graph_${row.id}_${timestamp}.zip`
    link.download = fileName

    // 触发下载
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)

    // 释放 URL
    URL.revokeObjectURL(url)

    proxy.$message.success(proxy.$t('modules.kb.exportGraphSuccess'))
  } catch (error: any) {
    console.error('导出知识图谱失败:', error)
    // 错误消息已在 axios 拦截器中显示（如果是 JSON 错误响应）
    // 如果是其他错误，显示错误消息
    if (error.message && !error.message.includes('exportGraphFailed')) {
      proxy.$message.error(error.message)
    }
  } finally {
    if (loadingInstance) {
      loadingInstance.close()
    }
  }
}

// 删除知识图谱（统一确认弹窗）
async function deleteKnowledgeGraphHandle (row: KnowledgeGraphItem) {
  const confirmed = await requestDeletion({
    resourceType: proxy.$t('modules.kb.resourceGraphKb'),
    warning: proxy.$t('modules.kb.deleteGraphWarning'),
    description: proxy.$t('modules.kb.deleteGraphDescription'),
    items: [{
      id: row.id,
      name: row.name,
      meta: row.id,
      letter: initialOf(row.name),
      av: avatarTone(0),
      tag: proxy.$t('modules.kb.tagGraph')
    }],
    detail: proxy.$t('modules.kb.deleteDetail', { docs: Number(row.currentFileCount) || 0 }),
    hint: proxy.$t('modules.kb.deleteHint')
  })
  if (!confirmed) {
    return
  }
  try {
    await deleteKnowledgeGraphApi(row.id)
    selectedMap.delete(row.id)
    proxy.$message.success(proxy.$t('public.deleteSuccess'))
    await refreshAfterMutation(1)
  } catch {
    // 拦截器已提示（含绑定工作流的 409）
  }
}

async function refreshAfterMutation (deletedCount = 0) {
  const remaining = Math.max(0, total.value - deletedCount)
  const maxPage = Math.max(1, Math.ceil(remaining / pageSize.value))
  if (currentPage.value > maxPage) {
    currentPage.value = maxPage
  }
  await refreshTableData()
  loadOverviewStats()
}

async function removeSelectedGraphs () {
  const targets = [...selectedRows.value].filter(row => isDeleteEnabled(toNum(row.status)))
  const skipped = selectedRows.value.length - targets.length
  if (!targets.length) {
    proxy.$message.warning(proxy.$t('modules.kb.deleteGraphBlocked'))
    return
  }
  if (skipped > 0) {
    proxy.$message.warning(proxy.$t('modules.kb.deleteGraphBatchSkipped', { count: skipped }))
  }
  const confirmed = await requestDeletion({
    resourceType: proxy.$t('modules.kb.resourceGraphKb'),
    title: proxy.$t('modules.kb.deleteGraphBatchTitle'),
    warning: proxy.$t('modules.kb.deleteGraphWarning'),
    description: proxy.$t('modules.kb.deleteGraphDescription'),
    items: targets.map(row => ({
      id: row.id,
      name: row.name,
      meta: row.id,
      letter: initialOf(row.name),
      av: avatarTone(0),
      tag: proxy.$t('modules.kb.tagGraph')
    })),
    detail: proxy.$t('modules.kb.deleteDetail', {
      docs: targets.reduce((sum, row) => sum + (Number(row.currentFileCount) || 0), 0)
    }),
    hint: proxy.$t('modules.kb.deleteHint')
  })
  if (!confirmed) {
    return
  }
  const results = await Promise.allSettled(targets.map(row => deleteKnowledgeGraphApi(row.id)))
  const success = results.filter(result => result.status === 'fulfilled').length
  const failed = targets.length - success
  results.forEach((result, index) => {
    if (result.status === 'fulfilled') {
      selectedMap.delete(targets[index].id)
    }
  })
  if (success) {
    proxy.$message.success(proxy.$t('modules.kb.deleteGraphBatchSuccess', { count: success }))
  }
  if (failed) {
    proxy.$message.error(proxy.$t('modules.kb.deleteBatchPartial', { success, failed }))
  }
  await refreshAfterMutation(success)
}


// 监听搜索关键词变化 - 立即触发查询
watch(searchKey, (newValue, oldValue) => {
  if (newValue !== oldValue) {
    // 立即触发搜索查询
    search()
    // 重新启动自动刷新计时器
    stopAutoRefresh()
    startAutoRefresh()
  }
})

// 组件挂载时刷新表格数据并启动自动刷新
onMounted(() => {
  refreshTableData()
  startAutoRefresh()
  loadOverviewStats()
  // 表格高度自适应：挂载后量一次并开始盯尺寸变化（本组件在子页签里，
  // 隐藏时量不到尺寸，等可见时 ResizeObserver 会补量）
})

// 页签切回本页时补一次静默刷新：隐藏期间不轮询，切回来要立刻看到最新数据
watch(
  [() => outerTab && outerTab.value, () => subTab && subTab.value],
  () => {
    if (isSurfaceVisible()) {
      refreshTableData('', true)
    }
  }
)

// 组件卸载时清理定时器
onUnmounted(() => {
  // composable 的 stop + 「用户停止输入」计时器一起清
  listAutoRefresh.dispose()
  // 摘掉表格高度的 ResizeObserver
})

</script>

<style lang="less" scoped>
/* 导入选择对话框样式 */
:deep(.import-choice-dialog) {
  .el-dialog__body {
    padding: 30px 24px;
  }
}

.dialog-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 10px 0;
}

.dialog-message {
  margin: 0 0 24px 0;
  font-size: 14px;
  color: var(--rs-text-2);
  text-align: center;
  line-height: 1.5;
}

.radio-group-container {
  display: flex;
  justify-content: center;
  width: 100%;
  margin-bottom: 10px;
}

.import-radio-group {
  display: flex;
  gap: 40px;
  justify-content: center;
}

.import-radio {
  margin: 0;

  :deep(.el-radio__label) {
    font-size: 14px;
    color: var(--rs-text);
    padding-left: 8px;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  :deep(.el-radio__input.is-checked .el-radio__inner) {
    background-color: var(--rs-primary);
    border-color: var(--rs-primary);
  }

  :deep(.el-radio__input.is-checked + .el-radio__label) {
    color: var(--rs-primary);
  }
}

.import-radio-tip-icon {
  color: var(--rs-text-3);
  cursor: help;
  font-size: 16px;
  vertical-align: middle;
  margin-left: 4px;

  &:hover {
    color: var(--rs-primary);
  }
}

.dialog-footer {
  display: flex;
  justify-content: center;
  gap: 12px;
  padding: 0;
}

</style>

<style lang="less">
// loading 服务挂载在 body 上，scoped 样式够不到；这里只作用于本页显式传入的
// graph-import-loading 自定义类，不再覆盖全局 .el-loading-mask / .vn-loading-mask。
.graph-import-loading {
  .el-loading-text,
  .vn-loading-text {
    color: #fff !important;
    font-size: 14px !important;
    margin-top: 12px !important;
    display: block !important;
    visibility: visible !important;
    opacity: 1 !important;
    line-height: 1.5 !important;
    text-align: center !important;
    position: relative !important;
    z-index: 1 !important;
  }

  .el-loading-spinner,
  .vn-loading-spinner {
    margin-top: -25px;

    .circular {
      width: 42px;
      height: 42px;
    }
  }
}

// 更具体的选择器，确保文字显示
.graph-import-loading.el-loading-mask .el-loading-text,
.graph-import-loading.vn-loading-mask .vn-loading-text,
.graph-import-loading .el-loading-text,
.graph-import-loading .vn-loading-text {
  color: #fff !important;
  font-size: 14px !important;
  margin-top: 12px !important;
  display: block !important;
  visibility: visible !important;
  opacity: 1 !important;
  line-height: 1.5 !important;
  text-align: center !important;
}
</style>

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
    .monitor-delta { color: var(--rs-success); }
</style>

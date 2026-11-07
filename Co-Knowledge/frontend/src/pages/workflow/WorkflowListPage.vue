<template>
  <AppPage class="management-page flow-page">
    <div class="page-inner">
      <PageHeader
        :title="$t('ragFlow.ragWorkflow')"
        :subtitle="$t('modules.workflow.pageSubtitle')"
        :icon="WorkflowIcon"
      />

      <div class="toolbar">
        <div class="toolbar-left">
          <el-button type="primary" @click="openCreateDialog">
            <Plus />
            {{ $t('ragFlow.createWorkflow') }}
          </el-button>
          <el-button @click="openUsageDocs">
            <Reading />
            {{ $t('modules.kb.viewDocs') }}
          </el-button>
        </div>
        <div class="toolbar-right">
          <TableRefreshButton :label="$t('modules.workflow.refreshList')" :refresh="refreshWorkflowList" />
          <el-input
            v-model.trim="searchKey"
            clearable
            class="search-field"
            :placeholder="$t('modules.workflow.searchPlaceholder')"
            :prefix-icon="Search"
            @input="handleSearchInput"
            @clear="handleSearchInput"
          />
          <el-select
            v-model="typeFilter"
            :aria-label="$t('modules.workflow.allTypes')"
            style="width: 130px"
          >
            <el-option :label="$t('modules.workflow.allTypes')" value="all" />
            <el-option :label="$t('modules.workflow.graphRetrieval')" value="graph" />
            <el-option :label="$t('ragFlow.mixWorkflow')" value="Blended" />
            <el-option :label="$t('ragFlow.sequenceWorkflow')" value="Sequential" />
            <el-option :label="$t('ragFlow.conditionWorkflow')" value="Conditional" />
          </el-select>
          <el-select
            v-model="statusFilter"
            :aria-label="$t('modules.workflow.allStatus')"
            style="width: 130px"
          >
            <el-option :label="$t('modules.workflow.allStatus')" value="all" />
            <el-option :label="$t('modules.workflow.published')" value="published" />
            <el-option :label="$t('modules.workflow.unpublished')" value="unpublished" />
          </el-select>
          <el-select
            v-model="sortBy"
            :aria-label="$t('modules.workflow.sortByTime')"
            style="width: 160px"
          >
            <template #prefix>
              <Sort class="workflow-sort-icon" />
            </template>
            <el-option :label="$t('modules.workflow.sortByTime')" value="time" />
            <el-option :label="$t('modules.workflow.sortByName')" value="name" />
          </el-select>
        </div>
      </div>

      <AppEmpty
        v-if="loadError"
        state="error"
        :description="loadErrorText"
        @retry="getWorkflowList"
      />

      <template v-else>
        <ListSelectionBar :count="selectedRows.length" @clear="clearSelection">
          <el-button link type="primary" @click="batchWorkflows('publish')">
            {{ $t('modules.workflow.batchPublish') }}
          </el-button>
          <el-button link @click="batchWorkflows('unpublish')">
            {{ $t('modules.workflow.batchUnpublish') }}
          </el-button>
          <el-button class="danger-action" link type="danger" @click="batchWorkflows('delete')">
            <Delete />{{ $t('modules.workflow.batchDelete') }}
          </el-button>
        </ListSelectionBar>
        <div v-loading="loading" class="table-card">
          <table class="list-table flow-table">
            <thead>
              <tr>
                <th class="check-cell">
                  <input
                    type="checkbox"
                    :aria-label="$t('modules.workflow.selectAllPage')"
                    :checked="allSelected"
                    @change="toggleAll($event.target.checked)"
                  >
                </th>
                <th>{{ $t('modules.workflow.knowledgeRetrievalName') }}</th>
                <th>{{ $t('modules.workflow.preview') }}</th>
                <th>{{ $t('modules.workflow.knowledgeSourceTemplate') }}</th>
                <th>{{ $t('public.creator') }}</th>
                <th>{{ $t('ragFlow.publishStatus') }}</th>
                <th>{{ $t('modules.kb.updateTimeColumn') }}</th>
                <th>{{ $t('public.operate') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in pagedList" :key="row.workFlowId">
                <td class="check-cell">
                  <input
                    v-model="row.selected"
                    type="checkbox"
                    :aria-label="$t('modules.workflow.selectWorkflow', { name: row.name || '' })"
                  >
                </td>
                <td>
                  <div class="entity">
                    <div :class="['avatar-square', avatarTone(index)]">
                      {{ initialOf(row.name) }}
                    </div>
                    <div>
                      <a
                        :key="`${row.name}_${row.workFlowId}`"
                        class="entity-title entity-link"
                        @click="setFlow(row)"
                      >{{ row.name || '--' }}</a>
                      <div class="entity-sub nowrap">
                        ID: {{ row.workFlowId }}
                        <button
                          class="icon-button copy"
                          :aria-label="$t('modules.workflow.copyId')"
                          @click.stop="copyWorkflowId(row.workFlowId)"
                        >
                          <CopyDocument />
                        </button>
                      </div>
                    </div>
                  </div>
                </td>
                <td>
                  <div class="mini-flow">
                    <template v-for="(step, stepIndex) in flowPreview(row)" :key="`${step.label}-${stepIndex}`">
                      <Right v-if="stepIndex" class="flow-arrow" />
                      <span :class="['flow-chip', step.tone]">
                        <component :is="step.icon" />
                        {{ step.label }}
                      </span>
                    </template>
                  </div>
                </td>
                <td>
                  <div class="flow-source-types">
                    <span v-for="kind in workflowSourceKinds(row)" :key="kind" :class="['tag-soft', sourceKindOf(kind).tone]">
                      <component :is="sourceKindOf(kind).icon" />{{ $t(sourceKindOf(kind).labelKey) }}
                    </span>
                  </div>
                  <div class="entity-sub">{{ workflowTypeLabel(row) }}</div>
                </td>
                <td>{{ row.createdBy || '--' }}</td>
                <td class="nowrap">
                  <span class="flow-status-inline">
                    <span :class="['status-dot', row.publishType === 0 ? 'muted' : 'success']" />
                    <b v-if="row.publishType !== 0">{{ $t('modules.workflow.published') }}</b>
                    <span v-else>{{ $t('modules.workflow.unpublished') }}</span>
                    <el-tooltip
                      v-if="row.publishType === 2"
                      effect="light"
                      :content="$t('ragFlow.published_modify')"
                      placement="top"
                    >
                      <el-icon class="workflow-status__tip">
                        <HelpTip />
                      </el-icon>
                    </el-tooltip>
                  </span>
                </td>
                <td class="nowrap">
                  {{ formatDateShort(row.lastUpdatedDate || row.createdDate) }}
                  <div class="entity-sub">
                    {{ relativeTime(row.lastUpdatedDate || row.createdDate) }}
                  </div>
                </td>
                <td>
                  <el-dropdown
                    trigger="click"
                    @command="command => action(command, row)"
                  >
                    <button class="icon-button" :aria-label="(row.name || '') + ' ' + $t('public.operate')">
                      <MoreFilled class="more-icon" />
                    </button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="export">
                          <Download />
                          {{ proxy.$t('public.export') }}
                        </el-dropdown-item>
                        <el-dropdown-item command="edit">
                          <Edit />
                          {{ proxy.$t('public.modify') }}
                        </el-dropdown-item>
                        <!-- 发布与取消发布是两个动作，不能合并成一个 toggle：
                             已发布的工作流改完草稿后必须能**重新发布**（生成新快照），
                             否则对话测试会继续使用发布前的快照。 -->
                        <el-dropdown-item
                          v-if="Number(row.publishType) === PUBLISH_TYPE.UNPUBLISHED"
                          command="publish"
                          :disabled="isWorkflowPublishing(row.workFlowId)"
                        >
                          <Upload />
                          {{ $t('public.publish') }}
                        </el-dropdown-item>
                        <el-dropdown-item
                          v-else
                          command="republish"
                          :disabled="isWorkflowPublishing(row.workFlowId)"
                        >
                          <Upload />
                          {{ $t('modules.workflow.republish') }}
                        </el-dropdown-item>
                        <el-dropdown-item
                          v-if="Number(row.publishType) !== PUBLISH_TYPE.UNPUBLISHED"
                          command="unpublish"
                          :disabled="isWorkflowPublishing(row.workFlowId)"
                        >
                          <VideoPause />
                          {{ $t('modules.workflow.unpublish') }}
                        </el-dropdown-item>
                        <el-dropdown-item class="danger-menu-item" command="delete" divided>
                          <Delete />
                          {{ proxy.$t('public.delete') }}
                        </el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </td>
              </tr>
              <tr v-if="!pagedList.length">
                <td colspan="8" class="empty-row">
                  {{ $t('public.noData') }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <TablePagination
          :total="filteredRecords"
          :page="currentPage"
          :size="pageSize"
          jumper
          @change="onPaginationChange"
        />
      </template>
    </div>

    <!-- 新建走弹窗；「重命名」仍复用 CreateWorkflow 的编辑态 -->
    <CreateWorkflowDialog
      v-model="createOpen"
      :existing="workflowList"
      :knowledge-options="workflowKbOptions"
      :submit-handler="createWorkflowWithDialog"
    />
    <CreateWorkflow ref="createWorkflowRef" @refresh="getWorkflowList" />
  </AppPage>
</template>
<script setup lang="ts">
import { computed, ref, watch, getCurrentInstance, onMounted } from 'vue';
import { debounce } from 'lodash';
import {
  getFlowList, createFlow, deleteFlowApi, exportWorkFlow, publishWorkFlow, unpublishWorkFlow, getAllKBList
} from '@/features/workflow/api/workflow';
import CreateWorkflow from '@/features/workflow/CreateWorkflow.vue'
import CreateWorkflowDialog from '@/features/workflow/components/CreateWorkflowDialog.vue'
import { v4 as uuidv4 } from 'uuid'
import { download } from '@/shared/lib/utils';
import { onceConfirm } from '@/shared/lib/confirm-once';
import { HelpTip, Plus, Reading, Upload, VideoPause } from '@/shared/lib/icons';
import { WorkflowIcon } from '@/shared/ui/icons';
import { ElMessageBox } from 'element-plus';
import TableRefreshButton from '@/shared/ui/TableRefreshButton.vue';
import ListSelectionBar from '@/shared/ui/ListSelectionBar.vue';
import { requestDeletion } from '@/shared/composables/deletion';
import AppPage from '@/shared/ui/AppPage.vue';
import PageHeader from '@/shared/ui/reference/PageHeader.vue';
import TablePagination from '@/shared/ui/reference/TablePagination.vue';
import AppEmpty from '@/shared/ui/AppEmpty.vue';
import {
  Search,
  Sort,
  Right,
  MoreFilled,
  CopyDocument,
  Download,
  Edit,
  Delete,
  ChatDotRound,
  Share,
  Coin,
  Histogram,
  Filter,
  Document
} from '@/shared/lib/icons';
import { copyTextWithToast } from '@/shared/lib/copy-with-toast';
import { matchesWorkflowType, sourceKindMeta, workflowDisplayType, workflowSourceKinds } from '@/features/workflow/lib/retrievalSources';
import { isBatchPublishTarget, PUBLISH_TYPE } from '@/features/workflow/lib/publishActions';

const { proxy } = getCurrentInstance() as any;
const workflowList = ref([])
const currentPage = ref(1)
const pageSize = ref(10)
const loading = ref(false);
const loadError = ref<any>(null);
const loadErrorText = computed(() => proxy.$t('public.loadFailedTip'));

/* ── 工具条筛选（新 UX） ──────────────────────────────────────────
 * 搜索走后端（/workflow?name=）；类型 / 发布状态 / 排序在本地完成。
 * 工作流数量很小，这里改为「一次性取全量（≤500）→ 本地过滤 → 本地分页」，
 * 分页总数始终等于筛选后的真实条数。
 */
const searchKey = ref('')
const typeFilter = ref('all')
const statusFilter = ref('all')
const sortBy = ref('time')
const ALL_PAGE_SIZE = 500

const selectedRows = computed(() => workflowList.value.filter((row: any) => row.selected))
const allSelected = computed(() => pagedList.value.length > 0 && pagedList.value.every((row: any) => row.selected))

function toggleAll (checked: boolean) {
  const selected = new Set(pagedList.value.map((row: any) => row.workFlowId))
  workflowList.value = workflowList.value.map((row: any) => (
    selected.has(row.workFlowId) ? { ...row, selected: checked } : row
  ))
}

function clearSelection () {
  workflowList.value = workflowList.value.map((row: any) => (
    row.selected ? { ...row, selected: false } : row
  ))
}

const filteredList = computed(() => {
  let rows = workflowList.value.slice()
  if (typeFilter.value !== 'all') {
    // 类型下拉筛的是**列表上显示的那个类型**：只绑图谱库的 Blended 工作流
    // 展示为「图谱检索」，就必须只出现在「图谱检索」里（见 matchesWorkflowType）。
    rows = rows.filter(row => matchesWorkflowType(row, typeFilter.value))
  }
  if (statusFilter.value === 'published') {
    rows = rows.filter(row => Number(row.publishType) !== 0)
  } else if (statusFilter.value === 'unpublished') {
    rows = rows.filter(row => Number(row.publishType) === 0)
  }
  if (sortBy.value === 'name') {
    rows.sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')))
  } else {
    rows.sort((a, b) => String(b.lastUpdatedDate || b.createdDate || '')
      .localeCompare(String(a.lastUpdatedDate || a.createdDate || '')))
  }
  return rows
})

const filteredRecords = computed(() => filteredList.value.length)

const pagedList = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredList.value.slice(start, start + pageSize.value)
})

function resetPage () {
  currentPage.value = 1
}

watch([typeFilter, statusFilter, sortBy], () => {
  resetPage()
  clearSelection()
})

/** 搜索防抖（300ms）：输入即筛，也不打断输入。 */
const search = debounce(() => {
  resetPage()
  getWorkflowList()
}, 300)

function handleSearchInput () {
  clearSelection()
  search()
}

function onPaginationChange ({ page, size }: { page: number, size: number }) {
  currentPage.value = page
  pageSize.value = size
}

function copyWorkflowId (id: string) {
  // 复制成功/失败统一由 copyTextWithToast 提示（所有复制入口同一套反馈）。
  return copyTextWithToast(id)
}

/* ── 工作流预览（按模板 + 绑定来源给出代表性的链路步骤） ─────────
 * - 顺序检索：**一个检索步骤**。画布播种时所有绑定的库都写进同一个检索器算子，
 *   运行时也是一次向量检索（整组库名一起传）—— 不能按库数逐个画，否则绑 5 个库会出
 *   5 个重复的 Vector Search。
 * - 混合检索：图谱库走 Graph Search，文档库走 Hybrid Search；
 * - 条件检索：先条件过滤，再按上面的规则取检索节点。
 * 没有绑定信息时回落到模板的代表性步骤。
 */
function flowPreview (row: any) {
  const normal = Array.isArray(row.kbPkIds) ? row.kbPkIds : []
  const graph = Array.isArray(row.graphKbPkIds) ? row.graphKbPkIds : []
  const steps = [{ label: 'Query', icon: ChatDotRound, tone: 'blue' }]
  if (row.template === 'Conditional') {
    steps.push({ label: '条件过滤', icon: Filter, tone: 'blue' })
  }
  if (graph.length) {
    steps.push({ label: 'Graph Search', icon: Share, tone: 'purple' })
  }
  if (normal.length || !graph.length) {
    steps.push({
      label: row.template === 'Sequential' ? 'Vector Search' : 'Hybrid Search',
      icon: row.template === 'Sequential' ? Coin : Share,
      tone: 'purple'
    })
  }
  if (row.knowledgeType !== 'database') {
    steps.push({ label: 'Rerank', icon: Histogram, tone: 'green' })
  }
  return steps
}

const AVATAR_TONES = ['av-blue', 'av-purple', 'av-green', 'av-orange']

function initialOf (name: string): string {
  return String(name || '?').charAt(0)
    .toUpperCase()
}

/** 按行序轮换头像色（蓝/紫/绿/橙）。 */
function avatarTone (index: number): string {
  return AVATAR_TONES[index % AVATAR_TONES.length]
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
// 添加发布状态管理：使用 Set 来管理正在发布的工作流ID
const publishingWorkflowIds = ref(new Set())

onMounted(() => {
  getWorkflowList()
})


/** 「查看使用文档」：静态上手步骤。 */
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

/** 翻页防御上限：后端 total 异常时不至于无限请求 */
const MAX_FETCH_PAGES = 20

/**
 * 取全量（工作流数量很小）：类型 / 发布状态 / 排序 / 分页都在本地完成，
 * 分页总数与筛选结果永远一致。
 *
 * 不能只取第一个 500 页：超过 500 条时工作流会被静默丢掉。首屏拿不到 total
 * 就先取一页，再按 total 补齐（后端若对 size 有上限也靠 items 累计判断）。
 */
async function fetchAllWorkflowItems (keyword: string): Promise<any[]> {
  const items: any[] = []
  let total = Infinity
  let page = 1
  while (items.length < total && page <= MAX_FETCH_PAGES) {
    const res = await getFlowList(page, ALL_PAGE_SIZE, keyword)
    const chunk = res?.items || []
    total = Number(res?.total ?? chunk.length)
    if (!chunk.length) {
      break
    }
    items.push(...chunk)
    page += 1
  }
  return items
}

async function getWorkflowList (): Promise<boolean> {
  loading.value = true;
  loadError.value = null;
  try {
    const selectedIds = new Set(
      workflowList.value.filter((row: any) => row.selected).map((row: any) => row.workFlowId)
    )
    const items = await fetchAllWorkflowItems(searchKey.value || '');
    workflowList.value = items.map((row: any) => ({
      ...row,
      selected: selectedIds.has(row.workFlowId)
    }));
    return true
  } catch (error: any) {
    // 首页取数失败时展示可重试的错误态；已有数据时保留列表（与 TableGroup 同一语义）
    if (!workflowList.value.length) {
      loadError.value = error;
    }
    return false
  } finally {
    loading.value = false;
  }
}

/** 刷新：保留搜索 / 筛选 / 排序 / 页码 / 勾选；失败保留旧列表。 */
async function refreshWorkflowList (): Promise<void> {
  const ok = await getWorkflowList()
  const maxPage = Math.max(1, Math.ceil(filteredRecords.value / pageSize.value))
  if (ok && currentPage.value > maxPage) {
    currentPage.value = maxPage
  }
  if (!ok) {
    throw new Error('refresh failed')
  }
}

function getWorkflowTemplateMap (template) {
  let mapper = {
    Sequential: proxy.$t('ragFlow.sequenceWorkflow'),
    Conditional: proxy.$t('ragFlow.conditionWorkflow'),
    Blended: proxy.$t('ragFlow.mixWorkflow')
  }
  return mapper[template]
}

/* 知识来源类型标签（文档 / 图谱 / 数据库）+ 展示用检索类型。
 * 只绑图谱库的工作流展示为「图谱检索」，不再笼统显示成「混合检索」。 */
const SOURCE_KIND_ICONS = { knowledge: Document, graph: Share, database: Coin }

function sourceKindOf (kind: string) {
  return { ...sourceKindMeta(kind), icon: SOURCE_KIND_ICONS[kind] || Document }
}

function workflowTypeLabel (row: any) {
  if (workflowDisplayType(row) === 'graph') {
    return proxy.$t('modules.workflow.graphRetrieval')
  }
  return getWorkflowTemplateMap(row.template) || '--'
}

function createWorkflow (type = 'create', workflowObj = {}) {
  if (type === 'create') {
    openCreateDialog()
  } else {
    proxy.$refs.createWorkflowRef.openDialog(workflowObj)
  }
}

/* ── 新建知识检索弹窗 ───────────────────────────────────────────
 * 来源下拉取自 `/workflow/allStatusKbase`（与画布同一份数据源）：
 * running = 已发布（7/8），dev = 未发布。没有资产中心，dev 也必须可选，
 * 否则新建弹窗里永远选不到库。
 */
const createOpen = ref(false)
const workflowKbOptions = ref<any[]>([])
const workflowKbRaw = new Map<string, any>()

async function loadWorkflowKbOptions () {
  try {
    const response: any = await getAllKBList()
    const running = Array.isArray(response?.running) ? response.running : []
    const dev = Array.isArray(response?.dev) ? response.dev : []
    const toOption = (item: any, group: string) => {
      const id = item.assetId || item.tableName || item.name
      workflowKbRaw.set(id, { ...item, __group: group })
      return {
        id,
        name: item.name || item.tableName || id,
        statusLabel: group === 'running'
          ? proxy.$t('modules.kb.filterReady')
          : proxy.$t('modules.workflow.unpublished'),
        // tableName 含 graph = 图谱库
        isGraph: /graph/i.test(String(item.tableName || '')),
        isStruct: item.type === 'struct_knowledge'
      }
    }
    workflowKbOptions.value = [
      ...running.map(item => toOption(item, 'running')),
      ...dev.map(item => toOption(item, 'dev'))
    ]
  } catch {
    workflowKbOptions.value = []
  }
}

function openCreateDialog () {
  createOpen.value = true
  loadWorkflowKbOptions()
}

/** 弹窗提交：真实建流（绑定所选知识库），成功后进入画布。 */
async function createWorkflowWithDialog (payload: any) {
  const boundInfo: Record<string, any[]> = { running: [], dev: [] }
  for (const id of payload.sourceIds) {
    const raw = workflowKbRaw.get(id)
    if (!raw) {
      continue
    }
    const { __group, ...item } = raw
    boundInfo[__group].push(item)
  }
  // 与 CreateWorkflow 同一套 id 生成：uuid 去横线取前 4 位。
  // 不用 crypto.randomUUID：它只在安全上下文可用，http 部署会直接抛错。
  const workFlowId = `RAG_Workflow_${uuidv4().replace(/-/g, '').slice(0, 4)}`
  await createFlow({
    name: payload.name,
    workFlowId,
    template: payload.template,
    knowledgeType: 'knowledgeBase',
    description: payload.description,
    boundInfo
  })
  proxy.$message.success(proxy.$t('modules.studioDialogs.createWorkflow.createSuccess'))
  await getWorkflowList()
  proxy.$router.push({ name: 'flow-detail', params: { id: workFlowId } })
}

function exportFlow (row) {
  exportWorkFlow(row.workFlowId).then(res => {
    download(res, '', '')
  })
}

function action (command: string, row: any) {
  if (command === 'export') {
    exportFlow(row)
  } else if (command === 'edit') {
    createWorkflow('update', row)
  } else if (command === 'publish' || command === 'republish') {
    // 未发布 → 首次发布；已发布（含「发布后修改」）→ 重新发布新快照。
    // 两个动作分开，不再用同一项 toggle：已发布后改草稿必须能重新发布，
    // 否则对话测试永远跑旧快照。
    publishFlow(row)
  } else if (command === 'unpublish') {
    unpublishFlow(row)
  } else if (command === 'delete') {
    deleteFlow(row)
  }
}

/** 取消发布（保留历史快照，只把 publishType 置 0）。 */
async function unpublishFlow (scope: any) {
  // onceConfirm：连点会把同一个确认框叠几层，同一刻只留一个
  const ok = await onceConfirm(() => proxy.$confirm(
    proxy.$t('modules.workflow.unpublishConfirm', { name: scope.name }),
    proxy.$t('messageBox.tip'),
    {
      confirmButtonText: proxy.$t('messageBox.confirm'),
      cancelButtonText: proxy.$t('messageBox.cancel'),
      type: 'warning'
    }
  ))
  if (!ok) {
    return
  }
  try {
    await unpublishWorkFlow(scope.workFlowId)
    proxy.$message.success(proxy.$t('modules.workflow.unpublishSuccess'))
    await getWorkflowList()
  } catch {
    // 拦截器已提示
  }
}

function publishFlow (scope) {
  const workflowId = scope.workFlowId

  // 如果当前工作流正在发布中，直接返回
  if (publishingWorkflowIds.value.has(workflowId)) {
    return
  }

  // 发布一律先确认：
  //   * 未发布过（publishType 0）→ 发布后**下游 Agent 就能引用**这个工作流，
  //     误触的代价是外部可见状态变化，不是本地操作；
  //   * 已发布过（1/2）→ 等于**追加一个新版本快照**（后端有意如此：每次发布插入
  //     不可变快照并把 version+1，线上引用
  //     可能随之切版本。
  const isRepublish = Number(scope.publishType) !== 0
  // onceConfirm：连点菜单会把同一个确认框叠几层
  onceConfirm(() => proxy.$confirm(
    isRepublish
      ? proxy.$t('ragFlow.republishConfirm', { name: scope.name })
      : proxy.$t('ragFlow.publishConfirm', { name: scope.name }),
    proxy.$t('messageBox.tip'),
    {
      confirmButtonText: proxy.$t('messageBox.confirm'),
      cancelButtonText: proxy.$t('messageBox.cancel'),
      type: 'warning'
    }
  )).then(ok => {
    if (ok) {
      doPublishWorkflow(scope)
    }
  })
}

function doPublishWorkflow (scope) {
  const workflowId = scope.workFlowId

  // 将当前工作流ID添加到发布中集合
  publishingWorkflowIds.value.add(workflowId)

  publishWorkFlow(scope.workFlowId).then(() => {
    proxy.$message({
      type: 'success',
      message: proxy.$t('ragFlow.publishWorkflowSuccessTip')
    });
    // 发布成功后刷新工作流列表
    getWorkflowList()
  })
    .catch(error => {
      // 发布失败时也要重置状态
      console.error('发布工作流失败:', error)
    })
    .finally(() => {
      // 1秒后从发布中集合移除该工作流ID
      setTimeout(() => {
        publishingWorkflowIds.value.delete(workflowId)
      }, 1000)
    })
}

// 添加一个计算函数来判断某个工作流是否正在发布
function isWorkflowPublishing (workflowId) {
  return publishingWorkflowIds.value.has(workflowId)
}

/** 删除统一确认弹窗（影响说明 + 对象信息 + 4 位确认码）。 */
async function deleteFlow (scope: any) {
  const confirmed = await requestDeletion({
    resourceType: proxy.$t('modules.workflow.resourceWorkflow'),
    warning: Number(scope.publishType) !== 0
      ? proxy.$t('modules.workflow.deletePublishedWarning')
      : proxy.$t('modules.workflow.deleteWarning'),
    description: proxy.$t('modules.workflow.deleteDescription'),
    items: [{
      id: scope.workFlowId,
      name: scope.name,
      meta: scope.workFlowId,
      letter: initialOf(scope.name),
      av: avatarTone(0),
      tag: getWorkflowTemplateMap(scope.template) || ''
    }],
    note: Number(scope.publishType) !== 0 ? proxy.$t('modules.workflow.deletePublishedNote') : '',
    hint: proxy.$t('modules.workflow.deleteHint')
  })
  if (!confirmed) {
    return
  }
  try {
    await deleteFlowApi(scope.workFlowId)
    proxy.$message.success(proxy.$t('messageBox.deleteSuccess'))
    await refreshAfterMutation(1)
  } catch {
    // 拦截器已提示
  }
}

/** 批量：发布 / 取消发布 / 删除（全部基于现有单条接口扇出）。 */
async function batchWorkflows (command: string) {
  const allTargets = [...selectedRows.value]
  if (!allTargets.length) {
    return
  }
  if (command === 'delete') {
    const confirmed = await requestDeletion({
      resourceType: proxy.$t('modules.workflow.resourceWorkflow'),
      title: proxy.$t('modules.workflow.batchDeleteTitle'),
      warning: proxy.$t('modules.workflow.batchDeleteWarning'),
      description: proxy.$t('modules.workflow.deleteDescription'),
      items: allTargets.map(row => ({
        id: row.workFlowId,
        name: row.name,
        meta: row.workFlowId,
        letter: initialOf(row.name),
        av: avatarTone(0),
        tag: getWorkflowTemplateMap(row.template) || ''
      })),
      hint: proxy.$t('modules.workflow.deleteHint')
    })
    if (!confirmed) {
      return
    }
    const results = await Promise.allSettled(
      allTargets.map(row => deleteFlowApi(row.workFlowId))
    )
    const success = results.filter(result => result.status === 'fulfilled').length
    const failed = allTargets.length - success
    clearSelection()
    if (success) {
      proxy.$message.success(proxy.$t('modules.workflow.batchDeleteSuccess', { count: success }))
    }
    if (failed) {
      proxy.$message.error(proxy.$t('modules.workflow.batchPartial', { success, failed }))
    }
    await refreshAfterMutation(success)
    return
  }

  const publish = command === 'publish'
  // 批量发布包含「未发布」与「发布后修改」（publishType=0/2），见 publishActions.js。
  const targets = allTargets.filter(row => (publish
    ? isBatchPublishTarget(row)
    : Number(row.publishType) !== 0))
  if (!targets.length) {
    proxy.$message.info(proxy.$t(publish
      ? 'modules.workflow.batchPublishSkipped'
      : 'modules.workflow.batchUnpublishSkipped'))
    return
  }
  const results = await Promise.allSettled(targets.map(row => (publish
    ? publishWorkFlow(row.workFlowId)
    : unpublishWorkFlow(row.workFlowId))))
  const success = results.filter(result => result.status === 'fulfilled').length
  const failed = targets.length - success
  clearSelection()
  if (success) {
    proxy.$message.success(proxy.$t('modules.workflow.batchUpdated', { count: success }))
  }
  if (failed) {
    proxy.$message.error(proxy.$t('modules.workflow.batchPartial', { success, failed }))
  }
  await getWorkflowList()
}

async function refreshAfterMutation (deletedCount = 0) {
  const remaining = Math.max(0, filteredRecords.value - deletedCount)
  const maxPage = Math.max(1, Math.ceil(remaining / pageSize.value))
  if (currentPage.value > maxPage) {
    currentPage.value = maxPage
  }
  await getWorkflowList()
}
function setFlow (scope) {
  proxy.$router.push({
    name: 'flow-detail',
    params: { id: scope.workFlowId }
  })
}

</script>
<style scoped>
.flow-source-types { display: flex; flex-wrap: wrap; gap: 4px; }
.flow-source-types .tag-soft { white-space: nowrap; }
.flow-table { min-width: 1250px; }
.flow-table th:nth-child(3) { width: 36%; }
@media (max-width: 1450px) { .flow-table { min-width: 1230px; } }

/* 业务补充：publishType=2 的提示图标 */
/* 圆点/文字/提示图标按视觉中线对齐；行内基线对齐会让 18px 图标高出文字约 4px */
.flow-status-inline { display: inline-flex; align-items: center; }
.workflow-status__tip {
  width: 18px;
  height: 18px;
  color: var(--rs-text-3);
  font-size: 12px;
  margin-left: 4px;
}
.workflow-sort-icon { width: 13px; height: 13px; }
</style>

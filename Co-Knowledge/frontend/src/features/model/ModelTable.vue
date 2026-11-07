<template>
  <div class="model-table">
    <div class="toolbar">
      <div class="toolbar-left">
        <el-button type="primary" @click="createHandle">
          <Plus />
          {{ $t('modules.modelManagement.create') }}
        </el-button>
      </div>
      <div class="toolbar-right">
        <TableRefreshButton :label="$t('modules.modelManagement.refreshList')" :refresh="refreshList" />
        <el-input
          v-model.trim="searchKey"
          class="search-field"
          :placeholder="$t('modules.modelManagement.searchPlaceholder')"
          :prefix-icon="Search"
          clearable
          @input="search"
        />
        <el-dropdown trigger="click" @command="setEnabledFilter">
          <el-button :class="{ 'filter-active': enabledFilter !== 'all' }">
            <Filter />
            {{ $t('modules.kb.filterStatus') }}
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="all">
                {{ $t('modules.modelManagement.filterAll') }}
              </el-dropdown-item>
              <el-dropdown-item command="enabled">
                {{ $t('modules.modelManagement.filterEnabled') }}
              </el-dropdown-item>
              <el-dropdown-item command="disabled">
                {{ $t('modules.modelManagement.filterDisabled') }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <ListSelectionBar :count="selectedRows.length" @clear="clearSelection">
      <el-button link type="primary" @click="batchModels('enable')">
        {{ $t('modules.modelManagement.batchEnable') }}
      </el-button>
      <el-button link @click="batchModels('disable')">
        {{ $t('modules.modelManagement.batchDisable') }}
      </el-button>
      <el-button class="danger-action" link type="danger" @click="batchModels('delete')">
        <Delete />{{ $t('modules.modelManagement.batchDelete') }}
      </el-button>
    </ListSelectionBar>

    <div class="table-card">
      <table class="list-table models-table">
        <thead>
          <tr>
            <th class="check-cell">
              <input
                type="checkbox"
                :aria-label="$t('modules.modelManagement.selectAllPage')"
                :checked="allSelected"
                @change="toggleAll($event.target.checked)"
              >
            </th>
            <th>
              {{ $t('modules.modelManagement.columnName') }}
              <span class="table-header-sub">{{ $t('modules.modelManagement.columnNameSub') }}</span>
            </th>
            <th>{{ $t('modules.modelManagement.columnBaseUrl') }}</th>
            <th>{{ $t('modules.modelManagement.columnApiKey') }}</th>
            <th>{{ $t('modules.modelManagement.columnHealth') }}</th>
            <th>{{ $t('public.operate') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.modelId || row.modelName">
            <td class="check-cell">
              <input
                type="checkbox"
                :checked="isSelected(row)"
                :aria-label="$t('modules.modelManagement.selectModel', { name: row.displayName || row.modelName })"
                @change="toggleRow(row, $event.target.checked)"
              >
            </td>
            <td>
              <div class="entity">
                <div :class="['avatar-square', avatarTone(row)]">
                  {{ initialOf(row.displayName || row.modelName) }}
                </div>
                <div>
                  <div class="entity-title">
                    {{ row.displayName || row.modelName }}
                  </div>
                  <div class="entity-sub">
                    {{ row.modelName }}
                  </div>
                  <div class="table-tags">
                    <span v-if="row.isDefault" class="tag-soft green">
                      {{ $t('modules.modelManagement.columnDefault') }}
                    </span>
                    <span v-if="kind === 'embedding' && row.dimension" class="tag-soft">
                      {{ $t('modules.modelManagement.dimensionTag', { count: row.dimension }) }}
                    </span>
                    <span v-if="thinkingTag(row)" class="tag-soft">{{ thinkingTag(row) }}</span>
                    <span class="tag-soft orange">
                      {{ $t(SOURCE_LABEL_KEY[row.source] || 'modules.modelManagement.sourceUser') }}
                    </span>
                  </div>
                </div>
              </div>
            </td>
            <td class="nowrap">
              <div class="endpoint-line">
                <span class="endpoint-icon"><Link /></span>
                <span>{{ row.baseUrl || '--' }}</span>
                <button
                  class="icon-button copy"
                  :aria-label="$t('public.copy')"
                  @click.stop="copyEndpoint(row)"
                >
                  <CopyDocument />
                </button>
              </div>
              <span class="tag-soft blue endpoint-sub">
                {{ row.apiModel && row.apiModel !== row.modelName
                  ? row.apiModel
                  : $t('modules.modelManagement.openaiCompatible') }}
              </span>
            </td>
            <td class="nowrap">
              <!-- 锁 / 掩码 / 眼睛共用一行 flex 居中；按钮若按行内基线排版会比文字高出约 5px -->
              <div class="key-line">
                <Lock style="width: 15px" />
                <span :title="row.hasApiKey ? row.apiKeyMasked : ''">
                  {{ row.hasApiKey ? row.apiKeyMasked : $t('modules.modelManagement.keyMissing') }}
                </span>
                <button
                  class="icon-button"
                  :aria-label="$t('modules.modelManagement.showKeyHint')"
                  :title="$t('modules.modelManagement.showKeyHint')"
                  @click.stop="showKeyHint"
                >
                  <View />
                </button>
              </div>
            </td>
            <td class="nowrap">
              <!-- 状态列 = 开关 + 文案：启停是这一列唯一的真实状态。 -->
              <div class="table-status">
                <el-switch
                  :model-value="row.enabled"
                  :loading="Boolean(toggling[row.modelId])"
                  :aria-label="$t('modules.modelManagement.toggleModel', { name: row.displayName || row.modelName })"
                  @change="value => toggleEnabled(row, value)"
                />
                <span>{{ row.enabled ? $t('modules.modelManagement.healthOk') : $t('modules.modelManagement.healthOff') }}</span>
              </div>
            </td>
            <td>
              <div class="row-actions">
                <!-- 真实调用可能要好几秒（实测一个模型 ~4s），期间按钮要给出「在测」的
                     反馈，否则看起来像点了没反应。 -->
                <el-button
                  link
                  type="primary"
                  :loading="testingId === row.modelId"
                  @click="testClickHandle(row)"
                >
                  {{ $t('modules.modelManagement.test') }}
                </el-button>
                <el-button link type="primary" @click="editClickHandle(row)">
                  {{ $t('modules.modelManagement.edit') }}
                </el-button>
                <el-button class="danger-action" link type="danger" @click="deleteClickHandle(row)">
                  <Delete />{{ $t('public.delete') }}
                </el-button>
                <el-dropdown trigger="click" @command="setDefault(row)">
                  <button class="icon-button" :aria-label="$t('app.more')">
                    <MoreFilled class="more-icon" />
                  </button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="default">
                        {{ $t('modules.modelManagement.setDefault') }}
                      </el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="7" class="empty-row">
              {{ $t('modules.modelManagement.empty') }}
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

    <ModelEditorDialog
      v-model="editorOpen"
      :editing="editingRow"
      :initial-kind="kind"
      :existing="allModels"
      :submit-handler="saveModel"
    />


    <el-dialog
      v-model="testVisible"
      :title="$t('modules.modelManagement.testResultTitle')"
      width="560px"
      :append-to-body="true"
    >
      <ModelTestResultTable
        v-if="testResult"
        :result="testResult"
        :kind="testRow ? testRow.modelKind : ''"
        :registered-dimension="testRow ? testRow.dimension : null"
      />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, getCurrentInstance, onMounted, reactive, ref } from 'vue'
import { debounce } from 'lodash'
import { Plus, Search, Filter, Link, Lock, CopyDocument, View, MoreFilled, Delete } from '@/shared/lib/icons'
import { copyTextWithToast } from '@/shared/lib/copy-with-toast'
import TablePagination from '@/shared/ui/reference/TablePagination.vue'
import TableRefreshButton from '@/shared/ui/TableRefreshButton.vue'
import ListSelectionBar from '@/shared/ui/ListSelectionBar.vue'
import { requestDeletion } from '@/shared/composables/deletion'
import { createModelApi, deleteModelApi, queryModelsApi, testModelApi, updateModelApi } from '@/features/model/api/model.js'
import { DEBOUNCETIME } from '@/shared/constants/index.js'
// 表格高度 = 页面剩余高度（与文档知识库 /kb 同一套量法）
import ModelEditorDialog from '@/features/model/components/ModelEditorDialog.vue'
import ModelTestResultTable from './ModelTestResultTable.vue'
import { SOURCE_LABEL_KEY } from './type'

const props = defineProps({
  kind: { type: String, required: true }
})
const emit = defineEmits(['change-kind'])

const { proxy } = getCurrentInstance() as any

/** 行的思考配置标签：自动/预设显示目录里的短名，自定义/未匹配/旧行各有文案。 */
function thinkingLabel (row: any): string {
  const zh = String(proxy.$i18n?.locale || 'zh').startsWith('zh')
  return zh
    ? (row.thinkingMatchedPresetLabel || row.thinkingPresetLabel || '')
    : (row.thinkingMatchedPresetLabelEn || row.thinkingPresetLabelEn || '')
}

function thinkingTag (row: any): string {
  if (row.modelKind !== 'llm') {
    return ''
  }
  if (row.thinkingMode === 'auto') {
    const label = thinkingLabel(row)
    return label
      ? proxy.$t('modules.modelManagement.tagThinkingAuto', { label })
      : proxy.$t('modules.modelManagement.tagThinkingNoMatch')
  }
  if (row.thinkingMode === 'preset') {
    const label = thinkingLabel(row) || row.thinkingPreset || ''
    return proxy.$t('modules.modelManagement.tagThinkingPreset', { label })
  }
  if (row.thinkingMode === 'custom') {
    return proxy.$t('modules.modelManagement.tagThinkingCustom')
  }
  return ''
}

const editorOpen = ref(false)
const editingRow = ref<any>(null)
const allModels = ref<any[]>([])
const searchKey = ref('')
const enabledFilter = ref('all')
const ALL_PAGE_SIZE = 500
const toggling = ref<Record<string, boolean>>({})
const selectedMap = reactive(new Map<string, any>())

/** 启用开关：后端 PUT /models/{id} 是部分合并语义，只传 enabled 即可。 */
function toggleEnabled (row: any, value: boolean) {
  if (toggling.value[row.modelId]) {
    return
  }
  toggling.value = { ...toggling.value, [row.modelId]: true }
  // 停用时同时取消默认标记：后端允许「停用 + 默认」，但运行时不会调用停用模型，
  // 留着默认标记会误导用户。
  const payload = value ? { enabled: true } : { enabled: false, isDefault: false }
  updateModelApi(row.modelId, payload)
    .then(() => {
      row.enabled = value
      if (!value) {
        row.isDefault = false
      }
      proxy.$message.success(value
        ? proxy.$t('modules.modelManagement.enabledSuccess')
        : proxy.$t('modules.modelManagement.disabledSuccess'))
    })
    .catch(() => {
      // 失败时保持原状态（没有本地乐观写入）
    })
    .finally(() => {
      const next = { ...toggling.value }
      delete next[row.modelId]
      toggling.value = next
    })
}

/** 启用状态筛选（本地）：与知识库页同一套「取全量 → 过滤 → 本地分页」。 */
function setEnabledFilter (value: string) {
  enabledFilter.value = value
  clearSelection()
  refreshTableData('initPage')
}

const AVATAR_TONES = ['av-blue', 'av-purple', 'av-green', 'av-orange']

function initialOf (name: string): string {
  return String(name || '?').charAt(0)
    .toUpperCase()
}

function avatarTone (row: any): string {
  // LLM 按名称首字母取色（蓝/紫/绿/橙），向量模型绿、重排模型紫。
  if (row.modelKind === 'embedding') {
    return 'av-green'
  }
  if (row.modelKind === 'rerank') {
    return 'av-purple'
  }
  const source = String(row.displayName || row.modelName || '?')
  return AVATAR_TONES[source.charCodeAt(0) % AVATAR_TONES.length]
}

function copyEndpoint (row: any) {
  if (row.baseUrl) {
    copyTextWithToast(row.baseUrl)
  }
}
const testVisible = ref(false)
const testResult = ref<any>(null)
/** 触发这次测试的行 —— 结果表的「登记维度」列取自它（`result` 本身不带登记值） */
const testRow = ref<any>(null)
/** 正在测的模型 id（按钮转圈的判据）；空串表示没有在测 */
const testingId = ref('')

/**
 * 列口径：名称（含内部名/标签）/ 端点 / 密钥 / 状态 / 操作。
 * - 不设「序号」列；
 * - 向量维度不单独占列（会把表挤到一屏外），收进名称下的标签；
 * - 「状态」列 = 启停开关 + 文案，**不再另设「启用」列**：两列取的都是 `enabled`，
 *   并排放只会重复同一句话。接口没有独立的健康检查结果，不伪造延迟/时间；
 *   真实可用性由每行的「连接测试」回答。
 */
const rows = ref<any[]>([])
const currentPage = ref(1)
const pageSize = ref(10)
const total = ref(0)
const selectedRows = computed(() => Array.from(selectedMap.values()))
const allSelected = computed(() => rows.value.length > 0 && rows.value.every((row: any) => selectedMap.has(row.modelId)))

function isSelected (row: any): boolean {
  return Boolean(row?.modelId) && selectedMap.has(row.modelId)
}

function toggleRow (row: any, checked: boolean) {
  if (!row?.modelId) {
    return
  }
  if (checked) {
    selectedMap.set(row.modelId, { ...row })
  } else {
    selectedMap.delete(row.modelId)
  }
}

function toggleAll (checked: boolean) {
  rows.value.forEach(row => {
    if (checked) {
      selectedMap.set(row.modelId, { ...row })
    } else {
      selectedMap.delete(row.modelId)
    }
  })
}

function clearSelection () {
  selectedMap.clear()
}

function syncSelectedRows (data: any[]) {
  data.forEach(row => {
    if (row?.modelId && selectedMap.has(row.modelId)) {
      selectedMap.set(row.modelId, { ...row })
    }
  })
}

async function loadRows (): Promise<boolean> {
  try {
    const result: any = await getTableDataApi(
      { currentPage: currentPage.value, pageSize: pageSize.value },
      {}
    )
    const data = Array.isArray(result?.items) ? result.items : []
    syncSelectedRows(data)
    rows.value = data
    total.value = Number(result?.total) || data.length
    return true
  } catch (e) {
    // 错误提示由拦截器统一弹；表格保持上一屏数据
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
  if (!ok) {
    throw new Error('refresh failed')
  }
}

/**
 * 返回分页体 `{ items, total, page, pageSize }`（列表接口的分页体约定）。
 * 类型由**当前页签**决定 —— 三级下拉/校验各自只关心自己那一类。
 */
function getTableDataApi (params: any, config: any) {
  params.kind = props.kind
  params.keyword = searchKey.value
  if (enabledFilter.value !== 'all') {
    const page = Number(params.currentPage) || 1
    const size = Number(params.pageSize) || 10
    return queryModelsApi(
      { ...params, currentPage: 1, pageSize: ALL_PAGE_SIZE },
      config
    ).then((res: any) => {
      const rows = (res && res.items ? res.items : []).filter((row: any) => (
        enabledFilter.value === 'enabled' ? row.enabled : !row.enabled
      ))
      const start = (page - 1) * size
      return {
        items: rows.slice(start, start + size),
        total: rows.length,
        page,
        pageSize: size
      }
    })
  }
  return queryModelsApi(params, config)
}

const search = debounce(() => {
  clearSelection()
  refreshTableData('initPage')
}, DEBOUNCETIME)

function refreshTableData (initPage = '') {
  if (initPage) {
    currentPage.value = 1
  }
  return loadRows()
}

function onPaginationChange ({ page, size }: { page: number, size: number }) {
  currentPage.value = page
  pageSize.value = size
  refreshTableData()
}

onMounted(() => {
  loadRows()
})

/**
 * 弹窗需要「全部类型」的模型做同名判重（弹窗内可以切类型），
 * 列表本身只加载当前页签，这里额外取一次全量（≤500）。
 */
async function loadAllModels () {
  try {
    const response: any = await queryModelsApi({ currentPage: 1, pageSize: ALL_PAGE_SIZE }, { skipErrorHandler: true })
    allModels.value = Array.isArray(response?.items) ? response.items : []
  } catch {
    allModels.value = rows.value
  }
}

function createHandle () {
  editingRow.value = null
  editorOpen.value = true
  loadAllModels()
}

/**
 * 眼睛按钮：真实接口只返回掩码，且没有任何接口能再次取回明文（这是安全要求，
 * 不该为了视觉去改协议），所以保留按钮位置并明确说明，而不是静默无响应。
 */
function showKeyHint () {
  proxy.$message.info(proxy.$t('modules.modelManagement.showKeyHint'))
}

function editClickHandle (row: any) {
  editingRow.value = row
  editorOpen.value = true
  loadAllModels()
}

/** 弹窗提交：新建 POST / 编辑 PUT；成功后刷新列表并按新类型切页签。 */
async function saveModel (values: any) {
  try {
    if (editingRow.value) {
      await updateModelApi(editingRow.value.modelId, values)
    } else {
      await createModelApi(values)
    }
    proxy.$message.success(proxy.$t('modules.modelManagement.saveSuccess'))
    refreshTableData()
    if (values.modelKind && values.modelKind !== props.kind) {
      emit('change-kind', values.modelKind)
    }
  } catch (error) {
    // 错误提示由拦截器统一弹；弹窗保持打开
    throw new Error('save failed')
  }
}

/** 设为默认模型（行菜单）：后端是部分合并语义，只传 isDefault。 */
function setDefault (row: any) {
  updateModelApi(row.modelId, { isDefault: true, enabled: true })
    .then(() => {
      proxy.$message.success(proxy.$t('modules.modelManagement.saveSuccess'))
      refreshTableData()
    })
    .catch(() => {})
}

function kindLabel (row: any): string {
  return {
    llm: proxy.$t('modules.modelManagement.tabLlm'),
    embedding: proxy.$t('modules.modelManagement.tabEmbedding'),
    rerank: proxy.$t('modules.modelManagement.tabRerank')
  }[row.modelKind] || ''
}

function deleteItem (row: any) {
  return {
    id: row.modelId,
    name: row.displayName || row.modelName,
    meta: row.modelName,
    letter: initialOf(row.displayName || row.modelName),
    av: avatarTone(row),
    tag: kindLabel(row)
  }
}

async function deleteClickHandle (row: any) {
  const confirmed = await requestDeletion({
    resourceType: proxy.$t('public.deleteConfirm.resourceModel'),
    warning: proxy.$t('modules.modelManagement.deleteWarning'),
    description: proxy.$t('modules.modelManagement.deleteDescription'),
    items: [deleteItem(row)],
    detail: row.baseUrl || '',
    note: row.isDefault ? proxy.$t('modules.modelManagement.deleteDefaultNote') : '',
    hint: proxy.$t('modules.modelManagement.deleteHint')
  })
  if (!confirmed) {
    return
  }
  try {
    await deleteModelApi(row.modelId)
    selectedMap.delete(row.modelId)
    proxy.$message.success(proxy.$t('modules.modelManagement.deleteSuccess'))
    await refreshAfterDelete(1)
  } catch {
    // 后端会拦「正被知识库使用」的 embedding 模型（0005 + 数量），提示由拦截器弹
  }
}

async function refreshAfterDelete (deletedCount: number) {
  const remaining = Math.max(0, total.value - deletedCount)
  const maxPage = Math.max(1, Math.ceil(remaining / pageSize.value))
  if (currentPage.value > maxPage) {
    currentPage.value = maxPage
  }
  await loadRows()
}

/** 批量：启用 / 停用 / 删除（现有单条接口扇出）。 */
async function batchModels (command: string) {
  const targets = [...selectedRows.value]
  if (!targets.length) {
    return
  }
  if (command === 'delete') {
    const confirmed = await requestDeletion({
      resourceType: proxy.$t('public.deleteConfirm.resourceModel'),
      title: proxy.$t('modules.modelManagement.batchDeleteTitle'),
      warning: proxy.$t('modules.modelManagement.deleteWarning'),
      description: proxy.$t('modules.modelManagement.deleteDescription'),
      items: targets.map(deleteItem),
      note: targets.some(row => row.isDefault)
        ? proxy.$t('modules.modelManagement.batchDeleteDefaultNote')
        : '',
      hint: proxy.$t('modules.modelManagement.deleteHint')
    })
    if (!confirmed) {
      return
    }
    const results = await Promise.allSettled(targets.map(row => deleteModelApi(row.modelId)))
    const success = results.filter(result => result.status === 'fulfilled').length
    const failed = targets.length - success
    results.forEach((result, index) => {
      if (result.status === 'fulfilled') {
        selectedMap.delete(targets[index].modelId)
      }
    })
    if (success) {
      proxy.$message.success(proxy.$t('modules.modelManagement.batchUpdated', { count: success }))
    }
    if (failed) {
      proxy.$message.error(proxy.$t('modules.modelManagement.batchPartial', { success, failed }))
    }
    await refreshAfterDelete(success)
    return
  }
  const enabled = command === 'enable'
  const results = await Promise.allSettled(targets.map(row => updateModelApi(
    row.modelId,
    enabled ? { enabled: true } : { enabled: false, isDefault: false }
  )))
  const success = results.filter(result => result.status === 'fulfilled').length
  const failed = targets.length - success
  clearSelection()
  if (success) {
    proxy.$message.success(proxy.$t('modules.modelManagement.batchUpdated', { count: success }))
  }
  if (failed) {
    proxy.$message.error(proxy.$t('modules.modelManagement.batchPartial', { success, failed }))
  }
  await loadRows()
}

function testClickHandle (row: any) {
  // 同一模型重复点击只发一次；真实调用是外部 HTTP，慢的时候会有几秒空窗
  if (testingId.value) {
    return
  }
  testingId.value = row.modelId
  testRow.value = row
  testModelApi(row.modelId, {})
    .then((res: any) => {
      testResult.value = res
      testVisible.value = true
    })
    .catch(() => {
      // 错误提示由拦截器统一弹
    })
    .finally(() => {
      testingId.value = ''
    })
}


defineExpose({ refreshTableData })
</script>

<style scoped>
.models-table { min-width: 1220px; }
.models-table .entity { min-width: 230px; }
.models-table .entity-title { white-space: nowrap; }
.models-table th:nth-child(2) { width: 22%; }
.models-table th:nth-child(3) { width: 25%; }
.models-table th:nth-child(4) { width: 12%; }
.models-table th:nth-child(5) { width: 10%; }
.endpoint-line { display: flex; gap: 7px; align-items: center; }
.key-line { display: flex; gap: 6px; align-items: center; }
.endpoint-icon {
  width: 27px;
  height: 27px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--rs-bg-selected);
  color: var(--rs-primary);
}
.endpoint-icon svg { width: 16px; height: 16px; }
.endpoint-sub { display: block; width: max-content; margin-top: 6px; }
</style>

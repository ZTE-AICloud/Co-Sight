<template>
  <WorkspaceShell
    class="knowledge-graph-detail-page"
    :class="{ 'is-graph-fullscreen': canvasFullscreen }"
    back="/graph"
    :parent="$t('modules.kb.graphKnowledgeBase')"
    :context="$t('modules.kb.viewDetail')"
    :title="detailData.name || '--'"
    :icon="Share"
    :show-focus-action="false"
  >
    <template #subtitle>
      <span class="tag-soft purple">{{ $t('modules.kb.knowledgeGraph') }}</span>
      <span v-if="detailData.embeddingModel">{{ detailData.embeddingModel }}</span>
    </template>
    <template #actions>
      <el-button class="button-compact" @click="goEditGraph">
        <Edit />{{ $t('modules.kb.editKnowledgeGraph') }}
      </el-button>
      <el-button class="button-compact" @click="exportGraph">
        <Download />{{ $t('modules.kb.exportGraph') }}
      </el-button>
    </template>
    <!-- 图谱页只保留画布内的「全屏查看」入口，页头不重复。 -->

    <!-- 一级tab -->
    <el-tabs v-model="activeTab" class="detail-tabs">
      <el-tab-pane :label="$t('modules.kb.viewKnowledgeGraph')" name="viewGraph">
        <div v-loading="graphLoading" class="view-graph-content">
          <!-- 可视化组件：始终渲染，内部根据数据渲染实体或空白画布 -->
          <GraphVisualization
            ref="graphVisRef"
            :graph-data="graphData"
            :entity-types="availableEntityTypes"
            :edge-types="availableEdgeTypes"
            :selected-entity-types="selectedEntityTypes"
            :selected-edge-types="selectedEdgeTypes"
            :limit-value="limitValue"
            :depth-value="depthValue"
            :schema-mapping="schemaMapping"
            :search-keyword="searchKeyword"
            :is-manual-query="isManualQuery"
            :last-query-payload="lastQueryPayload"
            :reset-token="graphResetToken"
            :graph-name="detailData.name"
            :result-has-more="graphResultHasMore"
            :refresh-graph="refreshGraphFromServer"
            @fullscreen-change="canvasFullscreen = $event"
            @entity-type-change="handleEntityTypeChange"
            @edge-type-change="handleEdgeTypeChange"
            @limit-change="handleLimitChange"
            @depth-change="handleDepthChange"
            @refresh-graph-data="handleRefreshGraphData"
            @search-input="handleSearchInput"
            @search-clear="handleSearchClear"
            @execute-query="handleExecuteQuery"
            @query-type-change="handleQueryTypeChange"
          />
        </div>
      </el-tab-pane>

      <el-tab-pane :label="$t('modules.kb.basicInfo')" name="basicInfo">
        <div class="graph-info" :aria-label="t('modules.kb.basicInfo')">
          <div class="gi-content">
            <div class="gi-summary" :aria-label="t('modules.kb.graphInfoDataOverview')">
              <div v-for="metric in infoMetrics" :key="metric.label" class="gi-metric">
                <span :class="['gi-icon', metric.tone]"><component :is="metric.icon" /></span>
                <div>
                  <span class="text-caption muted">{{ metric.label }}</span>
                  <div class="gi-metric-value">{{ metric.value }}<span class="text-caption muted">{{ metric.unit }}</span></div>
                </div>
              </div>
              <span class="gi-live text-caption"><InfoFilled />{{ t('modules.kb.graphInfoLiveData') }}</span>
            </div>

            <div class="gi-layout">
              <section class="gi-card" aria-labelledby="gi-overview-title">
                <div class="gi-heading">
                  <span class="gi-icon blue"><Share /></span>
                  <div>
                    <h2 id="gi-overview-title" class="text-section-title">{{ t('modules.kb.graphInfoOverview') }}</h2>
                    <p class="text-caption">{{ t('modules.kb.graphInfoOverviewDesc') }}</p>
                  </div>
                </div>
                <dl class="gi-properties text-secondary">
                  <div>
                    <dt>{{ t('modules.kb.graphInfoName') }}</dt>
                    <dd>{{ detailData.name || '--' }}</dd>
                  </div>
                  <div>
                    <dt>{{ t('modules.kb.graphInfoIdentifier') }}</dt>
                    <dd class="gi-copy">
                      <code>{{ graphIdentifier }}</code>
                      <button
                        type="button"
                        class="icon-button copy"
                        :aria-label="t('modules.kb.graphInfoCopyIdentifier')"
                        :title="t('modules.kb.graphInfoCopyIdentifier')"
                        @click="copyText(graphIdentifier)"
                      >
                        <CopyDocument />
                      </button>
                    </dd>
                  </div>
                  <div>
                    <dt>{{ t('modules.kb.graphInfoDescription') }}</dt>
                    <dd class="gi-description">{{ detailData.description || t('modules.kb.graphInfoNoDescription') }}</dd>
                  </div>
                  <div>
                    <dt>{{ t('modules.kb.graphInfoSource') }}</dt>
                    <dd>{{ detailData.source || t('modules.kb.graphInfoNotConfigured') }}</dd>
                  </div>
                  <div>
                    <dt>{{ t('modules.kb.graphInfoCreator') }}</dt>
                    <dd>{{ detailData.createdBy || '—' }}</dd>
                  </div>
                  <div>
                    <dt>{{ t('modules.kb.graphInfoCreateTime') }}</dt>
                    <dd>{{ detailData.createdAt || '—' }}</dd>
                  </div>
                  <div>
                    <dt>{{ t('modules.kb.graphInfoUpdateTime') }}</dt>
                    <dd>{{ detailData.lastUpdatedDate || '—' }}</dd>
                  </div>
                </dl>
              </section>

              <section class="gi-card" aria-labelledby="gi-config-title">
                <div class="gi-heading">
                  <span class="gi-icon purple"><LayersIcon /></span>
                  <div>
                    <h2 id="gi-config-title" class="text-section-title">{{ t('modules.kb.graphInfoModelTemplate') }}</h2>
                    <p class="text-caption">{{ t('modules.kb.graphInfoModelTemplateDesc') }}</p>
                  </div>
                </div>
                <dl class="gi-properties gi-config text-secondary">
                  <div>
                    <dt>{{ t('modules.kb.graphInfoEmbeddingModel') }}</dt>
                    <dd>
                      <span v-if="detailData.embeddingModel" class="tag-soft purple gi-model">
                        <LayersIcon />{{ detailData.embeddingModel }}
                      </span>
                      <span v-else>{{ t('modules.kb.graphInfoNotConfigured') }}</span>
                    </dd>
                  </div>
                  <div>
                    <dt>{{ t('modules.kb.graphInfoOperator') }}</dt>
                    <dd>{{ graphOperatorName || t('modules.kb.graphInfoNotConfigured') }}</dd>
                  </div>
                  <div>
                    <dt>{{ t('modules.kb.graphInfoTemplateName') }}</dt>
                    <dd>{{ detailData.templateName || t('modules.kb.graphInfoNoTemplate') }}</dd>
                  </div>
                  <div>
                    <dt>{{ t('modules.kb.graphInfoTemplateDescription') }}</dt>
                    <dd class="gi-description">{{ detailData.templateDescription || t('modules.kb.graphInfoNoTemplateDescription') }}</dd>
                  </div>
                  <div>
                    <dt>{{ t('modules.kb.graphInfoEntityTypes') }}</dt>
                    <dd class="gi-types">
                      <span v-for="item in visibleEntityTypes" :key="item.name" :class="['tag-soft', item.tone]">
                        <i />{{ item.name }}
                      </span>
                      <span v-if="!visibleEntityTypes.length">{{ t('modules.kb.graphInfoNoEntityTypes') }}</span>
                    </dd>
                  </div>
                </dl>
              </section>
            </div>

            <section class="gi-card gi-files" aria-labelledby="gi-files-title">
              <div class="gi-heading gi-file-heading">
                <span class="gi-icon orange"><FolderOpened /></span>
                <div>
                  <h2 id="gi-files-title" class="text-section-title">
                    {{ t('modules.kb.graphInfoFiles') }}
                    <span class="gi-count text-caption">{{ detailData.files.length }}</span>
                  </h2>
                  <p class="text-caption">{{ t('modules.kb.graphInfoFilesDesc') }}</p>
                </div>
                <div class="gi-file-controls">
                  <TableRefreshButton
                    :key="String(route.params.id)"
                    :label="t('modules.kb.graphInfoRefreshFiles')"
                    :refresh="refreshSourceFiles"
                    compact
                  />
                  <el-input
                    v-if="detailData.files.length"
                    v-model="fileSearch"
                    :prefix-icon="Search"
                    clearable
                    :placeholder="t('modules.kb.graphInfoFileSearch')"
                    :aria-label="t('modules.kb.graphInfoFileSearch')"
                    class="gi-file-search"
                  />
                </div>
              </div>

              <div v-if="detailData.files.length" class="table-card gi-table">
                <table class="list-table">
                  <thead>
                    <tr>
                      <th>{{ t('modules.kb.fileNameLabel') }}</th>
                      <th>{{ t('modules.kb.fileSizeLabel') }}</th>
                      <th>{{ t('modules.kb.fileSourceLabel') }}</th>
                      <th>{{ t('modules.kb.uploaderLabel') }}</th>
                      <th>{{ t('modules.kb.uploadTimeLabel') }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="file in pageFiles" :key="file.id">
                      <td>
                        <div class="gi-file-name"><Document /><span>{{ file.name }}</span></div>
                      </td>
                      <td class="nowrap">{{ formatFileSize(file.size) }}</td>
                      <td>{{ file.source || '—' }}</td>
                      <td>{{ file.uploader || '—' }}</td>
                      <td class="table-time">{{ file.uploadTime || '—' }}</td>
                    </tr>
                    <tr v-if="!filteredFiles.length">
                      <td colspan="5" class="empty-row">{{ t('modules.kb.graphInfoNoMatchingFiles') }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div v-else class="gi-file-empty">
                <span class="gi-icon"><Document /></span>
                <div>
                  <p class="text-body">{{ t('modules.kb.graphInfoNoFiles') }}</p>
                  <p class="text-secondary">{{ t('modules.kb.graphInfoNoFilesDesc') }}</p>
                </div>
              </div>

              <div v-if="detailData.files.length" class="gi-file-footer">
                <span class="text-caption muted">
                  {{ t('modules.kb.graphInfoFileSummary', { count: filteredFiles.length, size: formatFileSize(fileTotalBytes) }) }}
                </span>
                <el-pagination
                  v-model:current-page="filePage"
                  :page-size="10"
                  :total="filteredFiles.length"
                  layout="prev, pager, next"
                  background
                  :pager-count="5"
                  hide-on-single-page
                />
              </div>
            </section>

            <p class="gi-note text-caption"><InfoFilled />{{ t('modules.kb.graphInfoDataNote') }}</p>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </WorkspaceShell>
</template>

<script lang="ts" setup>
import { ref, computed, getCurrentInstance, onMounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  Connection,
  CopyDocument,
  Document,
  Download,
  Edit,
  FolderOpened,
  InfoFilled,
  Search,
  Share
} from '@element-plus/icons-vue'
import { LayersIcon } from '@/shared/ui/icons'
import { copyTextWithToast } from '@/shared/lib/copy-with-toast'
import WorkspaceShell from '@/app/layout/WorkspaceShell.vue'
import TableRefreshButton from '@/shared/ui/TableRefreshButton.vue'
import GraphVisualization from '@/features/graph/components/GraphVisualization.vue'
import { getKnowledgeGraphBasicInfoApi, getGraphQueryApi, getOperatorListApi } from '@/features/graph/api/knowledgeGraph'
import { assignEntityTones } from '@/features/graph/lib/entity-tones'
import { resolveGraphStats, type GraphStats } from '@/features/graph/lib/graph-stats'
import { processSchemaInfo, validateSchemaInfo } from '@/features/graph/lib/schemaMapper'

const { t } = useI18n()

const { proxy } = getCurrentInstance() as any
const route = useRoute()
const router = useRouter()

/* 只保留画布内的「全屏查看」；页面只跟踪状态用于隐藏页头/页签。 */
const canvasFullscreen = ref(false)

/**
 * 导出当前图谱（基础信息 + 当前可视化数据）。
 * 页头有「导出图谱」；接口没有专门的导出端点，这里导出的是页面已取到的
 * 真实数据快照，不伪造后端任务。
 */
function exportGraph () {
  const payload = {
    graph: detailData.value,
    nodes: graphData.value.entities || [],
    edges: graphData.value.edges || []
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${detailData.value.name || 'knowledge-graph'}.json`
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** 页头「修改图谱」：进入修改页（锁定项只读，保存即重新抽取）。 */
function goEditGraph () {
  if (!route.params.id) {
    return
  }
  router.push({ name: 'graph-edit', params: { id: route.params.id } })
}

// 当前激活的tab。URL 契约：基本信息是 `?tab=info`，
// 图谱画布是默认值（不带 tab）。内部页签名沿用 viewGraph / basicInfo，
// 只在路由 query 与页签名之间做一层映射，深链/刷新/前进后退都能正确回显。
const activeTab = computed({
  get: () => (route.query.tab === 'info' ? 'basicInfo' : 'viewGraph'),
  set: value => {
    const { tab, ...rest } = route.query // eslint-disable-line no-unused-vars
    router.replace({
      query: value === 'basicInfo' ? { ...rest, tab: 'info' } : rest
    })
  }
})

// 图谱可视化数据
const graphData = ref({
  entities: [],
  edges: []
})
const graphVisRef = ref(null)
const graphLoading = ref(false)
const graphResetToken = ref(0)
/** 后端 has_more —— 当前结果可能被 Limit 截断，摘要行给出提示。 */
const graphResultHasMore = ref(false)
const MIN_ENTITY_RECOVERY_QUERY_LIMIT = 200
const DEFAULT_LIMIT_VALUE = 50
const DEFAULT_DEPTH_VALUE = 10

// 控制面板参数
const selectedEntityTypes = ref([])
const selectedEdgeTypes = ref([])
const limitValue = ref(50)
const depthValue = ref(10)
const searchKeyword = ref('')
const currentQueryType = ref('entity') // 保存当前选择的查询类型

// 可选的实体和关系类型（从schemaInfo获取）
const availableEntityTypes = ref([])
const availableEdgeTypes = ref([])

// schemaInfo数据
const schemaInfo = ref(null)

// schema映射数据
const schemaMapping = ref({
  entity_meta: {},
  adjacency_map: {}
})

// 详情数据
const detailData = ref({
  id: '',
  name: '',
  description: '',
  embeddingModel: '',
  operatorId: '',
  tableName: '',
  templateName: '',
  schemaId: '',
  templateDescription: '',
  templateCreatedAt: '',
  templateCreatedBy: '',
  fileCount: 0,
  source: '',
  buildStatus: '',
  buildProgress: 0,
  publishStatus: '',
  createdBy: '',
  createdAt: '',
  lastUpdatedDate: '',
  files: [] as any[]
})

/* ── 基本信息页 ─────────────────────────────────────────────── */
const fileSearch = ref('')
const filePage = ref(1)

// 图谱全量实体/关系数（详情接口 stats）。为空时回落到当前查询结果。
const graphStats = ref<GraphStats | null>(null)

const infoMetrics = computed(() => [
  {
    label: t('modules.kb.graphInfoMetricEntities'),
    value: graphStats.value?.entityCount ?? (graphData.value.entities || []).length,
    unit: t('modules.kb.graphInfoUnitEntity'),
    icon: Share,
    tone: 'blue'
  },
  {
    label: t('modules.kb.graphInfoMetricEdges'),
    value: graphStats.value?.edgeCount ?? (graphData.value.edges || []).length,
    unit: t('modules.kb.graphInfoUnitEdge'),
    icon: Connection,
    tone: 'purple'
  },
  {
    label: t('modules.kb.graphInfoMetricFiles'),
    value: (detailData.value.files || []).length,
    unit: t('modules.kb.graphInfoUnitFile'),
    icon: Document,
    tone: 'orange'
  }
])

const graphIdentifier = computed(() => detailData.value.tableName || detailData.value.id || '--')

const entityToneMap = computed(() => assignEntityTones(availableEntityTypes.value, availableEntityTypes.value))

/* 知识图谱算子：详情接口只回 operatorId，名称走算子列表（一次加载，失败不阻塞页面）。 */
const operatorList = ref<any[]>([])
const graphOperatorName = computed(() => {
  const operator = operatorList.value.find((item: any) => String(item?.id) === String(detailData.value.operatorId))
  if (!operator) {
    // 算子列表还没回来 / 加载失败时至少把已配置的 id 如实显示，不写成「未配置」
    return detailData.value.operatorId === '' || detailData.value.operatorId === null
      ? ''
      : `#${detailData.value.operatorId}`
  }
  return proxy?.$i18n?.locale === 'zh'
    ? operator.name || operator.nameEn || ''
    : operator.nameEn || operator.name || ''
})

async function loadOperatorList () {
  try {
    operatorList.value = await getOperatorListApi('graph_extract')
  } catch (error) {
    operatorList.value = []
  }
}

const visibleEntityTypes = computed(() => {
  const presentTypes = new Set(
    (graphData.value.entities || [])
      .map(entity => entity.entity_type || entity.class)
      .filter(Boolean)
  )
  const isPresent = (type: string) => presentTypes.has(type) ||
    Array.from(presentTypes).some(item => String(item).toLowerCase() === String(type).toLowerCase())
  // 图谱数据还没回来时先展示模板里的全部实体类型；有数据时只展示数据里出现的类型
  const types = presentTypes.size === 0 ? availableEntityTypes.value : availableEntityTypes.value.filter(isPresent)
  return types.map((type: string) => ({ name: type, tone: entityToneMap.value[type] || 'blue' }))
})

const filteredFiles = computed(() => {
  const term = fileSearch.value.trim().toLowerCase()
  const files = detailData.value.files || []
  return term ? files.filter(file => String(file.name || '').toLowerCase().includes(term)) : files
})

const pageFiles = computed(() => filteredFiles.value.slice((filePage.value - 1) * 10, filePage.value * 10))

const fileTotalBytes = computed(() =>
  (detailData.value.files || []).reduce((sum, file) => sum + (Number(file.size) || 0), 0)
)

watch(fileSearch, () => {
  filePage.value = 1
})

/** 复制并提示结果（成功/失败都要有反馈，见 copy-with-toast.js）。 */
function copyText (text: string | number) {
  return copyTextWithToast(text)
}

// 设置基本信息
function setBasicInfo (data: any, id: string) {
  detailData.value.id = data.id || id
  detailData.value.name = data.name || '--'
  detailData.value.description = data.description || ''
  detailData.value.embeddingModel = data.embeddingModel || ''
  detailData.value.operatorId = data.operatorId ?? ''
  detailData.value.tableName = data.tableName || ''
  detailData.value.source = data.source || ''
  detailData.value.createdAt = data.createdDate || ''
  detailData.value.createdBy = data.createdBy || ''
  detailData.value.fileCount = data.currentFileCount || 0
  detailData.value.lastUpdatedDate = data.lastUpdatedDate || ''
}

// 从schemaInfo中提取实体和关系类型，并生成映射数据
function extractEntityAndEdgeTypes (schemaInfoData: any) {
  if (!schemaInfoData) {
    return
  }

  // 验证schema数据
  const validation = validateSchemaInfo(schemaInfoData)
  if (!validation.valid) {
    console.error('Schema数据验证失败:', validation.errors)
    proxy.$message.error(`${proxy.$t('modules.kb.schemaValidationFailed')}: ${validation.errors.join(', ')}`)
    return
  }

  if (validation.warnings.length > 0) {
    console.warn('Schema数据警告:', validation.warnings)
  }

  // 调试：检查原始schemaInfo数据

  // 处理schema数据，生成映射关系
  schemaMapping.value = processSchemaInfo(schemaInfoData)

  // 调试：检查生成的映射数据

  // 从schemaInfo的entities数组中直接提取实体类型
  const entityTypes = new Set()
  if (schemaInfoData.entities && Array.isArray(schemaInfoData.entities)) {
    schemaInfoData.entities.forEach(entity => {
      if (entity.entity_type) {
        entityTypes.add(entity.entity_type)
      }
    })
  }
  availableEntityTypes.value = Array.from(entityTypes)

  // 从schemaInfo的edges数组中直接提取关系类型
  const edgeTypes = new Set()
  if (schemaInfoData.edges && Array.isArray(schemaInfoData.edges)) {
    schemaInfoData.edges.forEach(edge => {
      if (edge.edge_type) {
        edgeTypes.add(edge.edge_type)
      }
    })
  }
  availableEdgeTypes.value = Array.from(edgeTypes)

  // 默认全选所有类型
  selectedEntityTypes.value = [...availableEntityTypes.value]
  selectedEdgeTypes.value = [...availableEdgeTypes.value]



  // 不再自动触发可视化数据获取，只在用户点击"查看知识图谱"tab时才查询
}

// 仅更新可用类型列表（不重置用户选择）- 用于数据刷新时
function updateAvailableTypesFromSchema (schemaInfoData: any) {
  if (!schemaInfoData) {
    return
  }

  // 从schemaInfo的entities数组中直接提取实体类型
  const entityTypes = new Set()
  if (schemaInfoData.entities && Array.isArray(schemaInfoData.entities)) {
    schemaInfoData.entities.forEach(entity => {
      if (entity.entity_type) {
        entityTypes.add(entity.entity_type)
      }
    })
  }
  availableEntityTypes.value = Array.from(entityTypes)

  // 从schemaInfo的edges数组中直接提取关系类型
  const edgeTypes = new Set()
  if (schemaInfoData.edges && Array.isArray(schemaInfoData.edges)) {
    schemaInfoData.edges.forEach(edge => {
      if (edge.edge_type) {
        edgeTypes.add(edge.edge_type)
      }
    })
  }
  availableEdgeTypes.value = Array.from(edgeTypes)

}

// 设置模版信息
function setTemplateInfo (schemaInfo: any) {
  if (schemaInfo) {
    detailData.value.templateName = schemaInfo.schema_name || ''
    detailData.value.schemaId = schemaInfo.schema_id || ''
    detailData.value.templateDescription = schemaInfo.schema_desc || ''
    detailData.value.templateCreatedAt = ''
    detailData.value.templateCreatedBy = ''
  } else {
    // 当schemaInfo为null时，清空模版信息
    detailData.value.templateName = ''
    detailData.value.schemaId = ''
    detailData.value.templateDescription = ''
    detailData.value.templateCreatedAt = ''
    detailData.value.templateCreatedBy = ''
  }
}

// 设置文件信息
function setFileInfo (fileInfo: any[]) {
  detailData.value.files = fileInfo.map((f: any) => ({
    id: f.id,
    name: f.title,
    size: f.fileSize, // 单位：字节，需要转换为MB
    source: f.fileFrom === '1' ? proxy.$t('modules.kb.localFileSource') : proxy.$t('modules.kb.knowledgeAccessSource'),
    uploader: f.createdBy || '',
    uploadTime: f.createdDate || ''
  }))
}

/**
 * 只刷新「基本信息」的全量实体/关系计数。
 *
 * 手工增删实体/关系后画布会重新查询（`refreshFromServer`），但详情接口的
 * `stats` 不会跟着变 —— 基本信息页会一直显示改动前的数字。
 * 失败只影响统计显示，吞掉并留下日志，不影响画布。
 */
async function refreshGraphStats () {
  try {
    const res: any = await getKnowledgeGraphBasicInfoApi(route.params.id)
    graphStats.value = resolveGraphStats(res?.stats)
  } catch (error) {
    console.warn('刷新图谱统计失败:', error)
  }
}

/** 只刷新来源文件，不重置实体类型筛选 / 图谱数据。 */
async function refreshSourceFiles () {
  const id = route.params.id
  if (!id) {
    return
  }
  try {
    const res: any = await getKnowledgeGraphBasicInfoApi(id)
    const fileInfo: any[] = Array.isArray(res?.fileInfo) ? res.fileInfo : []
    setFileInfo(fileInfo)
    graphStats.value = resolveGraphStats(res?.stats)
    const maxPage = Math.max(1, Math.ceil(filteredFiles.value.length / 10))
    filePage.value = Math.min(filePage.value, maxPage)
  } catch (error) {
    // 失败保留旧文件列表，让刷新按钮显示重试
    throw error
  }
}

/** 切换详情 ID 时先清空旧资源状态，避免请求失败时继续显示上一个图谱。 */
function resetDetailState () {
  detailData.value = {
    id: '', name: '', description: '', embeddingModel: '', operatorId: '', tableName: '',
    templateName: '', schemaId: '', templateDescription: '', templateCreatedAt: '',
    templateCreatedBy: '', fileCount: 0, source: '', buildStatus: '', buildProgress: 0,
    publishStatus: '', createdBy: '', createdAt: '', lastUpdatedDate: '', files: []
  }
  schemaInfo.value = null
  graphStats.value = null
  graphData.value = { entities: [], edges: [] }
  availableEntityTypes.value = []
  availableEdgeTypes.value = []
  selectedEntityTypes.value = []
  selectedEdgeTypes.value = []
  lastQueryPayload.value = null
  graphResultHasMore.value = false
  // 上一次手动查询 / 「新增实体」遗留的 sticky 数据不能带进下一个图谱，
  // 否则会把 A 的实体合并到 B 的画布上。
  searchKeyword.value = ''
  stickyEnsureEntities.value = []
  stickyEnsureEdges.value = []
  isManualQuery.value = false
  loadedDetailId.value = ''
}

// 获取详情数据
async function fetchDetailData () {
  const id = route.params.id
  if (!id) {
    return false
  }
  resetDetailState()

  try {
    const res = await getKnowledgeGraphBasicInfoApi(id)
    // 连续切换 ID 时先发出的请求可能后返回：只认当前 URL 对应的结果。
    if (route.params.id !== id) {
      return false
    }

    // 根据API返回的数据结构解析
    const data: any = res?.data || {}
    // 数据直接从res中取，等价于从bo中取
    const schemaInfoData: any = res?.schemaInfo || null
    const fileInfo: any[] = Array.isArray(res?.fileInfo) ? res.fileInfo : []

    // 保存schemaInfo数据
    schemaInfo.value = schemaInfoData

    // 全量实体/关系数（后端直接数图存储，与查询条件无关）
    graphStats.value = resolveGraphStats(res?.stats)

    // 设置基本信息
    setBasicInfo(data, id as string)

    // 设置文件信息
    setFileInfo(fileInfo)

    // 只有当schemaInfo存在时才处理模版信息
    if (schemaInfoData) {
      // 从schemaInfo中提取实体和关系类型
      extractEntityAndEdgeTypes(schemaInfoData)
      // 设置模版信息
      setTemplateInfo(schemaInfoData)
    } else {
      // 当schemaInfo为null时，清空模版信息
      setTemplateInfo(null)
    }
    loadedDetailId.value = id
    return true
  } catch (error: any) {
    console.error('获取知识图谱详情失败:', error)
    if (route.params.id !== id) {
      return false
    }
    if (error?.status === 404) {
      // 不存在的 ID：明确提示并回列表，不再渲染一个名称为 "--" 的空详情页。
      proxy.$message.error(proxy.$t('modules.kb.graphNotFound'))
      router.replace({ name: 'graph' })
      return false
    }
    proxy.$message.error(proxy.$t('modules.kb.getDetailFailed'))
    return false
  }
}

// 格式化文件大小（输入单位：字节）
function formatFileSize (bytes: number) {
  if (!bytes || bytes <= 0) {
    return '0 B'
  }

  const kb = bytes / 1024
  if (kb < 1) {
    return `${bytes} B`
  }

  const mb = kb / 1024
  if (mb < 1) {
    return `${Math.round(kb * 10) / 10} KB`
  }

  const gb = mb / 1024
  if (gb >= 1) {
    return `${Math.round(gb * 10) / 10} GB`
  }

  return `${Math.round(mb * 10) / 10} MB`
}

// 关闭按钮处理
// function handleClose () {
//   router.push({ path: '/graph' })
// }

const lastQueryPayload = ref(null)
const isManualQuery = ref(false)
const stickyEnsureEntities = ref<EnsureEntityPayload[]>([])
const stickyEnsureEdges = ref<EnsureEdgePayload[]>([])
// 详情加载完成后记录当前 ID：用来区分「详情已就绪」与「正在切 ID/已被重定向」。
const loadedDetailId = ref('')

// 获取知识图谱可视化数据 - 使用动态查询参数
async function fetchGraphVisualizationData (
  queryPayload = null,
  manual = false,
  ensureEntities: EnsureEntityPayload[] = [],
  ensureEdges: EnsureEdgePayload[] = [],
  preserveSearch = false
) {
  const id = route.params.id
  if (!id) {
    return
  }
  // 详情尚未就绪 / 已切到别的图谱时不要查询，避免旧 schema 或旧数据串台。
  if (loadedDetailId.value !== id) {
    return
  }

  // 记录最后一次查询是否为手动，供刷新时使用
  isManualQuery.value = manual
  if (manual) {
    lastQueryPayload.value = queryPayload
  }

  // 检查schemaInfo是否存在
  if (!schemaInfo.value) {
    proxy.$message.error(proxy.$t('modules.kb.noTemplateInfoForPreview'))
    return
  }

  // 数据查询时清空搜索关键词；工具栏「刷新」要保持用户当前的筛选。
  // **带着 keyword 的查询不清** —— 搜索框现在是真作用于后端的，
  // 清空输入框却显示过滤后的结果，看上去就像搜索没生效。
  const searchKeywordForQuery = String(queryPayload?.keyword ?? searchKeyword.value ?? '').trim()
  if (!preserveSearch && !searchKeywordForQuery) {
    searchKeyword.value = ''
  }
  let effectiveQueryType = currentQueryType.value || 'entity'

  try {
    let response

    // 判断是否为“空查询”：即手动点击查询但没有选择任何类型、没有属性筛选、也没填搜索词
    let isEmptyQuery = false
    if (manual && queryPayload) {
      const filters = queryPayload.filters || []
      // 检查是否包含任何有效的过滤条件（类型或属性）
      const hasAnyCondition = filters.some(f => {
        // 汇总当前过滤对象中可能存在的所有类型字段
        const types = [
          ...(f.entity_type || []),
          ...(f.edge_type || []),
          ...(f.start_entity_type || []),
          ...(f.path_entity_type || []),
          ...(f.path_edge_type || [])
        ]
        // 汇总当前过滤对象中可能存在的所有属性字段
        const properties = f.properties || f.start_entity_properties || f.path_entity_properties || f.path_edge_properties || {}
        return types.length > 0 || Object.keys(properties).length > 0
      })
      // 搜索词也算「有查询条件」：否则只填搜索框点查询会走「空查询」分支，
      // 把 filters=[] 原样发下去 —— 正是 G-1 里「搜什么都是全量」的那条路。
      isEmptyQuery = !hasAnyCondition && !searchKeywordForQuery
    }

    if (manual && queryPayload && !isEmptyQuery) {
      // (2) 手动点击查询按钮 且 有筛选条件，调用 query 接口
      const queryType = queryPayload.queryType || ''
      effectiveQueryType = queryType || effectiveQueryType
      const filters = queryPayload.filters || []
      const direction = queryPayload.direction || 'both'
      const limit = limitValue.value || 1000
      const depth = depthValue.value || 10

      response = await getGraphQueryApi(
        detailData.value.id,
        limit,
        depth,
        direction,
        queryType,
        filters,
        searchKeywordForQuery
      )
    } else {
      // (1) 默认查询、切换 Tab 或 空条件手动查询，调用 query 接口（新接口）
      // 使用保存的查询类型，如果没有则默认为 "entity"
      // 默认参数：limit: 50, filters: [], depth: 10, direction: "both"
      const queryType = (manual && queryPayload?.queryType) || currentQueryType.value || 'entity'
      effectiveQueryType = queryType
      const filters = []
      const limit = limitValue.value || 50
      const depth = depthValue.value || 10
      const direction = (manual && queryPayload?.direction) || 'both'

      response = await getGraphQueryApi(
        detailData.value.id,
        limit,
        depth,
        direction,
        queryType,
        filters,
        searchKeywordForQuery
      )
    }


    // 请求期间用户切到了另一个图谱：丢弃这次响应，别覆盖新画布。
    if (route.params.id !== id || loadedDetailId.value !== id) {
      return
    }

    if (response) {
      // entities / edges 为 null 时按空数组处理
      const entities = response.entities || []
      const edges = response.edges || []
      graphResultHasMore.value = Boolean(response.has_more)

      if (entities.length > 0 || edges.length > 0) {
        // 转换数据格式以适配GraphVisualization组件
        // 实体数据转换：保留原始字段名，取消rid字段
        const transformedEntities = entities.map(entity => ({
          entity_id: entity.entity_id,
          entity_type: entity.entity_type, // 保持原始字段名
          properties: entity.properties || {},
          entity_name: entity.entity_name
          // 取消rid字段
        }))

        // 关系数据转换：保留原始字段名，取消rid、in、out字段
        const transformedEdges = edges.map(edge => ({
          edge_id: edge.edge_id,
          edge_type: edge.edge_type, // 保持原始字段名
          source_id: edge.source_id,
          target_id: edge.target_id,
          properties: edge.properties || {}
          // 取消rid、in、out字段
        }))

        graphData.value = {
          entities: transformedEntities,
          edges: transformedEdges
        }
        mergeEnsureEntitiesIntoGraphData(ensureEntities)
        mergeEnsureEdgesIntoGraphData(ensureEdges)
        syncQueryLimitToLocalCount(effectiveQueryType)

        proxy.$message.success(proxy.$t('modules.kb.loadKnowledgeGraphDataSuccessWithCount', {
          nodeCount: transformedEntities.length,
          edgeCount: transformedEdges.length
        }))
      } else {
        console.warn('图谱可视化数据为空:', response)
        // 无论手动还是自动，结果为空时都清空画布
        graphData.value = { entities: [], edges: [] }
        mergeEnsureEntitiesIntoGraphData(ensureEntities)
        mergeEnsureEdgesIntoGraphData(ensureEdges)
        syncQueryLimitToLocalCount(effectiveQueryType)
        proxy.$message.warning(proxy.$t('modules.kb.queryDataEmpty'))
      }
    } else {
      console.warn('图谱可视化接口响应格式不正确:', response)
      proxy.$message.warning(proxy.$t('modules.kb.knowledgeGraphPreviewNoData'))
      graphResultHasMore.value = false
      graphData.value = { entities: [], edges: [] }
      mergeEnsureEntitiesIntoGraphData(ensureEntities)
      mergeEnsureEdgesIntoGraphData(ensureEdges)
      syncQueryLimitToLocalCount(effectiveQueryType)
    }
  } catch (error) {
    console.error('获取图谱可视化数据失败:', error)
    if (route.params.id !== id || loadedDetailId.value !== id) {
      return
    }
    // proxy.$message.error(proxy.$t('modules.kb.loadKnowledgeGraphDataFailed') + ': ' + (error.message || proxy.$t('modules.kb.unknownError')))
    graphResultHasMore.value = false
    graphData.value = { entities: [], edges: [] }
    mergeEnsureEntitiesIntoGraphData(ensureEntities)
    mergeEnsureEdgesIntoGraphData(ensureEdges)
    syncQueryLimitToLocalCount(effectiveQueryType)
  }
}

// 加载知识图谱预览数据 - 已注释，改为使用接口请求
// async function loadGraphPreviewData () {
//   try {
//     // 动态导入知识图谱预览JSON数据
//     const previewData = await import('@/views/graphView/知识图谱预览.json')

//     if (previewData && previewData.default && previewData.default.data) {
//       return {
//         entities: previewData.default.data.entities || [],
//         edges: previewData.default.data.edges || []
//       }
//     }

//     return { entities: [], edges: [] }
//   } catch (error) {
//     console.error('导入知识图谱预览数据失败:', error)
//     return { entities: [], edges: [] }
//   }
// }

/**
 * 当前画布数量超过 limit 时同步提高 limit，保证后续查询不截断本地已存在数据。
 * - 实体查询按 entities 对齐
 * - 关系查询、子图/路径查询按 edges 对齐
 */
function syncQueryLimitToLocalCount (queryType?: string) {
  const effectiveQueryType = queryType || currentQueryType.value || 'entity'
  const n = effectiveQueryType === 'relation' || effectiveQueryType === 'subgraph'
    ? graphData.value.edges.length
    : graphData.value.entities.length
  if (n > limitValue.value) {
    limitValue.value = n
  }
}

// 控制面板参数变化处理函数
function handleEntityTypeChange (types) {
  selectedEntityTypes.value = types
  // 注意：不再自动触发查询，仅记录状态
}

function handleEdgeTypeChange (types) {
  selectedEdgeTypes.value = types
  // 注意：不再自动触发查询，仅记录状态
}

function handleLimitChange (value) {
  // 防止null或undefined值导致重置
  if (value === null || value === undefined || Number.isNaN(value)) {
    console.warn('Limit值无效，保持当前值:', limitValue.value)
    return
  }
  limitValue.value = value
  // 注意：不再自动触发查询，仅记录状态
}

function handleDepthChange (value) {
  depthValue.value = value
  // 注意：不再自动触发查询，仅记录状态
}

function handleSearchInput (keyword) {
  searchKeyword.value = keyword
}

function handleSearchClear () {
  searchKeyword.value = ''
}

function handleQueryTypeChange (queryType) {
  // 当用户切换查询类型时，保存当前的查询类型
  currentQueryType.value = queryType || 'entity'
}

async function handleExecuteQuery (payload) {
  // 保存当前查询类型，即使没有条件也要保存
  if (payload && payload.queryType) {
    currentQueryType.value = payload.queryType
  }
  if (activeTab.value === 'viewGraph') {
    // 用户主动触发自定义查询时，以查询条件结果为准，清空历史累计缓存
    stickyEnsureEntities.value = []
    stickyEnsureEdges.value = []

    const loadingMsg = proxy.$message({
      message: proxy.$t('modules.kb.requestingData'),
      type: 'info',
      duration: 0
    })
    try {
      await fetchGraphVisualizationData(payload, true, [], [])
      // 查询结果（尤其是把 Limit 调小）可能落在原视口之外，查询后重新适配画布。
      // 等两帧：GraphVisualization → GraphCanvasVis 的 DataSet 同步发生在下一轮 flush。
      await nextTick()
      await graphVisRef.value?.restoreLayoutAfterRefresh?.()
      await new Promise(resolve => requestAnimationFrame(resolve))
      if (graphData.value.entities.length || graphData.value.edges.length) {
        graphVisRef.value?.fitViewImmediate?.()
      }
    } finally {
      if (loadingMsg?.close) {
        loadingMsg.close()
      }
    }
  }
}

/**
 * 当服务端按原查询条件未返回新增实体时，使用自定义查询接口补查该实体并合并。
 */
interface EnsureEntityPayload {
  entity_id: string
  entity_type: string
  entity_name?: string
  properties?: Record<string, unknown>
}

interface EnsureEdgePayload {
  edge_id: string
  edge_type: string
  source_id: string
  target_id: string
  properties?: Record<string, unknown>
}

function mergeEnsureEntitiesIntoGraphData (ensureEntities: EnsureEntityPayload[] = []) {
  if (!ensureEntities.length) {
    return
  }

  ensureEntities.forEach(item => {
    if (!item?.entity_id || !item?.entity_type) {
      return
    }

    const exists = graphData.value.entities.some(
      current => String(current.entity_id) === String(item.entity_id)
    )
    if (!exists) {
      graphData.value.entities.push({
        entity_id: item.entity_id,
        entity_type: item.entity_type,
        entity_name: item.entity_name || item.entity_id,
        properties: item.properties || {}
      })
    }
  })
}

function mergeEnsureEdgesIntoGraphData (ensureEdges: EnsureEdgePayload[] = []) {
  if (!ensureEdges.length) {
    return
  }

  ensureEdges.forEach(item => {
    if (!item?.edge_id || !item?.source_id || !item?.target_id) {
      return
    }

    const hasSource = graphData.value.entities.some(
      current => String(current.entity_id) === String(item.source_id)
    )
    const hasTarget = graphData.value.entities.some(
      current => String(current.entity_id) === String(item.target_id)
    )
    if (!hasSource || !hasTarget) {
      return
    }

    const exists = graphData.value.edges.some(
      current => String(current.edge_id) === String(item.edge_id)
    )
    if (!exists) {
      graphData.value.edges.push({
        edge_id: item.edge_id,
        edge_type: item.edge_type,
        source_id: item.source_id,
        target_id: item.target_id,
        properties: item.properties || {}
      })
    }
  })
}

function upsertStickyEnsureEntities (entities: EnsureEntityPayload[] = []) {
  entities.forEach(item => {
    if (!item?.entity_id || !item?.entity_type) {
      return
    }
    const index = stickyEnsureEntities.value.findIndex(
      current => String(current.entity_id) === String(item.entity_id)
    )
    if (index >= 0) {
      stickyEnsureEntities.value[index] = { ...stickyEnsureEntities.value[index], ...item }
      return
    }
    stickyEnsureEntities.value.push({ ...item })
  })
}

function upsertStickyEnsureEdges (edges: EnsureEdgePayload[] = []) {
  edges.forEach(item => {
    if (!item?.edge_id || !item?.source_id || !item?.target_id) {
      return
    }
    const index = stickyEnsureEdges.value.findIndex(
      current => String(current.edge_id) === String(item.edge_id)
    )
    if (index >= 0) {
      stickyEnsureEdges.value[index] = { ...stickyEnsureEdges.value[index], ...item }
      return
    }
    stickyEnsureEdges.value.push({ ...item })
  })
}

function purgeStickyByDeletedEntityId (deletedEntityId?: string) {
  if (!deletedEntityId) {
    return
  }
  stickyEnsureEntities.value = stickyEnsureEntities.value.filter(
    item => String(item.entity_id) !== String(deletedEntityId)
  )
  stickyEnsureEdges.value = stickyEnsureEdges.value.filter(
    edge => String(edge.source_id) !== String(deletedEntityId) &&
      String(edge.target_id) !== String(deletedEntityId)
  )

  // 同步移除当前画布数据（避免本次 refresh merge 仍残留）
  graphData.value.entities = graphData.value.entities.filter(
    item => String(item.entity_id) !== String(deletedEntityId)
  )
  graphData.value.edges = graphData.value.edges.filter(
    edge => String(edge.source_id) !== String(deletedEntityId) &&
      String(edge.target_id) !== String(deletedEntityId)
  )
}

function purgeStickyByDeletedEdgeId (deletedEdgeId?: string) {
  if (!deletedEdgeId) {
    return
  }
  stickyEnsureEdges.value = stickyEnsureEdges.value.filter(
    edge => String(edge.edge_id) !== String(deletedEdgeId)
  )
  graphData.value.edges = graphData.value.edges.filter(
    edge => String(edge.edge_id) !== String(deletedEdgeId)
  )
}

async function ensureEntityIncludedByCustomQuery (ensureEntity?: EnsureEntityPayload) {
  if (!ensureEntity || !ensureEntity.entity_id || !ensureEntity.entity_type) {
    return
  }

  const exists = graphData.value.entities.some(
    item => String(item.entity_id) === String(ensureEntity.entity_id)
  )
  if (exists) {
    return
  }

  try {
    const baseLimit = Math.max(limitValue.value || DEFAULT_LIMIT_VALUE, MIN_ENTITY_RECOVERY_QUERY_LIMIT)
    const fallbackFilter = {
      entity_type: [ensureEntity.entity_type],
      properties: {}
    }

    const properties = ensureEntity.properties || {}
    const firstValidEntry = Object.entries(properties).find(([, value]) => {
      return value !== null && value !== undefined && String(value).trim() !== ''
    })

    const candidateFilters = [fallbackFilter]
    if (firstValidEntry) {
      const [propertyName, propertyValue] = firstValidEntry
      candidateFilters.unshift({
        entity_type: [ensureEntity.entity_type],
        properties: {
          [propertyName]: {
            op: 'eq',
            value: propertyValue
          }
        }
      })
    }

    for (const filter of candidateFilters) {
      const response = await getGraphQueryApi(
        detailData.value.id,
        baseLimit,
        depthValue.value || DEFAULT_DEPTH_VALUE,
        'both',
        'entity',
        [filter]
      )

      const entities = response?.entities || []
      const edges = response?.edges || []
      const target = entities.find(
        item => String(item.entity_id) === String(ensureEntity.entity_id)
      )

      if (!target) {
        continue
      }

      const transformedEntity = {
        entity_id: target.entity_id,
        entity_type: target.entity_type,
        properties: target.properties || {},
        entity_name: target.entity_name
      }

      const transformedEdges = edges.map(edge => ({
        edge_id: edge.edge_id,
        edge_type: edge.edge_type,
        source_id: edge.source_id,
        target_id: edge.target_id,
        properties: edge.properties || {}
      }))

      const hasEntity = graphData.value.entities.some(
        item => String(item.entity_id) === String(transformedEntity.entity_id)
      )
      if (!hasEntity) {
        graphData.value.entities.push(transformedEntity)
      }

      transformedEdges.forEach(edge => {
        const hasEdge = graphData.value.edges.some(
          item => String(item.edge_id) === String(edge.edge_id)
        )
        if (!hasEdge) {
          graphData.value.edges.push(edge)
        }
      })

      syncQueryLimitToLocalCount('entity')
      return
    }
  } catch (error) {
    console.warn('补查新增实体失败：', error)
  }
}


/**
 * 工具栏「刷新知识图谱」：重新按最后一次查询取服务端数据。
 * 保留名称 / 类型 / 高级查询与当前选中、缩放（fetch 内走增量同步，不重建画布）。
 */
async function refreshGraphFromServer () {
  await handleRefreshGraphData({ refreshFromServer: true }, true)
  // 位置缓存存的是收拢前的基准布局；刷新不会重跑物理，需按当前画布再收拢一次。
  await graphVisRef.value?.restoreLayoutAfterRefresh?.()
}

// 处理实体更新后的数据刷新（优化版本，避免不必要的重新渲染）
async function handleRefreshGraphData (data: any, preserveSearch = false) {

  if (data && data.startLoading) {
    graphLoading.value = true
    return
  }

  if (data && data.stopLoading) {
    graphLoading.value = false
    return
  }

  if (data && data.refreshFromServer) {
    purgeStickyByDeletedEntityId(data.deletedEntityId)
    purgeStickyByDeletedEdgeId(data.deletedEdgeId)
    const ensureEntities = data.ensureEntity ? [data.ensureEntity] : []
    const ensureEdges = Array.isArray(data.ensureEdges) ? data.ensureEdges : []
    upsertStickyEnsureEntities(ensureEntities)
    upsertStickyEnsureEdges(ensureEdges)
    await fetchGraphVisualizationData(
      lastQueryPayload.value,
      isManualQuery.value,
      stickyEnsureEntities.value,
      stickyEnsureEdges.value,
      preserveSearch
    )
    await ensureEntityIncludedByCustomQuery(data.ensureEntity)
    // 手工增删实体/关系后同步基本信息页的全量计数（不阻塞画布刷新）
    refreshGraphStats()
    return
  }

  // 数据更新时清空搜索关键词
  searchKeyword.value = ''

  if (data && data.entities && data.edges) {
    // 优化：检查是否为增量更新
    const isIncrementalUpdate = data.incremental === true

    if (isIncrementalUpdate) {
      // 增量更新：只添加/更新数据，不替换整个数组，不触发 loading

      if (data.addedEntities && data.addedEntities.length > 0) {
        upsertStickyEnsureEntities(data.addedEntities)
        data.addedEntities.forEach(newEntity => {
          const existingIndex = graphData.value.entities.findIndex(
            e => (e.entity_id || e.id) === (newEntity.entity_id || newEntity.id)
          )
          if (existingIndex === -1) {
            graphData.value.entities.push(newEntity)
          }
        })
      }
      if (data.updatedEntities && data.updatedEntities.length > 0) {
        upsertStickyEnsureEntities(data.updatedEntities)
        data.updatedEntities.forEach(upd => {
          const idx = graphData.value.entities.findIndex(
            e => (e.entity_id || e.id) === (upd.entity_id || upd.id)
          )
          if (idx >= 0) {
            graphData.value.entities[idx] = upd
          }
        })
      }
      if (data.addedEdges && data.addedEdges.length > 0) {
        upsertStickyEnsureEdges(data.addedEdges)
        data.addedEdges.forEach(newEdge => {
          const existingIndex = graphData.value.edges.findIndex(
            e => (e.edge_id || e.id) === (newEdge.edge_id || newEdge.id)
          )
          if (existingIndex === -1) {
            graphData.value.edges.push(newEdge)
          }
        })
      }
      if (data.updatedEdges && data.updatedEdges.length > 0) {
        upsertStickyEnsureEdges(data.updatedEdges)
        data.updatedEdges.forEach(upd => {
          const idx = graphData.value.edges.findIndex(
            e => (e.edge_id || e.id) === (upd.edge_id || upd.id)
          )
          if (idx >= 0) {
            graphData.value.edges[idx] = upd
          }
        })
      }

      syncQueryLimitToLocalCount()

    } else {
      // 全量更新：替换整个数组
      graphData.value.entities = data.entities
      graphData.value.edges = data.edges


      // 注意：实体类型和关系类型应该始终来自schema定义，而不是从graphData中提取
      // 这样可以确保即使画布上没有某个类型的实体，下拉框仍然显示schema中定义的所有类型
      // 如果schemaInfo存在，更新可用类型列表（保持用户当前的选择）
      if (schemaInfo.value) {
        // 只更新可用类型列表，不重置用户的选择
        updateAvailableTypesFromSchema(schemaInfo.value)
      } else {
        console.warn('schemaInfo不存在，无法更新实体类型和关系类型列表')
      }


      // 强制触发响应式更新
      nextTick(() => {
      })

      // 显示成功消息
      proxy.$message.success(proxy.$t('modules.kb.entityUpdateSuccessGraphRefreshed'))
    }
  } else {
    console.warn('刷新数据格式异常:', data)
    // 子组件已处理成功提示；此处仅记录日志，避免重复提示“更新成功但刷新失败”
  }
}

async function requestViewGraphData () {
  const requestId = route.params.id
  // 详情还没加载完（或正在切 ID）时先不查：否则 schema 被清空后会误报「模版不存在」。
  if (!requestId || loadedDetailId.value !== requestId) {
    return
  }
  // 等 tab 内容挂载并完成一帧布局后再请求，避免子组件容器尚未有尺寸导致图谱不展示
  await nextTick()
  await new Promise(resolve => requestAnimationFrame(resolve))
  if (route.params.id !== requestId || loadedDetailId.value !== requestId) {
    return
  }
  const loadingMsg = proxy.$message({
    message: proxy.$t('modules.kb.requestingData'),
    type: 'info',
    duration: 0
  })
  try {
    await fetchGraphVisualizationData(
      null,
      false,
      stickyEnsureEntities.value,
      stickyEnsureEdges.value
    )
  } finally {
    if (loadingMsg?.close) {
      loadingMsg.close()
    }
    graphResetToken.value += 1
  }
}

// 监听tab切换：先拉取数据，再递增 resetToken，保证画布用新数据做完整重渲染
watch(activeTab, async newTab => {
  if (newTab === 'viewGraph') {
    // 同一导航同时换 ID 与 tab 时，本 watcher 会先于 id watcher 触发；
    // 此时详情尚未加载，交给 id watcher 加载完成后再查询，避免误报“模版不存在”。
    if (route.params.id !== loadedDetailId.value) {
      return
    }
    await requestViewGraphData()
  } else {
    // 离开知识图谱页签时退出沉浸画布
    graphVisRef.value?.exitFullscreen?.()
  }
})

// 同一路由只变参数时 Vue Router 会复用组件实例：重新拉详情并清空旧状态，
// 否则 URL 已换到新 ID/无效 ID，页面仍显示上一个图谱的名称与数据。
watch(() => route.params.id, async (id, previous) => {
  if (!id || id === previous) {
    return
  }
  const ok = await fetchDetailData()
  if (ok && activeTab.value === 'viewGraph') {
    await requestViewGraphData()
  }
})

onMounted(async () => {
  loadOperatorList()
  const ok = await fetchDetailData()
  if (ok && activeTab.value === 'viewGraph') {
    await requestViewGraphData()
  }
})
</script>

<style lang="less" scoped>
.knowledge-graph-detail-page {
  /* height/padding/background 由 src/styles/workspaces.css 的
     .workspace-page 统一给，不再叠加旧的主题兜底值。 */
  min-height: 0;
  display: flex;
  flex-direction: column;

  /* 沉浸画布时隐藏页头与页签栏，画布组件自己覆盖整个窗口。 */
  &.is-graph-fullscreen :deep(.workspace-header),
  &.is-graph-fullscreen .detail-tabs :deep(.el-tabs__header) {
    display: none;
  }
}

/* 页头/面包屑/标题/图标/操作区都由 WorkspaceShell 渲染，样式在全局
   styles/workspaces.css。scoped 规则够不到子组件 DOM（会编译成 `.xxx[data-v-本页]`），
   这里再写一遍只会造成假象。 */

// 页签吃掉面包屑之外的剩余高度：header 固定，content 拉伸
.detail-tabs {
  flex: 1 1 auto;
  min-height: 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  /* 页签紧接 workspace-body 的首个位置（页头与 body 之间只有
     .workspace-page 的 24px gap），这里再加 margin 会把整块内容下推 24px */
  margin-top: 0;
}

/* 页签栏 47px（nav-wrap 48 含 -1 边框） */
.detail-tabs :deep(.el-tabs__header) {
  height: 47px;
  margin-bottom: 0;
}

.detail-tabs :deep(.el-tabs__nav-wrap) {
  height: 48px;
}

.detail-tabs :deep(.el-tabs__content) {
  flex: 1 1 auto;
  min-height: 0;
}

.detail-tabs :deep(.el-tab-pane) {
  height: 100%;
}

// 不要给 .detail-tabs :deep(.el-tabs__content) 加 padding：
// 内容区当前 `padding: 0`，画布 tab 的内容紧贴页签栏
// （`.controls-wrapper` y = 页签条底部 + 8px）。加上下各 20px 会把查询面板和画布整体下推。

/* ── 基本信息页 ─────────────────────────────────────────────── */
.graph-info {
  height: 100%;
  min-height: 0;
  /* 页签与内容之间由 workspace-body 的 16px gap 隔开；
     本页内容在 el-tab-pane 里，用上内距补同样的 16px */
  padding-top: 16px;
  overflow-y: auto;
  scrollbar-gutter: stable;
  position: relative;
}

.gi-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 0 4px 8px 0;
}

.gi-summary {
  display: flex;
  align-items: center;
  gap: 32px;
  padding: 18px 24px;
  background: var(--rs-bg-soft);
  border: 1px solid var(--rs-border-soft);
  border-radius: var(--rs-radius);
}

.gi-metric {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.gi-metric-value {
  display: flex;
  align-items: baseline;
  gap: 8px;
  color: var(--rs-text);
  font-size: var(--rs-overview-value-size-compact);
  font-weight: 650;
  line-height: 1.4;
  font-variant-numeric: tabular-nums;
}

.gi-metric-value span {
  font-weight: 400;
}

.gi-icon {
  width: 36px;
  height: 36px;
  border-radius: 9px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--tint, var(--rs-bg-soft));
  color: var(--tone, var(--rs-text-3));
}

.gi-icon svg {
  width: 19px;
  height: 19px;
}

.gi-live,
.gi-note {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--rs-text-3);
}

.gi-live {
  white-space: nowrap;
}

.gi-live svg,
.gi-note svg {
  width: 14px;
  height: 14px;
}

.gi-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
  gap: 20px;
}

.gi-card {
  min-width: 0;
  padding: 22px 24px;
  border: 1px solid var(--rs-border);
  border-radius: var(--rs-radius);
  background: var(--rs-bg-card);
}

.gi-heading {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  min-width: 0;
}

.gi-heading h2 {
  margin: 0;
  color: var(--rs-text);
}

.gi-heading p {
  margin: 4px 0 0;
  color: var(--rs-text-3);
}

.gi-properties {
  margin: 0;
}

.gi-properties > div {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr);
  gap: 16px;
  padding: 13px 0;
  border-bottom: 1px solid var(--rs-border-soft);
}

.gi-properties > div:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}

.gi-properties dt {
  color: var(--rs-text-3);
}

.gi-properties dd {
  margin: 0;
  min-width: 0;
  color: var(--rs-text);
  overflow-wrap: anywhere;
}

.gi-description {
  white-space: pre-wrap;
  line-height: 1.8;
}

.gi-copy {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.gi-copy code {
  min-width: 0;
  font-size: var(--rs-font-size-code);
  line-height: 1.8;
}

.gi-copy button {
  flex-shrink: 0;
  margin-left: auto;
}

.gi-config > div {
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
}

.gi-model {
  white-space: normal;
  overflow-wrap: anywhere;
  max-width: 100%;
}

.gi-types {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.gi-types .tag-soft {
  margin: 0;
}

.gi-types i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.gi-count {
  display: inline-block;
  margin-left: 8px;
  padding: 0 7px;
  border-radius: 4px;
  background: var(--rs-bg-soft);
  color: var(--rs-text-2);
  vertical-align: middle;
  font-weight: 500;
}

.gi-file-heading {
  flex-wrap: wrap;
}

.gi-file-controls {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-left: auto;
  max-width: 100%;
  min-width: 0;
}

.gi-file-search {
  width: 240px;
  margin-left: auto;
}

.gi-table {
  border-radius: 6px;
}

.gi-table table {
  min-width: 720px;
  table-layout: fixed;
}

.gi-table th:first-child {
  width: 36%;
}

.gi-table th:nth-child(2) {
  width: 13%;
}

.gi-table th:nth-child(3) {
  width: 15%;
}

.gi-table th:nth-child(4) {
  width: 12%;
}

.gi-table th:last-child {
  width: 24%;
}

.gi-table td {
  overflow-wrap: anywhere;
}

.gi-file-name {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  color: var(--rs-text);
}

.gi-file-name svg {
  color: var(--rs-primary);
  margin-top: 1px;
}

.gi-file-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 28px 16px;
  background: var(--rs-bg-soft);
  border-radius: 6px;
}

.gi-file-empty p {
  margin: 0;
}

.gi-file-empty p + p {
  margin-top: 5px;
  color: var(--rs-text-3);
}

.gi-file-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 16px;
}

.gi-note {
  margin: 0;
}

@media (max-width: 1150px) {
  .gi-layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .gi-config > div {
    grid-template-columns: 116px minmax(0, 1fr);
    gap: 16px;
  }

  .gi-summary {
    gap: 16px;
  }

  .gi-live {
    display: none;
  }
}

@media (max-width: 700px) {
  .gi-content {
    padding-right: 0;
    gap: 16px;
  }

  .gi-summary {
    padding: 14px 12px;
    gap: 12px;
  }

  .gi-metric {
    gap: 0;
  }

  .gi-metric > .gi-icon {
    display: none;
  }

  .gi-card {
    padding: 18px 16px;
  }

  .gi-properties > div,
  .gi-config > div {
    grid-template-columns: minmax(0, 1fr);
    gap: 7px;
  }

  .gi-file-search {
    width: 100%;
  }

  .gi-file-controls {
    width: 100%;
    margin-left: 0;
  }

  .gi-file-empty {
    align-items: flex-start;
    padding: 20px 12px;
  }

  .gi-note {
    align-items: flex-start;
  }
}

.view-graph-content {
  // 高度由父级 flex 给足；画布自己 flex:1 吃掉控制面板之外的空间，不产生滚动条
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  justify-content: flex-start;
  overflow: hidden;
}

:deep(.el-tabs__header) {
  align-items: center;
  display: flex;
  justify-content: space-between;
  margin: 0 0 8px;
  padding: 0;
  position: relative;
  // 不能用 97.5vw：视口里还含 256px 左栏 + 32px 页面内边距，
  // 97.5vw 比实际可用宽度多出约 208px，直接把主区撑出横向滚动条。
  width: 100%;
  flex: 0 0 auto;
}

</style>

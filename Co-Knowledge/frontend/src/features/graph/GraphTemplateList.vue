<template>
  <div class="knowledge-graph-template-page">
    <input
      ref="uploadInput"
      type="file"
      accept=".zip"
      style="display: none"
      @change="onFileChange"
    />

    <div class="toolbar">
      <div class="toolbar-left">
        <el-button type="primary" @click="createKnowledgeGraphTemplateHandle">
          <Plus />
          {{ $t('modules.kb.createKnowledgeGraphTemplate') }}
        </el-button>
        <el-button @click="handleUpload">
          {{ $t('public.import') }}
        </el-button>
        <el-button @click="handleDownloadStaticTemplate">
          {{ $t('modules.kb.downloadTemplate') }}
        </el-button>
      </div>
      <div class="toolbar-right">
        <el-input
          v-model.trim="searchKey"
          class="search-field"
          :placeholder="$t('modules.kb.searchKnowledgeGraphTemplateName')"
          :prefix-icon="Search"
          clearable
          @input="search"
        />
      </div>
    </div>

    <div v-loading="loading" class="table-card">
      <table class="list-table template-table">
        <thead>
          <tr>
            <th class="sortable" @click="toggleSort('name')">
              {{ $t('modules.kb.knowledgeGraphTemplateName') }}
              <DCaret class="sort-icon" />
            </th>
            <th class="sortable" @click="toggleSort('schema_id')">
              {{ $t('modules.kb.knowledgeGraphTemplateId') }}
              <DCaret class="sort-icon" />
            </th>
            <th>{{ $t('modules.kb.knowledgeGraphTemplateDescription') }}</th>
            <th class="sortable" @click="toggleSort('createdBy')">
              {{ $t('public.creator') }}
              <DCaret class="sort-icon" />
            </th>
            <th class="sortable" @click="toggleSort('createTime')">
              {{ $t('app.createTime') }}
              <DCaret class="sort-icon" />
            </th>
            <th>{{ $t('public.operate') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td>
              <a class="entity-title entity-link" @click="handleEditTemplate(row)">
                {{ row.name || '--' }}
              </a>
            </td>
            <td class="nowrap">{{ row.schema_id || '--' }}</td>
            <td>
              <div class="template-description" :title="row.description || '--'">
                {{ row.description || '--' }}
              </div>
            </td>
            <td>{{ row.createdBy || '--' }}</td>
            <td class="nowrap">{{ formatTimestamp(row.createTime) }}</td>
            <td>
              <div class="row-actions">
                <el-button link type="primary" @click="handleExportTemplate(row)">
                  {{ $t('public.export') }}
                </el-button>
                <el-button link type="primary" @click="deleteKnowledgeGraphTemplateHandle(row)">
                  {{ $t('public.delete') }}
                </el-button>
              </div>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="6" class="empty-row">{{ $t('public.noData') }}</td>
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

    <!-- 删除确认对话框 -->
    <DangerConfirmDialog
      ref="dangerConfirmDialogRef"
      :title="$t('public.delete')"
      :confirm-text="$t('public.delete')"
      :cancel-text="$t('public.cancel')"
      @confirm="handleDeleteConfirm"
    />

    <!-- 新建图谱模版对话框 -->
    <CreateKnowledgeGraphTemplateDialog ref="createDialogRef" />
  </div>
</template>
<script setup lang="ts">
import { ref, getCurrentInstance, onMounted, inject, watch } from 'vue'
import { debounce } from 'lodash'
import { DEBOUNCETIME } from '@/shared/constants/index'
import { Search, DCaret, Plus } from '@element-plus/icons-vue'
import TablePagination from '@/shared/ui/reference/TablePagination.vue'
import DangerConfirmDialog from '@/shared/ui/DangerConfirmDialog.vue'
import CreateKnowledgeGraphTemplateDialog from '@/features/graph/CreateKnowledgeGraphTemplateDialog.vue'
import {
  uploadKnowledgeGraphTemplateApi,
  knowledgeGraphTemplateListApi,
  deleteKnowledgeGraphTemplateApi,
  getGraphSchemaTemplateDetail
} from '@/features/graph/api/knowledgeGraph'
import { formatTimestamp } from './lib/graph-template-common'
// 表格高度自适应（写死高度会把分页条挤出可视区），与文档知识库列表页共用
import {
  createZipFromExportData,
  extractSchemaDataFromResponse,
  transformSchemaDataToExportFormat
} from './lib/graph-template-export'

interface KnowledgeGraphTemplateItem {
  id: string
  name: string
  schema_id: string
  description: string
  createTime: number
  createdBy: string
}

const { proxy } = getCurrentInstance() as any

// 注入父组件提供的当前激活tab
const activeTabName = inject<any>('activeTabName', ref(''))

// 搜索关键词
const searchKey = ref('')

// 原生表格状态（列表契约：内容自然高度 + 整页滚动）
const rows = ref<KnowledgeGraphTemplateItem[]>([])
const currentPage = ref(1)
const pageSize = ref(10)
const total = ref(0)
const loading = ref(false)
const sortProp = ref('')
const sortDir = ref('')

// 删除对话框引用
const dangerConfirmDialogRef = ref()
// 当前要删除的知识图谱模版信息
const currentDeleteTemplate = ref<{id: string, name: string} | null>(null)

// 上传文件输入框引用
const uploadInput = ref<HTMLInputElement | null>(null)

// 新建对话框引用
const createDialogRef = ref()

// 搜索功能
const search = debounce(() => {
  refreshTableData('initPage')
}, DEBOUNCETIME)

// 获取表格数据的API函数
function getTableDataApi (params: any, config: any) {
  // 该接口不需要任何查询参数，返回所有数据
  // 前端需要自行处理搜索、排序和分页
  return knowledgeGraphTemplateListApi(params, config).then(response => {
    // 后端返回数据在 bo 字段中，需要进行字段映射
    const rawData = response || []

    // 映射后端字段到前端字段
    let data = rawData.map((item: any) => ({
      id: item.schemaId || item.id,
      name: item.schemaName || item.name,
      schema_id: item.schemaId || item.schema_id,
      description: item.schemaDesc || item.description,
      createTime: item.createTime ? Number(item.createTime) : 0,
      createdBy: item.createUser || item.createdBy
    }))

    // 1. 搜索过滤
    if (searchKey.value) {
      const keyword = searchKey.value.toLowerCase()
      data = data.filter((item: KnowledgeGraphTemplateItem) => {
        return item.name?.toLowerCase().includes(keyword) ||
               item.schema_id?.toLowerCase().includes(keyword) ||
               item.description?.toLowerCase().includes(keyword)
      })
    }

    // 2. 排序处理（点表头切换升/降序）
    if (sortProp.value && sortDir.value) {
      const prop = sortProp.value
      const direction = sortDir.value
      data = [...data].sort((a: any, b: any) => {
        const aVal = a[prop] ?? ''
        const bVal = b[prop] ?? ''
        if (aVal === bVal) {
          return 0
        }
        const result = aVal > bVal ? 1 : -1
        return direction === 'asc' ? result : -result
      })
    }

    // 3. 分页处理
    const defaultPageSize = 10
    const { pageSize = defaultPageSize, currentPage = 1 } = params
    const total = data.length
    const start = (currentPage - 1) * pageSize
    const end = start + pageSize
    const pageData = data.slice(start, end)

    // 返回符合 TableGroup 组件期望的分页格式
    return {
      items: pageData,
      total,
      page: currentPage,
      pageSize
    }
  })
}

function toggleSort (prop: string) {
  if (sortProp.value === prop) {
    if (sortDir.value === 'asc') {
      sortDir.value = 'desc'
    } else if (sortDir.value === 'desc') {
      sortProp.value = ''
      sortDir.value = ''
    } else {
      sortDir.value = 'asc'
    }
  } else {
    sortProp.value = prop
    sortDir.value = 'asc'
  }
  refreshTableData('initPage')
}

async function loadRows (background = false) {
  if (!background) {
    loading.value = true
  }
  try {
    const result: any = await getTableDataApi(
      { currentPage: currentPage.value, pageSize: pageSize.value },
      {}
    )
    const data = Array.isArray(result?.items) ? result.items : []
    rows.value = data
    total.value = Number(result?.total) || data.length
  } catch {
    // 错误提示由拦截器统一弹；表格保持上一屏数据
    rows.value = []
    total.value = 0
  } finally {
    if (!background) {
      loading.value = false
    }
  }
}

// 刷新表格数据；background=true 是后台静默刷新（不挂转圈）
function refreshTableData (initPage = '', background = false) {
  if (initPage) {
    currentPage.value = 1
  }
  return loadRows(background)
}

function onPaginationChange ({ page, size }: { page: number, size: number }) {
  currentPage.value = page
  pageSize.value = size
  loadRows()
}

// 上传文件处理
function handleUpload () {
  uploadInput.value?.click()
}

// 下载静态模板文件（从 assets/template 目录，根据语言选择对应的模板）
async function handleDownloadStaticTemplate () {
  try {
    // 根据当前语言环境选择模板文件
    const isZh = proxy.$i18n.locale === 'zh'
    const fileName = isZh ? 'import_graph_schema_template_ZH.zip' : 'import_graph_schema_template_EN.zip'

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

function onFileChange (e: Event) {
  const files = (e.target as HTMLInputElement).files
  if (!files || files.length === 0) {
    return
  }
  const file = files[0]

  // 验证文件格式
  if (!file.name.endsWith('.zip')) {
    proxy.$message({
      message: proxy.$t('knowledge.uploadFileTip1', { type: 'ZIP' }),
      type: 'error'
    })
    return
  }

  // 验证ZIP文件大小（前端验证：不超过1MB）
  const maxZipFileSize = 1024 * 1024 // 1MB
  if (file.size > maxZipFileSize) {
    proxy.$message({
      message: proxy.$t('modules.kb.graphTemplateMaxSizeTip'),
      type: 'error'
    })
    return
  }

  // 注意：解压后文件大小（不超过10MB）的验证由后端接口完成
  // 前端只验证压缩包本身的大小，以提供更好的用户体验

  // 调用上传接口
  uploadKnowledgeGraphTemplateApi(file).then(response => {
    // 根据响应数据显示详细信息

    // 检查响应是否成功
    if (response.success === false) {
      // API层面已经处理了错误，直接显示错误信息
      return
    }

    // 后端返回的数据在 bo 字段中
    const responseData = response
    const { successCount, failedCount, failedDetails } = responseData

    if (failedCount > 0) {
      // 部分失败或全部失败
      let errorMessage = proxy.$t('modules.kb.importCompleteWithPartialFailure', {
        successCount,
        failedCount
      })

      if (failedDetails && failedDetails.length > 0) {
        // 格式化失败详情，包含文件名和错误信息
        const failedDetailsList = failedDetails.map((item: any) => {
          const fileName = item.file || proxy.$t('modules.knowledgeGraphStudio.common.unknownFile')
          const errorMsg = item.error || proxy.$t('modules.knowledgeGraphStudio.common.unknownError')
          return `${fileName}: ${errorMsg}`
        })
        const failedDetailsText = proxy.$t('modules.kb.importFailedDetails', {
          details: `[${failedDetailsList.join(';')}]`
        })
        errorMessage = `${errorMessage}\n${failedDetailsText}`
      }

      if (successCount > 0) {
        // 部分成功
        proxy.$message({
          message: errorMessage,
          type: 'warning',
          duration: 8000 // 延长显示时间以便查看详情
        })
      } else {
        // 全部失败
        proxy.$message({
          message: errorMessage,
          type: 'error',
          duration: 8000
        })
      }
    } else {
      // 全部成功
      proxy.$message({
        message: proxy.$t('modules.kb.importCompleteAllSuccess', { successCount }),
        type: 'success'
      })
    }

    // 刷新表格数据
    refreshTableData()
  })
    .catch(error => {
      // 只在网络错误或其他未处理的异常时显示错误消息
      console.error('上传失败:', error)
      proxy.$message({
        message: `${proxy.$t('modules.kb.importFailed')}：${error.message || proxy.$t('public.noData')}`,
        type: 'error'
      })
    })

  // 上传后清空input
  if (uploadInput.value) {
    uploadInput.value.value = ''
  }
}

function createKnowledgeGraphTemplateHandle () {
  // 打开新建图谱模板对话框，让用户先填写模板信息
  if (createDialogRef.value) {
    createDialogRef.value.openDialog()
  }
}

// 编辑图谱模板
function handleEditTemplate (row: KnowledgeGraphTemplateItem) {
  // Navigate to graph template designer page with template ID
  proxy.$router.push({
    name: 'graph-template',
    params: {
      templateId: row.id
    }
  })
}

// 删除图谱模版
function deleteKnowledgeGraphTemplateHandle (row: KnowledgeGraphTemplateItem) {
  currentDeleteTemplate.value = { id: row.id, name: row.name }
  dangerConfirmDialogRef.value.openDialog({
    message: proxy.$t('modules.kb.deleteKnowledgeGraphTemplateConfirm', { name: row.name }),
    description: proxy.$t('messageBox.deleteTips')
  })
}

// 处理删除确认
function handleDeleteConfirm ({ done, setLoading }: { done: () => void, setLoading: (loading: boolean) => void }) {
  if (!currentDeleteTemplate.value) {
    done()
    return
  }

  deleteKnowledgeGraphTemplateApi(currentDeleteTemplate.value.id)
    .then(() => {
      proxy.$message.success(proxy.$t('public.deleteSuccess'))
      refreshTableData()
      done()
    })
    .catch(() => {
      setLoading(false)
    })
    .finally(() => {
      currentDeleteTemplate.value = null
    })
}

// 下载ZIP文件
function downloadZipFile (zipBlob: Blob, fileName: string): void {
  const url = URL.createObjectURL(zipBlob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

// 获取错误消息
function getExportErrorMessage (error: any): string {
  return error?.detail ||
         error?.message ||
         proxy.$t('modules.kb.exportTemplateFailed')
}

// 导出模板
async function handleExportTemplate (row: KnowledgeGraphTemplateItem) {
  let loadingInstance: any = null
  try {
    loadingInstance = proxy.$loading({
      lock: true,
      text: proxy.$t('modules.kb.exportingTemplate'),
      spinner: 'el-icon-loading',
      background: 'rgba(0, 0, 0, 0.7)'
    })

    const response = await getGraphSchemaTemplateDetail(row.schema_id)

    if (loadingInstance) {
      loadingInstance.close()
      loadingInstance = null
    }

    const schemaData = extractSchemaDataFromResponse(response)
    if (!schemaData) {
      console.error('无法从响应中提取数据，响应结构:', response)
      throw new Error(proxy.$t('modules.kb.exportTemplateFailed'))
    }

    const exportData = transformSchemaDataToExportFormat(schemaData)
    const zipBlob = await createZipFromExportData(exportData)
    const fileName = `${schemaData.schema_name || schemaData.schema_id || 'template'}.zip`

    downloadZipFile(zipBlob, fileName)
    proxy.$message.success(proxy.$t('modules.kb.exportTemplateSuccess'))
  } catch (error: any) {
    console.error('导出模板失败:', error)
    if (loadingInstance) {
      loadingInstance.close()
    }
    proxy.$message.error(getExportErrorMessage(error))
  }
}

// 定时刷新定时器
// 页签头删除后容器按 subTab 二选一渲染：本组件只在「模版面」挂载，
// activeTabName 闸门平时恒通过。保留它是为了 document.hidden
// （拿不到注入值时按「可见」处理，而不是把刷新掐死）。
const outerTab = inject<any>('kbaseActiveTab', null)
function isSurfaceVisible (): boolean {
  if (document.hidden) {
    return false
  }
  if (outerTab && outerTab.value !== 'knowledgeGraph') {
    return false
  }
  if (activeTabName.value && activeTabName.value !== 'knowledgeGraphTemplate') {
    return false
  }
  return true
}

// 模版列表是静态数据（没有「构建中」这类会自己往下走的状态），不轮询：
// 只在挂载、切换到本页签、外层页签切回时各取一次。
onMounted(() => {
  refreshTableData()
  // 表格高度自适应：挂载后量一次并开始盯尺寸变化（本组件在子页签里，
  // 隐藏时量不到尺寸，等可见时 ResizeObserver 会补量）
})

// 监听tab切换，当切换到"知识图谱模版"tab时刷新数据
watch(activeTabName, newTab => {
  if (newTab === 'knowledgeGraphTemplate') {
    refreshTableData()
  }
})

// 外层页签切回"知识图谱"时补一次静默刷新
watch(
  () => outerTab && outerTab.value,
  () => {
    if (isSurfaceVisible()) {
      refreshTableData('', true)
    }
  }
)
</script>

<style scoped>
/* 管理列表样式 */
.template-table { min-width: 980px; }
.template-table .sortable { cursor: pointer; }
.template-table .entity-title { font-size: 13px; }
.template-description {
  max-width: 420px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--rs-text-2);
}
</style>

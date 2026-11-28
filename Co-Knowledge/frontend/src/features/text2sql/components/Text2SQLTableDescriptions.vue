<template>
  <div>
    <el-row :gutter="12"><el-col :xs="24" :sm="14"><el-input v-model="search" aria-label="搜索表说明" clearable :prefix-icon="Search" placeholder="搜索表名或说明…"/></el-col><el-col :xs="24" :sm="10"><el-checkbox v-model="missingOnly">只看待补充（{{ missingCount }}）</el-checkbox></el-col></el-row>
    <p class="text-caption muted">共 {{ tables.length }} 张表，{{ tables.length - missingCount }} 张已有说明、{{ missingCount }} 张待补充。说明选填，不必逐张重写。</p>
    <p v-if="editable && missingOnly" class="text-caption muted">填写过程中保留当前行，重新切换筛选可刷新待补充列表。</p>
    <el-space v-if="editable" wrap><el-button @click="exportTemplate"><Download/>导出说明模板</el-button><el-button @click="fileInput.click()"><Upload/>导入说明 CSV</el-button><el-button @click="useComments">补入已有数据库注释</el-button></el-space>
    <p v-if="editable" class="text-caption muted">CSV 支持批量填写；空白说明跳过，已有填写不会被空白覆盖。修改在确认准备后生效。</p>
    <input v-if="editable" ref="fileInput" type="file" accept=".csv,text/csv" hidden @change="importDescriptions"/>
    <el-table :data="pageRows" row-key="name" max-height="320" border empty-text="没有匹配的数据表" aria-label="表的业务说明">
      <el-table-column prop="name" label="数据表" min-width="160" show-overflow-tooltip/>
      <el-table-column label="业务说明" min-width="220"><template #default="{ row }"><el-input v-if="editable" v-model="descriptions[row.name]" :aria-label="`${row.name} 的业务说明`" maxlength="200" placeholder="可选：补充业务含义"/><span v-else>{{ tableDescription(row, descriptions) || '待补充（选填）' }}</span></template></el-table-column>
    </el-table>
    <TablePagination v-model:page="page" v-model:size="size" :total="filtered.length"/>
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Download, Upload } from '@element-plus/icons-vue'
import TablePagination from '@/shared/ui/reference/TablePagination.vue'
import { tableDescription } from '@/features/text2sql/demo-data/text2sqlScale'
import { parseDescriptionCSV, descriptionCSV } from '@/features/text2sql/utils/text2sqlDescriptions'
import { downloadText } from '@/features/text2sql/utils/demo'
const props = defineProps({ tables: { type: Array, required: true }, editable: Boolean })
const descriptions = defineModel({ type: Object, default: () => ({}) })
const search = ref(''); const missingOnly = ref(false); const page = ref(1); const size = ref(10); const fileInput = ref(); const missingSnapshot = ref(new Set())
const missingCount = computed(() => props.tables.filter(table => !tableDescription(table, descriptions.value).trim()).length)
function refreshFilter () {
  page.value = 1; missingSnapshot.value = new Set(props.tables.filter(table => !tableDescription(table, descriptions.value).trim()).map(table => table.name))
}
watch([search, missingOnly, () => props.tables], refreshFilter, { immediate: true })
const filtered = computed(() => props.tables.filter(table => (!missingOnly.value || missingSnapshot.value.has(table.name)) && `${table.name} ${tableDescription(table, descriptions.value)}`.toLowerCase().includes(search.value.trim().toLowerCase())))
const pageRows = computed(() => filtered.value.slice((page.value - 1) * size.value, page.value * size.value))
watch(size, () => {
  page.value = 1
})
watch(() => filtered.value.length, count => {
  page.value = Math.min(page.value, Math.max(1, Math.ceil(count / size.value)))
})
function exportTemplate () {
  downloadText('text2sql-table-descriptions.csv', descriptionCSV(props.tables, descriptions.value), 'text/csv;charset=utf-8')
}
function useComments () {
  const updates = Object.fromEntries(props.tables.filter(table => !tableDescription(table, descriptions.value).trim() && table.description).map(table => [table.name, table.description]))
  descriptions.value = { ...descriptions.value, ...updates }
  ElMessage.info(Object.keys(updates).length ? `已补入 ${Object.keys(updates).length} 张表的数据库注释` : '当前没有可补入的注释，已填写的说明保持不变')
}
async function importDescriptions (event) {
  const file = event.target.files?.[0]; event.target.value = ''
  if (!file) {
    return
  }
  if (file.size > 100 * 1024) {
    ElMessage.error('说明文件不能超过 100KB'); return
  }
  try {
    const updates = parseDescriptionCSV(await file.text(), props.tables.map(table => table.name))
    descriptions.value = { ...descriptions.value, ...updates }
    ElMessage.success(`已导入 ${Object.keys(updates).length} 张表的说明，确认准备后保存`)
  } catch (error) {
    ElMessage.error(error.message || '无法读取 CSV，请使用导出的模板')
  }
}
</script>

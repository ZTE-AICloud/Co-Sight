<template>
  <div class="t2s-results">
    <div class="studio-callout t2s-answer-callout" role="status">
      <CircleCheckFilled aria-hidden="true"/>
      <div>
        <strong class="text-section-title text-label">{{ resultSummary(response) }}</strong>
        <p class="text-caption">{{ response.reference_date ? `统计基准 ${response.reference_date}` : '只读查询' }} · {{ result.row_count }} 行结果 · {{ result.truncated ? '已截断' : '只读执行' }}</p>
      </div>
    </div>
    <div class="toolbar t2s-result-toolbar">
      <el-input v-model="search" aria-label="筛选查询结果" placeholder="筛选结果" title="仅筛选已返回的结果；修改指标、日期或城市请使用调整条件重新查询" clearable :prefix-icon="Search"/>
      <el-button v-if="chart" link type="primary" :aria-expanded="chartVisible" @click="showChart = !showChart">
        <Histogram/>{{ chartVisible ? '收起图表' : '显示图表' }}
      </el-button>
    </div>
    <div class="t2s-result-grid" :class="{ 'with-chart': chartVisible }">
      <div class="t2s-result-data">
        <div class="table-card t2s-result-table">
          <table class="list-table list-table--compact">
            <thead>
              <tr>
                <th scope="col" class="t2s-row-number">#</th>
                <th v-for="(column, index) in result.columns" :key="column" scope="col" :class="{ 't2s-number-cell': isNumericColumn(index) }" :aria-sort="sort.column === index ? sort.direction === 1 ? 'ascending' : 'descending' : 'none'">
                  <button class="table-sort-button" @click="sortBy(index)">{{ labels[column] || column }}<Sort/></button>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in pageRows" :key="index">
                <td class="t2s-row-number">{{ (page - 1) * size + index + 1 }}</td>
                <td v-for="(value, col) in row" :key="col" :class="{ 't2s-number-cell': typeof value === 'number' }">{{ typeof value === 'number' ? formatNumber(value, result.columns[col]) : value }}</td>
              </tr>
              <tr v-if="!pageRows.length"><td :colspan="result.columns.length + 1" class="empty-row">没有匹配的结果，清除筛选后重试。</td></tr>
            </tbody>
          </table>
        </div>
        <TablePagination v-if="filteredRows.length > defaultPageSize" v-model:page="page" v-model:size="size" :total="filteredRows.length"/>
        <p v-if="search" class="text-caption muted">筛选仅作用于当前结果；导出始终包含本次查询的全部 {{ result.row_count }} 行。</p>
      </div>
      <div v-if="chartVisible" class="table-card t2s-result-chart">
        <div class="t2s-result-chart-header">
          <h3 class="text-body text-label">{{ chart.title }}</h3>
          <p class="text-caption">{{ chart.subtitle }}</p>
        </div>
        <div v-for="(row, index) in chart.rows" :key="index" class="t2s-result-bar text-secondary">
          <span>{{ row.label }}</span>
          <div aria-hidden="true"><i :style="{ width: `${(row.value / maxValue) * 100}%` }"/></div>
          <strong>{{ formatChartValue(row.value) }}</strong>
        </div>
      </div>
    </div>
    <div class="t2s-result-tools t2s-result-feedback">
      <span class="text-caption muted">{{ feedbackSaved ? '反馈已提交' : '核对口径后，可反馈问题' }}</span>
      <div class="t2s-result-buttons"><el-button link @click="$emit('feedback', 'helpful')">答案有帮助</el-button><el-button link @click="$emit('feedback', 'meaning')">反馈问题</el-button><el-button v-if="issues.length" link type="primary" @click="$emit('feedback-progress')">查看处理进度</el-button></div>
    </div>
    <div v-for="item in issues" :key="item.id || item.category" class="t2s-feedback-progress text-secondary" role="status"><span class="tag-soft" :class="item.status === 'resolved' ? 'green' : 'orange'">{{ feedbackStatus(item) }}</span><span>{{ feedbackCategory(item.category) }}：{{ item.resolution || '问题已记录，等待维护者核对。' }}</span></div>
  </div>
</template>
<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { CircleCheckFilled, Histogram, Search, Sort } from '@element-plus/icons-vue'
import TablePagination from '@/shared/ui/reference/TablePagination.vue'
import { columnLabels, resultSummary } from '@/features/text2sql/utils/text2sqlWorkspace'
import { buildChart } from '@/features/text2sql/utils/resultChart'
import { feedbackStatus, feedbackCategory } from '@/features/text2sql/utils/text2sqlExperience'
const props = defineProps({ response: { type: Object, required: true }, busy: Boolean, feedbackSaved: Boolean, feedbackItems: { type: Array, default: () => [] }, contextValid: { type: Boolean, default: true }, metrics: { type: Array, default: () => [] } })
defineEmits(['followup', 'continue', 'feedback', 'feedback-progress'])
const defaultPageSize = 10
const page = ref(1); const size = ref(defaultPageSize); const search = ref(''); const showChart = ref(false); const sort = reactive({ column: -1, direction: 1 })
const result = computed(() => props.response.result)
const filteredRows = computed(() => {
  const rows = result.value.rows.filter(row => row.some(value => String(value).toLowerCase()
    .includes(search.value.trim().toLowerCase())))
  if (sort.column < 0) {
    return rows
  }
  return [...rows].sort((a, b) => (typeof a[sort.column] === 'number' ? a[sort.column] - b[sort.column] : String(a[sort.column]).localeCompare(String(b[sort.column]), 'zh-CN')) * sort.direction)
})
const pageRows = computed(() => filteredRows.value.slice((page.value - 1) * size.value, page.value * size.value))
const metricLabels = computed(() => Object.fromEntries((props.metrics || [])
  .filter(metric => metric.key)
  .map(metric => [metric.key, metric.unit ? `${metric.businessName} / ${metric.unit}` : metric.businessName])))
const labels = computed(() => ({ ...columnLabels, ...metricLabels.value }))
const chart = computed(() => buildChart(result.value.columns, filteredRows.value, labels.value))
const chartVisible = computed(() => showChart.value && Boolean(chart.value?.rows?.length))
const maxValue = computed(() => Math.max(1, ...((chart.value?.rows) || []).map(row => row.value)))
function isNumericColumn (index) {
  return result.value.rows.some(row => typeof row[index] === 'number')
}
function formatNumber (value, column) {
  const moneyLike = /(gmv|amount|pay|revenue|sales|price)/i.test(column || '')
  return value.toLocaleString('zh-CN', {
    minimumFractionDigits: moneyLike ? 2 : 0,
    maximumFractionDigits: 2
  })
}
function formatChartValue (value) {
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}
const issues = computed(() => props.feedbackItems.filter(item => item.category !== 'helpful'))
watch([search, size], () => {
  page.value = 1
})
watch(() => props.response.request_id, () => {
  page.value = 1; search.value = ''; sort.column = -1; showChart.value = false
})
function sortBy (column) {
  sort.direction = sort.column === column ? -sort.direction : 1; sort.column = column; page.value = 1
}
</script>
<style scoped>
.t2s-results { container-type: inline-size; }
.t2s-answer-callout > svg { color: var(--rs-success); }
.t2s-answer-callout p { margin-block-start: 4px; }
.t2s-result-tools,
.t2s-result-buttons {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.t2s-result-tools { justify-content: space-between; }
.t2s-result-toolbar {
  justify-content: flex-start;
  gap: 8px 12px;
  margin: 12px 0 8px;
}
.t2s-result-toolbar > .el-input { width: 210px; max-width: 100%; }
.t2s-result-data { min-width: 0; }
.t2s-result-table th { background: var(--rs-bg-card); }
.t2s-result-table .t2s-row-number { width: 36px; color: var(--rs-text-3); }
.t2s-number-cell { text-align: right; font-variant-numeric: tabular-nums; }
.t2s-result-grid { display: grid; gap: 14px; }
.t2s-result-chart { min-width: 0; }
.t2s-result-chart-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 2px 8px;
  min-height: var(--rs-table-header-height);
  padding: 8px 16px;
  border-bottom: 1px solid var(--rs-border);
}
.t2s-result-chart-header h3,
.t2s-result-chart-header p { margin: 0; }
.t2s-result-chart-header p { color: var(--rs-text-2); }
.t2s-result-bar {
  display: grid;
  grid-template-columns: 78px minmax(0, 1fr) 82px;
  gap: 10px;
  align-items: center;
  min-height: var(--el-component-size);
  padding: 8px 16px;
  overflow-wrap: anywhere;
}
.t2s-result-bar + .t2s-result-bar { border-top: 1px solid var(--rs-border-soft); }
.t2s-result-bar i {
  display: block;
  height: 8px;
  border-radius: 3px;
  background: var(--rs-primary);
}
.t2s-result-bar strong {
  color: var(--rs-text);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  text-align: right;
}
.t2s-result-feedback { margin: 12px 0 0; }
.t2s-feedback-progress { display: flex; align-items: flex-start; gap: 8px; margin-top: 12px; overflow-wrap: anywhere; }
.t2s-feedback-progress .tag-soft { flex-shrink: 0; }
@container (min-width: 880px) {
  .t2s-result-grid.with-chart { grid-template-columns: minmax(0, 1.2fr) minmax(300px, .8fr); align-items: start; }
}
@container (max-width: 560px) {
  .t2s-result-toolbar > .el-input { flex: 1 1 140px; }
  .t2s-result-table th,
  .t2s-result-table td { padding-inline: 8px; }
  .t2s-result-chart-header,
  .t2s-result-bar { padding-inline: 12px; }
  .t2s-result-bar { grid-template-columns: 58px minmax(0, 1fr) 64px; gap: 8px; }
}
@container (max-width: 230px) {
  .t2s-result-table .t2s-row-number { display: none; }
}
</style>

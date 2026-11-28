<template>
  <StudioDialog v-model="open" dialog-class="t2s-preparation-dialog" title="准备可查询的数据" subtitle="选择数据范围、补充业务说明，再确认准备。" :icon="Coin" hint="选择表和业务说明后会创建新版本，构建并发布后即可查询" :show-close="!preparing" :close-on-press-escape="!preparing" width="1080px">
    <div class="t2s-prep-source text-secondary"><span><strong class="text-label">{{ source.name }}</strong><code class="text-code text-caption">{{ source.database }} / {{ source.schema }}</code></span><span>已选 {{ draft.tables.length }} 张表 · {{ selectedColumnCount }} 个字段</span></div>
    <el-steps :active="step" finish-status="success" simple><el-step><template #title><span class="t2s-step-full">选择数据表</span><span class="t2s-step-short">选表</span></template></el-step><el-step><template #title><span class="t2s-step-full">业务说明</span><span class="t2s-step-short">说明</span></template></el-step><el-step><template #title><span class="t2s-step-full">确认并准备</span><span class="t2s-step-short">确认</span></template></el-step></el-steps>

    <div v-if="step === 0" class="t2s-prep-content t2s-prep-browser">
      <aside class="t2s-prep-selection">
        <div class="t2s-prep-heading"><h3 class="text-section-title">可查询的数据表</h3><span class="text-caption muted">{{ availableTables.length }} 张</span></div>
        <el-input v-model="tableSearch" aria-label="搜索可查询表" clearable :prefix-icon="Search" placeholder="搜索表名或业务说明…"/>
        <el-select v-model="tableGroup" aria-label="按业务域筛选表"><el-option label="全部业务域" value="all"/><el-option v-for="group in groups" :key="group" :label="group" :value="group"/></el-select>
        <el-space wrap><el-checkbox v-model="selectedOnly">仅看已选</el-checkbox><el-button link @click="draft.tables = []">清空选择</el-button></el-space>
        <el-checkbox :model-value="allMatched" :indeterminate="someMatched && !allMatched" :disabled="!filteredTables.length" @change="selectMatched">全选匹配（{{ filteredTables.length }} 张）</el-checkbox>
        <el-scrollbar height="320px">
        <el-checkbox-group v-model="draft.tables" aria-label="可查询数据表" class="t2s-prep-tables">
          <div v-for="table in filteredTables" :key="table.name" class="t2s-prep-table" :class="{ active: previewTable === table.name }">
            <el-checkbox :value="table.name" @change="previewTable = table.name"><span><strong class="text-body">{{ tableLabel(table) }}</strong><span class="text-caption">{{ tableMeta(table) }}</span></span></el-checkbox>
            <el-button link :aria-label="`预览${tableLabel(table)}`" @click="previewTable = table.name"><View/></el-button>
          </div>
        </el-checkbox-group>
        <p v-if="!filteredTables.length" class="text-secondary">没有匹配的表，请调整搜索或业务域。</p>
        </el-scrollbar>
        <el-button link @click="draft.tables = availableTables.map(table => table.name)">选择全部 {{ availableTables.length }} 张表</el-button>
        <div class="t2s-prep-scope text-caption" :class="{ warning: !draft.tables.includes('order_info') }"><InfoFilled/><span>{{ capabilityHint }}</span></div>
      </aside>
      <section class="t2s-prep-inspector" aria-label="数据表预览">
        <div class="t2s-prep-heading"><div><h3 class="text-section-title">{{ tableLabel(previewDefinition) }}</h3><span class="text-caption muted">{{ previewDefinition.fullName || previewDefinition.name }} · {{ previewDefinition.columns.length }} 个字段</span></div><span class="tag-soft" :class="draft.tables.includes(previewTable) ? 'green' : 'orange'">{{ draft.tables.includes(previewTable) ? '已纳入查询' : '未纳入查询' }}</span></div>
        <div class="table-card t2s-prep-preview"><table class="list-table"><thead><tr><th>字段</th><th>类型</th><th>业务含义</th></tr></thead><tbody><tr v-for="column in previewDefinition.columns" :key="column.name"><td><code class="text-code">{{ column.name }}</code><span v-if="column.primaryKey || column.foreignKey" class="tag-soft blue">{{ column.primaryKey ? '主键' : '关联键' }}</span></td><td>{{ column.type }}</td><td>{{ column.description }}</td></tr></tbody></table></div>
        <p class="text-caption muted">字段结构来自最近一次扫描；字段的启用状态与业务说明在「业务说明」步骤维护。</p>
      </section>
    </div>

    <div v-else-if="step === 1" class="t2s-prep-content t2s-prep-semantics">
      <el-form label-position="top" class="studio-form">
        <FormSection number="01" title="业务名称与说明">
          <el-collapse v-if="availableTables.length > 10"><el-collapse-item title="指标与数据源补充说明（选填）" name="source-semantics"><div class="studio-field-grid"><el-form-item label="支付金额指标名称"><el-input v-model="draft.semantics.amountName" maxlength="60"/></el-form-item><el-form-item label="付费用户指标名称"><el-input v-model="draft.semantics.userName" maxlength="60"/></el-form-item></div><el-form-item label="补充业务说明"><el-input v-model="draft.semantics.notes" aria-label="补充业务说明" type="textarea" :rows="2" maxlength="1000"/></el-form-item></el-collapse-item></el-collapse>
          <div v-else class="studio-field-grid"><el-form-item label="支付金额指标名称"><el-input v-model="draft.semantics.amountName" aria-label="支付金额指标名称" maxlength="60"/></el-form-item><el-form-item label="付费用户指标名称"><el-input v-model="draft.semantics.userName" aria-label="付费用户指标名称" maxlength="60"/></el-form-item></div>
          <Text2SQLTableDescriptions v-model="draft.semantics.tableDescriptions" :tables="selectedTables" editable/>
          <el-form-item v-if="availableTables.length <= 10" label="补充业务说明"><el-input v-model="draft.semantics.notes" aria-label="补充业务说明" type="textarea" :rows="2" maxlength="1000" placeholder="例如：城市按用户当前归属地区统计。"/></el-form-item>
        </FormSection>
        <FormSection number="02" title="字段与说明">
          <p class="text-caption muted">只启用需要参与查询的字段；字段说明会进入检索与生成上下文。城市、商品等开放维度无需录入取值，查询时会自动解析存储值。</p>
          <el-form-item label="维护数据表">
            <el-select v-model="columnTable" aria-label="选择要维护字段的表" placeholder="选择已选数据表">
              <el-option v-for="table in selectedTables" :key="table.name" :label="tableOptionLabel(table)" :value="table.name"/>
            </el-select>
          </el-form-item>
          <el-table :data="columnRows" max-height="320" border :empty-text="selectedTables.length ? '请选择数据表' : '先在第一步选择数据表'">
            <el-table-column label="字段" min-width="190"><template #default="{ row }"><code class="text-code">{{ row.name }}</code><span class="text-caption muted t2s-column-type">{{ row.dataType }}</span></template></el-table-column>
            <el-table-column label="启用" width="72" align="center"><template #default="{ row }"><el-checkbox v-model="draft.columns[columnTable][row.id].enabled" :aria-label="`启用字段 ${row.name}`"/></template></el-table-column>
            <el-table-column label="业务说明" min-width="220"><template #default="{ row }"><el-input v-model="draft.columns[columnTable][row.id].businessDescription" :aria-label="`${row.name} 的业务说明`" maxlength="200" placeholder="可选：补充业务含义"/></template></el-table-column>
          </el-table>
          <p class="text-caption muted">已启用 {{ enabledColumnCount }} / {{ selectedColumnCount }} 个字段；未启用的字段不会进入 Schema 上下文。</p>
        </FormSection>
      </el-form>
      <aside class="t2s-prep-reference">
        <h3 class="text-section-title">本次配置的作用范围</h3>
        <dl class="t2s-prep-rules text-secondary"><div><dt>查询范围</dt><dd>仅包含已选表与已启用字段。<span class="text-caption muted">未选表不会进入 Schema 上下文。</span></dd></div><div><dt>业务说明</dt><dd>表与字段的业务名称、说明、同义词。<span class="text-caption muted">用于检索、生成与查询解释。</span></dd></div><div><dt>安全边界</dt><dd>只读连接 · 单条 SELECT · 行数与超时限制。<span class="text-caption muted">由后端强制执行。</span></dd></div></dl>
        <details class="text-caption muted"><summary>名称与说明如何生效？</summary><p>名称与说明会进入检索与生成上下文；计算公式与关联由“指标 / 关联”配置决定。</p></details>
      </aside>
    </div>

    <div v-else class="t2s-prep-content t2s-prep-confirm">
      <div class="t2s-prep-confirm-main">
        <div class="t2s-prep-heading"><h3 class="text-section-title">确认准备内容</h3><el-button link :disabled="preparing" @click="step = 0">修改表范围</el-button></div>
        <p class="text-secondary">已选择 {{ selectedTables.length }} 张表、{{ enabledColumnCount }} 个字段，{{ missingDescriptionCount }} 张待补充说明（选填）。</p>
        <el-table :data="confirmRows" max-height="320" border><el-table-column prop="name" label="数据表" min-width="160" show-overflow-tooltip/><el-table-column label="业务说明" min-width="180" show-overflow-tooltip><template #default="{ row }">{{ tableDescription(row, draft.semantics.tableDescriptions) || '未补充（选填）' }}</template></el-table-column><el-table-column label="字段" width="70"><template #default="{ row }">{{ row.columns.length }}</template></el-table-column></el-table>
        <TablePagination v-model:page="confirmPage" v-model:size="confirmSize" :total="selectedTables.length"/>
        <div class="t2s-prep-confirm-metrics text-secondary"><span>金额指标<strong class="text-label">{{ draft.semantics.amountName }}</strong></span><span>用户指标<strong class="text-label">{{ draft.semantics.userName }}</strong></span><el-button link :disabled="preparing" @click="step = 1">修改说明</el-button></div>
        <p v-if="draft.semantics.notes" class="text-caption muted">补充说明：{{ draft.semantics.notes }}</p>
      </div>
      <aside class="t2s-prep-reference">
        <h3 class="text-section-title">{{ hasChanges ? '本次准备将更新配置' : source.status === 'indexed' ? '配置未变化，可直接确认' : source.requiresPublication ? '准备后验证并发布' : '准备完成后即可查询' }}</h3>
        <p class="text-secondary">{{ capabilityHint }}</p>
        <p class="text-caption muted">当前配置版本 {{ source.revision || 1 }}；确认后创建新版本，构建完成后需要发布。</p>
        <p class="text-secondary">新增 {{ difference.added.length }} 张表，移除 {{ difference.removed.length }} 张表，修改 {{ difference.descriptions.length }} 条表说明、{{ columnChanges.length }} 个字段、{{ difference.settings.length }} 项指标或补充说明。</p>
        <details v-if="difference.added.length || difference.removed.length || difference.descriptions.length || columnChanges.length || difference.settings.length" class="text-caption"><summary>查看配置变更</summary><p v-if="difference.added.length">新增：{{ difference.added.join('、') }}</p><p v-if="difference.removed.length">移除：{{ difference.removed.join('、') }}</p><p v-if="difference.descriptions.length">表说明：{{ difference.descriptions.join('、') }}</p><p v-if="columnChanges.length">字段：{{ columnChanges.map(change => `${change.columnName}（${change.enabled ? '启用' : '停用'}${change.businessDescription ? '，已填说明' : ''}）`).join('、') }}</p><p v-if="difference.settings.length">设置：{{ difference.settings.map(key => ({ amountName: '金额指标名称', userName: '用户指标名称', notes: '数据源补充说明' })[key]).join('、') }}</p></details>
        <p class="text-caption muted">{{ hasChanges ? '准备完成后切换到新配置，常用查询的人工核对标记需重新确认。' : '现有配置版本与人工核对标记保持有效。' }} 历史结果会保留。</p>
        <p class="text-caption muted">构建完成后还需要发布版本，发布后新查询才会使用这套配置。</p>
        <ul class="t2s-prep-tasks text-secondary"><li><CircleCheck/>保存表范围与业务说明</li><li><CircleCheck/>冻结配置版本</li><li><CircleCheck/>向量化并构建索引</li></ul>
        <div v-if="preparing" class="t2s-prep-progress" role="status" aria-live="polite"><el-progress :percentage="Math.round((prepareStage + 1) / 3 * 100)"/><p class="text-secondary">{{ ['保存配置…', '冻结版本...', '构建索引…'][prepareStage] }}</p></div>
      </aside>
    </div>
    <template #actions><el-button :disabled="preparing" @click="open = false">取消</el-button><el-button v-if="step > 0" :disabled="preparing" @click="step--">上一步</el-button><el-button v-if="step < 2" type="primary" :disabled="!draft.tables.length || !draft.semantics.amountName.trim() || !draft.semantics.userName.trim()" @click="step++">下一步</el-button><el-button v-else type="primary" :loading="preparing" @click="$emit('prepare', { selectedTables: [...draft.tables], semantics: JSON.parse(JSON.stringify(draft.semantics)), columns: columnChanges.map(change => ({ ...change })) })">{{ confirmText }}</el-button></template>
  </StudioDialog>
</template>
<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { Coin, View, InfoFilled, CircleCheck, Search } from '@element-plus/icons-vue'
import StudioDialog from '@/shared/ui/StudioDialog.vue'
import FormSection from '@/shared/ui/FormSection.vue'
import TablePagination from '@/shared/ui/reference/TablePagination.vue'
import Text2SQLTableDescriptions from './Text2SQLTableDescriptions.vue'
import { tableLabel, tableDescription, updateTableSelection } from '@/features/text2sql/demo-data/text2sqlScale'
import { defaultSemantics } from '@/features/text2sql/utils/text2sqlWorkspace'
import {
  buildColumnState,
  collectColumnChanges,
  countEnabledColumns
} from '@/features/text2sql/utils/text2sqlPreparation'
const open = defineModel({ type: Boolean, default: false })
const props = defineProps({ source: { type: Object, required: true }, tables: { type: Array, default: () => [] }, relations: { type: Array, default: () => [] }, preparing: Boolean, prepareStage: Number, initialStep: { type: Number, default: 0 }, confirmText: { type: String, default: '准备并开始查询' } })
defineEmits(['prepare'])
const step = ref(0); const previewTable = ref('order_info'); const previewMode = ref('data')
const tableSearch = ref(''); const tableGroup = ref('all'); const selectedOnly = ref(false); const confirmPage = ref(1); const confirmSize = ref(10)
const columnTable = ref('')
let initialColumns = {}
let initialTableDescriptions = {}
const availableTables = computed(() => (props.tables || []).map(table => ({
  ...table,
  label: table.businessName || '',
  description: table.businessDescription || table.dbComment || '',
  group: table.schema || '业务数据',
  columns: (table.columns || []).map(column => ({
    ...column,
    type: column.dataType || column.type,
    description: column.businessDescription || column.dbComment || '',
    primaryKey: Boolean(column.primaryKey),
    foreignKey: Boolean(column.foreignKey)
  }))
})))
const groups = computed(() => [...new Set(availableTables.value.map(table => table.group || '业务示例'))])
const draft = reactive({ tables: [], semantics: { ...defaultSemantics, tableDescriptions: {} }, columns: {} })
const shortTableName = name => String(name || '').split('.').pop()
// 扫描来的表没有业务名称时 tableLabel() 会回落成表名；此时副标题与下拉项不再重复一遍表名。
const tableHasLabel = table => tableLabel(table) !== table.name
function tableMeta (table) {
  const name = tableHasLabel(table) ? `${table.name} · ` : ''
  const isView = Boolean(table.type) && table.type !== 'BASE_TABLE'
  return `${name}${(table.columns || []).length} 个字段${isView ? ' · 视图' : ''}`
}
function tableOptionLabel (table) {
  return tableHasLabel(table) ? `${tableLabel(table)}（${table.name}）` : table.name
}
const selectedTableNames = computed(() => (props.source.selectedTables || []).map(shortTableName))
watch(open, value => {
  if (!value) {
    return
  }
  step.value = props.source.status === 'indexed' ? props.initialStep : 0
  tableSearch.value = ''; tableGroup.value = 'all'; selectedOnly.value = false; confirmPage.value = 1
  draft.tables = [...selectedTableNames.value]
  previewTable.value = draft.tables[0] || availableTables.value[0]?.name || ''; previewMode.value = 'columns'
  draft.semantics = { ...defaultSemantics, tableDescriptions: Object.fromEntries(availableTables.value.map(table => [table.name, tableDescription(table)])) }
  draft.columns = buildColumnState(availableTables.value)
  columnTable.value = draft.tables[0] || availableTables.value[0]?.name || ''
  initialColumns = buildColumnState(availableTables.value)
  initialTableDescriptions = Object.fromEntries(availableTables.value.map(table => [table.name, tableDescription(table)]))
})
watch(() => draft.tables, names => {
  if (!names.includes(columnTable.value)) {
    columnTable.value = names[0] || ''
  }
})
const filteredTables = computed(() => availableTables.value.filter(table => `${table.name} ${tableLabel(table)}`.toLowerCase().includes(tableSearch.value.trim().toLowerCase()) && (tableGroup.value === 'all' || (table.group || '业务示例') === tableGroup.value) && (!selectedOnly.value || draft.tables.includes(table.name))))
const allMatched = computed(() => filteredTables.value.length > 0 && filteredTables.value.every(table => draft.tables.includes(table.name)))
const someMatched = computed(() => filteredTables.value.some(table => draft.tables.includes(table.name)))
function selectMatched (checked) {
  draft.tables = updateTableSelection(draft.tables, filteredTables.value.map(table => table.name), checked)
}
const selectedTables = computed(() => availableTables.value.filter(table => draft.tables.includes(table.name)))
const selectedColumnCount = computed(() => selectedTables.value.reduce((count, table) => count + table.columns.length, 0))
const columnRows = computed(() => availableTables.value.find(table => table.name === columnTable.value)?.columns || [])
const columnChanges = computed(() => collectColumnChanges(draft.columns, initialColumns, selectedTables.value))
const enabledColumnCount = computed(() => countEnabledColumns(draft.columns, selectedTables.value))
const previewDefinition = computed(() => availableTables.value.find(table => table.name === previewTable.value) || availableTables.value[0])
const difference = computed(() => {
  const before = new Set(selectedTableNames.value)
  const after = new Set(draft.tables)
  return {
    added: [...after].filter(name => !before.has(name)),
    removed: [...before].filter(name => !after.has(name)),
    descriptions: selectedTables.value
      .filter(table => (draft.semantics.tableDescriptions[table.name] || '') !== (initialTableDescriptions[table.name] || ''))
      .map(table => table.name),
    // 指标名称与补充说明只用于本次对话引导，服务端没有对应字段，不计入配置变更。
    settings: []
  }
})
const hasChanges = computed(() => JSON.stringify([...draft.tables].sort()) !== JSON.stringify([...selectedTableNames.value].sort())
  || difference.value.descriptions.length > 0
  || columnChanges.value.length > 0)
const capabilityHint = computed(() => draft.tables.length
  ? `已选 ${draft.tables.length} 张表；只有这些表会进入生成上下文。`
  : '至少选择一张表才能创建版本。')
const missingDescriptionCount = computed(() => selectedTables.value.filter(table => !tableDescription(table, draft.semantics.tableDescriptions).trim()).length)
const confirmRows = computed(() => selectedTables.value.slice((confirmPage.value - 1) * confirmSize.value, confirmPage.value * confirmSize.value))
watch(confirmSize, () => {
  confirmPage.value = 1
})
watch(step, () => {
  confirmPage.value = 1
})
</script>
<style scoped>
.t2s-step-short{display:none}
.t2s-prep-selection>.el-select{margin:8px 0}.t2s-prep-selection>.el-select :deep(.el-select__wrapper){min-height:40px}.t2s-prep-selection>.el-checkbox{display:flex;margin:8px 0}.t2s-prep-selection>.el-scrollbar{height:auto}
.t2s-prep-source,.t2s-prep-source>span{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.t2s-prep-source{justify-content:space-between;padding:20px 0}.t2s-prep-source code{color:var(--rs-text-3)}
.t2s-prep-content{padding:16px 0 0;min-width:0}.t2s-prep-browser{display:grid;grid-template-columns:250px minmax(0,1fr);gap:24px}.t2s-prep-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.t2s-prep-heading h3,.t2s-prep-reference h3{margin:0;color:var(--rs-text)}.t2s-prep-heading>div>span{display:block;margin-top:4px}
.t2s-prep-tables{display:grid;gap:8px}.t2s-prep-table{display:flex;align-items:center;gap:6px;padding:10px 12px;border:1px solid var(--rs-border);border-radius:8px}.t2s-prep-table.active{border-color:var(--rs-primary-border);background:var(--rs-bg-selected)}.t2s-prep-table :deep(.el-checkbox){height:auto;margin:0;min-width:0;flex:1}.t2s-prep-table :deep(.el-checkbox__label){white-space:normal;min-width:0;padding-left:8px}.t2s-prep-table strong,.t2s-prep-table span.text-caption{display:block}.t2s-prep-table span.text-caption{color:var(--rs-text-2);margin-top:4px}.t2s-prep-table>.el-button{margin:0}.t2s-prep-scope{display:flex;align-items:flex-start;gap:8px;padding:12px;background:var(--rs-bg-soft);border-radius:8px;color:var(--rs-text-2)}.t2s-prep-scope svg{flex-shrink:0;margin-top:2px}.t2s-prep-scope.warning{color:var(--rs-warning)}
.t2s-prep-inspector,.t2s-prep-confirm-main{min-width:0}.t2s-prep-preview{margin:0}.t2s-prep-preview table{min-width:420px}.t2s-prep-preview th{height:44px;padding:10px 12px}.t2s-prep-preview td{height:56px;padding:10px 12px;white-space:nowrap}.t2s-prep-preview .tag-soft{margin-left:8px}.t2s-prep-preview-tabs :deep(.el-tabs__header){margin:0 0 12px}.t2s-prep-preview-tabs :deep(.el-tabs__content){display:none}
.t2s-prep-semantics,.t2s-prep-confirm{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:24px;align-items:start}.t2s-prep-semantics .studio-form{min-width:0}.t2s-prep-semantics :deep(.studio-form-section){padding:0}.t2s-prep-semantics :deep(.studio-section-heading){margin-bottom:14px}.t2s-prep-semantics :deep(.el-form-item){margin-bottom:14px}.t2s-prep-semantics :deep(.studio-form-section + .studio-form-section){margin-top:18px}.t2s-column-type{display:block;margin-top:2px}
.t2s-prep-reference{padding:16px;background:var(--rs-bg-soft);border:1px solid var(--rs-border-soft);border-radius:8px;min-width:0}.t2s-prep-reference p{margin:10px 0 0;overflow-wrap:anywhere}.t2s-prep-reference details{margin-top:14px}.t2s-prep-reference summary{cursor:pointer;color:var(--rs-primary)}.t2s-prep-rules{margin:10px 0 0}.t2s-prep-rules>div{padding:12px 0;border-bottom:1px solid var(--rs-border-soft)}.t2s-prep-rules>div:last-child{border:0}.t2s-prep-rules dt{color:var(--rs-text-3);margin-bottom:4px}.t2s-prep-rules dd{margin:0;overflow-wrap:anywhere}.t2s-prep-rules dd>span{display:block;margin-top:4px}
.t2s-prep-confirm-metrics{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin-top:16px}.t2s-prep-confirm-metrics>span{display:grid;gap:4px;flex:1}.t2s-prep-tasks{list-style:none;padding:0;margin:16px 0 0;display:grid;gap:8px}.t2s-prep-tasks li{display:flex;align-items:center;gap:8px}.t2s-prep-tasks svg{color:var(--rs-primary)}.t2s-prep-progress{margin-top:16px}
@media(max-width:850px){.t2s-prep-browser{grid-template-columns:210px minmax(0,1fr);gap:16px}.t2s-prep-semantics,.t2s-prep-confirm{grid-template-columns:minmax(0,1fr);gap:16px}.t2s-prep-rules{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 20px}}
@media(max-width:600px){.t2s-step-full{display:none}.t2s-step-short{display:inline}.t2s-prep-browser{grid-template-columns:minmax(0,1fr)}.t2s-prep-source{gap:6px}.t2s-prep-source>span{gap:6px}.t2s-prep-rules{grid-template-columns:minmax(0,1fr)}.t2s-prep-content{padding:12px 0 0}.t2s-prep-heading{flex-wrap:wrap}}
</style>

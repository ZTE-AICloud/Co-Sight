<template>
  <section class="t2s-quality" aria-label="验证与反馈">
    <div class="t2s-quality-heading">
      <div>
        <h2 class="text-section-title">维护可信的分析主题</h2>
        <p class="text-secondary">准备数据 → 核对业务定义 → 构建版本 → 发布 → 跟进反馈。</p>
      </div>
      <el-select :model-value="source.id" aria-label="选择维护的数据源" :disabled="busy" @update:model-value="$emit('source', $event)">
        <el-option v-for="item in sources" :key="item.id" :label="topicDetails(item).name" :value="item.id"/>
      </el-select>
    </div>
    <div class="studio-callout text-secondary"><InfoFilled/><span>版本冻结表范围、业务说明、关联与指标；构建成功后仍需发布，新查询才会绑定该版本。</span></div>
    <el-tabs v-model="tab">
      <el-tab-pane label="验证与发布" name="validation"/>
      <el-tab-pane label="枚举与指标" name="semantics"/>
      <el-tab-pane :label="`反馈处理${pending ? ` (${pending})` : ''}`" name="feedback"/>
    </el-tabs>

    <template v-if="tab === 'validation'">
      <div class="t2s-quality-overview">
        <div class="t2s-panel t2s-quality-card">
          <span class="text-caption muted">{{ topicDetails(source).name }}</span>
          <h3 class="text-section-title">{{ statusTitle }}</h3>
          <p class="text-secondary">当前配置 v{{ source.revision || 1 }} · {{ enabledTableCount }} 张已选表<span v-if="activeVersion"> · 活动版本 v{{ activeVersion.revision }}</span></p>
          <p class="text-caption muted">{{ source.businessDescription || source.topic?.description || '未填写业务说明' }} · {{ source.businessTimezone || 'UTC' }}</p>
          <div class="t2s-inline-actions">
            <el-button :disabled="busy" @click="$emit('manage')">查看数据状态</el-button>
            <el-button :disabled="busy || source.enabled === false" @click="$emit('prepare', 0)">准备数据</el-button>
            <el-button :disabled="busy || source.enabled === false" :loading="busy" @click="$emit('scan')">扫描结构</el-button>
            <el-button :disabled="busy || source.enabled === false" @click="$emit('assist')">AI 辅助</el-button>
            <el-button type="primary" :disabled="busy || source.enabled === false || source.status === 'configured'" :loading="busy" @click="$emit('build')">构建最新版本</el-button>
          </div>
        </div>
        <div class="t2s-panel t2s-quality-card">
          <span class="text-caption muted">发布前检查</span>
          <h3 class="text-section-title">{{ publishTitle }}</h3>
          <p class="text-secondary">{{ publishHint }}</p>
          <p class="text-caption muted">{{ latestReady ? `最新 READY：v${latestReady.revision}` : '还没有构建成功的版本' }}</p>
          <div class="t2s-inline-actions">
            <el-button type="primary" :disabled="busy || !publishable" @click="$emit('publish')">{{ activeVersion && latestReady?.id === activeVersion.id ? '当前版本已发布' : '发布最新版本' }}</el-button>
            <el-button v-if="activeVersion" :disabled="busy || source.status !== 'indexed'" @click="$emit('query')">使用此主题提问</el-button>
          </div>
        </div>
      </div>
      <el-alert v-if="source.enabled === false" title="数据源已停用，请在数据源管理中启用后再准备或发布。" type="warning" :closable="false"/>
      <div class="t2s-quality-report">
        <div class="t2s-quality-heading">
          <div class="t2s-quality-heading-main">
            <h3 class="text-section-title">版本历史</h3>
            <span class="text-caption muted">{{ versions.length }} 个版本</span>
          </div>
          <el-button link type="primary" :disabled="busy" title="保留最近 3 个就绪版本，其余归档并回收知识；活动版本与被查询历史引用的版本不动" @click="$emit('cleanup')">清理旧版本</el-button>
        </div>
        <div class="table-card">
          <table class="list-table t2s-compact-table">
            <thead><tr><th>版本</th><th>状态</th><th>知识对象</th><th>创建时间</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="version in versions" :key="version.id">
                <td>v{{ version.revision }}<span v-if="version.id === source.activeVersionId" class="tag-soft green">活动中</span></td>
                <td><span class="tag-soft" :class="versionTone(version.status)">{{ versionLabel(version.status) }}</span></td>
                <td>{{ version.indexedCount || 0 }} / {{ version.expectedKnowledgeCount || 0 }}<span v-if="version.failedCount" class="text-secondary"> · 失败 {{ version.failedCount }}</span></td>
                <td class="nowrap">{{ formatTime(version.createdAt) }}</td>
                <td>
                  <el-button v-if="['DRAFT','FAILED'].includes(version.status)" link type="primary" :disabled="busy" @click="$emit('build')">构建</el-button>
                  <el-button v-else-if="version.status === 'READY' && version.revision === (source.revision || 1) && version.id !== source.activeVersionId" link type="primary" :disabled="busy" @click="$emit('publish')">发布</el-button>
                  <span v-else class="text-caption muted">—</span>
                </td>
              </tr>
              <tr v-if="!versions.length"><td colspan="5" class="empty-row">还没有版本，请先准备数据并构建。</td></tr>
            </tbody>
          </table>
        </div>
      </div>
      <div class="t2s-quality-report">
        <div class="t2s-quality-heading"><h3 class="text-section-title">发布记录</h3><span class="text-caption muted">{{ publications.length }} 次</span></div>
        <div class="table-card">
          <table class="list-table t2s-compact-table">
            <thead><tr><th>版本</th><th>操作者</th><th>时间</th></tr></thead>
            <tbody>
              <tr v-for="item in publications" :key="item.id"><td>v{{ item.revision }}</td><td>{{ item.actorId || '—' }}</td><td class="nowrap">{{ formatTime(item.createdAt) }}</td></tr>
              <tr v-if="!publications.length"><td colspan="3" class="empty-row">还没有发布记录。</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <template v-else-if="tab === 'semantics'">
      <div class="t2s-quality-heading">
        <div><h3 class="text-section-title">枚举值与业务指标</h3><p class="text-secondary">枚举值只用于封闭小字典（状态、渠道、等级）和常见别名；城市、商品等开放维度无需逐条录入，查询时会自动回库解析存储值。</p></div>
      </div>
      <div class="t2s-quality-overview t2s-semantics-overview">
        <div class="t2s-panel t2s-quality-card">
          <div class="t2s-quality-heading"><h3 class="text-section-title">枚举值</h3><el-checkbox v-model="showDisabledValues">显示已停用</el-checkbox></div>
          <div class="table-card">
            <table class="list-table t2s-compact-table">
              <thead><tr><th>字段</th><th>原始值</th><th>业务名称</th><th>同义词</th><th>操作</th></tr></thead>
              <tbody>
                <tr v-for="item in visibleValues" :key="item.id">
                  <td><code class="text-code">{{ columnLabel(item.columnId) }}</code></td>
                  <td>{{ item.rawValue }}<span v-if="item.enabled === false" class="tag-soft orange">已停用</span></td>
                  <td>{{ item.businessName || '—' }}</td>
                  <td>{{ (item.aliases || []).join('、') || '—' }}</td>
                  <td>
                    <el-button link @click="openValueEditor(item)">编辑</el-button>
                    <el-button link type="danger" @click="$emit('delete-value', item)">删除</el-button>
                  </td>
                </tr>
                <tr v-if="!visibleValues.length"><td colspan="5" class="empty-row">{{ values.length ? '没有启用中的枚举值；勾选「显示已停用」可查看。' : '还没有枚举值。' }}</td></tr>
              </tbody>
            </table>
          </div>
          <div class="semantic-form">
            <el-select v-model="valueDraft.columnId" filterable placeholder="选择字段" aria-label="枚举字段">
              <el-option v-for="item in columnOptions" :key="item.id" :label="`${item.table}.${item.name}`" :value="item.id"/>
            </el-select>
            <el-input v-model="valueDraft.rawValue" placeholder="原始值，如 2 或 西安市" aria-label="枚举原始值" style="width: 160px"/>
            <el-input v-model="valueDraft.businessName" placeholder="业务名称，如 已支付" aria-label="枚举业务名称" style="width: 160px"/>
            <el-input v-model="valueDraft.aliases" placeholder="同义词，逗号分隔" aria-label="枚举同义词" style="width: 180px"/>
            <el-button type="primary" :disabled="!valueDraft.columnId || !valueDraft.rawValue.trim()" @click="createValue">添加枚举值</el-button>
          </div>
        </div>
        <div class="t2s-panel t2s-quality-card">
          <h3 class="text-section-title">业务指标</h3>
          <div class="table-card">
            <table class="list-table t2s-compact-table">
              <thead><tr><th>指标</th><th>表达式</th><th>基础表</th><th>状态</th><th>操作</th></tr></thead>
              <tbody>
                <tr v-for="item in metrics" :key="item.id">
                  <td><strong class="text-label">{{ item.businessName }}</strong><div class="entity-sub">{{ item.key }}</div></td>
                  <td><code class="text-code">{{ item.expressionSql }}</code></td>
                  <td>{{ tableLabel(item.baseTableId) }}</td>
                  <td><span class="tag-soft" :class="metricStatusTone(item.status)">{{ metricStatusLabel(item.status) }}</span></td>
                  <td>
                    <el-button v-if="item.status !== 'APPROVED'" link type="primary" :disabled="busy" @click="$emit('set-metric-status', { metric: item, status: 'APPROVED' })">审核通过</el-button>
                    <el-button v-else link type="warning" :disabled="busy" @click="$emit('set-metric-status', { metric: item, status: 'DISABLED' })">停用</el-button>
                    <el-button link type="danger" @click="$emit('delete-metric', item)">删除</el-button>
                  </td>
                </tr>
                <tr v-if="!metrics.length"><td colspan="5" class="empty-row">还没有指标定义。</td></tr>
              </tbody>
            </table>
          </div>
          <div class="semantic-form">
            <el-input v-model="metricDraft.key" placeholder="指标 key，如 pay_amount" aria-label="指标 key" style="width: 160px"/>
            <el-input v-model="metricDraft.businessName" placeholder="业务名称，如 支付金额" aria-label="指标名称" style="width: 160px"/>
            <el-select v-model="metricDraft.baseTableId" placeholder="基础表" aria-label="指标基础表">
              <el-option v-for="table in tables" :key="table.id" :label="table.fullName" :value="table.id"/>
            </el-select>
            <el-input v-model="metricDraft.expressionSql" placeholder="表达式，如 SUM(order_info.pay_amount)" aria-label="指标表达式" style="min-width: 0; flex: 1 1 220px"/>
            <el-button type="primary" :disabled="!metricDraft.key.trim() || !metricDraft.businessName.trim() || !metricDraft.baseTableId || !metricDraft.expressionSql.trim()" @click="createMetric">添加指标</el-button>
          </div>
        </div>
      </div>
      <p class="text-caption muted">修改枚举或指标会递增配置版本；请在上方构建并发布新版本后生效。</p>
    </template>

    <template v-else>
      <div class="t2s-quality-heading"><div><h3 class="text-section-title">让反馈有明确去向</h3><p class="text-secondary">结果页提交的业务口径、SQL 与数据问题会汇总到这里，便于核对当前版本。</p></div></div>
      <div v-for="item in feedback" :key="item.id" class="t2s-panel t2s-quality-card">
        <div class="t2s-quality-heading">
          <span class="text-label">{{ categoryLabel(item.category) }} · {{ feedbackStatusLabel(item.status) }}</span>
          <span class="tag-soft" :class="item.status === 'RESOLVED' ? 'green' : 'orange'">{{ item.status === 'RESOLVED' ? '已解决' : '待处理' }}</span>
        </div>
        <p class="text-secondary">{{ item.notes }}</p>
        <p class="text-caption muted">提交于 {{ formatTime(item.createdAt) }}</p>
      </div>
      <el-empty v-if="!feedback.length" description="暂无反馈；结果页的「反馈问题」会出现在这里。"/>
    </template>

    <el-dialog v-model="valueEditorOpen" class="studio-dialog" style="--studio-dialog-width: 560px" title="编辑枚举值" append-to-body>
      <el-form v-if="valueEditor" label-position="top" class="studio-form" @submit.prevent>
        <el-form-item label="字段"><code class="text-code">{{ columnLabel(valueEditor.item.columnId) }}</code></el-form-item>
        <el-form-item label="原始值"><code class="text-code">{{ valueEditor.item.rawValue }}</code></el-form-item>
        <el-form-item label="业务名称"><el-input v-model="valueEditor.businessName" maxlength="255" aria-label="枚举业务名称"/></el-form-item>
        <el-form-item label="同义词"><el-input v-model="valueEditor.aliases" maxlength="500" placeholder="逗号或顿号分隔" aria-label="枚举同义词"/></el-form-item>
        <el-form-item label="说明"><el-input v-model="valueEditor.description" type="textarea" :rows="2" maxlength="2000" aria-label="枚举说明"/></el-form-item>
        <el-form-item label="启用"><el-checkbox v-model="valueEditor.enabled">参与检索与生成</el-checkbox></el-form-item>
      </el-form>
      <template #footer><div class="studio-dialog-footer"><span class="studio-footer-hint text-caption">保存后需构建并发布新版本才会生效</span><div class="studio-footer-actions"><el-button @click="valueEditorOpen = false">取消</el-button><el-button type="primary" :disabled="busy" @click="saveValueEditor">保存</el-button></div></div></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { InfoFilled } from '@element-plus/icons-vue'
import { topicDetails } from '@/features/text2sql/utils/text2sqlExperience'

const props = defineProps({
  source: { type: Object, required: true },
  sources: { type: Array, default: () => [] },
  versions: { type: Array, default: () => [] },
  publications: { type: Array, default: () => [] },
  feedback: { type: Array, default: () => [] },
  tables: { type: Array, default: () => [] },
  values: { type: Array, default: () => [] },
  metrics: { type: Array, default: () => [] },
  busy: Boolean,
  initialTab: { type: String, default: 'validation' }
})
const emit = defineEmits(['source', 'prepare', 'scan', 'build', 'publish', 'query', 'manage', 'create-value', 'update-value', 'delete-value', 'create-metric', 'delete-metric', 'set-metric-status', 'cleanup', 'assist'])
const tab = ref(props.initialTab)
const valueDraft = ref({ columnId: '', rawValue: '', businessName: '', aliases: '' })
const valueEditorOpen = ref(false)
const valueEditor = ref(null)
const showDisabledValues = ref(false)
const visibleValues = computed(() => showDisabledValues.value
  ? props.values
  : props.values.filter(item => item.enabled !== false))
const metricDraft = ref({ key: '', businessName: '', baseTableId: '', expressionSql: '' })
watch(() => props.initialTab, value => {
  tab.value = value
})
watch(() => props.source.id, () => {
  tab.value = props.initialTab
})

const enabledTableCount = computed(() => (props.source.selectedTables || []).length)
const columnOptions = computed(() => props.tables.flatMap(table => (table.columns || []).map(column => ({ id: column.id, name: column.name, table: table.fullName, dataType: column.dataType }))))
function columnLabel (columnId) {
  const option = columnOptions.value.find(item => item.id === columnId)
  return option ? `${option.table}.${option.name}` : columnId
}
function tableLabel (tableId) {
  return props.tables.find(item => item.id === tableId)?.fullName || tableId
}
function createValue () {
  if (!valueDraft.value.columnId || !valueDraft.value.rawValue.trim()) {
    return
  }
  const column = columnOptions.value.find(item => item.id === valueDraft.value.columnId)
  emit('create-value', {
    columnId: valueDraft.value.columnId,
    rawValue: valueDraft.value.rawValue.trim(),
    businessName: valueDraft.value.businessName.trim(),
    aliases: valueDraft.value.aliases.split(/[,，、]/).map(item => item.trim()).filter(Boolean),
    valueType: column?.dataType || 'varchar',
    sourceType: 'MANUAL'
  })
  valueDraft.value = { columnId: '', rawValue: '', businessName: '', aliases: '' }
}
function openValueEditor (item) {
  valueEditor.value = {
    item,
    businessName: item.businessName || '',
    aliases: (item.aliases || []).join('、'),
    description: item.description || '',
    enabled: item.enabled !== false
  }
  valueEditorOpen.value = true
}
function saveValueEditor () {
  if (!valueEditor.value) {
    return
  }
  emit('update-value', valueEditor.value.item, {
    businessName: valueEditor.value.businessName.trim(),
    aliases: valueEditor.value.aliases.split(/[,，、]/).map(item => item.trim()).filter(Boolean),
    description: valueEditor.value.description.trim(),
    enabled: valueEditor.value.enabled
  })
  valueEditorOpen.value = false
}
function createMetric () {
  if (!metricDraft.value.key.trim() || !metricDraft.value.businessName.trim() || !metricDraft.value.baseTableId || !metricDraft.value.expressionSql.trim()) {
    return
  }
  emit('create-metric', {
    key: metricDraft.value.key.trim(),
    businessName: metricDraft.value.businessName.trim(),
    baseTableId: metricDraft.value.baseTableId,
    expressionSql: metricDraft.value.expressionSql.trim()
  })
  metricDraft.value = { key: '', businessName: '', baseTableId: '', expressionSql: '' }
}
const activeVersion = computed(() => props.versions.find(item => item.id === props.source.activeVersionId) || null)
const latestReady = computed(() => props.versions.find(item => item.status === 'READY') || null)
const publishable = computed(() => Boolean(latestReady.value) && latestReady.value.revision === (props.source.revision || 1) && latestReady.value.id !== props.source.activeVersionId)
const pending = computed(() => (props.feedback || []).filter(item => item.status !== 'RESOLVED').length)
const statusTitle = computed(() => props.source.enabled === false ? '数据源已停用'
  : props.source.status === 'indexed' ? '当前版本可用于查询'
    : props.source.status === 'scanned' ? '结构已扫描，等待构建版本'
      : '配置已保存，等待扫描与准备')
const publishTitle = computed(() => props.source.status === 'indexed' ? '已有可用版本'
  : publishable.value ? '最新版本可以发布' : '先构建一个 READY 版本')
const publishHint = computed(() => props.source.status === 'indexed'
  ? `当前活动版本 v${activeVersion.value?.revision ?? '—'}；重新构建后需要再次发布。`
  : publishable.value ? '发布后新查询会绑定该版本；历史查询仍保留原版本快照。'
    : '扫描结构、准备表范围并构建成功后，才能发布。')

function versionTone (status) {
  return status === 'READY' ? 'green' : status === 'ARCHIVED' ? 'blue' : status === 'FAILED' ? 'orange' : ''
}
function versionLabel (status) {
  return { DRAFT: '草稿', BUILDING: '构建中', READY: '就绪', FAILED: '失败', CANCELLED: '已取消', ARCHIVED: '已归档' }[status] || status
}
function categoryLabel (category) {
  return { helpful: '答案有帮助', meaning: '业务口径', sql: 'SQL 问题', data: '数据问题' }[category] || category
}
function metricStatusLabel (status) {
  return { DRAFT: '草稿', APPROVED: '已审核', DISABLED: '已停用' }[status] || status
}
function metricStatusTone (status) {
  return status === 'APPROVED' ? 'green' : status === 'DISABLED' ? '' : 'orange'
}
function feedbackStatusLabel (status) {
  return { OPEN: '待处理', REVIEWING: '处理中', RESOLVED: '已验证解决' }[status] || status
}
function formatTime (value) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
}
</script>

<style scoped>
.t2s-quality{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;min-width:0}
.t2s-quality>*{min-width:0}
.t2s-quality-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}
.t2s-quality-heading-main{display:flex;align-items:baseline;gap:12px}
.t2s-quality-heading>.el-select{width:260px;max-width:100%}
.t2s-quality-heading>.el-select :deep(.el-select__wrapper){min-height:40px}
.t2s-quality h2,.t2s-quality h3{margin:0}
.t2s-quality p{margin:8px 0;overflow-wrap:anywhere}
.t2s-quality-overview{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
.t2s-quality-card{padding:18px;min-width:0;background:var(--rs-bg-card);border:1px solid var(--rs-border);border-radius:8px}
.t2s-quality-card>.text-caption:first-child{display:block;margin-bottom:8px}
.t2s-quality-card .t2s-inline-actions{margin-top:16px;display:flex;gap:12px;flex-wrap:wrap}
.t2s-quality-card .el-button+.el-button{margin-left:0}
.t2s-quality-report{min-width:0}
.t2s-quality-report>.t2s-quality-heading{margin-bottom:12px}
.t2s-quality-report table{min-width:700px}
@container management (max-width:850px){.t2s-quality-overview{grid-template-columns:minmax(0,1fr)}}
@media(max-width:600px){.t2s-quality-card{padding:16px}.t2s-quality-heading>.el-select{width:100%}}
.semantic-form{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-top:16px}
.semantic-form>.el-select{width:240px;flex:0 1 240px}
.semantic-form>.el-select :deep(.el-select__wrapper){min-height:40px}
.t2s-semantics-overview{grid-template-columns:minmax(0,1fr)}
.t2s-compact-table th{height:44px;padding:10px 14px}
.t2s-compact-table td{height:56px;padding:10px 14px;white-space:normal}
.t2s-quality .list-table td .el-button+.el-button{margin-left:12px}
.t2s-compact-table .entity-sub{margin-top:4px}
</style>

<template>
  <StudioDrawer v-model="open" class="t2s-source-drawer" :data-source-id="source.id" :title="source.name" :close-on-press-escape="!busy" :show-close="!busy">
    <el-tabs v-model="tab" class="t2s-source-tabs" aria-label="数据源详情">
      <el-tab-pane label="概览" name="overview"/>
      <el-tab-pane label="数据结构" name="schema"/>
      <el-tab-pane label="业务说明" name="semantics"/>
    </el-tabs>
    <template v-if="tab === 'overview'">
      <StudioStatus :tone="statusTone" :label="statusLabel" :description="statusDescription"/>
      <FormSection number="01" title="连接信息">
        <dl class="workspace-properties text-secondary">
          <div><dt>数据库类型</dt><dd>PostgreSQL</dd></div>
          <div><dt>连接地址</dt><dd>{{ source.host }}:{{ source.port }}</dd></div>
          <div><dt>数据库 / 模式</dt><dd>{{ source.database }} / {{ (source.includeSchemas || [source.schema]).join(', ') }}</dd></div>
          <div><dt>访问账号</dt><dd>{{ source.username }}</dd></div>
          <div><dt>访问模式</dt><dd>只读 · 行数 {{ source.queryPolicy?.max_rows || 1000 }} · 超时 {{ source.queryPolicy?.timeout_ms || 30000 }}ms</dd></div>
        </dl>
        <p class="studio-inline-note text-caption"><Lock/>密码只用于建立连接，接口不会回显。</p>
      </FormSection>
      <FormSection number="02" title="数据准备">
        <dl class="workspace-properties text-secondary">
          <div><dt>可查询表</dt><dd>{{ selectedTableCount }} / {{ tables.length }} 张表<span v-if="viewCount" class="text-secondary">（含 {{ viewCount }} 个视图）</span> · {{ columnCount }} 个字段</dd></div>
          <div><dt>最近扫描</dt><dd>{{ source.scannedAt || '尚未扫描' }}</dd></div>
          <div><dt>最近发布</dt><dd>{{ source.indexedAt || '尚未发布' }}</dd></div>
          <div><dt>配置版本</dt><dd>v{{ source.revision || 1 }}</dd></div>
          <div><dt>业务时区</dt><dd>{{ source.businessTimezone || 'UTC' }}</dd></div>
          <div><dt>Embedding 模型</dt><dd>{{ source.embeddingModel || '默认模型（首次构建时确定）' }}</dd></div>
          <div><dt>LLM 模型</dt><dd>{{ source.llmModel || '部署默认模型（可随时修改）' }}</dd></div>
        </dl>
        <p class="studio-field-help text-caption">主题：{{ source.topic?.name || '未填写' }} · 维护人：{{ source.topic?.owner || '未填写' }}</p>
        <div class="toolbar"><div class="toolbar-left">
          <el-button :disabled="busy" @click="$emit('edit')">配置数据源</el-button>
          <el-button :disabled="busy || source.enabled === false" @click="$emit('prepare', 0)">准备数据</el-button>
        </div></div>
      </FormSection>
      <details class="studio-disclosure"><summary class="text-secondary"><Setting/>高级维护<ArrowDown/></summary><div class="studio-disclosure-body">
        <el-form class="studio-form" label-position="top" @submit.prevent>
          <el-form-item label="结构与索引"><el-space wrap>
            <el-button :loading="action === 'scan'" :disabled="busy || source.enabled === false" @click="$emit('scan')">扫描 Schema</el-button>
            <el-button :loading="action === 'index'" :disabled="busy || source.status === 'configured' || source.enabled === false" @click="$emit('index')">构建版本</el-button>
          </el-space><p class="studio-field-help text-caption">扫描只更新结构目录；构建会冻结当前配置并向量化知识对象，发布后新查询才会使用。</p></el-form-item>
          <el-form-item label="数据源状态"><el-space wrap>
            <el-button :disabled="busy" @click="$emit('toggle')">{{ source.enabled === false ? '启用数据源' : '停用数据源' }}</el-button>
            <el-tooltip content="至少保留一个数据源" :disabled="canDelete"><span><el-button type="danger" plain :disabled="busy || !canDelete" @click="$emit('delete')">删除数据源</el-button></span></el-tooltip>
          </el-space></el-form-item>
        </el-form>
      </div></details>
    </template>
    <template v-else-if="tab === 'schema'">
      <FormSection number="01" title="可查询表">
        <p class="workspace-panel-intro text-secondary">{{ tables.length }} 张表{{ viewCount ? `（含 ${viewCount} 个视图）` : '' }} · {{ columnCount }} 个字段 · {{ relations.length }} 条关联。</p>
        <el-empty v-if="!tables.length" description="尚未扫描结构"/>
        <template v-else>
          <el-input v-model="schemaSearch" clearable :prefix-icon="Search" aria-label="搜索数据结构" placeholder="搜索表名或业务说明…"/>
          <p class="text-caption muted">匹配 {{ filteredTables.length }} 张表</p>
          <el-collapse v-model="expandedTables">
            <el-collapse-item v-for="table in filteredTables" :key="table.id" :name="table.id" :title="tableTitle(table)">
              <div class="table-card"><table class="list-table"><thead><tr><th>字段</th><th>类型</th><th>说明</th></tr></thead><tbody>
                <tr v-for="column in table.columns" :key="column.id"><td><code class="text-code">{{ column.name }}</code><div v-if="column.primaryKey || column.foreignKey" class="entity-sub">{{ column.primaryKey ? '主键' : '关联键' }}</div></td><td>{{ column.dataType }}</td><td>{{ column.businessDescription || column.dbComment || '—' }}<div v-if="column.valueCardinality === 'LOW'" class="entity-sub">自动收录 {{ column.distinctValueCount || 0 }} 个取值</div><div v-else-if="column.valueCardinality === 'HIGH'" class="entity-sub">高基数 · 查询时按需解析</div></td></tr>
              </tbody></table></div>
            </el-collapse-item>
          </el-collapse>
        </template>
      </FormSection>
      <FormSection number="02" title="表关联"><el-space wrap class="t2s-source-actions"><el-button link type="primary" @click="$emit('relations')">维护关联</el-button></el-space><ul class="workspace-panel-list"><li v-for="relation in relations" :key="relation.id" class="text-secondary"><code class="text-code">{{ relation.name }}：{{ relation.sourceTable?.fullName || relation.sourceTableId }} → {{ relation.targetTable?.fullName || relation.targetTableId }}</code><span v-if="relation.cardinality" class="entity-sub">{{ relation.cardinality }}</span></li><li v-if="!relations.length" class="text-secondary">还没有关联；同名表需要手工补充。</li></ul></FormSection>
    </template>
    <template v-else>
      <FormSection number="01" title="业务说明"><dl class="workspace-properties text-secondary"><div><dt>数据源说明</dt><dd>{{ source.businessDescription || source.topic?.description || '未填写' }}</dd></div><div><dt>主题维护人</dt><dd>{{ source.topic?.owner || '未填写' }}</dd></div></dl><el-space wrap class="t2s-source-actions"><el-button :disabled="busy || source.enabled === false" @click="$emit('prepare', 1)">维护表与字段说明</el-button><el-button :disabled="busy || source.enabled === false" @click="$emit('quality')">维护枚举值与指标</el-button></el-space></FormSection>
      <FormSection number="02" title="指标"><ul class="workspace-panel-list"><li v-for="metric in metrics" :key="metric.id" class="text-secondary"><strong class="text-label">{{ metric.businessName }}</strong><code class="text-code">{{ metric.expressionSql }}</code><span class="entity-sub">{{ metric.status }}</span></li><li v-if="!metrics.length" class="text-secondary">还没有指标定义。</li></ul></FormSection>
    </template>
    <template #footer><div class="studio-dialog-footer"><span class="studio-footer-hint text-caption">{{ isQuerySource ? '当前查询工作台使用此数据源' : '查看详情不会切换查询数据源' }}</span><div class="studio-footer-actions"><el-button :disabled="busy" @click="open = false">关闭</el-button><el-button v-if="source.enabled === false" type="primary" :disabled="busy" @click="$emit('toggle')">启用数据源</el-button><el-button v-else-if="source.status !== 'indexed'" type="primary" :disabled="busy" @click="$emit('prepare', 0)">准备数据</el-button><el-button v-else type="primary" :disabled="busy" @click="$emit('use')">使用此数据源查询<Right/></el-button></div></div></template>
  </StudioDrawer>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ArrowDown, Lock, Right, Search, Setting } from '@element-plus/icons-vue'
import StudioDrawer from '@/shared/ui/StudioDrawer.vue'
import StudioStatus from '@/shared/ui/StudioStatus.vue'
import FormSection from '@/shared/ui/FormSection.vue'
import { tableTitle } from '@/features/text2sql/utils/tableTitle'
const open = defineModel({ type: Boolean, default: false })
const props = defineProps({
  source: { type: Object, required: true },
  tables: { type: Array, default: () => [] },
  relations: { type: Array, default: () => [] },
  metrics: { type: Array, default: () => [] },
  initialTab: { type: String, default: 'overview' },
  busy: Boolean,
  action: String,
  canDelete: Boolean,
  isQuerySource: Boolean
})
defineEmits(['edit', 'prepare', 'scan', 'relations', 'index', 'toggle', 'delete', 'use', 'quality'])
const tab = ref(props.initialTab)
const schemaSearch = ref('')
const expandedTables = ref([])
const selectedTableCount = computed(() => (props.source.selectedTables || []).length)
const viewCount = computed(() => props.tables.filter(table => table.type && table.type !== 'BASE_TABLE').length)
const columnCount = computed(() => props.tables.reduce((total, table) => total + (table.columns?.length || 0), 0))
const filteredTables = computed(() => props.tables.filter(table => `${table.fullName} ${table.businessName || ''} ${table.dbComment || ''}`.toLowerCase().includes(schemaSearch.value.trim().toLowerCase())))
const statusTone = computed(() => props.source.enabled === false ? 'muted' : props.source.status === 'indexed' ? 'success' : props.source.status === 'scanned' ? 'warning' : 'info')
const statusLabel = computed(() => props.source.enabled === false ? '已停用' : props.source.status === 'indexed' ? '索引就绪' : props.source.status === 'scanned' ? '结构已扫描' : '待准备')
const statusDescription = computed(() => props.source.status === 'indexed' ? '当前版本已发布，可用于查询。' : '扫描结构、选择表并构建发布后才能查询。')
</script>

<style scoped>
.t2s-source-tabs :deep(.el-tabs__nav > .el-tabs__item:nth-child(2)) { padding-left: 0 !important; }
.t2s-source-actions { margin-top: 16px; }
.el-collapse :deep(.el-collapse-item__content) { padding-bottom: 8px; }
.workspace-panel-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }
.workspace-panel-list li { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
</style>

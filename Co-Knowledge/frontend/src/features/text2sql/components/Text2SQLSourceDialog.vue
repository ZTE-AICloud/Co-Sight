<template>
  <StudioDialog v-model="open" dialog-class="text2sql-source-dialog" :title="source ? '配置数据源' : '新增数据源'" subtitle="配置结构化知识来源，测试连接后保存。" :icon="Coin" hint="密码只用于建立连接，不会回显" width="680px">
    <el-form ref="form" :model="draft" :rules="rules" label-position="top" class="studio-form" @submit.prevent="save">
      <FormSection number="01" title="基本信息">
        <div class="studio-field-grid">
          <el-form-item label="数据源名称" prop="name"><el-input v-model="draft.name" aria-label="数据源名称" maxlength="60" placeholder="例如：电商业务库"/></el-form-item>
          <el-form-item label="数据库类型"><el-input model-value="PostgreSQL" disabled aria-label="数据库类型"/></el-form-item>
        </div>
      </FormSection>
      <FormSection number="02" title="面向提问者的分析主题" note="主题信息只用于介绍数据，不改变计算口径">
        <div class="studio-field-grid"><el-form-item label="主题名称"><el-input v-model="draft.topic.name" aria-label="主题名称" maxlength="60" placeholder="例如：电商经营分析"/></el-form-item><el-form-item label="维护人"><el-input v-model="draft.topic.owner" aria-label="主题维护人" maxlength="60" placeholder="例如：数据分析团队"/></el-form-item></div>
        <el-form-item label="主题介绍"><el-input v-model="draft.topic.description" aria-label="主题介绍" type="textarea" :rows="2" maxlength="200" placeholder="说明业务范围，帮助提问者选对数据。"/></el-form-item>
      </FormSection>
      <FormSection number="03" title="连接配置" note="PostgreSQL · 只读账号">
        <div class="studio-field-grid">
          <el-form-item label="Host" prop="host"><el-input v-model="draft.host" aria-label="Host" maxlength="255" placeholder="localhost"/></el-form-item>
          <el-form-item label="Port" prop="port"><el-input-number v-model="draft.port" aria-label="Port" :min="1" :max="65535" :precision="0" controls-position="right"/></el-form-item>
        </div>
        <div class="studio-field-grid">
          <el-form-item label="Database" prop="database"><el-input v-model="draft.database" aria-label="Database" maxlength="100"/></el-form-item>
          <el-form-item label="Schema" prop="schemas">
            <el-select v-model="draft.schemas" multiple filterable allow-create default-first-option
                       :reserve-keyword="false" aria-label="Schema（可多个）"
                       :placeholder="schemaOptions.length ? '选择或输入 schema，可多选' : '先测试连接，再选择 schema'">
              <el-option v-for="name in schemaOptions" :key="name" :label="name" :value="name"/>
            </el-select>
            <p class="studio-field-help text-caption">只扫描这里选中的 schema，可添加多个；测试连接后会列出该库可用的 schema。</p>
          </el-form-item>
        </div>
        <div class="studio-field-grid">
          <el-form-item label="Username" prop="username"><el-input v-model="draft.username" aria-label="Username" maxlength="100" autocomplete="off"/></el-form-item>
          <el-form-item label="Password" prop="password"><el-input v-model="draft.password" type="password" aria-label="Password" maxlength="200" autocomplete="new-password" :placeholder="source?.passwordConfigured ? '留空表示沿用已保存密码' : '输入数据库密码'"/></el-form-item>
        </div>
        <div class="studio-field-grid source-policy-grid">
          <el-form-item label="业务时区">
            <el-select v-model="draft.businessTimezone" filterable allow-create aria-label="业务时区">
              <el-option v-for="zone in timezoneOptions" :key="zone" :value="zone"
                         :label="zone === currentTimezone ? `${zone}（当前）` : zone"/>
            </el-select>
          </el-form-item>
          <el-form-item label="最大返回行数"><el-input-number v-model="draft.maxRows" :min="1" :max="10000" controls-position="right" aria-label="最大返回行数"/></el-form-item>
          <el-form-item label="查询超时（ms）"><el-input-number v-model="draft.timeoutMs" :min="100" :max="120000" :step="1000" controls-position="right" aria-label="查询超时毫秒"/></el-form-item>
        </div>
        <el-form-item label="Embedding 模型" prop="embeddingModel">
          <el-select v-model="draft.embeddingModel" filterable :disabled="Boolean(source?.embeddingModel)"
                     :placeholder="embeddingModels.length ? '选择向量化模型' : '未注册模型，使用默认端点'" aria-label="Embedding 模型">
            <el-option v-for="model in embeddingModels" :key="model" :label="model" :value="model"/>
          </el-select>
        </el-form-item>
        <p class="text-caption studio-inline-note">模型决定向量维度；首次构建后固定，之后换模型需要新建数据源。</p>
        <el-form-item label="LLM 模型" prop="llmModel">
          <el-select v-model="draft.llmModel" filterable clearable
                     :placeholder="llmModels.length ? '选择 SQL 生成模型（留空跟随部署默认）' : '未注册模型，使用部署默认'" aria-label="LLM 模型">
            <el-option v-for="model in llmModels" :key="model" :label="model" :value="model"/>
          </el-select>
        </el-form-item>
        <p class="text-caption studio-inline-note">用于把业务问题生成 SQL；创建后可随时修改，留空表示跟随部署默认模型。</p>
        <p class="text-caption studio-inline-note"><Lock/>推荐使用只读账号；查询在只读事务中执行，并受行数与超时限制。</p>
        <div class="t2s-connection-test">
          <el-button :loading="testing" @click="testConnection"><Connection/>测试连接</el-button>
          <span v-if="tested" class="text-caption"><CircleCheckFilled/>连接成功 {{ latency ? `· ${latency} ms` : '' }}</span>
        </div>
      </FormSection>
    </el-form>
    <template #actions><el-button @click="open = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存配置</el-button></template>
  </StudioDialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { Coin, Lock, Connection, CircleCheckFilled } from '@element-plus/icons-vue'
import StudioDialog from '@/shared/ui/StudioDialog.vue'
import FormSection from '@/shared/ui/FormSection.vue'
import { getModelList, getLLMModel } from '@/features/model/api/models.js'
import {
  testConnection as testSavedConnection,
  testConnectionPayload
} from '@/features/text2sql/api/text2sql.js'

const open = defineModel({ type: Boolean, default: false })
const props = defineProps({ source: Object, existingNames: { type: Array, default: () => [] } })
const emit = defineEmits(['save'])
const form = ref()
const testing = ref(false)
const saving = ref(false)
const tested = ref(false)
const latency = ref(0)
const embeddingModels = ref([])
const llmModels = ref([])
const draft = reactive({ topic: { name: '', owner: '', description: '' }, schemas: [] })
// 业务时区：默认跟浏览器/部署环境的当前时区一致，候选是 IANA 全量清单。
const currentTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai'
const timezoneOptions = (() => {
  let zones = []
  try {
    zones = Intl.supportedValuesOf?.('timeZone') || []
  } catch {
    zones = []
  }
  if (!zones.length) {
    zones = ['UTC', 'Asia/Shanghai', 'Asia/Tokyo', 'Europe/London', 'America/New_York']
  }
  return Array.from(new Set([currentTimezone, ...zones]))
})()
// 测试连接后由后端列出账号可见的 schema；已选值始终保留在候选里，避免标签失去选项。
const fetchedSchemas = ref([])
const schemaOptions = computed(() => Array.from(new Set([
  ...(draft.schemas || []), ...fetchedSchemas.value
])))

// 注册表（模型管理页）是唯一数据源：这里能选的就是运行期模型解析认的那些。
async function loadEmbeddingModels () {
  try {
    const models = await getModelList()
    embeddingModels.value = (Array.isArray(models) ? models : [])
      .map(item => (typeof item === 'string' ? item : item?.modelName))
      .filter(Boolean)
  } catch {
    embeddingModels.value = []
  }
}

// SQL 生成模型：可选注入；留空时运行期回落到部署默认模型。
async function loadLlmModels () {
  try {
    const models = await getLLMModel()
    llmModels.value = (Array.isArray(models) ? models : [])
      .map(item => item?.modelValue)
      .filter(Boolean)
  } catch {
    llmModels.value = []
  }
}
const required = label => ({
  validator: (_, value, callback) => callback(typeof value === 'string' && value.trim() ? undefined : new Error(`请输入${label}`)),
  trigger: 'blur'
})
const rules = {
  name: [required('数据源名称'), {
    validator: (_, value, callback) => callback(props.existingNames.some(name => name.toLowerCase() === String(value || '').trim().toLowerCase()) ? new Error('已存在同名数据源') : undefined),
    trigger: 'blur'
  }],
  host: [required('Host')],
  database: [required('Database')],
  schemas: [{
    validator: (_, value, callback) => callback(
      Array.isArray(value) && value.some(name => String(name).trim())
        ? undefined
        : new Error('请至少选择一个 Schema')),
    trigger: 'change'
  }],
  username: [required('Username')],
  port: [{ type: 'number', required: true, min: 1, max: 65535, message: '请输入 1–65535 的端口号', trigger: 'change' }],
  embeddingModel: [{
    validator: (_, value, callback) => callback(
      !props.source && embeddingModels.value.length && !value
        ? new Error('请选择 Embedding 模型')
        : undefined),
    trigger: 'change'
  }],
  password: [{
    validator: (_, value, callback) => callback(value || props.source?.passwordConfigured ? undefined : new Error('请输入数据库密码')),
    trigger: 'blur'
  }]
}
watch(open, value => {
  testing.value = false
  saving.value = false
  tested.value = false
  latency.value = 0
  fetchedSchemas.value = []
  if (value && !embeddingModels.value.length) {
    loadEmbeddingModels()
  }
  if (value && !llmModels.value.length) {
    loadLlmModels()
  }
  Object.assign(draft, value
    ? {
        name: props.source?.name || '',
        host: props.source?.host || 'localhost',
        port: props.source?.port || 5432,
        database: props.source?.database || '',
        schemas: [...(props.source?.includeSchemas || [props.source?.schema || 'public'])],
        username: props.source?.username || '',
        password: '',
        businessTimezone: props.source?.businessTimezone || currentTimezone,
        maxRows: props.source?.queryPolicy?.max_rows || 1000,
        timeoutMs: props.source?.queryPolicy?.timeout_ms || 30000,
        embeddingModel: props.source?.embeddingModel || '',
        llmModel: props.source?.llmModel || '',
        topic: props.source
          ? { ...(props.source.topic || {}) }
          : { name: '', owner: '', description: '' }
      }
    : { password: '' })
})
watch(() => [draft.host, draft.port, draft.database, draft.username, draft.password,
  JSON.stringify(draft.schemas)], () => {
  tested.value = false
})
async function valid () {
  try {
    return await form.value.validate()
  } catch {
    return false
  }
}

// 测试连接只校验连接相关字段：Embedding 模型还没选也不该挡住连通性验证。
const CONNECTION_FIELDS = ['name', 'host', 'port', 'database', 'schemas', 'username', 'password']
async function validConnection () {
  try {
    await form.value.validateField(CONNECTION_FIELDS)
    return true
  } catch {
    return false
  }
}
function payload () {
  const values = {
    name: draft.name.trim(),
    dbType: 'postgresql',
    host: draft.host.trim(),
    port: draft.port,
    database: draft.database.trim(),
    schemas: (draft.schemas || []).map(name => String(name).trim()).filter(Boolean),
    username: draft.username.trim(),
    password: draft.password,
    topic: Object.fromEntries(Object.entries(draft.topic).map(([key, value]) => [key, String(value || '').trim()])),
    businessTimezone: draft.businessTimezone.trim() || 'UTC',
    queryPolicy: { max_rows: draft.maxRows, timeout_ms: draft.timeoutMs }
  }
  // 空值不发：后端把「未指定」解释为使用默认模型，空字符串会被当成非法非空文本。
  if (draft.embeddingModel && draft.embeddingModel.trim()) {
    values.embeddingModel = draft.embeddingModel.trim()
  }
  // LLM 可随时改：空串也发，PATCH 时表示「清空 = 跟随部署默认」。
  values.llmModel = (draft.llmModel || '').trim()
  return values
}
async function testConnection () {
  if (!await validConnection()) {
    return
  }
  testing.value = true
  tested.value = false
  try {
    const result = draft.password || !props.source
      ? await testConnectionPayload(payload())
      : await testSavedConnection(props.source.id)
    tested.value = true
    latency.value = result?.latencyMs || 0
    if (Array.isArray(result?.schemas) && result.schemas.length) {
      fetchedSchemas.value = result.schemas
      // 首次测试后如果只默认选了 public 而该库没有 public，改为空选择让用户挑。
      if (draft.schemas.length === 1 && draft.schemas[0] === 'public' &&
          !result.schemas.includes('public')) {
        draft.schemas = []
      }
    }
  } catch (error) {
    // 全局 toast 已提示；保留表单便于修正
  } finally {
    testing.value = false
  }
}
async function save () {
  if (!await valid()) {
    return
  }
  saving.value = true
  try {
    const values = payload()
    if (!draft.password && props.source?.passwordConfigured) {
      delete values.password
    }
    emit('save', values)
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.t2s-connection-test { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-top: 12px; }
.t2s-connection-test .text-caption { color: var(--rs-success); display: inline-flex; align-items: center; gap: 6px; }
.source-policy-grid { grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr) minmax(0, 1fr); }
.source-policy-grid :deep(.el-input-number),
.source-policy-grid :deep(.el-select) { width: 100%; }
@media (max-width: 600px) {
  .source-policy-grid { grid-template-columns: minmax(0, 1fr); }
}
</style>

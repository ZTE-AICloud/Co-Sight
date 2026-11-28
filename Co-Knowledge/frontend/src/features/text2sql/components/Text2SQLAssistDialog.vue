<script setup>
/**
 * AI 辅助：生成「建议」，人确认后才写入。
 *
 * 三种建议共用一套流程：选范围 → 生成 → 勾选 → 采纳。
 * 生成不落库；采纳走既有 PATCH 接口，建议只是把人工填写变成人工审核。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Loading, MagicStick } from '@element-plus/icons-vue'
import StudioDialog from '@/shared/ui/StudioDialog.vue'
import {
  assistStream,
  createMetric,
  createRelation,
  updateColumn,
  updateDatasource,
  updateTable,
  updateValue
} from '@/features/text2sql/api/text2sql.js'

const open = defineModel({ type: Boolean, default: false })
const props = defineProps({
  datasourceId: { type: String, default: '' },
  source: { type: Object, default: () => ({}) },
  tables: { type: Array, default: () => [] },
  values: { type: Array, default: () => [] }
})
const emit = defineEmits(['refresh'])

const KINDS = [
  { value: 'descriptions', label: '表与字段说明', hint: '为已选表生成业务名称、说明、别名与语义类型' },
  { value: 'tables', label: '推荐表', hint: '按业务主题推荐应纳入查询范围的表' },
  { value: 'values', label: '枚举释义', hint: '为已收录的取值补中文业务名称（如 status=1 → 已支付）' },
  { value: 'relations', label: '关联推断', hint: '推断没有外键但查询需要的关联，创建为「推断」关联，核对后可在表关联里标记已验证' },
  { value: 'metrics', label: '指标建议', hint: '从数值字段提出指标，表达式先经 SQL 白名单校验，采纳后仍是草稿待审核' },
  { value: 'questions', label: '示例问题', hint: '生成提问框展示的业务问题示例，保存后替换按表名拼出来的默认示例' }
]

const kind = ref('descriptions')
const includeSamples = ref(true)
const question = ref('')
const loading = ref(false)
const applying = ref(false)
const suggestions = ref([])
const selected = ref([])
const meta = ref(null)
const progress = ref(null)

const currentKind = computed(() => KINDS.find(item => item.value === kind.value) || KINDS[0])
const selectedCount = computed(() => selected.value.filter(Boolean).length)

let controller = null

function abortRun () {
  if (controller) {
    controller.abort()
    controller = null
  }
  loading.value = false
  progress.value = null
}

watch(open, value => {
  abortRun()
  suggestions.value = []
  selected.value = []
  meta.value = null
  applying.value = false
  if (value) {
    kind.value = 'descriptions'
    includeSamples.value = true
    question.value = props.source?.topic?.description || ''
  }
})

watch(kind, () => {
  // 切换种类时丢弃上一类的在途结果，避免「示例问题」页里冒出表说明。
  abortRun()
  suggestions.value = []
  selected.value = []
  meta.value = null
})

function parseFrame (frame) {
  try {
    return JSON.parse(frame.data)
  } catch {
    return null
  }
}

async function generate () {
  if (!props.datasourceId || loading.value) {
    return
  }
  abortRun()
  controller = new AbortController()
  const current = controller
  loading.value = true
  progress.value = null
  suggestions.value = []
  selected.value = []
  meta.value = null
  try {
    const outcome = await assistStream(props.datasourceId, {
      kind: kind.value,
      includeSamples: includeSamples.value,
      question: kind.value === 'tables' ? question.value.trim() : undefined
    }, {
      signal: current.signal,
      onEvent: frame => {
        if (controller !== current) {
          return
        }
        const data = parseFrame(frame)
        if (!data) {
          return
        }
        if (frame.event === 'stage') {
          const state = progress.value || {}
          if (data.id === 'collect') {
            progress.value = { ...state, collect: true }
          } else if (data.id === 'sample') {
            progress.value = { ...state, sample: true, sampled: data.status === 'success' }
          } else if (data.id === 'generate') {
            progress.value = { ...state, generate: data }
          }
        } else if (frame.event === 'result') {
          suggestions.value = data.suggestions || []
          selected.value = suggestions.value.map(item => item.target !== 'table' || item.enabled !== true)
          meta.value = {
            model: data.model || '',
            tokens: data.usage?.total_tokens || 0,
            sampled: Boolean(data.sampled),
            batches: data.batches || 1
          }
        }
      }
    })
    if (controller !== current) {
      return
    }
    if (outcome.errorEnvelope) {
      ElMessage.error(outcome.errorEnvelope.detail || '生成失败')
    } else if (outcome.errorEvent) {
      ElMessage.error(outcome.errorEvent.detail || '生成失败')
    } else if (!suggestions.value.length) {
      ElMessage.info('模型没有给出可用建议，可调整范围后重试')
    }
  } catch (error) {
    if (error?.name !== 'AbortError' && controller === current) {
      ElMessage.error('生成失败，请稍后重试')
    }
  } finally {
    if (controller === current) {
      controller = null
      loading.value = false
    }
  }
}

function payloadOf (item) {
  if (kind.value === 'tables') {
    return { enabled: true }
  }
  if (kind.value === 'relations') {
    return {
      name: item.name,
      type: 'INFERRED',
      cardinality: item.cardinality,
      description: item.reason || '',
      sourceTableId: item.sourceTableId,
      targetTableId: item.targetTableId,
      columnPairs: item.columnPairs
    }
  }
  if (kind.value === 'metrics') {
    const payload = {
      key: item.key,
      businessName: item.businessName,
      businessDescription: item.businessDescription || '',
      baseTableId: item.baseTableId,
      expressionSql: item.expressionSql
    }
    if (item.unit) {
      payload.unit = item.unit
    }
    return payload
  }
  const payload = {}
  if (item.businessName) {
    payload.businessName = item.businessName
  }
  if (item.businessDescription) {
    payload.businessDescription = item.businessDescription
  }
  if (item.aliases?.length) {
    payload.aliases = item.aliases
  }
  if (item.target === 'column' && item.semanticType) {
    payload.semanticType = item.semanticType
  }
  return payload
}

async function apply () {
  const chosen = suggestions.value.filter((item, index) => selected.value[index])
  if (!chosen.length || applying.value) {
    return
  }
  applying.value = true
  if (kind.value === 'questions') {
    // 示例问题是数据源级字段，一次 PATCH 保存选中的问题。
    try {
      await updateDatasource(props.datasourceId, {
        queryExamples: chosen.map(item => ({ question: item.question, hint: item.hint || '' }))
      })
      ElMessage.success(`已保存 ${chosen.length} 个示例问题`)
      emit('refresh')
      open.value = false
    } catch (error) {
      // 全局 toast 已提示
    } finally {
      applying.value = false
    }
    return
  }
  let applied = 0
  try {
    for (const item of chosen) {
      const payload = payloadOf(item)
      if (!Object.keys(payload).length) {
        continue
      }
      if (item.target === 'table') {
        await updateTable(props.datasourceId, item.id, payload)
      } else if (item.target === 'column') {
        await updateColumn(props.datasourceId, item.id, payload)
      } else if (item.target === 'value') {
        await updateValue(props.datasourceId, item.id, payload)
      } else if (item.target === 'relation') {
        await createRelation(props.datasourceId, payload)
      } else if (item.target === 'metric') {
        await createMetric(props.datasourceId, payload)
      }
      applied += 1
    }
    ElMessage.success(`已采纳 ${applied} 条建议，构建并发布新版本后生效`)
    emit('refresh')
    open.value = false
  } catch (error) {
    // 全局 toast 已提示
  } finally {
    applying.value = false
  }
}

const SEMANTIC_LABEL = {
  identifier: '标识', measure: '度量', dimension: '维度', time: '时间', category: '分类'
}

const TARGET_META = {
  table: { label: '表', tone: 'blue' },
  column: { label: '字段', tone: 'cyan' },
  value: { label: '枚举', tone: 'orange' },
  relation: { label: '关联', tone: 'purple' },
  metric: { label: '指标', tone: 'green' },
  question: { label: '问题', tone: '' }
}

const CARDINALITY_LABEL = {
  ONE_TO_ONE: '一对一',
  ONE_TO_MANY: '一对多',
  MANY_TO_ONE: '多对一',
  MANY_TO_MANY: '多对多'
}

function targetMeta (target) {
  return TARGET_META[target] || { label: '建议', tone: '' }
}

// 把不同 target 的字段收敛成「标签 + 值」两列，模板只负责排版。
function factsOf (item) {
  const facts = []
  if (item.target === 'metric') {
    if (item.expressionSql) {
      facts.push({ label: '表达式', value: item.expressionSql, code: true })
    }
    if (item.key) {
      facts.push({ label: '指标 key', value: item.key, code: true })
    }
    if (item.baseTable) {
      facts.push({ label: '基础表', value: item.baseTable })
    }
    if (item.unit) {
      facts.push({ label: '单位', value: item.unit })
    }
    if (item.businessDescription) {
      facts.push({ label: '口径', value: item.businessDescription })
    }
    return facts
  }
  if (item.businessName) {
    facts.push({ label: '名称', value: item.businessName, strong: true })
  }
  if (item.businessDescription) {
    facts.push({ label: '说明', value: item.businessDescription })
  }
  if (item.aliases?.length) {
    facts.push({ label: '别名', value: item.aliases.join('、') })
  }
  if (item.semanticType) {
    facts.push({ label: '语义类型', value: SEMANTIC_LABEL[item.semanticType] || item.semanticType })
  }
  if (item.target === 'relation') {
    if (item.name) {
      facts.push({ label: '关联名', value: item.name, code: true })
    }
    if (item.cardinality) {
      facts.push({ label: '基数', value: CARDINALITY_LABEL[item.cardinality] || item.cardinality })
    }
  }
  return facts
}
</script>

<template>
  <StudioDialog v-model="open" dialog-class="text2sql-assist-dialog" title="AI 辅助" :icon="MagicStick"
                subtitle="模型只给建议，勾选后才会写入；写入后需构建并发布新版本。" width="760px">
    <div class="assist">
      <el-tabs v-model="kind" class="assist-tabs" aria-label="建议类型">
        <el-tab-pane v-for="item in KINDS" :key="item.value" :label="item.label" :name="item.value"/>
      </el-tabs>
      <p class="assist-hint text-caption muted">{{ currentKind.hint }}</p>

      <el-form v-if="kind === 'tables'" class="studio-form assist-topic" label-position="top" @submit.prevent="generate">
        <el-form-item label="业务主题">
          <el-input v-model="question" maxlength="500" placeholder="例如：分析订单、支付与城市分布"/>
        </el-form-item>
      </el-form>

      <div class="assist-run">
        <el-checkbox v-model="includeSamples" class="assist-samples">
          <span class="assist-samples-label">发送少量样本数据</span>
          <span class="assist-samples-note">每表最多 3 行，字段值截断到 80 字</span>
        </el-checkbox>
        <el-button type="primary" :icon="MagicStick" :loading="loading" :disabled="!datasourceId" @click="generate">
          {{ suggestions.length ? '重新生成' : '生成建议' }}
        </el-button>
      </div>

      <div v-if="meta" class="assist-meta">
        <span class="tag-soft blue">模型 {{ meta.model || '默认' }}</span>
        <span v-if="meta.tokens" class="tag-soft">{{ meta.tokens }} tokens</span>
        <span v-if="meta.sampled" class="tag-soft green">已附带样本</span>
        <span v-if="meta.batches > 1" class="tag-soft cyan">分 {{ meta.batches }} 批生成</span>
      </div>

      <div v-if="loading" class="assist-progress" role="status" aria-live="polite">
        <span class="assist-progress-icon"><Loading class="assist-spinner"/></span>
        <div class="assist-progress-main">
          <strong>正在生成建议</strong>
          <p v-if="progress?.collect || progress?.sample || progress?.generate" class="text-caption muted">
            <span v-if="progress?.collect">目录已读取</span>
            <span v-if="progress?.sample">样本{{ progress.sampled ? '已采集' : '未采集' }}</span>
            <span v-if="progress?.generate">模型生成 {{ progress.generate.batch }}/{{ progress.generate.batches }}</span>
          </p>
        </div>
      </div>

      <section v-else-if="suggestions.length" class="assist-results" aria-label="建议列表">
        <div class="assist-heading">
          <h4 class="text-section-title">{{ suggestions.length }} 条建议</h4>
          <span class="text-caption muted">已选 {{ selectedCount }} 条</span>
        </div>
        <ul class="assist-list">
          <li v-for="(item, index) in suggestions" :key="`${item.target}-${item.id}-${index}`"
              :class="{ 'is-selected': selected[index] }">
            <el-checkbox v-model="selected[index]" class="assist-check" :aria-label="`选择建议 ${item.label}`"/>
            <div class="assist-main">
              <div class="assist-label">
                <span class="tag-soft" :class="targetMeta(item.target).tone">{{ targetMeta(item.target).label }}</span>
                <code v-if="item.target !== 'question' && item.target !== 'metric'" class="text-code assist-object">{{ item.label }}</code>
                <span v-else-if="item.target === 'question'" class="assist-question text-body">{{ item.label }}</span>
                <span v-else class="assist-object assist-object-title">{{ item.businessName || item.label }}</span>
                <span v-if="item.target === 'table' && item.enabled" class="tag-soft green">已在范围内</span>
              </div>
              <dl v-if="factsOf(item).length" class="assist-facts">
                <div v-for="fact in factsOf(item)" :key="fact.label">
                  <dt>{{ fact.label }}</dt>
                  <dd :class="{ 'assist-facts-strong': fact.strong }">
                    <code v-if="fact.code" class="text-code">{{ fact.value }}</code>
                    <template v-else>{{ fact.value }}</template>
                  </dd>
                </div>
              </dl>
              <p v-if="item.hint" class="assist-note text-caption muted">依据：{{ item.hint }}</p>
              <p v-if="item.reason" class="assist-note text-caption muted">理由：{{ item.reason }}</p>
              <p v-if="item.target === 'relation'" class="assist-note text-caption muted">
                采纳后创建为「推断」关联，核对后可在表关联里标记已验证。
              </p>
            </div>
          </li>
        </ul>
      </section>

      <div v-else class="assist-empty">
        <span class="assist-empty-icon"><MagicStick/></span>
        <strong>选择范围后生成建议</strong>
        <p class="text-caption muted">生成不会修改任何配置；勾选后点「采纳选中」才会写入。</p>
      </div>
    </div>

    <template #actions>
      <el-button @click="open = false">关闭</el-button>
      <el-button type="primary" :disabled="!selectedCount || applying" :loading="applying" @click="apply">
        采纳选中（{{ selectedCount }}）
      </el-button>
    </template>
  </StudioDialog>
</template>

<style scoped>
.assist { padding: 18px 0 26px; }
.assist-tabs :deep(.el-tabs__header) { margin: 0; }
.assist-tabs :deep(.el-tabs__item) { height: 44px; padding: 0 13px !important; font-size: var(--rs-font-size-body); }
.assist-tabs :deep(.el-tabs__item:first-child) { padding-left: 0 !important; }
.assist-tabs :deep(.el-tabs__nav-wrap::after) { background: var(--rs-border-soft); }
.assist-hint { margin: 10px 0 0; }
.assist-topic { margin-top: 20px; }
.assist-topic :deep(.el-form-item) { margin-bottom: 0; }
.assist-run { display: flex; align-items: center; justify-content: space-between; gap: 12px 20px; flex-wrap: wrap; margin-top: 20px; }
.assist-run > .el-button { flex-shrink: 0; }
.assist-samples { height: auto; min-height: 0; margin-right: auto; align-items: flex-start; }
.assist-samples :deep(.el-checkbox__label) { display: flex; flex-direction: column; gap: 2px; padding-left: 8px; line-height: 1.45; white-space: normal; }
.assist-samples-label { color: var(--rs-text); font-size: var(--rs-font-size-secondary); }
.assist-samples-note { color: var(--rs-text-3); font-size: var(--rs-font-size-caption); }
.assist-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.assist-progress { display: flex; align-items: center; justify-content: center; gap: 14px; min-height: 220px; margin-top: 12px; padding: 32px 20px; }
.assist-progress-icon { display: flex; align-items: center; justify-content: center; width: 42px; height: 42px; border-radius: 11px; background: var(--rs-bg-selected); color: var(--rs-primary); }
.assist-progress-icon svg { width: 22px; height: 22px; }
.assist-spinner { animation: assist-spin 1.1s linear infinite; }
.assist-progress-main { min-width: 0; }
.assist-progress-main strong { display: block; color: var(--rs-text); font-weight: 600; line-height: 1.4; }
.assist-progress-main p { display: flex; flex-wrap: wrap; align-items: center; gap: 2px 8px; margin: 5px 0 0; }
.assist-progress-main p span + span::before { content: '·'; margin-right: 8px; color: var(--rs-text-3); }
.assist-results { margin-top: 18px; }
.assist-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.assist-heading h4 { margin: 0; color: var(--rs-text); }
.assist-list { display: flex; flex-direction: column; gap: 8px; margin: 0; padding: 0; list-style: none; }
.assist-list > li { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 10px; padding: 12px 14px; border: 1px solid var(--rs-border); border-radius: 10px; background: var(--rs-bg-card); transition: border-color .15s, background .15s; }
.assist-list > li:hover { border-color: var(--rs-primary-border); }
.assist-list > li.is-selected { border-color: var(--rs-primary-border); background: var(--rs-bg-selected); }
.assist-check { height: auto; min-height: 0; margin-top: 1px; }
.assist-main { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.assist-label { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; min-width: 0; }
.assist-object { min-width: 0; color: var(--rs-text); font-size: var(--rs-font-size-code); overflow-wrap: anywhere; word-break: break-all; }
.assist-object-title { font-size: var(--rs-font-size-body); font-weight: 600; word-break: normal; }
.assist-question { min-width: 0; color: var(--rs-text); overflow-wrap: anywhere; }
.assist-facts { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 3px 10px; margin: 0; }
.assist-facts > div { display: contents; }
.assist-facts dt { color: var(--rs-text-3); font-size: var(--rs-font-size-caption); line-height: 1.6; white-space: nowrap; }
.assist-facts dd { min-width: 0; margin: 0; color: var(--rs-text-2); font-size: var(--rs-font-size-secondary); line-height: 1.6; overflow-wrap: anywhere; }
.assist-facts dd .text-code { font-size: var(--rs-font-size-caption); }
.assist-facts dd.assist-facts-strong { color: var(--rs-text); font-weight: 600; }
.assist-note { margin: 0; }
.assist-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; min-height: 250px; margin-top: 12px; padding: 32px 24px; text-align: center; }
.assist-empty-icon { display: flex; align-items: center; justify-content: center; width: 52px; height: 52px; margin-bottom: 4px; border-radius: 14px; background: var(--rs-bg-selected); color: var(--rs-primary); }
.assist-empty-icon svg { width: 24px; height: 24px; }
.assist-empty strong { color: var(--rs-text); font-size: var(--rs-font-size-body); font-weight: 600; }
.assist-empty p { max-width: 420px; margin: 0; }
@keyframes assist-spin { to { transform: rotate(360deg); } }
@media (max-width: 600px) {
  .assist { padding: 14px 0 20px; }
  .assist-tabs :deep(.el-tabs__item) { padding: 0 10px !important; }
  .assist-tabs :deep(.el-tabs__item:first-child) { padding-left: 0 !important; }
  .assist-run { align-items: stretch; flex-direction: column; }
  .assist-run > .el-button { width: 100%; }
  .assist-empty { min-height: 200px; padding: 28px 16px; }
}
</style>

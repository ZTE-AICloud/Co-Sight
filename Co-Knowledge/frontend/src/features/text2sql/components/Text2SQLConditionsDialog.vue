<template>
  <StudioDialog v-model="open" :title="title" subtitle="先核对指标、城市和日期策略，再按当前数据配置查询。" :icon="Filter" hint="固定演示数据；不支持的条件组合不会生成结果" width="720px">
    <FormSection number="01" title="分析条件" :note="source.name">
      <el-form label-position="top" class="studio-form">
        <div class="studio-field-grid"><el-form-item label="业务指标"><el-select v-model="draft.metric" aria-label="分析指标"><el-option label="已支付订单金额（元）" value="amount"/><el-option label="付费用户数（去重，人）" value="users"/></el-select></el-form-item><el-form-item label="分析方式"><el-select v-model="draft.breakdown" aria-label="分析方式"><el-option label="汇总" value="total"/><template v-if="draft.metric === 'amount'"><el-option label="按城市分组" value="cities"/><el-option label="城市金额排行" value="top"/></template><el-option v-else label="按月统计" value="monthly"/></el-select></el-form-item></div>
        <div class="studio-field-grid"><el-form-item label="城市范围"><el-select v-model="draft.city" aria-label="分析城市" :disabled="draft.breakdown !== 'total' || draft.metric === 'users'"><el-option label="全部城市" value="all" :disabled="draft.breakdown === 'monthly'"/><el-option label="西安市" value="xian" :disabled="draft.metric === 'users' && draft.breakdown === 'total'"/></el-select></el-form-item><el-form-item label="时间范围"><el-select v-model="draft.period" aria-label="分析时间范围"><el-option label="最近30天" value="recent30"/><el-option label="全部演示月份" value="all" :disabled="draft.breakdown !== 'monthly'"/></el-select></el-form-item></div>
        <el-form-item label="日期策略"><el-select v-model="draft.datePolicy" aria-label="分析日期策略"><template v-if="draft.period !== 'all'"><el-option label="每次按数据基准取最近30天" value="relative"/><el-option label="固定本次日期范围" value="fixed"/></template><el-option v-else label="全部演示月份" value="all"/></el-select></el-form-item>
      </el-form>
    </FormSection>
    <FormSection number="02" title="确认本次查询"><template v-if="intent"><p class="text-body">{{ questionForIntent(intent) }}</p><dl class="workspace-properties text-secondary"><div><dt>指标与单位</dt><dd>{{ summary.metric }}</dd></div><div><dt>日期</dt><dd>{{ summary.dates }}</dd></div><div><dt>日期策略</dt><dd>{{ summary.policy }}</dd></div><div><dt>统计口径</dt><dd>已支付订单，不含退款；按订单创建时间、UTC 统计。</dd></div></dl></template><el-alert v-else title="该条件组合未提供演示，请调整选择。" type="warning" :closable="false"/><p class="studio-field-help text-caption">城市来自用户归属地区；月度用户按每月独立去重。演示日期基准固定为 {{ demoDate }}，日期策略不代表真实数据已经更新。</p></FormSection>
    <el-alert v-if="missingTables.length" :title="`本次分析还需要 ${missingTables.join('、')}，请先调整数据范围。`" type="warning" :closable="false"/>
    <template #actions><el-button @click="open = false">取消</el-button><el-button v-if="source.enabled === false || missingTables.length" @click="$emit('manage')">查看数据状态</el-button><el-button type="primary" :disabled="!intent || busy || source.enabled === false || !!missingTables.length" @click="$emit('apply', intent)">{{ source.status === 'indexed' ? '应用并查询' : '应用并准备数据' }}</el-button></template>
  </StudioDialog>
</template>
<script setup>
import { computed, reactive, watch } from 'vue'
import { Filter } from '@element-plus/icons-vue'
import StudioDialog from '@/shared/ui/StudioDialog.vue'
import FormSection from '@/shared/ui/FormSection.vue'
import { demoDate } from '@/features/text2sql/demo-data/text2sql'
import { requiredTables, enabledTables } from '@/features/text2sql/utils/text2sqlWorkspace'
import { parametersFromIntent, intentFromParameters, conditionSummary, questionForIntent, normalizeDatePolicy } from '@/features/text2sql/utils/text2sqlFlow'
const open = defineModel({ type: Boolean, default: false })
const props = defineProps({ source: { type: Object, required: true }, initialIntent: Object, busy: Boolean, title: { type: String, default: '调整查询条件' } })
defineEmits(['apply', 'manage'])
const draft = reactive(parametersFromIntent({ id: 'cities', period: 'recent30' }))
watch(open, value => {
  if (value) {
    Object.assign(draft, parametersFromIntent(props.initialIntent || { id: 'cities', period: 'recent30' }))
  }
})
watch(() => [draft.metric, draft.breakdown, draft.period], () => {
  if (draft.metric === 'amount' && !['total', 'cities', 'top'].includes(draft.breakdown)) {
    draft.breakdown = 'total'
  }
  if (draft.metric === 'users' && !['total', 'monthly'].includes(draft.breakdown)) {
    draft.breakdown = 'total'
  }
  if (draft.breakdown === 'monthly') {
    draft.city = 'xian'
  } else {
    if (draft.breakdown !== 'total' || draft.metric === 'users') {
      draft.city = 'all';
    } draft.period = 'recent30'
  }
  draft.datePolicy = normalizeDatePolicy(draft.period, draft.datePolicy)
})
const intent = computed(() => intentFromParameters(draft)); const summary = computed(() => conditionSummary(intent.value))
const missingTables = computed(() => (intent.value ? requiredTables(intent.value.id).filter(name => !enabledTables(props.source).includes(name)) : []))
</script>

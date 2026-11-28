<template>
  <StudioDrawer v-model="open" title="本次运行详情" size="min(760px, 100vw)" class="t2s-attempt-drawer">
    <StudioStatus :tone="item.error ? 'warning' : 'success'" :label="item.error?.message || '本次查询已完成'"/>
    <FormSection number="01" title="运行记录"><dl class="workspace-properties text-secondary"><div><dt>问题</dt><dd>{{ item.question }}</dd></div><div><dt>数据源</dt><dd>{{ item.datasource_name }}</dd></div><div><dt>请求编号</dt><dd class="text-code">{{ item.request_id }}</dd></div><div><dt>总耗时</dt><dd>{{ item.timing.total_ms }} ms · 模拟</dd></div></dl></FormSection>
    <FormSection number="02" title="执行阶段"><el-table :data="item.stages" border><el-table-column prop="name" label="阶段"/><el-table-column label="状态"><template #default="{ row }">{{ ({ success: '完成', error: '失败', skipped: '未执行' })[row.status] || row.status }}</template></el-table-column><el-table-column prop="ms" label="耗时（ms）"/></el-table></FormSection>
    <FormSection v-if="item.sql.final || item.sql.generated" number="03" title="SQL"><el-form class="studio-form" @submit.prevent><el-input :model-value="item.sql.final || item.sql.generated" class="text-code" type="textarea" :rows="8" readonly/></el-form></FormSection>
    <details class="studio-disclosure"><summary class="text-secondary">查看完整响应</summary><div class="studio-disclosure-body"><pre class="code text-caption">{{ JSON.stringify(item, null, 2) }}</pre></div></details>
    <template #footer><div class="studio-dialog-footer"><span class="studio-footer-hint text-caption">查看详情不会替换上一次成功答案</span><div class="studio-footer-actions"><el-button @click="exportDetails">导出本次详情</el-button><el-button type="primary" @click="open = false">返回答案</el-button></div></div></template>
  </StudioDrawer>
</template>
<script setup>
import FormSection from '@/shared/ui/FormSection.vue'
import StudioDrawer from '@/shared/ui/StudioDrawer.vue'
import StudioStatus from '@/shared/ui/StudioStatus.vue'
import { downloadText } from '@/features/text2sql/utils/demo'
const open = defineModel({ type: Boolean, default: false })
const props = defineProps({ item: { type: Object, required: true } })
function exportDetails () {
  downloadText(`text2sql-attempt-${props.item.request_id}.json`, JSON.stringify(props.item, null, 2), 'application/json')
}
</script>

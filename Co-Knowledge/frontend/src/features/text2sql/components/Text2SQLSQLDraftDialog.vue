<template>
  <StudioDialog v-model="open" title="SQL 草稿与演示校验" subtitle="核对或调整草稿，匹配支持的查询后再运行演示。" :icon="Edit" hint="仅识别内置模板，不是 SQL 解析器或服务端安全校验" width="960px">
    <FormSection number="01" title="SQL 草稿" :note="source.name"><el-input v-model="sql" aria-label="SQL 草稿" type="textarea" :rows="12" class="text-code"/><p class="text-caption muted">支持内置查询模板及其排版、注释变化。可通过“调整条件”生成其他支持的模板；任意 SQL 执行需要真实服务接入。</p><el-button @click="validate">校验草稿（演示）</el-button></FormSection>
    <el-alert v-if="validation" :title="validation.message" :type="validation.valid ? 'success' : 'warning'" :closable="false"/>
    <FormSection v-if="validation?.valid" number="02" title="即将运行的查询"><p class="text-body">{{ validation.question }}</p><p class="text-caption muted">演示仅返回匹配模板的内置数据，保存实际草稿文本作为本次 SQL 快照。</p></FormSection>
    <template #actions><el-button @click="open = false">取消</el-button><el-button type="primary" :disabled="!validation?.valid || busy" @click="$emit('apply', { sql, binding })">运行匹配的演示查询</el-button></template>
  </StudioDialog>
</template>
<script setup>
import { ref, watch } from 'vue'
import { Edit } from '@element-plus/icons-vue'
import StudioDialog from '@/shared/ui/StudioDialog.vue'
import FormSection from '@/shared/ui/FormSection.vue'
import { validateDemoSQL } from '@/features/text2sql/utils/text2sqlFlow'
const open = defineModel({ type: Boolean, default: false })
const props = defineProps({ source: { type: Object, required: true }, initialSql: String, binding: String, busy: Boolean })
defineEmits(['apply'])
const sql = ref(''); const validation = ref(null)
watch(open, value => {
  if (value) {
    sql.value = props.initialSql || ''; validation.value = null
  }
})
watch([sql, () => props.binding], () => {
  validation.value = null
}, { flush: 'sync' })
function validate () {
  validation.value = validateDemoSQL(sql.value, props.source)
}
</script>

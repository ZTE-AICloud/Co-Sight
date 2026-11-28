<script setup>
/**
 * 表关联维护：扫描只会带出数据库外键，人工补充的关联（MANUAL）和「已验证」
 * 标记一直只能靠 API —— 这个弹窗把后端已有能力接上。
 *
 * 数据由页面传入（tables / relations），这里只负责编辑与调用接口，
 * 保存后 emit refresh 让页面重新加载。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createRelation, deleteRelation, updateRelation, verifyRelation } from '@/features/text2sql/api/text2sql'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  datasourceId: { type: String, default: '' },
  tables: { type: Array, default: () => [] },
  relations: { type: Array, default: () => [] }
})
const emit = defineEmits(['update:modelValue', 'refresh'])

const CARDINALITIES = ['MANY_TO_ONE', 'ONE_TO_MANY', 'ONE_TO_ONE', 'MANY_TO_MANY']

const visible = computed({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value)
})

const draft = ref(emptyDraft())
const saving = ref(false)

function emptyDraft () {
  return { name: '', sourceTableId: '', targetTableId: '', cardinality: 'MANY_TO_ONE', description: '', columnPairs: [] }
}

function columnsOf (tableId) {
  return props.tables.find(table => table.id === tableId)?.columns || []
}

// 选中表变化时重置列对，避免留下不属于该表的列。
watch(() => draft.value.sourceTableId, () => { draft.value.columnPairs = [] })
watch(() => draft.value.targetTableId, () => { draft.value.columnPairs = [] })

function addPair () {
  draft.value.columnPairs.push({ sourceColumnId: '', targetColumnId: '' })
}

function removePair (index) {
  draft.value.columnPairs.splice(index, 1)
}

const canSubmit = computed(() => Boolean(
  props.datasourceId && draft.value.name.trim() &&
  draft.value.sourceTableId && draft.value.targetTableId &&
  draft.value.columnPairs.length &&
  draft.value.columnPairs.every(pair => pair.sourceColumnId && pair.targetColumnId)
))

async function submit () {
  if (!canSubmit.value || saving.value) {
    return
  }
  saving.value = true
  try {
    await createRelation(props.datasourceId, {
      name: draft.value.name.trim(),
      sourceTableId: draft.value.sourceTableId,
      targetTableId: draft.value.targetTableId,
      cardinality: draft.value.cardinality,
      description: draft.value.description,
      columnPairs: draft.value.columnPairs
    })
    ElMessage.success('关联已添加；重新构建并发布后才会进入查询上下文')
    draft.value = emptyDraft()
    emit('refresh')
  } finally {
    saving.value = false
  }
}

async function toggleVerified (relation) {
  await verifyRelation(props.datasourceId, relation.id, !relation.verified)
  emit('refresh')
}

async function remove (relation) {
  await ElMessageBox.confirm(`删除关联「${relation.name}」？`, '删除关联', { type: 'warning' })
  await deleteRelation(props.datasourceId, relation.id)
  ElMessage.success('关联已删除')
  emit('refresh')
}

async function updateCardinality (relation, cardinality) {
  await updateRelation(props.datasourceId, relation.id, { cardinality })
  emit('refresh')
}

function rowOf (scope) {
  return (scope && scope.row) || {}
}

function tableName (tableId) {
  return props.tables.find(table => table.id === tableId)?.fullName || tableId
}
</script>

<template>
  <el-dialog v-model="visible" title="维护表关联" width="720px" append-to-body>
    <p class="text-secondary relation-hint">
      扫描会带出数据库外键；同名但无外键的表需要在这里手工补充。标记「已验证」的关系在补全 JOIN 路径时优先使用。
    </p>

    <el-table :data="relations" size="small" empty-text="还没有关联" max-height="260">
      <el-table-column label="关联" min-width="200">
        <template #default="scope">
          <div class="text-code">{{ rowOf(scope).name }}</div>
          <div class="entity-sub text-caption">
            {{ tableName(rowOf(scope).sourceTableId) }} → {{ tableName(rowOf(scope).targetTableId) }}
          </div>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="110">
        <template #default="scope">
          <span class="entity-sub">{{ rowOf(scope).type === 'MANUAL' ? '手工' : '外键' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="基数" width="150">
        <template #default="scope">
          <el-select :model-value="rowOf(scope).cardinality" size="small"
                     @update:model-value="value => updateCardinality(rowOf(scope), value)">
            <el-option v-for="item in CARDINALITIES" :key="item" :label="item" :value="item" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="验证" width="90">
        <template #default="scope">
          <el-switch :model-value="rowOf(scope).verified" @update:model-value="toggleVerified(rowOf(scope))" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="80">
        <template #default="scope">
          <el-button link type="danger" @click="remove(rowOf(scope))">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-divider content-position="left">新增关联</el-divider>

    <el-form class="studio-form" label-position="top" size="small">
      <el-form-item label="名称">
        <el-input v-model="draft.name" maxlength="255" placeholder="例如 orders_user" />
      </el-form-item>
      <el-form-item label="源表 → 目标表">
        <div class="relation-tables">
          <el-select v-model="draft.sourceTableId" filterable placeholder="源表">
            <el-option v-for="table in tables" :key="table.id" :label="table.fullName" :value="table.id" />
          </el-select>
          <span class="entity-sub">→</span>
          <el-select v-model="draft.targetTableId" filterable placeholder="目标表">
            <el-option v-for="table in tables" :key="table.id" :label="table.fullName" :value="table.id" />
          </el-select>
        </div>
      </el-form-item>
      <el-form-item label="字段对">
        <div class="relation-pairs">
          <div v-for="(pair, index) in draft.columnPairs" :key="index" class="relation-pair">
            <el-select v-model="pair.sourceColumnId" filterable placeholder="源字段" size="small">
              <el-option v-for="column in columnsOf(draft.sourceTableId)" :key="column.id"
                         :label="column.name" :value="column.id" />
            </el-select>
            <span class="entity-sub">=</span>
            <el-select v-model="pair.targetColumnId" filterable placeholder="目标字段" size="small">
              <el-option v-for="column in columnsOf(draft.targetTableId)" :key="column.id"
                         :label="column.name" :value="column.id" />
            </el-select>
            <el-button link type="danger" @click="removePair(index)">移除</el-button>
          </div>
          <el-button link type="primary" @click="addPair">+ 添加字段对</el-button>
        </div>
      </el-form-item>
      <el-form-item label="基数">
        <el-select v-model="draft.cardinality">
          <el-option v-for="item in CARDINALITIES" :key="item" :label="item" :value="item" />
        </el-select>
      </el-form-item>
      <el-form-item label="说明">
        <el-input v-model="draft.description" type="textarea" :rows="2" maxlength="2000" />
      </el-form-item>
    </el-form>

    <template #footer>
      <div class="studio-footer-actions">
        <el-button @click="visible = false">关闭</el-button>
        <el-button type="primary" :disabled="!canSubmit" :loading="saving" @click="submit">添加关联</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.relation-hint { margin: 0 0 12px; }
.relation-tables { display: flex; align-items: center; gap: 8px; width: 100%; }
.relation-tables :deep(.el-form-item__label) { margin-bottom: 0; }
.relation-tables :deep(.el-select) { flex: 1; }
.relation-pairs { display: flex; flex-direction: column; gap: 8px; width: 100%; }
.relation-pair { display: flex; align-items: center; gap: 8px; }
.relation-pair :deep(.el-select) { flex: 1; }
</style>

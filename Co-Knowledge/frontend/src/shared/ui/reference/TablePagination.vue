<!--
  列表分页（共 N 条 + el-pagination + 每页条数 + 可选跳页）。
  真实的 page / size 仍由父级传入，组件通过 update:page / update:size / change
  事件回报，保持既有调用方（列表页全部用 :page / :size + @change）不变。
-->
<template>
  <div class="table-pagination">
      <span>{{ $t('public.pagination.total', { total }) }}</span>
      <el-pagination
        :current-page="page"
        :page-size="size"
        :total="total"
        :pager-count="5"
        layout="prev, pager, next"
        background
        @current-change="goPage"
      />
      <el-select
        :model-value="size"
        :aria-label="$t('public.pagination.pageSize')"
        style="width: 112px"
        @update:model-value="changeSize"
      >
        <el-option
          v-for="value in [10, 20, 50]"
          :key="value"
          :label="$t('public.pagination.perPage', { size: value })"
          :value="value"
        />
      </el-select>
      <template v-if="jumper">
        <span>{{ $t('public.pagination.jumpTo') }}</span>
        <el-input-number
          :model-value="page"
          :min="1"
          :max="pageCount"
          :controls="false"
          :precision="0"
          :aria-label="$t('public.pagination.pageNumber')"
          style="width: 60px"
          @change="jumpTo"
        />
        <span>{{ $t('public.pagination.page') }}</span>
      </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  total: { type: Number, default: 0 },
  page: { type: Number, default: 1 },
  size: { type: Number, default: 10 },
  jumper: { type: Boolean, default: false }
})

const emit = defineEmits(['update:page', 'update:size', 'change'])

const pageCount = computed(() => Math.max(1, Math.ceil((props.total || 0) / (props.size || 10))))

function goPage (next) {
  const value = Math.min(Math.max(1, Number(next) || 1), pageCount.value)
  if (value === props.page) {
    return
  }
  emit('update:page', value)
  emit('change', { page: value, size: props.size })
}

function changeSize (next) {
  emit('update:size', next)
  emit('update:page', 1)
  emit('change', { page: 1, size: next })
}

/** 跳页输入框：回车/失焦生效。 */
function jumpTo (value) {
  const next = Number.parseInt(String(value), 10)
  if (Number.isFinite(next)) {
    goPage(next)
  }
}
</script>

<style scoped>
.table-pagination { display:flex;align-items:center;justify-content:flex-end;flex-wrap:wrap;gap:8px;padding-top:14px;color:var(--rs-text-2);font-size:var(--rs-font-size-secondary); }
.table-pagination > span:first-child { margin-right:14px; }
.table-pagination :deep(.el-select__wrapper) { min-height:36px; }
.table-pagination :deep(.el-input__wrapper) { height:36px; }
.table-pagination :deep(.el-input__inner) { text-align:center; }
.table-pagination :deep(.el-pagination) { max-width:100%;overflow-x:auto; }
</style>

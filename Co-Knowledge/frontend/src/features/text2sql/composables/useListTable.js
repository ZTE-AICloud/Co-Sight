import { computed, ref, toValue, watch } from 'vue'

/**
 * 本地列表分页（数据源表格用）。
 *
 * `rows` / `filteredRows` 可以是 ref 或 getter；筛选条件变化时回到第一页并清空选择。
 */
export function useListTable (rows, filteredRows, filters = []) {
  const page = ref(1)
  const pageSize = ref(10)
  const pageRows = computed(() => toValue(filteredRows).slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
  const selectedRows = computed(() => toValue(rows).filter(row => row.selected))
  const clearSelection = () => toValue(rows).forEach(row => {
    row.selected = false
  })
  const clampPage = () => {
    const requested = Number.isFinite(page.value) ? Math.trunc(page.value) : 1
    page.value = Math.max(1, Math.min(requested, Math.ceil(toValue(filteredRows).length / pageSize.value) || 1))
  }
  function refreshList () {
    const current = toValue(rows)
    current.splice(0, current.length, ...current)
    clampPage()
  }
  watch(page, clampPage)
  watch(() => toValue(filteredRows).length, clampPage)
  watch(pageSize, () => {
    page.value = 1
  })
  if (filters.length) {
    watch(filters, () => {
      page.value = 1
      clearSelection()
    })
  }
  return { page, pageSize, pageRows, selectedRows, clearSelection, refreshList }
}

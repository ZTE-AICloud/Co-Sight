/**
 * 列表刷新按钮的状态机。
 *
 * `load` 成功时记录刷新完成时刻；失败时保留原内容并给出可重试的文案。
 * 组件只负责渲染，请求是否保留原列表由调用方的 `load` 决定。
 */
import { ref } from 'vue'

export function useTableRefresh (load) {
  const refreshing = ref(false)
  const refreshedAt = ref(null)
  const refreshError = ref(false)

  async function refresh () {
    if (refreshing.value) {
      return false
    }
    refreshing.value = true
    refreshError.value = false
    try {
      await load()
      refreshedAt.value = new Date()
      return true
    } catch {
      refreshError.value = true
      return false
    } finally {
      refreshing.value = false
    }
  }

  return { refreshing, refreshedAt, refreshError, refresh }
}

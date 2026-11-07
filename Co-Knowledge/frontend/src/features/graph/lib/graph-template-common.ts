/**
 * 图谱模板页的两个零依赖工具函数（时间戳格式化 / UUID）。
 *
 * ⚠️ 与 graphUtils.js 的同名导出行为不同，不要合并：
 *   - 那边多了 `isNaN(date.getTime())` 守卫，非法输入返回 '--'；
 *   - 这里没有守卫，非法输入输出 'NaN-NaN-NaN NaN:NaN:NaN'。
 *   两边差异由 tests/unit/graphTemplate.common.spec.js「与 graphUtils 的差异」组钉住，
 *   合并任一边都会让那组红。
 *   `generateUUID` 在 GraphTemplateDesigner.vue 中有另一份本地实现；`useCrypto.js` 走 uuid 库。
 */

// 时间戳转换函数
// ⚠️ 不加 isNaN 守卫：非法输入出 'NaN-NaN-NaN NaN:NaN:NaN' 是既定行为，用例已钉住；
//    不要按 graphUtils.js 那份"补上守卫"。
export function formatTimestamp (timestamp: number): string {
  if (!timestamp) {
    return '--'
  }
  const date = new Date(timestamp)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')
  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`
}

/**
 * Generate UUID v4
 */
export function generateUUID(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = Math.random() * 16 | 0
    const v = c === 'x' ? r : (r & 0x3 | 0x8)
    return v.toString(16)
  })
}

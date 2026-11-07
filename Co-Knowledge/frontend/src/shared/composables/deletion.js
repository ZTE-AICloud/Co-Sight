/**
 * 全局删除确认。
 *
 * 「删除确认」是一个应用级弹窗：任何页面调用 `requestDeletion(options)`
 * 都会打开同一个 `DeleteConfirmDialog`，并拿到一个在用户确认/取消后 resolve 的
 * Promise。这样删除的视觉、验证码、批量清单和取消语义只有一份实现。
 *
 * 注意：
 * - `options.items` 为空时直接 resolve(false)，连弹窗都不开；
 * - 同一个时刻只允许一个待确认删除，新的请求会先把旧的 settle(false)；
 * - 路由切换 / 弹窗被关闭时由 `App.vue` 调 `settleDeletion(false)`，
 *   避免页面已经离开、Promise 永远悬挂。
 */
import { shallowReactive } from 'vue'

export const deletion = shallowReactive({ open: false, options: {} })
let pending

export function requestDeletion (options) {
  if (!options?.items?.length) {
    return Promise.resolve(false)
  }
  settleDeletion(false)
  deletion.options = { ...options, items: options.items.map(item => ({ ...item })) }
  deletion.open = true
  return new Promise(resolve => {
    pending = resolve
  })
}

export function settleDeletion (confirmed) {
  const resolve = pending
  pending = undefined
  deletion.open = false
  resolve?.(confirmed)
}

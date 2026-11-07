/**
 * 「同一时刻只允许一个确认框」的小工具。
 *
 * 为什么需要：`$confirm` 每调一次就新建一个 `ElMessageBox`，**没有互斥**。
 * 用户快速连点菜单项（或双击）时，同一个确认框会叠成 2~3 层，关的时候得一层层点。
 * 收到一个公用件里，别再各写各的。
 *
 * 用法（保持调用点原有的 `$confirm` 语义：确认返回 true、取消返回 false，**不抛错**）：
 *
 *     import { onceConfirm } from '@/shared/lib/confirm-once'
 *     if (!await onceConfirm(() => proxy.$confirm(msg, title, opts))) return
 *     doSomething()
 *
 * 注意：这是**进程级**闸门（模块级变量），不是组件级 —— 界面上本来就只该有一个
 * 模态确认框，跨组件互斥正是想要的效果。
 */

let pending = false

/**
 * @param {() => Promise<unknown>} open 真正打开确认框的函数（通常是 `() => $confirm(...)`）
 * @returns {Promise<boolean>} 确认 true / 取消或已有确认框在开 false
 */
export function onceConfirm (open) {
  if (pending) {
    return Promise.resolve(false)
  }
  pending = true
  return Promise.resolve()
    .then(open)
    .then(() => true)
    .catch(() => false)
    .finally(() => {
      pending = false
    })
}

/** 仅测试用：把闸门复位。 */
export function __resetConfirmOnce () {
  pending = false
}

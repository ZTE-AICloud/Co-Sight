/**
 * 复制文本并给出统一反馈（成功 / 失败都弹 toast）。
 *
 * 为什么要有这一层：`copyText` 只返回布尔值，页面大多写成了
 * `@click="copyText(value)"`，**成功时什么也不显示** —— 用户点完复制不知道
 * 到底复制没有。这里把「复制 + 反馈」收成一处，任何复制按钮都不要再直接调用 `copyText`。
 *
 * 文案走 `public.copySuccess` / `public.copyFailed`，中英文各一份。
 */
import { ElMessage } from 'element-plus'
import { $t } from '@/app/i18n/i18n.js'
import { copyText } from './clipboard'

/**
 * @param {unknown} text 要复制的值（统一转成字符串）
 * @returns {Promise<boolean>} 是否复制成功
 */
export async function copyTextWithToast (text) {
  const ok = await copyText(String(text ?? ''))
  if (ok) {
    ElMessage.success($t('public.copySuccess'))
  } else {
    ElMessage.error($t('public.copyFailed'))
  }
  return ok
}

export default copyTextWithToast

import { ElMessage } from 'element-plus'
import { copyText as copyToClipboard } from '@/shared/lib/clipboard'

/**
 * 复制文本并提示结果。
 *
 * 底层走 `@/shared/lib/clipboard`：`navigator.clipboard` 只在安全上下文
 * （HTTPS / localhost）可用，纯 HTTP 部署时会回落到 `execCommand`。
 */
export async function copyText (text) {
  if (await copyToClipboard(text)) {
    ElMessage.success('已复制到剪贴板')
    return
  }
  ElMessage.error('复制失败，请手动复制')
}

/** 把文本内容作为文件下载。 */
export function downloadText (name, content, type = 'text/plain') {
  const url = URL.createObjectURL(new Blob([content], { type }))
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

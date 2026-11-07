/**
 * 复制文本到剪贴板。
 *
 * 为什么需要回落：`navigator.clipboard` **只在安全上下文**（HTTPS / localhost）
 * 可用，而本产品经常以纯 HTTP 部署（同一类问题也打崩过 `crypto.subtle` 的上传链）。
 * 此时直接 `navigator.clipboard.writeText` 会抛 `TypeError` / 返回 undefined，
 * 用户看到的是「点了复制没反应」。`document.execCommand('copy')` 虽然已标记
 * deprecated，但在这些浏览器里仍是唯一可用路径。
 *
 * @param {string} text
 * @returns {Promise<boolean>} 是否成功
 */
export async function copyText (text) {
  const value = String(text ?? '')

  if (typeof navigator !== 'undefined' && navigator.clipboard &&
      (typeof window === 'undefined' || window.isSecureContext)) {
    try {
      await navigator.clipboard.writeText(value)
      return true
    } catch {
      // 权限被拒 / 非安全上下文 / 浏览器实现差异：继续走 execCommand。
    }
  }

  if (typeof document === 'undefined') {
    return false
  }

  let textarea = null
  try {
    textarea = document.createElement('textarea')
    textarea.value = value
    textarea.setAttribute('readonly', '')
    textarea.style.position = 'fixed'
    textarea.style.top = '0'
    textarea.style.left = '0'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    textarea.setSelectionRange(0, value.length)
    return document.execCommand('copy') !== false
  } catch {
    return false
  } finally {
    if (textarea && textarea.parentNode) {
      textarea.parentNode.removeChild(textarea)
    }
  }
}

export default copyText


import { $t } from '@/app/i18n/i18n.js'

/** 文档数带单位；英文单复数分开，避免出现 “1 documents”。 */
export function docCountLabel (count: number | string): string {
  const value = Number(count) || 0
  return $t(value === 1 ? 'modules.kb.docCountOne' : 'modules.kb.docCount', { count: value })
}

export function highlightText (text: string, searchText: string) {
  if (!searchText) {
    return
  }

  const escapedText = searchText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  const regex = new RegExp(escapedText, 'gi');

  let match;
  let matches = [];
  let lastIndex = 0;

  while ((match = regex.exec(text)) !== null) {
    const index = match.index;
    const content = match[0];

    // 添加非匹配部分
    if (index > lastIndex) {
      const nonMatchedText = text.substring(lastIndex, index);
      matches.push({
        text: nonMatchedText,
        matched: false
      });
    }

    // 添加匹配部分
    matches.push({
      text: content,
      matched: true
    });

    lastIndex = index + content.length;
  }

  // 添加剩余的非匹配部分
  if (lastIndex < text.length) {
    const nonMatchedText = text.substring(lastIndex);
    matches.push({
      text: nonMatchedText,
      matched: false
    });
  }

  return matches;
}

/**
 * 表格排序方向 → 后端 `orderList[].ascending` 的取值。
 *
 * 多个列表页依赖它；点表头排序会调用，缺了会直接抛 TypeError
 * （异常被 catch 吞掉后表现为「按钮没反应」）。
 * 默认 `asc` / `desc`，允许调用方覆盖。
 */
export function formatterSortOrder (
  order: 'ascending' | 'descending',
  ascending: unknown = 'asc',
  descending: unknown = 'desc'
): unknown {
  const orderMap = { ascending, descending }
  return Object.prototype.hasOwnProperty.call(orderMap, order)
    ? orderMap[order]
    : ascending
}

/**
 * 浏览器端「把二进制响应存成文件」。
 *
 * 多个页面依赖它；缺了点击下载会直接抛 TypeError
 * （异常被 catch 吞掉后表现为「按钮没反应」）。
 * 语义：Blob → object URL → 触发 <a download>。
 *
 * @param data 响应体（axios `responseType: 'blob'` 返回的 Blob）
 * @param filename 下载文件名；为空时浏览器按 object URL 推断
 * @param mime 可选 MIME，传入时会用该类型重新包一层 Blob
 */
export function download (data: Blob | ArrayBuffer | string, filename = '', mime = ''): void {
  const blob = data instanceof Blob ? data : new Blob([data], mime ? { type: mime } : undefined)
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  if (filename) {
    anchor.download = filename
  }
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

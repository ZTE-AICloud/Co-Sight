/**
 * 0.1.4 知识库详情页的切片展示纯函数。
 *
 * 真实 `/chunk` 响应只有正文（没有 `title` 字段）：
 * - 正文首行是 Markdown 标题时，标题取它、正文去掉这一行（避免同一句显示两遍）；
 * - 否则标题取首行前 60 字，正文保留全文（卡片 = 摘要 + 正文）。
 *
 * 零 Vue / i18n 依赖，可在 Node 里直接单测。
 */

export interface ChunkParts {
  /** 卡片标题（≤ 60 字） */
  title: string
  /** 卡片正文（去掉 Markdown 标题行后的正文） */
  body: string
}

const MAX_TITLE_LENGTH = 60
const MARKDOWN_HEADING = /^#{1,6}\s+/

export function chunkParts (content: unknown): ChunkParts {
  const text = String(content ?? '')
  const lines = text.split('\n')
  const firstIndex = lines.findIndex(line => line.trim())
  const firstLine = firstIndex === -1 ? '' : lines[firstIndex].trim()
  const isHeading = MARKDOWN_HEADING.test(firstLine)
  const rawTitle = isHeading ? firstLine.replace(/^#+\s*/, '') : firstLine
  return {
    title: rawTitle.slice(0, MAX_TITLE_LENGTH) || '--',
    body: isHeading ? lines.slice(firstIndex + 1).join('\n').trim() : text
  }
}

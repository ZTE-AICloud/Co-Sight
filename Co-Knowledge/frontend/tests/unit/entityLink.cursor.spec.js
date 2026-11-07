// 列表里的知识库/图谱/编排/模版名称是行内跳转入口，悬停必须是手型（与 5173 原型一致）。
//
// 原型用 RouterLink 渲染成带 href 的 <a>，浏览器默认给 pointer；真实页面的名称是
// `<a class="entity-title entity-link" @click="...">`（没有 href，路由靠点击处理），
// 浏览器算出来的是 `cursor: auto` —— 手感与原型不一致。这里钉住共享样式层的兜底，
// 避免有人「清理」掉这条看起来多余的声明。
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const tablesCss = fs.readFileSync(path.join(ROOT, 'src/styles/tables.css'), 'utf8')

/** 取出 `.list-table .entity-link` 的基础规则体（不含 :hover） */
function entityLinkRuleBody () {
  const match = tablesCss.match(/(?:^|\n)\.list-table \.entity-link\s*\{([^}]*)\}/)
  return match ? match[1] : ''
}

describe('列表名称链接的鼠标形态对齐 5173 原型', () => {
  it('.list-table .entity-link 显式声明 cursor: pointer', () => {
    expect(entityLinkRuleBody()).toMatch(/cursor:\s*pointer/)
  })
})

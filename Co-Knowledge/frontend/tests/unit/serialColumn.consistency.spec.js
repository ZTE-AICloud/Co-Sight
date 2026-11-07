// 设计系统：全仓不渲染「序号」列（没有业务意义）。
//
// 规则：
//   - 一级页面与子页面都不再渲染序号列；
//   - 宽度单一来源库已移除，防止旧口径被重新引入。
//
// 只读源码、不挂组件：这些文件里有好几个要登录态/接口才渲染得出来，源码形状是
// 唯一能在单测里 100% 覆盖全仓的判据（本仓惯例，见 i18n.colonToast.spec.js）。
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

/** 递归收集 src 下的 .vue / .ts */
function sourceFiles (dir = path.join(ROOT, 'src'), out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      sourceFiles(full, out)
    } else if (/\.(vue|ts)$/.test(entry.name)) {
      out.push(full)
    }
  }
  return out
}

const files = sourceFiles()
const rel = f => path.relative(ROOT, f)

// 例外：模型管理页（ModelTable.vue）按设计保留「序号」列；
// 其余页面仍不主动声明序号列。
const SERIAL_COLUMN_ALLOWLIST = ['src/features/model/ModelTable.vue']

describe('设计系统：序号列已全仓删除（模型管理页除外）', () => {
  it('页面 / 组件不再声明 type="index" 的序号列', () => {
    const offenders = files
      .filter(file => !SERIAL_COLUMN_ALLOWLIST.includes(rel(file)))
      .filter(file => fs.readFileSync(file, 'utf8').includes('type="index"'))
      .map(rel)
    expect(offenders).toEqual([])
  })

  it('columns 配置里不再出现 prop: index（模型管理页除外）', () => {
    const offenders = files
      .filter(file => !SERIAL_COLUMN_ALLOWLIST.includes(rel(file)))
      .filter(file => /prop:\s*'index'/.test(fs.readFileSync(file, 'utf8')))
      .map(rel)
    expect(offenders).toEqual([])
  })

  it('旧的序号列宽度单一来源库已删除（防止口径复活）', () => {
    expect(fs.existsSync(path.join(ROOT, 'src/shared/lib/table-serial-column.ts'))).toBe(false)
  })
})

import { readFileSync, readdirSync } from 'fs'
import { join } from 'path'
import zhI18n from '@/app/i18n/zh.js'
import enI18n from '@/app/i18n/en.js'

/**
 * i18n 键完整性守卫。
 *
 * 为什么需要它：有两类 i18n 问题单测抓不到 ——
 *   ① `modules.kb.updateTimeLabel` 只在 zh 侧存在，而 KnowledgeGraphDetail.vue 在用它，
 *      于是**英文界面会把裸键名 `modules.kb.updateTimeLabel` 当标签渲染出来**；
 *   ② `zh/kb.js` 里同一对象内 21 组重复键（JS 后者胜 → 先写的翻译永远不会生效，
 *      而且改它也没有任何效果）。
 * 两件都"渲染不报错、测试全绿"，只能靠把**引用与定义交叉核对**来发现。这就是本文件。
 *
 * 做法：扫描 `src/` 下所有 `.vue/.js/.ts` 里**字面量**形式的 `$t('…')` / `t('…')`，
 * 逐个在 zh 与 en 两棵消息树里解析，断言全部命中。
 * 动态拼出来的键（模板字符串）无法静态判定，跳过不误报。
 */

const SRC = join(__dirname, '../../src')
const SKIP_DIR = 'i18n' // 定义处自身不参与"被引用"的统计

function walk(dir, acc = []) {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, e.name)
    if (e.isDirectory()) {
      if (e.name === 'node_modules' || e.name === SKIP_DIR) continue
      walk(p, acc)
    } else if (/\.(vue|js|ts)$/.test(e.name)) {
      acc.push(p)
    }
  }
  return acc
}

/** 收集源码里字面量引用的 i18n 键 → 引用它的文件（相对 src 的路径）。 */
function collectReferencedKeys() {
  // 只认字面量：$t('a.b') / t('a.b') / translate('a.b')；模板串与变量一律不匹配。
  const re = /(?:\$t|translate|(?<![\w$])t)\(\s*'([A-Za-z][\w]*(?:\.[\w]+)+)'/g
  const found = new Map()
  for (const file of walk(SRC)) {
    const txt = readFileSync(file, 'utf8')
    let m
    while ((m = re.exec(txt))) {
      const key = m[1]
      if (!found.has(key)) found.set(key, new Set())
      found.get(key).add(file.slice(SRC.length + 1))
    }
  }
  return found
}

/** 按点号路径在消息树里取值；取不到返回 undefined。 */
function resolve(tree, path) {
  let node = tree
  for (const seg of path.split('.')) {
    if (node === null || typeof node !== 'object' || !(seg in node)) return undefined
    node = node[seg]
  }
  return node
}

describe('i18n 键完整性', () => {
  const referenced = collectReferencedKeys()

  it('扫到的被引用键数量是合理的（防止正则失效导致空转假绿）', () => {
    // 这条是**阳性对照**：正则哪天被改坏、一个键都扫不到，下面的断言会全过。
    // 钉一个下限，让"扫不到东西"本身变成失败。
    expect(referenced.size).toBeGreaterThan(500)
  })

  it('所有被引用的键都能在 zh 消息树里解析到', () => {
    const missing = []
    for (const [key, files] of referenced) {
      if (resolve(zhI18n, key) === undefined) {
        missing.push(`${key}  ← ${[...files].join(', ')}`)
      }
    }
    expect(missing, `zh 缺失 ${missing.length} 个被引用的键：\n${missing.join('\n')}`).toEqual([])
  })

  it('所有被引用的键都能在 en 消息树里解析到（英文界面不会渲染裸键名）', () => {
    const missing = []
    for (const [key, files] of referenced) {
      if (resolve(enI18n, key) === undefined) {
        missing.push(`${key}  ← ${[...files].join(', ')}`)
      }
    }
    expect(missing, `en 缺失 ${missing.length} 个被引用的键：\n${missing.join('\n')}`).toEqual([])
  })

  /**
   * 允许为空串的键（**显式登记，不是"跳过"**）。
   * 空译文通常是漏译（界面上什么都不显示），但有一类是真的设计如此：
   * 语言相关的分隔符 —— 中文不需要词间空格，英文需要。
   */
  const ALLOW_EMPTY = new Set([
    // CustomSplitRuleItem.vue 用它拼接「扩展名 + 空格 + 文件」：
    // 中文 `''` → "md文件"，英文 `' '` → "md file"。两侧都是对的。
    'public.space',
  ])

  it('解析到的值都是非空字符串（空串只允许已登记的例外）', () => {
    const empties = []
    for (const [key] of referenced) {
      if (ALLOW_EMPTY.has(key)) continue
      const v = resolve(zhI18n, key)
      if (v !== undefined && (typeof v !== 'string' || v.trim() === '')) {
        empties.push(key)
      }
    }
    expect(empties, `zh 侧这些键的值为空（若属有意为之，请登记进 ALLOW_EMPTY）：\n${empties.join('\n')}`).toEqual([])
  })
})

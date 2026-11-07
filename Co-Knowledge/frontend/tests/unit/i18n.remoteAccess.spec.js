import zhI18n from '@/app/i18n/zh.js'
import enI18n from '@/app/i18n/en.js'
import { SCOPE_LABEL_KEYS } from '@/features/agent/lib/helpers'

/**
 * 远程接入页的 i18n 守卫。
 *
 * 为什么单开一条：`i18n.consistency.spec.js` 只比对模块名与一份固定关键键，
 * **不做整棵树的递归比对**；而 scope 标签是 `SCOPE_LABEL_KEYS` 里的动态键，
 * `i18n.keyIntegrity.spec.js` 的静态扫描看不到。缺一边时界面会直接渲染裸键名。
 */

function collectKeys (tree, prefix = '') {
  const keys = []
  for (const key of Object.keys(tree || {})) {
    const full = prefix ? `${prefix}.${key}` : key
    const value = tree[key]
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      keys.push(...collectKeys(value, full))
    } else {
      keys.push(full)
    }
  }
  return keys
}

function resolve (tree, path) {
  let node = tree
  for (const segment of path.split('.')) {
    if (!node || typeof node !== 'object' || !(segment in node)) return undefined
    node = node[segment]
  }
  return node
}

describe('remoteAccess i18n', () => {
  it('zh / en 的 modules.remoteAccess 键集完全一致', () => {
    const zh = collectKeys(zhI18n.modules.remoteAccess).sort()
    const en = collectKeys(enI18n.modules.remoteAccess).sort()
    expect(en).toEqual(zh)
  })

  it('左栏分组与两个子菜单文案在两侧都存在', () => {
    for (const key of ['remoteAccess', 'remoteAccessGuide', 'remoteAccessKeys']) {
      expect(zhI18n.nav[key]).toBeTruthy()
      expect(enI18n.nav[key]).toBeTruthy()
    }
  })

  it('所有动态 scope 标签在中英文两侧都能解析且非空', () => {
    const missing = []
    for (const key of Object.values(SCOPE_LABEL_KEYS)) {
      for (const [locale, tree] of [['zh', zhI18n], ['en', enI18n]]) {
        const value = resolve(tree, key)
        if (typeof value !== 'string' || !value) missing.push(`${locale}:${key}`)
      }
    }
    expect(missing).toEqual([])
  })
})

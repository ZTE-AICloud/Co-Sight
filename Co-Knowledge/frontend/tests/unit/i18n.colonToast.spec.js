// 英文侧一致性：5 处「键外全角冒号」toast 的冒号一并搬进 i18n 词条值
// （en 下会渲染成 "Delete failed：…"）。
//
// zh 渲染不能变（zh 值里本来就是全角「：」，只是从模板字符串挪进词条）；
// en 用半角「: 」（对齐 base.js 里 `Prefix: msg` 的惯例）。
//
// 两层钉子（行为测试测不出这类漂移 —— 要挂 5 个组件、还要驱动失败分支才能看 toast，
// 而渲染结果又只是拼接，所以照仓内惯例「行为 + 源码形状」双重钉）：
//   1) 词条值：zh 以「：」结尾；en 以半角 ': ' 结尾且**不含全角冒号**；
//   2) 源码形状：调用方不得再在代码里拼「：」（防止有人加回去 → zh 双冒号 / en 全角）。
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import zh from '@/app/i18n/zh.js'
import en from '@/app/i18n/en.js'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

/** [i18n 键路径, 期望 zh 值, 期望 en 值, [调用方相对路径, ...]] */
const CASES = [
  [
    'public.deletefail',
    '删除失败：',
    'Delete failed: ',
    [
      'src/pages/knowledge-base/KnowledgeBaseListPage.vue'
    ]
  ],
  [
    'public.createFail',
    '创建失败：',
    'Create Failed: ',
    ['src/features/graph/CreateKnowledgeGraphTemplateDialog.vue']
  ],
  [
    'modules.kb.overwriteImportFailed',
    '全量覆盖导入失败：',
    'Full overwrite import failed: ',
    ['src/features/graph/GraphList.vue']
  ]
]

function valueAt (tree, keyPath) {
  return keyPath.split('.').reduce((acc, k) => acc?.[k], tree)
}

describe('toast 冒号并进 i18n 词条值', () => {
  it.each(CASES.map(c => [c[0], c[1], c[2]]))(
    'given_%s_when_取值_then_zh 全角冒号结尾 / en 半角冒号结尾',
    (keyPath, zhValue, enValue) => {
      // Assert：zh 文案不变；en 有半角冒号、没有全角冒号
      expect(valueAt(zh, keyPath)).toBe(zhValue)
      expect(valueAt(en, keyPath)).toBe(enValue)
      expect(enValue).toContain(':')
      expect(enValue).not.toContain('：')
    }
  )

  it.each(
    CASES.flatMap(([keyPath, , , files]) => files.map(f => [keyPath, f]))
  )('given_%s_when_扫 %s_then_代码里不再拼全角冒号', (keyPath, file) => {
    // Arrange
    const source = fs.readFileSync(path.join(ROOT, file), 'utf8')

    // Assert：`$t('<key>')}：` 这个拼接形状已被移除（注释里的历史行不算 —— 用
    // 「该行不是注释」粗判：真实拼接行不含 `// 冒号在」这类说明，所以只查代码形状）
    const live = source
      .split('\n')
      .filter(l => !l.trim().startsWith('//') && !l.trim().startsWith('*'))
      .join('\n')
    expect(live).not.toContain(`$t('${keyPath}')}：`)
  })

})

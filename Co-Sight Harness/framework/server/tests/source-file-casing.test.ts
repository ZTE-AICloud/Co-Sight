/**
 * 源码文件名大小写守卫测试。
 *
 * **为什么需要它**：Windows 的 NTFS 与 macOS 的 APFS 默认大小写不敏感，
 * `AgentProxyForm.tsx` 与 `agentProxyForm.ts` 这样的两个文件能并存；而解析
 * `import ... from './AgentProxyForm'` 时，TS 按扩展名探测顺序（`.ts` → `.tsx` →
 * `.d.ts`）先试 `AgentProxyForm.ts`——在大小写不敏感的盘上，这一步退化成
 * **大小写不敏感匹配**，于是命中的是纯逻辑模块 `agentProxyForm.ts`，
 * 报 TS2305「模块没有导出成员 AgentProxyForm」。Vite 的 dev/build 用同一套
 * 探测顺序，所以运行时也会解析到错误的那一个。
 *
 * **Linux 上编译通过**，所以这类问题只会在同事的 Windows/macOS 机器上炸，
 * 而且报错指向的是「文件名看起来对得上」的那一行，很难反查到是两个文件抢名字。
 * 看不到的问题只能靠断言守住：**同一目录下不许出现主干只差大小写的 TS/JS 文件**。
 *
 * 只判「主干不同、小写相同」这一种。主干完全相同、仅扩展名不同（如 `Foo.ts`
 * 与 `Foo.tsx`）不在范围内：那两者在两种文件系统上都稳定地由 `.ts` 胜出，
 * 不存在跨平台差异。
 */

import fs from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

/** tests/ → server/ → framework/ = 仓库的 framework 根。 */
const FRAMEWORK_ROOT = path.resolve(import.meta.dirname, '../..');

/** 会被 TypeScript / Vite 的模块解析当候选的目录。 */
const SCANNED_DIRS = ['shared', 'server', 'web'].flatMap((pkg) =>
  ['src', 'tests', 'e2e'].map((sub) => path.join(FRAMEWORK_ROOT, pkg, sub)),
);

/** 构建产物与依赖目录不参与；`.` 开头的目录（`.run`、`.vite` 等）一并跳过。 */
const SKIPPED_DIRS = new Set(['node_modules', 'dist', 'build', 'coverage']);

/**
 * 会被扩展名探测的文件类型。`PROBED_EXTENSIONS` 的顺序**无关紧要**——
 * 这里只用集合成员关系，探测顺序由 TypeScript 决定。
 */
const PROBED_EXTENSIONS = ['.ts', '.tsx', '.mts', '.cts', '.js', '.jsx', '.mjs', '.cjs'];

/**
 * 拆出主干与扩展名；不是 TS/JS 家族返回 `null`。
 * `.d.ts` 整段算扩展名（`Foo.d.ts` 的主干是 `Foo`），因为 TS 把它当作独立候选。
 */
function splitName(name: string): { stem: string; extension: string } | null {
  const candidates = name.endsWith('.d.ts') ? ['.d.ts'] : PROBED_EXTENSIONS;
  for (const extension of candidates) {
    if (name.length > extension.length && name.endsWith(extension)) {
      return { stem: name.slice(0, -extension.length), extension };
    }
  }
  return null;
}

/** 递归收集一个目录下「主干只差大小写」的文件对，写进 `offenders`。 */
function collectCollisions(dir: string, offenders: string[]): void {
  let entries: fs.Dirent[];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    // 目录不存在（如某些包没有 e2e/）：没有可扫的，不是错误。
    return;
  }

  const byStem = new Map<string, string[]>();
  for (const entry of entries) {
    if (entry.isDirectory()) {
      if (!SKIPPED_DIRS.has(entry.name) && !entry.name.startsWith('.')) {
        collectCollisions(path.join(dir, entry.name), offenders);
      }
      continue;
    }
    const parts = splitName(entry.name);
    if (parts === null) {
      continue;
    }
    const key = parts.stem.toLowerCase();
    byStem.set(key, [...(byStem.get(key) ?? []), entry.name]);
  }

  for (const names of byStem.values()) {
    // 同名文件不可能并存，所以这里只要有两个成员，主干就必定只差大小写。
    if (names.length > 1) {
      offenders.push(`${path.relative(FRAMEWORK_ROOT, dir)}: ${names.toSorted().join('  ⇄  ')}`);
    }
  }
}

describe('源码文件名的大小写', () => {
  it('同一目录下没有主干只差大小写的 TS/JS 文件', () => {
    const offenders: string[] = [];
    for (const dir of SCANNED_DIRS) {
      collectCollisions(dir, offenders);
    }
    expect(
      offenders,
      '这两类文件在大小写不敏感的文件系统（Windows/macOS）上会互相遮蔽：import "./X" 会先命中另一个。' +
        '改掉其中一个的名字（组件的名字可以在前面加限定词，如 ModelConfigForm 之于 modelForm）。',
    ).toEqual([]);
  });
});

/**
 * 契约隔离守卫测试。
 *
 * `shared/src/contracts/module-model.ts` 里定义的类型**带明文 `apiKey` 字段**。
 * 它不该出现在任何前端代码里——不是为了"少一个类型"，而是因为一旦它进了前端，
 * 就一定会有人写出"用这个类型接一个返回密钥的接口"的代码，那正是浏览器面那条
 * 硬契约要防的事。
 *
 * 隔离目前靠三件事成立：文件不写进 `contracts/index.ts`（那是个 `export *` barrel）、
 * 用 subpath 导出、前端只从 `harness-shared` 根入口 import。**三件都是"约定"，
 * 都能被一次顺手改动打破，而打破时不会有任何编译错误**——因为模块面那张脸本来
 * 就是合法的、能被正常 import 的。所以这里用测试把它变成 CI 能拦住的错误。
 *
 * 这类测试的价值全在"后来人不知道它为什么存在"时。所以断言失败信息里写清楚原委。
 */

import fs from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

/** tests/ → server/ → framework/ = 仓库的 framework 根。 */
const FRAMEWORK_ROOT = path.resolve(import.meta.dirname, '../..');

const WEB_SRC = path.join(FRAMEWORK_ROOT, 'web/src');
const CONTRACTS_BARREL = path.join(FRAMEWORK_ROOT, 'shared/src/contracts/index.ts');
const SHARED_INDEX = path.join(FRAMEWORK_ROOT, 'shared/src/index.ts');

/** 模块面契约的标识串：出现在前端的 import 里即视为越界。 */
const FORBIDDEN_SPECIFIERS = [
  'module-models',
  'contracts/module-model',
  'module-rag-knowledge',
  'contracts/module-rag-knowledge',
];

function listFiles(dir: string): string[] {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  return entries.flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      return listFiles(full);
    }
    return /\.(ts|tsx)$/.test(entry.name) ? [full] : [];
  });
}

describe('模块面契约的隔离', () => {
  it('前端源码里没有任何一处 import 模块面契约', () => {
    const offenders: string[] = [];
    for (const file of listFiles(WEB_SRC)) {
      const source = fs.readFileSync(file, 'utf8');
      for (const specifier of FORBIDDEN_SPECIFIERS) {
        if (source.includes(specifier)) {
          offenders.push(`${path.relative(FRAMEWORK_ROOT, file)} → ${specifier}`);
        }
      }
    }
    expect(
      offenders,
      '模块面契约带明文 apiKey，不得进入前端。前端要展示模型请用 harness-shared 的 ModelConfig。',
    ).toEqual([]);
  });

  it('contracts/index.ts 这个 export * barrel 里没有模块面契约', () => {
    const barrel = fs.readFileSync(CONTRACTS_BARREL, 'utf8');
    for (const specifier of ['module-model', 'module-rag-knowledge']) {
      expect(
        barrel.includes(specifier),
        'contracts/index.ts 是 export * barrel，把模块面契约写进去会让它自动流向前端。要导出请走 package.json 的 subpath。',
      ).toBe(false);
    }
  });

  it('shared/src/index.ts 的 barrel 里没有模块面契约', () => {
    const index = fs.readFileSync(SHARED_INDEX, 'utf8');
    for (const specifier of ['module-model', 'module-rag-knowledge']) {
      expect(
        index.includes(specifier),
        'shared/src/index.ts 是前端唯一的类型入口，不得转出模块面契约。',
      ).toBe(false);
    }
  });

  it('subpath 导出确实配好了（否则上面三条会因为"根本用不了"而失去意义）', () => {
    const packageJson = JSON.parse(
      fs.readFileSync(path.join(FRAMEWORK_ROOT, 'shared/package.json'), 'utf8'),
    ) as { exports: Record<string, string> };
    expect(packageJson.exports['./module-models']).toBe('./src/contracts/module-model.ts');
    expect(packageJson.exports['./module-rag-knowledge']).toBe(
      './src/contracts/module-rag-knowledge.ts',
    );
  });
});

/**
 * 服务端清单里的 Node 版本要求。
 *
 * 为什么这个字段必须声明在**服务端** package.json、而且值得一条测试守住：
 * 产物（tar.gz / zip）里只有 `start.mjs + server/ + web/`，**仓库根的 package.json 不进产物**。
 * 而"这台机器上的 Node 够不够"是安装与启动两侧都要回答的问题——
 * `start.mjs` 每次启动都读 `appDir/package.json` 的 `engines.node` 来判，
 * 读不到就只剩一句"跳过版本校验"。字段放在根 package.json 里等于没放。
 *
 * 钉住两件事：
 *   1. server 的 `engines.node` 与仓库根**逐字相同**——两处各写一份必然漂，
 *      漂了以后症状是"开发机能跑、用户装完起不来"，排查成本远高于这条断言；
 *   2. 写法是 node-version.mjs 那个小解析器认得的形状（比较符 + 数字版本，可用 `||` 并列）。
 *      它**不认识的写法会抛错**（fail-closed），所以 "latest" / ">=22" 这类会让用户
 *      在启动时收到一条"这是打包侧的 bug"——那种错该在 CI 就被拦下。
 *
 * 不 import `scripts/lib/node-version.mjs`：server 的 `tsconfig.rootDir` 是 `.`，
 * 从 `tests/` 反引仓库另一侧的 `.mjs` 会让 tsc 报 TS6059。
 * 所以这里只做形状断言，真正的比较逻辑由 `scripts/tests/node-version.test.mjs` 覆盖。
 */

import fs from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

interface PackageManifest {
  engines?: { node?: unknown };
}

/** 用 `import.meta.dirname` 而不是 `process.cwd()`：与测试运行时的目录无关。 */
const serverManifestPath = path.resolve(import.meta.dirname, '..', 'package.json');
const rootManifestPath = path.resolve(import.meta.dirname, '..', '..', '..', 'package.json');

function readManifest(filePath: string): PackageManifest {
  return JSON.parse(fs.readFileSync(filePath, 'utf8')) as PackageManifest;
}

/** 与 `lib/node-version.mjs` 的 `parseComparator` 同一形状：可选比较符 + 至少主版本号。 */
const SEGMENT_PATTERN = /^(>=|<=|>|<|\^|~|=)?\d+(\.\d+)?(\.\d+)?$/;

describe('服务端 Node 版本要求', () => {
  it('声明了 engines.node，且与仓库根逐字一致', () => {
    // 根清单不存在 = 不在仓库布局里跑，这条测试的前提没了，如实失败而不是静默跳过。
    if (!fs.existsSync(rootManifestPath)) {
      throw new Error(`这条测试要求仓库布局，但找不到 ${rootManifestPath}`);
    }

    const serverRange = readManifest(serverManifestPath).engines?.node;
    const rootRange = readManifest(rootManifestPath).engines?.node;

    expect(typeof rootRange).toBe('string');
    expect(typeof serverRange).toBe('string');
    expect(serverRange).toBe(rootRange);
  });

  it('写法被启动期的版本校验器认识', () => {
    const range = readManifest(serverManifestPath).engines?.node;

    expect(typeof range).toBe('string');
    const segments = String(range)
      .split('||')
      .map((segment) => segment.trim())
      .filter((segment) => segment !== '');

    expect(segments.length).toBeGreaterThan(0);
    for (const segment of segments) {
      expect(segment).toMatch(SEGMENT_PATTERN);
    }
  });
});

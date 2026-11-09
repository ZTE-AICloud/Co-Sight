/**
 * 产物里必须带齐 `start.mjs` 真正 import 的每一个内部模块。
 *
 * 这是打包里**唯一一类"本机完全看不出来"的错**：漏搬一个 `lib/*.mjs` 时，
 * 仓库里 `node start.mjs` 一切正常，打包也正常，只有用户解压后才会看到
 * `ERR_MODULE_NOT_FOUND`——而且是在一个他没写过的文件上。
 *
 * 所以这里不检查"清单里有没有那一行"（那只是同义反复），而是**从 start.mjs 出发
 * 顺着相对 import 走一遍**，把闭包与 `ENTRY_SCRIPT_SOURCES` 对起来。
 * 新增一个 `lib/*.mjs` 而忘了登记时，这个测试会红，而不是用户的那台机器。
 */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { describe, it } from 'node:test';

import { ARTIFACT_LAYOUT, ENTRY_SCRIPT_SOURCES, MODULE_ROOT } from '../lib/project.mjs';

const scriptsDir = path.join(MODULE_ROOT, 'scripts');

/** 抓 `import ... from './x.mjs'` 与 `export ... from './x.mjs'` 里的相对路径。 */
function relativeImports(text) {
  return [...text.matchAll(/\bfrom\s+'(\.[^']+)'/g)].map((match) => match[1]);
}

/**
 * 从入口出发，按相对 import 递归收集它依赖的**本地文件**（仓库相对 `scripts/` 的路径）。
 * `node:` 前缀与裸包名（如 `harness-shared`）不是本地文件，直接跳过。
 */
function localImportClosure(entry) {
  const seen = new Set();
  const queue = [entry];

  while (queue.length > 0) {
    const relative = queue.shift();
    if (seen.has(relative)) {
      continue;
    }
    seen.add(relative);

    const text = fs.readFileSync(path.join(scriptsDir, relative), 'utf8');
    for (const specifier of relativeImports(text)) {
      // 统一成 `/` 分隔再入集合：Windows 上 `path.normalize` 会给出 `lib\x.mjs`，
      // 而 `ENTRY_SCRIPT_SOURCES` 与归档里的路径一律是 `lib/x.mjs`。不归一会让
      // 下面两条断言在 Windows 打包机上恒红——恰好是这道防线最该生效的机器。
      const target = path.normalize(path.join(path.dirname(relative), specifier)).split(path.sep).join('/');
      if (!fs.existsSync(path.join(scriptsDir, target))) {
        assert.fail(`${relative} import 的 './${specifier}' 不存在——产物里也不会存在`);
      }
      queue.push(target);
    }
  }

  return seen;
}

describe('start.mjs 的 import 闭包与搬运清单', () => {
  const closure = localImportClosure(ARTIFACT_LAYOUT.entryFile);
  const declared = new Set(ENTRY_SCRIPT_SOURCES.map((entry) => entry.relative));

  it('闭包里的每一个文件都在搬运清单里', () => {
    const missing = [...closure].filter((relative) => !declared.has(relative)).toSorted();
    assert.deepEqual(missing, [], `这些文件会被 import，但不会被打进产物：${missing.join(', ')}`);
  });

  it('清单里也没有多余的（清单写错了名字同样是漏搬）', () => {
    const extra = [...declared].filter((relative) => !closure.has(relative)).toSorted();
    assert.deepEqual(extra, [], `清单里有 start.mjs 其实不会加载的文件：${extra.join(', ')}`);
  });

  it('清单里声明的源码文件都真的存在，且只有入口是可执行的', () => {
    for (const entry of ENTRY_SCRIPT_SOURCES) {
      assert.ok(fs.existsSync(path.join(scriptsDir, entry.source)), `缺少 ${entry.source}`);
      assert.equal(
        entry.executable === true,
        entry.relative === ARTIFACT_LAYOUT.entryFile,
        `${entry.relative} 的 executable 只该在入口上是 true`,
      );
    }
  });
});

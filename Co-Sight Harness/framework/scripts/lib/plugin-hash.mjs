/**
 * 插件载荷的内容哈希与文件集合。
 *
 * 为什么需要哈希：Claude Code 的两个实测行为让"版本号相同"不足以判断是否要重装——
 *   - `plugin install` 对已安装插件是 no-op，不会更新内容；
 *   - `plugin update` 只在版本号变化时才复制内容。
 * 所以运行期要拿"cache 里那份内容"与"产物里这份内容"比一次。
 *
 * 算法（打包期与运行期必须完全一致，否则每次启动都会重装）：
 *   相对路径排序 → 对每个文件写入 `posix/相对路径\0` + 文件字节
 *   → SHA-256 → 取前 16 位十六进制。
 *
 * 文件集合就是**复制进产物的那套**：排除规则在这里定义一次，打包复制与哈希
 * 都引用它（`isExcludedPluginPath`）。两边各写一遍是这类"看起来没变、其实变了"
 * 的最常见来源。
 */

import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

/**
 * 不进入产物的路径（相对插件根目录，统一用 `/` 分隔）。
 *
 * 这些是开发/测试产物与**本机配置**：测试与缓存与运行无关；`.env` 可能含密钥，
 * 绝不能随包发出去（安全要求：不得把机密带进交付物）。
 *
 * 除 `.claude` 外都按"任意层级"匹配：插件里的 skill 常带自己的 `tests/`，
 * 留在包里只会增大体积。`.claude` 只排除插件根目录那一层——嵌套的
 * `.claude` 是 golden 样例的一部分（如 agent-genesis 的 output-snapshot）。
 */
const EXCLUDED_PATTERNS = [
  /(^|\/)tests(\/|$)/,
  /(^|\/)__pycache__(\/|$)/,
  /(^|\/)\.pytest_cache(\/|$)/,
  /(^|\/)\.ruff_cache(\/|$)/,
  /\.pyc$/,
  /(^|\/)\.git(\/|$)/,
  /(^|\/)node_modules(\/|$)/,
  /^\.claude(\/|$)/,
  /(^|\/)\.env$/,
  /(^|\/)work(\/|$)/,
  /(^|\/)output(\/|$)/,
  /(^|\/)\.agent-genesis(\/|$)/,
];

/**
 * @param {string} relative 相对插件根目录的路径（`/` 分隔）
 */
export function isExcludedPluginPath(relative) {
  const normalized = relative.split(path.sep).join('/');
  return EXCLUDED_PATTERNS.some((pattern) => pattern.test(normalized));
}

/**
 * 列出会进入产物的文件（相对路径，`/` 分隔，已排序）。
 *
 * 遇到符号链接直接抛错：五个插件目录实测都是干净的源码树，出现链接说明
 * checkout 被换过。让它在这里失败，比在 Windows 用户那里变成 0 字节文件好。
 *
 * @param {string} rootDir
 * @returns {string[]}
 */
export function collectPluginFiles(rootDir) {
  const files = [];
  const pending = [''];

  while (pending.length > 0) {
    const relativeDir = pending.pop();
    const absoluteDir = path.join(rootDir, relativeDir);
    const dirents = fs.readdirSync(absoluteDir, { withFileTypes: true });

    for (const dirent of dirents) {
      const relative = relativeDir === '' ? dirent.name : `${relativeDir}/${dirent.name}`;
      if (isExcludedPluginPath(relative)) {
        continue;
      }
      if (dirent.isSymbolicLink()) {
        throw new Error(`插件目录里不应有符号链接：${relative}（${rootDir}）`);
      }
      if (dirent.isDirectory()) {
        pending.push(relative);
        continue;
      }
      if (dirent.isFile()) {
        files.push(relative);
        continue;
      }
      throw new Error(`插件目录里有无法打包的文件类型：${relative}（${rootDir}）`);
    }
  }

  return files.toSorted();
}

/**
 * 对一批相对路径算哈希。
 *
 * @param {string} rootDir
 * @param {string[]} files
 * @returns {{sha256: string, files: number}}
 */
export function hashPluginFiles(rootDir, files) {
  const hash = createHash('sha256');
  for (const relative of files) {
    hash.update(`${relative}\0`);
    hash.update(fs.readFileSync(path.join(rootDir, relative)));
  }
  return { sha256: hash.digest('hex').slice(0, 16), files: files.length };
}

/**
 * 直接对一个插件目录算哈希。
 *
 * @param {string} rootDir
 * @returns {{sha256: string, files: number}}
 */
export function hashPluginDirectory(rootDir) {
  return hashPluginFiles(rootDir, collectPluginFiles(rootDir));
}

/**
 * 对"已经展开成归档条目"的那套文件算哈希。
 *
 * 打包期用它做交叉校验：目录哈希与归档条目哈希必须相等。两者不等说明
 * 复制规则与哈希规则分叉了——那会让运行期永远判定"内容变了"、每次启动都重装。
 *
 * @param {Array<{path: string, kind: string, read?: () => Buffer}>} entries
 * @param {string} prefix 归档里的插件根（如 `base/plugins/drive`）
 * @returns {{sha256: string, files: number}}
 */
export function hashPluginEntries(entries, prefix) {
  const expected = prefix.endsWith('/') ? prefix : `${prefix}/`;
  const files = entries
    .filter((entry) => entry.kind === 'file' && entry.path.startsWith(expected))
    .map((entry) => ({
      relative: entry.path.slice(expected.length),
      read: entry.read,
    }))
    .toSorted((left, right) => (left.relative < right.relative ? -1 : left.relative > right.relative ? 1 : 0));

  const hash = createHash('sha256');
  for (const file of files) {
    hash.update(`${file.relative}\0`);
    hash.update(file.read());
  }
  return { sha256: hash.digest('hex').slice(0, 16), files: files.length };
}

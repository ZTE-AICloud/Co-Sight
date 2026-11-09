/**
 * 目录遍历 → 归档条目。
 *
 * 两条不显眼但关键的性质：
 *
 * 1. **只 lstat，不跟随符号链接。** pnpm 的 node_modules 里绝大多数的"包"
 *    是指向 `.pnpm/...` 的符号链接。若跟随展开，同一份代码会被复制多份（体积翻倍），
 *    而且归档里不再有链接语义。归档格式本身支持符号链接，让格式去表达它。
 * 2. **顺序确定。** 排序后产出，配合归档里固定的 mtime，同一份输入得到同一串字节。
 *    这样"产物变了"就一定是内容变了，不会因为目录读取顺序抖动而误报。
 */

import fs from 'node:fs';
import path from 'node:path';

/**
 * @param {string} rootDir 要打包的目录
 * @param {{prefix?: string, prune?: (relativePath: string) => boolean}} [options]
 *   prefix：归档里给这些条目加的前缀（通常是产物根目录名）。
 *   prune：对每个条目（含文件）判断是否排除；命中目录时整棵子树跳过。
 * @returns {Array<{path: string, absPath: string, kind: 'file'|'dir'|'symlink', mode: number, size: number, linkTarget?: string, read?: () => Buffer}>}
 */
export function collectEntries(rootDir, options = {}) {
  const prefix = options.prefix ?? '';
  const prune = options.prune ?? (() => false);
  const entries = [];

  // 显式栈而非递归：遍历顺序完全由自己控制，且不受目录深度影响。
  const stack = [{ absolute: rootDir, relative: '' }];

  while (stack.length > 0) {
    const current = stack.pop();
    const dirents = fs.readdirSync(current.absolute, { withFileTypes: true });

    for (const dirent of dirents) {
      const relative = current.relative === '' ? dirent.name : `${current.relative}/${dirent.name}`;
      const absolute = path.join(current.absolute, dirent.name);
      // 排除规则对文件与目录都生效：产物里既要去掉测试目录，也要去掉单个配置文件。
      // 符号链接也要过规则——一个指向被排除目录的链接进了产物就是断链。
      if (prune(relative)) {
        continue;
      }
      // lstat：dirent 的类型来自 readdir，对符号链接不会误判成它指向的东西。
      const stat = fs.lstatSync(absolute);

      if (stat.isSymbolicLink()) {
        entries.push({
          path: withPrefix(prefix, relative),
          absPath: absolute,
          kind: 'symlink',
          mode: 0o777,
          linkTarget: fs.readlinkSync(absolute),
          size: 0,
        });
        continue;
      }

      if (stat.isDirectory()) {
        entries.push({
          path: withPrefix(prefix, relative),
          absPath: absolute,
          kind: 'dir',
          mode: stat.mode & 0o7777,
          size: 0,
        });
        stack.push({ absolute, relative });
        continue;
      }

      if (stat.isFile()) {
        entries.push({
          path: withPrefix(prefix, relative),
          absPath: absolute,
          kind: 'file',
          mode: stat.mode & 0o7777,
          // 大小在遍历时就记下来：汇总体积时不必再 stat 一遍，更不必读文件内容。
          size: stat.size,
          read: () => fs.readFileSync(absolute),
        });
      }
      // 设备、FIFO、socket 之类不进产物：框架运行不需要，且归档表示各异。
    }
  }

  // 字典序排序。父目录（`a`）必然排在子项（`a/b`）之前，解压器无需自行补建中间目录。
  entries.sort((left, right) => (left.path < right.path ? -1 : left.path > right.path ? 1 : 0));
  return entries;
}

function withPrefix(prefix, relative) {
  return prefix === '' ? relative : `${prefix}/${relative}`;
}

/**
 * 检查树内所有符号链接的目标是否都落在树内。
 *
 * 产物是要搬到别的机器上解压的：一个指向 `/home/someone/...` 的链接在那边
 * 就是断的，而它在打包机器上一切正常。所以宁可在这里报错。
 *
 * @returns {string[]} 越界链接的清单（为空表示通过）
 */
export function findEscapingSymlinks(entries) {
  const paths = new Set(entries.map((entry) => entry.path));
  const escapes = [];

  for (const entry of entries) {
    if (entry.kind !== 'symlink') {
      continue;
    }
    const target = entry.linkTarget ?? '';
    if (path.isAbsolute(target)) {
      escapes.push(`${entry.path} -> ${target}（绝对路径）`);
      continue;
    }
    // 归档里的路径一律用 '/'，因此这里手工做归并，不借用平台相关的 path.resolve。
    const base = entry.path.split('/').slice(0, -1);
    const segments = [...base];
    for (const segment of target.split('/')) {
      if (segment === '' || segment === '.') {
        continue;
      }
      if (segment === '..') {
        if (segments.length === 0) {
          escapes.push(`${entry.path} -> ${target}（跳出产物根目录）`);
          break;
        }
        segments.pop();
        continue;
      }
      segments.push(segment);
    }
    const resolved = segments.join('/');
    if (!paths.has(resolved)) {
      escapes.push(`${entry.path} -> ${target}（目标 ${resolved} 不在产物内）`);
    }
  }

  return escapes;
}

/** 递归删除；不存在时静默返回，便于"清理后重建"的写法。 */
export function removeIfExists(target) {
  fs.rmSync(target, { recursive: true, force: true });
}

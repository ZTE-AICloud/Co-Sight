/**
 * 原子写文件（D26 的落盘纪律）。
 *
 * 这段逻辑原本长在 `credentials/store.ts` 的 `#write()` 里。抽出来是因为现在有
 * 第二个文件要用它（`credentials/module-token.ts` 的模块面令牌）。**抽出来不是
 * 为了省几行代码，而是为了让"写入前就以 0600 创建临时文件"这条纪律只有一个实现**——
 * 这是这类文件唯一容易写错、且写错了不会立刻被发现的地方。
 *
 * 三条性质，缺一不可：
 * 1. 临时文件以 `wx` + mode **在写入之前**创建。先创建再 chmod 会留下一个短暂的
 *    世界可读窗口——恰好是密钥/令牌最危险的那一小段。
 * 2. 写完 `fsync` 再 `rename`。缺了 fsync，断电可能得到一个"已改名但内容还在页缓存"
 *    的空文件；rename 在同一文件系统内是原子的，进程中途被杀不会留下半截内容。
 * 3. rename 之后**再 chmod 一次**兜底：rename 保留的是临时文件的 mode，但目标路径
 *    可能本来就存在且带着更宽的权限位。这一步走 `chmodBestEffort`：在没有 chmod
 *    这个概念的文件系统上它是空操作，**不该因此让写令牌直接失败**（见 lib/file-mode.ts）。
 *
 * 不负责跨进程互斥——v1 单实例，这条缺口与 `.credentials.yaml` 是同一个，见
 * `credentials/store.ts` 文件头第 3 条。
 */

import fs from 'node:fs';
import path from 'node:path';

import { ensureDirectory } from '../config/paths';
import { chmodBestEffort } from './file-mode';

export function writeFileAtomicSync(filePath: string, contents: string, mode: number): void {
  ensureDirectory(path.dirname(filePath));

  const tmpPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  const handle = fs.openSync(tmpPath, 'wx', mode);
  try {
    fs.writeFileSync(handle, contents, 'utf8');
    fs.fsyncSync(handle);
  } finally {
    fs.closeSync(handle);
  }

  try {
    fs.renameSync(tmpPath, filePath);
  } catch (error) {
    // rename 失败会留下临时文件；不清掉的话会在数据目录里越积越多，
    // 而且那些临时文件是 0600 的"半成品"，比垃圾更烦人。
    fs.rmSync(tmpPath, { force: true });
    throw error;
  }

  chmodBestEffort(filePath, mode);
}

/**
 * 读文件；不存在返回 null，其余错误照抛。
 *
 * 把 ENOENT 与"读不了"分开是刻意的：前者是正常状态（还没写过），后者是真实故障
 * （权限、IO），静默当成 null 会把故障伪装成"没配"。
 */
export function readFileIfExists(filePath: string): string | null {
  try {
    return fs.readFileSync(filePath, 'utf8');
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      return null;
    }
    throw error;
  }
}

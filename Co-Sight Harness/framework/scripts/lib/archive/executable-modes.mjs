/**
 * 给"必须可执行"的条目补上可执行位。
 *
 * POSIX 上文件自带 X 位，这里不会改动它；**Windows 没有可执行位**（`stat` 一律给
 * 0666），于是 `assertExecutableEntries` 在 Windows 打包机上永远不可能通过——
 * 而产物是拿到 Linux 上跑的，X 位必须真的写进归档。
 *
 * 只补缺、不覆盖：已经带 X 位的条目原样保留（可能比 0755 更严格）。
 *
 * 这个函数放在 `lib/` 而不是留在 `package.mjs` 里，是为了能脱离打包流水线直接测：
 * 它是 Windows 打包机上唯一能决定"产物在 Linux 上能不能执行"的纯函数，而
 * 解压后的可执行位断言在 Windows 上被跳过，等于没有第二道本地防线。
 *
 * @param {Array<{path: string, kind: string, mode: number}>} entries 归档条目
 * @param {Iterable<string>} targets 必须可执行的条目路径（归档内路径，含顶层目录）
 * @returns 新数组；未命中的条目原样返回（不改入参）
 */
export function withExecutableModes(entries, targets) {
  const required = new Set(targets);
  return entries.map((entry) =>
    entry.kind === 'file' && required.has(entry.path) && (entry.mode & 0o111) === 0
      ? { ...entry, mode: entry.mode | 0o755 }
      : entry,
  );
}

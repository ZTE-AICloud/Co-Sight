/**
 * 判定 Info-ZIP 的 stderr 是不是"只关乎元数据"的告警。
 *
 * Info-ZIP 的退出码语义：0 = 干净，1 = **成功但有告警**，≥2 才是真失败。
 * 冒烟要把其中一类告警跟着退出码 1 一起放行：解压后给某些目录设权限/时间戳时
 * 报 `No such file or directory`（Windows 文件系统语义 + 同时有杀毒软件在扫
 * 刚解出来的 350 MB 树时偶发）。文件内容本身是完整的，同一个归档重跑一次就是 0 告警。
 *
 * 放行的口径是**"每一行都必须落在这两类里"**，而不是按关键词白名单放行：
 * 白名单漏掉的未知告警会被当成失败，这正是我们要的方向。
 *
 * 但续行不能无条件放行。Info-ZIP 会把真正的失败也缩进打印
 * （`  skipping: … need PK compat`），只看"以空白开头"就会把它一起吞掉。
 * 所以续行额外过一道失败词黑名单：宁可把一次偶发告警判成失败（人一看就知道），
 * 也不要让一条真失败混进"通过"里。
 */

/** 元数据告警的首行，三种措辞都见过。 */
const METADATA_HEADER =
  /^warning:\s+(cannot set permissions for|cannot set modif\.\/access times for|set times\/attribs failed for)\s/;

/** 缩进的续行：标准形态是 `          No such file or directory`。 */
const INDENTED = /^\s+\S/;

/** 续行里出现这些词就不是纯元数据告警，一律按失败处理。 */
const FAILURE_WORDS = /\b(?:error|failed|failing|skipping|unsupported|truncated|corrupt|invalid|cannot create|could not)\b/i;

/**
 * @param {string} stderr unzip 的 stderr
 * @returns {number} 纯元数据告警的条数；出现任何一条别的输出时返回 0（= 不接受）
 */
export function countMetadataOnlyUnzipWarnings(stderr) {
  const lines = stderr.split(/\r?\n/).filter((line) => line.trim() !== '');
  if (lines.length === 0) {
    return 0;
  }

  let headers = 0;
  for (const line of lines) {
    if (METADATA_HEADER.test(line)) {
      headers += 1;
      continue;
    }
    if (INDENTED.test(line) && !FAILURE_WORDS.test(line)) {
      continue;
    }
    return 0;
  }

  return headers;
}

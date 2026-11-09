/**
 * 给人看的数值格式化。
 *
 * 单独成文件的原因：这些函数既要被**打包脚本**用（产物体积），也要被
 * **产物里的 start.mjs** 用（磁盘空间提醒）。`lib/project.mjs` 只服务于打包、
 * 不进产物，而启动链路不能 import 它——把纯格式化放在这里，两边都能用，
 * 又不必把整个 project.mjs 拖进产物。
 */

/**
 * 字节数 → `1.5 MB` 这样的短串。
 *
 * @param {number} bytes
 * @returns {string}
 */
export function humanSize(bytes) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(1)} ${units[unitIndex]}`;
}

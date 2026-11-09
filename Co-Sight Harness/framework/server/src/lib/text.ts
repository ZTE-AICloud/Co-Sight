/**
 * 读文本时的杂项处理。
 *
 * 与服务端同源的另一份实现在 `scripts/lib/text.mjs`（启动脚本也读同一批
 * 手写清单）。两边不能互相 import——那边是 node 直接跑的 .mjs，这边是 TS，
 * 所以**改动时两处一起**。
 */

/**
 * 去掉开头的 UTF-8 BOM（U+FEFF）。
 *
 * 为什么必须有这一行：Windows 记事本"UTF-8"那个选项写出来的文件**带 BOM**，
 * 而 `JSON.parse` 碰到 BOM 会直接抛 `Unexpected token`。用户看到的现象是
 * "module.json 我明明写对了，这个模块却没被注册"——错在一个看不见的字节上。
 *
 * 只剥开头那一个，不做 `trim()`：BOM 是编码产物，空白是内容，
 * 顺手 trim 会把"文件开头有个空行"这种真实现象一起抹掉。
 */
export function stripBom(text: string): string {
  return text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
}

/**
 * `cosight.env` 的解析：纯 `KEY=VALUE` 文本，两个平台共用同一份。
 *
 * ── 为什么不让 sh / cmd 各自 source 一下 ────────────────────────────────
 *
 * 那样就得准备两份语法不同的模板（`export K=V` 与 `set K=V`），同一份配置在两个
 * 平台会带出两种行为——比如 Windows 的 `set` 会把值里的引号一起塞进去，而 sh 的
 * `source` 会吃掉它们。这类分歧不是"可能发生"，是"一定发生"，而且只在另一个平台
 * 上发生。所以解析只做一次，在 Node 里做。
 *
 * ── 规则（刻意少而明确）────────────────────────────────────────────────
 *
 *  - 一行一条 `KEY=VALUE`；空行与 `#` 开头的行忽略；
 *  - 键必须是 `[A-Za-z_][A-Za-z0-9_]*`，不合法**报错并带上行号**，不静默跳过
 *    （静默跳过的表现是"我明明配了却没用上"，最难查）；
 *  - 值两侧空白去掉；整体被单引号或双引号包住时剥掉引号，支持 `KEY="a b"` 这种带空格的写法；
 *  - 允许写 `export KEY=VALUE`（写惯了 sh 的人会这么写），`export` 被忽略；
 *  - **不覆盖已存在的环境变量**：真实环境 > 配置文件。这样临时 `COSIGHT_PORT=8080 ./start.sh`
 *    能压过文件里的值，不用先改文件。
 */

import { stripBom } from './text.mjs';

/**
 * 解析成 `{ key, value, line }` 列表。语法错误抛 `Error`（消息里带行号）。
 *
 * `label` 只用于报错文案：调用方通常传实际文件路径，用户看到的就不是
 * "cosight.env 第 3 行…" 这种既没路径也没上下文的说法。
 */
export function parseEnvFile(text, label = 'cosight.env') {
  const entries = [];
  // 这份文件是**用户唯一会手改的东西**，而 Windows 记事本存"UTF-8"时带 BOM。
  // 不剥的话，第一行的键会变成 "\uFEFFCOSIGHT_PORT" 而被判非法——报错还指着一个
  // 看着完全正确的名字。BOM 是编码产物，不是内容。
  const lines = stripBom(text).split(/\r?\n/);

  lines.forEach((rawLine, index) => {
    const lineNumber = index + 1;
    const line = rawLine.trim();
    if (line === '' || line.startsWith('#')) {
      return;
    }

    const withoutExport = line.startsWith('export ') ? line.slice('export '.length).trim() : line;
    const equalsAt = withoutExport.indexOf('=');
    if (equalsAt <= 0) {
      throw new Error(`${label} 第 ${lineNumber} 行不是 KEY=VALUE：${line}`);
    }

    const key = withoutExport.slice(0, equalsAt).trim();
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) {
      throw new Error(`${label} 第 ${lineNumber} 行的变量名不合法：${key}`);
    }

    entries.push({ key, value: stripQuotes(withoutExport.slice(equalsAt + 1).trim()), line: lineNumber });
  });

  return entries;
}

function stripQuotes(value) {
  const pairs = [
    ['"', '"'],
    ["'", "'"],
  ];
  for (const [open, close] of pairs) {
    if (value.length >= 2 && value.startsWith(open) && value.endsWith(close)) {
      return value.slice(1, -1);
    }
  }
  return value;
}

/**
 * 把解析结果写进一份环境变量对象（默认 `process.env`）。
 * 已存在的一律不动，返回实际写入的键，便于启动日志如实说明"哪些来自配置文件"。
 */
export function applyEnvFile(entries, env = process.env) {
  const applied = [];
  for (const { key, value } of entries) {
    if (env[key] !== undefined) {
      continue;
    }
    env[key] = value;
    applied.push(key);
  }
  return applied;
}

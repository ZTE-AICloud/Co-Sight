/**
 * 安装/启动前的前置检查骨架：登记、聚合、渲染。
 *
 * ── 为什么要有这一层 ────────────────────────────────────────────────────
 *
 * "启动前要先检查哪些东西"会随着产品变多（Claude Code、插件载荷、marketplace
 * 冲突、端口……）。如果把每一条都写成 start.mjs 里的一段 if，最后会得到一段
 * 既不能单独测试、也说不清"哪些问题会拦住启动"的代码。
 *
 * 所以这里只做三件事：
 *   1. **登记**：每个检查项是一个 `{ id, label, level, run() }` 对象；
 *   2. **聚合**：统一执行，任何一项抛错都收敛成一条失败（而不是让整轮检查断掉）；
 *   3. **渲染**：固定格式的报告 + 一个退出码。
 *
 * 新增检查只加一个文件、在 start.mjs 的清单里加一行，流程本身不改。
 *
 * ── 只读约定 ────────────────────────────────────────────────────────────
 *
 * 这一层跑在**任何写操作之前**，`--self-check` 也跑它。因此每个 `run()` 都必须
 * 只读：不建目录、不写文件、不调用会改状态的命令。需要写的东西属于后面的
 * init / plugins 阶段。
 *
 * ── 状态标记为什么用 ASCII ──────────────────────────────────────────────
 *
 * `[OK] / [WARN] / [FAIL]` 而不是 `✓ ✗`：Windows 控制台在 GBK 代码页下会把
 * 后者打成乱码，而这段输出恰恰是给"看不懂日志的人"看的第一屏。
 */

/**
 * 产物覆盖的平台。
 *
 * 打包侧（`lib/project.mjs` 的 `ARTIFACT_TARGETS`）直接引用这份清单——
 * 只写一处，才不会出现"打包带了 win32 原生件、启动却把 Windows 判成不支持"。
 */
export const SUPPORTED_PLATFORMS = ['linux-x64', 'win32-x64'];

/** 前置检查失败时的退出码（见 docs/install-preflight-and-plugins.md §6.1）。 */
export const EXIT_PREFLIGHT = 10;

const LEVELS = new Set(['block', 'warn']);

/**
 * 校验一个检查项的形状。写错字段名时希望**立刻**报错，而不是在报告里
 * 得到一行 `undefined`。
 *
 * @param {{id: string, label: string, level?: 'block'|'warn', run: () => object|Promise<object>}} check
 */
export function defineCheck(check) {
  for (const field of ['id', 'label', 'run']) {
    if (check[field] === undefined) {
      throw new Error(`检查项缺少 ${field}：${JSON.stringify(check)}`);
    }
  }
  const level = check.level ?? 'block';
  if (!LEVELS.has(level)) {
    throw new Error(`检查项 ${check.id} 的 level 只能是 block / warn，收到 ${String(level)}`);
  }
  return { level, ...check };
}

/**
 * 依次执行检查项。**顺序执行**是有意的：它们大多是毫秒级的文件系统探测，
 * 只有 Claude CLI 那条要起子进程；并发跑会让报告顺序不稳定，也会让
 * "先看平台、再看 Node"这种阅读顺序失去意义。
 *
 * 某一项自己抛错时不终止整轮：把它收敛成一条失败，其余检查照常给出结论——
 * 只报"检查器崩了"会把真正缺的东西藏起来。
 *
 * 单项可以返回 `level: 'warn'` 来降低自己的严重级别。这是给"检查没能完成、
 * 但已经确认关键能力还在"这种情形留的口子（例如 Claude Code 的版本行解析
 * 失败、`plugin list --json` 却可用，见 D45）：报告里显示 [WARN]，不拦启动。
 *
 * @param {Array<ReturnType<typeof defineCheck>>} checks
 * @returns {Promise<Array<{id: string, label: string, level: 'block'|'warn', ok: boolean,
 *   detail: string, remedy: string[], impact: string|null}>>}
 */
export async function runChecks(checks) {
  const results = [];

  for (const raw of checks) {
    const check = defineCheck(raw);
    let outcome;
    try {
      outcome = await check.run();
    } catch (error) {
      outcome = {
        ok: false,
        detail: `检查本身出错：${error instanceof Error ? error.message : String(error)}`,
        remedy: ['这是程序缺陷，请把上面的信息连同运行环境一起反馈'],
        impact: '无法确认这一项是否满足，按失败处理',
      };
    }

    results.push({
      id: check.id,
      label: check.label,
      level: LEVELS.has(outcome.level) ? outcome.level : check.level,
      ok: outcome.ok === true,
      detail: typeof outcome.detail === 'string' ? outcome.detail : '',
      remedy: Array.isArray(outcome.remedy) ? outcome.remedy : [],
      impact: typeof outcome.impact === 'string' ? outcome.impact : null,
    });
  }

  return results;
}

/** 这一项是否拦住了后续流程。 */
export function isBlocking(result) {
  return !result.ok && result.level === 'block';
}

export function blockingFailures(results) {
  return results.filter(isBlocking);
}

/** 0 表示可以继续；否则为前置检查的退出码。 */
export function exitCodeFor(results) {
  return blockingFailures(results).length === 0 ? 0 : EXIT_PREFLIGHT;
}

/* ── 渲染 ─────────────────────────────────────────────────────────────── */

/**
 * 终端显示宽度：CJK 与全角标点占两列。
 *
 * 不用 `String.length` 对齐：中文标签（「平台」「插件载荷」）按字符数补空格，
 * 在等宽字体里仍然会缩进一格，整张报告看起来是歪的。
 */
function displayWidth(text) {
  let width = 0;
  for (const character of text) {
    const code = character.codePointAt(0);
    width +=
      (code >= 0x1100 && code <= 0x115f)
      || (code >= 0x2e80 && code <= 0xa4cf)
      || (code >= 0xac00 && code <= 0xd7a3)
      || (code >= 0xf900 && code <= 0xfaff)
      || (code >= 0xfe30 && code <= 0xfe6f)
      || (code >= 0xff00 && code <= 0xff60)
      || (code >= 0xffe0 && code <= 0xffe6)
      || (code >= 0x1f300 && code <= 0x1faff)
        ? 2
        : 1;
  }
  return width;
}

function padEndDisplay(text, width) {
  return text + ' '.repeat(Math.max(0, width - displayWidth(text)));
}

/** 报告里状态标记的宽度（`[WARN]` / `[FAIL]` / `[OK]  `）。 */
const MARKER_WIDTH = 6;

function markerFor(result) {
  if (result.ok) {
    return '[OK]  ';
  }
  return result.level === 'warn' ? '[WARN]' : '[FAIL]';
}

/**
 * 渲染成固定格式的报告。
 *
 * 失败项永远是四段：**检查项 / 原因 / 处理 / 影响**。少了"影响"，用户会
 * 把它当成可以忽略的警告；少了"处理"，他只能把整份日志贴给别人。
 *
 * @param {Awaited<ReturnType<typeof runChecks>>} results
 * @param {{title?: string, context?: string[]}} [options]
 *   `context` 是"不是检查项、但排查时一定需要"的环境事实（布局、数据目录…）。
 */
export function renderReport(results, options = {}) {
  const title = options.title ?? 'Co-Sight Harness 安装前检查';
  const context = options.context ?? [];
  const labelWidth = results.reduce((width, result) => Math.max(width, displayWidth(result.label)), 0);
  const detailIndent = ' '.repeat(2 + MARKER_WIDTH + 1 + labelWidth + 2);

  const lines = [title, ''];

  if (context.length > 0) {
    lines.push('环境：', ...context.map((line) => `  ${line}`), '');
  }

  if (results.length === 0) {
    lines.push('（没有登记任何检查项）', '');
  }

  for (const result of results) {
    lines.push(`  ${markerFor(result)} ${padEndDisplay(result.label, labelWidth)}  ${result.detail}`);

    if (result.ok) {
      continue;
    }
    result.remedy.forEach((line, index) => {
      lines.push(`${detailIndent}${index === 0 ? '处理：' : '      '}${line}`);
    });
    if (result.impact !== null) {
      lines.push(`${detailIndent}影响：${result.impact}`);
    }
  }

  const failed = blockingFailures(results);
  const warnings = results.filter((result) => !result.ok && result.level === 'warn');
  lines.push('');

  if (failed.length === 0) {
    lines.push(
      warnings.length === 0
        ? '结论：可以继续。'
        : `结论：可以继续（${warnings.length} 项提醒，不阻塞）。`,
    );
  } else {
    lines.push(`结论：${failed.length} 项失败，无法继续。退出码 ${EXIT_PREFLIGHT}。`);
  }

  return `${lines.join('\n')}\n`;
}

/**
 * 把某条检查的结果压成一行摘要，供启动横幅使用
 * （例如 `v22.22.2（满足 ^22.19.0 || >=24.0.0）`）。
 *
 * @param {Awaited<ReturnType<typeof runChecks>>} results
 * @param {string} id
 * @param {string} [fallback]
 */
export function detailOf(results, id, fallback = '（未检查）') {
  return results.find((result) => result.id === id)?.detail ?? fallback;
}

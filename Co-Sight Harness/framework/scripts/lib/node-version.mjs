/**
 * Node 版本区间判定（不必装 semver 依赖）。
 *
 * ── 为什么自己写 ────────────────────────────────────────────────────────
 *
 * 这段代码跑在**用户的机器上**、且是产物启动的第一道关，所以：
 *
 *  1. 不能引依赖。产物根目录没有 `node_modules`（依赖树在 `server/` 下），
 *     启动入口只应依赖 Node 内置能力；
 *  2. 用到的区间语法就只有我们自己在 `engines.node` 里写的那几种，
 *     不需要一个完整的 semver 实现。
 *
 * ── 不认识的写法要**报错**，不许静默放过 ────────────────────────────────
 *
 * 这是本文件最重要的一条约定。版本校验唯一的坏失败模式是"它以为自己通过了"：
 * 将来有人把 `engines.node` 改成 `>=22 <25` 或 `latest` 这类本文件没实现的写法，
 * 如果这里返回 `true`，校验就**静默失效**了——而它正是给别人机器把关的那一道。
 * 所以遇到不认识的比较符一律抛错，把问题暴露在打包/启动的那一刻。
 *
 * 支持的写法：`||` 分隔多个区间，每个区间是空格分隔的若干比较符，比较符可以是
 * `^1.2.3`（同主版本、且不低于）、`~1.2.3`（同主+次版本）、`>=` `>` `<=` `<` `=`，
 * 以及裸版本号 `1.2.3`（等价于 `=`）。版本号允许省略次/修订号（`22` 等价 `22.0.0`）。
 * `*` / `x` / `-` 区间 / 预发布区间都**不支持**，遇到就抛。
 */

/** 认不出来的比较符。单独一个类，调用方可以据此区分"用户版本不对"和"我们写错了"。 */
export class UnsupportedRangeError extends Error {}

const COMPARATOR = /^(>=|<=|>|<|\^|~|=)?(\d+)(?:\.(\d+))?(?:\.(\d+))?$/;

/**
 * 拆一个版本号（`22.19.0-nightly20250101` 这种带预发布后缀的也认）。
 *
 * 预发布后缀只被**记下来**、不参与大小比较：产物要拦的是"Node 太老"，
 * 拿一个 nightly 的人不该被我们拦在门外，但要让他知道这是按 `22.19.0` 判的。
 */
export function parseVersion(input) {
  const match = /^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+](.+))?$/.exec(input.trim());
  if (match === null) {
    throw new UnsupportedRangeError(`看不懂的版本号：${input}`);
  }
  return {
    major: Number(match[1]),
    minor: Number(match[2] ?? 0),
    patch: Number(match[3] ?? 0),
    prerelease: match[4] ?? null,
  };
}

export function formatVersion(version) {
  return `${version.major}.${version.minor}.${version.patch}`;
}

/** 逐段比较。只看主/次/修订，预发布不参与（理由见 `parseVersion`）。 */
export function compareVersions(left, right) {
  for (const key of ['major', 'minor', 'patch']) {
    if (left[key] !== right[key]) {
      return left[key] < right[key] ? -1 : 1;
    }
  }
  return 0;
}

function parseComparator(text) {
  const match = COMPARATOR.exec(text);
  if (match === null) {
    throw new UnsupportedRangeError(`不支持的版本区间写法：${text}`);
  }
  const [, operator, major, minor, patch] = match;
  return {
    operator: operator ?? '=',
    version: {
      major: Number(major),
      minor: Number(minor ?? 0),
      patch: Number(patch ?? 0),
      prerelease: null,
    },
  };
}

/** 拆成"或"的分组；每组是"且"的比较符列表。语法不认识就抛。 */
export function parseRange(range) {
  const groups = range
    .split('||')
    .map((group) => group.trim().split(/\s+/).filter((token) => token !== ''))
    .map((tokens) => tokens.map(parseComparator));
  if (groups.length === 0 || groups.some((group) => group.length === 0)) {
    throw new UnsupportedRangeError(`不支持的版本区间写法（空区间）：${range}`);
  }
  return groups;
}

function satisfiesComparator(current, { operator, version }) {
  const order = compareVersions(current, version);
  switch (operator) {
    case '=':
      return order === 0;
    case '>':
      return order > 0;
    case '>=':
      return order >= 0;
    case '<':
      return order < 0;
    case '<=':
      return order <= 0;
    case '^':
      // 同主版本，且不低于 1.2.3。刻意**不**实现 semver 的"0.x 特殊规则"：
      // 我们自己的区间里没有 0.x，真出现了就让下面那条测试暴露出来。
      return current.major === version.major && order >= 0;
    case '~':
      return current.major === version.major && current.minor === version.minor && order >= 0;
    default:
      throw new UnsupportedRangeError(`不支持的比较符：${operator}`);
  }
}

/** `satisfies('22.19.1', '^22.19.0 || >=24.0.0')`。语法不认识时抛 `UnsupportedRangeError`。 */
export function satisfies(rawVersion, range) {
  const current = parseVersion(rawVersion);
  return parseRange(range).some((group) =>
    group.every((comparator) => satisfiesComparator(current, comparator)),
  );
}

/** 给用户看的一行人话，例如 `Node ^22.19.0 || >=24.0.0（当前 v22.5.0）`。 */
export function describeRequirement(range, rawVersion) {
  return `Node ${range}（当前 ${rawVersion}）`;
}

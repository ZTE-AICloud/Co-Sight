/**
 * 工作区名 → 目录名。
 *
 * ## 为什么必须有这一层（这是安全项，不是美化项）
 *
 * 工作区名契约（`contracts/workspace.ts`）只 `trim()` 和限长，**不限制字符**——
 * 它是给人看的显示名，凭什么不让人叫「周报助手 / 2026 Q1」。但它现在要变成一个
 * **路径段**，而 `../../etc` 完全是一个合法的显示名。让用户输入直接进路径，
 * 路径穿越就不是"可能的漏洞"，是"随手可得"。
 *
 * 于是规则是：**只保留明确安全的字符，其余一律吃掉**。白名单而不是黑名单——
 * 黑名单要枚举 `..`、`~`、`/`、`\`、NUL、各平台的路径分隔符与保留名，
 * 漏一个就是漏洞；白名单漏掉的只是"某个字符没能出现在目录名里"，代价是零。
 *
 * ## 中文会被保留，这是刻意的
 *
 * 这个产品的主路径是中文名（种子数据、占位符文案都是中文）。若按
 * `[a-z0-9._-]` 那种常见做法过滤，`周报助手开发` 会变成一串 `-`，用户打开
 * 工作区根目录看到一屏 `-----`。所以保留 Unicode 的字母与数字类（`\p{L}`/`\p{N}`），
 * 只把标点、空白、控制字符、路径分隔符折叠掉。
 *
 * 长度按 **48 个码点**而不是 48 个字节或 48 个 UTF-16 单位来截：
 * - 按字节截会在多字节字符中间断开，切出一个半个汉字；
 * - 按 UTF-16 单位截会把代理对（emoji 之外的星际平面字符）切成孤立代理项，
 *   那是一个无法编码进文件名的串。所以用 `[...str]` 按码点切。
 * 48 个 CJK 字符 = 144 字节，离 ext4 的单组件 255 字节上限还有一倍余量。
 */

/** 目录名长度上限（码点）。 */
export const MAX_DIRECTORY_SLUG_LENGTH = 48;

/** 名字里一个可保留字符都没有时的兜底。它是**合法的**目录名，不是错误占位。 */
export const FALLBACK_DIRECTORY_SLUG = 'workspace';

/**
 * Windows 的保留设备名。**不区分大小写**，且带扩展名同样算（`CON.txt` 也打不开）。
 *
 * 这**不是**安全项——设备名穿不出目录去；它是可用性项：Windows 上 `CreateFile`
 * 会把这些名字当成设备，于是新建一个叫「CON」的工作区时 `mkdir` 直接失败，
 * 在 Linux/macOS 上却一切正常。列全是为了让它只出现一次，而不是变成一张
 * "以后遇到再加"的清单——微软的清单就这 22 个（`COM0`/`LPT0` 不在其中，可以建）。
 *
 * 只列裸名就够：目录名里不可能出现 `.`——白名单折叠会把 `.` 吃成 `-`，
 * 去边界那一步又把首尾的 `-` 剥掉，所以 `CON.txt` 这种写法根本走不到这里。
 */
const WINDOWS_DEVICE_NAMES = new Set([
  'CON',
  'PRN',
  'AUX',
  'NUL',
  ...Array.from({ length: 9 }, (_, index) => `COM${String(index + 1)}`),
  ...Array.from({ length: 9 }, (_, index) => `LPT${String(index + 1)}`),
]);

/**
 * 撞上保留设备名时接的后缀：`CON` → `CON-ws`。
 *
 * 加后缀而不是改名或加前缀，是为了留住用户输入的痕迹；而 `_` 不能用来加后缀——
 * 它属于框架自己的命名空间前缀（见 `config/paths.ts` 的 `_public`）。
 * 设备名最长 4 个字符，加完 7 个，离 48 的上限还很远。
 */
const DEVICE_NAME_SUFFIX = '-ws';
/**
 * 判断一个候选目录名是否合法。只用于自检与测试断言；
 * 生产路径上 slug 是**生成**出来的，不是校验出来的。
 */
const SLUG_PATTERN = /^[\p{L}\p{N}_][\p{L}\p{N}_-]*$/u;

export function isDirectorySlug(value: string): boolean {
  return (
    value.length > 0 &&
    [...value].length <= MAX_DIRECTORY_SLUG_LENGTH &&
    SLUG_PATTERN.test(value) &&
    !isWindowsDeviceName(value)
  );
}

/** 是否撞上 Windows 的保留设备名。单独一个函数是因为生成与自检都要问同一个问题。 */
function isWindowsDeviceName(value: string): boolean {
  return WINDOWS_DEVICE_NAMES.has(value.toUpperCase());
}

/**
 * 派生目录名。纯函数：同样的输入永远得到同样的输出，不碰磁盘、不看库。
 *
 * 步骤与每一步的理由：
 * 1. `normalize('NFKC')` —— 全角字母数字折成半角（`ＡＢ` 与 `AB` 是同一个东西），
 *    `①` 折成 `1`。不折的话 `ＡＢ` 与 `AB` 会生成两个看着一样、比着不同的目录名。
 * 2. 白名单折叠：保留 `\p{L}\p{N}` 与 `_`、`-`，**其余连续字符一律折成一个 `-`**。
 *    这一步消灭了 `/`、`\`、空格、`..`、NUL、以及一切控制字符。
 * 3. 折叠重复的 `-`。
 * 4. 去掉首尾的 `-`、`.`、`_`：
 *    - 尾部的 `.` 在 Windows 上会被文件系统静默吃掉，留着一个"看着一样但比着不同"的名字；
 *    - 前导 `.` 是隐藏目录，会破坏"`readdir` 出来的都是工作区"这条预期；
 *    - 前导 `_` 是框架自用名的前缀（`_public`，见 `config/paths.ts`），
 *      剥掉它比维护一张保留名清单更彻底——**用户无论如何都落不到框架的命名空间里**。
 * 5. 空结果 → `workspace`。这不是边缘情况：`。。`、`///`、`---` 都会走到这里。
 * 6. 按码点截断到上限，再修一次尾部——截断可能正好切在一个 `-` 上。
 * 7. 撞上 Windows 保留设备名时接一个后缀（`CON` → `CON-ws`）。这一步与安全无关，
 *    只是让"新建一个叫 CON 的工作区"在 Windows 上不至于建不出来。
 *
 * 注意**不**做的事：不做重名去重。那是"看磁盘和库"的事，属于调用方，
 * 见 `services/workspaces.ts` 的分配循环。
 */
export function toDirectorySlug(name: string): string {
  const collapsed = name
    .normalize('NFKC')
    .replace(/[^\p{L}\p{N}_-]+/gu, '-')
    .replace(/-{2,}/g, '-');

  const trimmed = stripEdges(collapsed);
  if (trimmed === '') {
    return FALLBACK_DIRECTORY_SLUG;
  }

  const capped = stripEdges([...trimmed].slice(0, MAX_DIRECTORY_SLUG_LENGTH).join(''));
  if (capped === '') {
    return FALLBACK_DIRECTORY_SLUG;
  }

  return isWindowsDeviceName(capped) ? `${capped}${DEVICE_NAME_SUFFIX}` : capped;
}

/** 去掉首尾的 `-`、`.`、`_`。 */
function stripEdges(value: string): string {
  return value.replace(/^[-._]+/, '').replace(/[-._]+$/, '');
}

/**
 * 第 `index` 次冲突尝试的候选名（`index` 从 1 起）。
 *
 * 1 → `周报`，2 → `周报-2`，… 99 → `周报-99`。
 *
 * 为什么是加后缀而不是换一套前缀/加时间戳：`ls` 出来的人一眼能看出这几个目录
 * 是同一批重名的工作区，而 `workspace-a1b2c3` 这种看不出任何东西。
 */
export function directorySlugAttempt(slug: string, index: number): string {
  return index <= 1 ? slug : `${slug}-${String(index)}`;
}

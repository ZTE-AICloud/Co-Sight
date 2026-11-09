/**
 * 配色的对比度守卫（WCAG 2.x 相对亮度）。
 *
 * 为什么这件事需要一个测试：jsdom 没有布局、也不算层叠后的颜色，所以"这段文字在
 * 那个底色上读不读得清"在组件测试里**量不出来**——它只会以"设计评审时说了一句"
 * 的形式存在，然后在下一次调色时无声地失效。本文件把这条评审意见变成断言。
 *
 * 覆盖范围是**本轮 UX 修复真正引入的两处"文字压在有颜色的底上"**：
 *
 *   - 需求 UX-3.6 追加的六色标签底（配 `--text-body` 的深灰字，10px）；
 *   - 需求 UX-3.3 的卡片按钮蓝字（配白底 / 悬浮底 / 按下底，12px）。
 *
 * 后者的原始取值 `--color-primary`（#1993ff）在白底上只有 3.15:1，而 12px 属于正文
 * 尺寸，阈值是 4.5:1。**这就是本文件存在的原因**：`--color-primary` 在稿里的用途是
 * 边框与图标（非文字，3:1 就够），拿它当文字用的那天，阈值悄悄变了。
 *
 * 不覆盖 `--text-placeholder`（#999999，白底 2.85:1）：那是 UX 稿逐字提取的 [稿] 值，
 * 改它就改了设计稿还原度，属于"要不要偏离设计稿"的决策，不是本文件能替它答的。
 */

import fs from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

/*
 * vitest 在 jsdom 环境里给的 `import.meta.url` 不是 `file:` 地址（`fs` 会直接抛
 * "The URL must be of scheme file"），所以从 `process.cwd()` 解析——vitest 的配置
 * 就在 harness-web 包根，cwd 就是它。路径错了会以 ENOENT 报出来，带完整路径，好查。
 */
const TOKENS_CSS = path.resolve(process.cwd(), 'src/styles/tokens.css');

/** WCAG 2.x 的最低下限：正文尺寸文字 4.5:1。 */
const MIN_TEXT_CONTRAST = 4.5;

interface Rgba {
  r: number;
  g: number;
  b: number;
  a: number;
}

/**
 * 只解析本次要用的两种写法：`#rrggbb` 与 `rgb(r g b [/ a%])`。
 *
 * 遇到别的写法就抛错，而不是返回一个默认值——守卫最坏的失败模式是"没读懂所以放过了"。
 */
function parseColor(raw: string): Rgba {
  const value = raw.trim();
  if (/^#[0-9a-f]{6}$/i.test(value)) {
    return {
      r: Number.parseInt(value.slice(1, 3), 16),
      g: Number.parseInt(value.slice(3, 5), 16),
      b: Number.parseInt(value.slice(5, 7), 16),
      a: 1,
    };
  }
  const rgb = /^rgb\(\s*(\d+)\s+(\d+)\s+(\d+)(?:\s*\/\s*(\d+(?:\.\d+)?)%)?\s*\)$/.exec(value);
  if (rgb !== null) {
    return {
      r: Number(rgb[1]),
      g: Number(rgb[2]),
      b: Number(rgb[3]),
      a: rgb[4] === undefined ? 1 : Number(rgb[4]) / 100,
    };
  }
  throw new Error(`token-contrast 不认识这个色值写法：${raw}（要么补解析，要么把被测的令牌换掉）`);
}

/** 把半透明色叠到不透明底色上，得到实际渲染出来的那个颜色。 */
function over(top: Rgba, bottom: Rgba): Rgba {
  return {
    r: top.r * top.a + bottom.r * (1 - top.a),
    g: top.g * top.a + bottom.g * (1 - top.a),
    b: top.b * top.a + bottom.b * (1 - top.a),
    a: 1,
  };
}

function channelLinear(channel: number): number {
  const c = channel / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function luminance(color: Rgba): number {
  return (
    0.2126 * channelLinear(color.r) +
    0.7152 * channelLinear(color.g) +
    0.0722 * channelLinear(color.b)
  );
}

function contrast(foreground: Rgba, background: Rgba): number {
  const [lighter, darker] = [luminance(foreground), luminance(background)].toSorted((a, b) => b - a) as [
    number,
    number,
  ];
  return (lighter + 0.05) / (darker + 0.05);
}

/**
 * 从 `:root { ... }` 里抽出令牌。只认纯字面色值的行——`rgb(...)` 也认，`var()` 不认
 * （它没有可算的颜色）。多行注释里的色值不会被误取，因为那些行不带 `--名字:` 前缀。
 */
function readTokens(): Record<string, string> {
  const css = fs.readFileSync(TOKENS_CSS, 'utf8');
  const tokens: Record<string, string> = {};
  for (const line of css.split('\n')) {
    const match = /^\s*(--[a-z0-9-]+):\s*([^;]+);/.exec(line);
    if (match === null) {
      continue;
    }
    const [, name, rawValue] = match as unknown as [string, string, string];
    tokens[name] = rawValue.trim();
  }
  return tokens;
}

const tokens = readTokens();

function token(name: string): Rgba {
  const raw = tokens[name];
  if (raw === undefined) {
    throw new Error(`tokens.css 里没有 ${name}`);
  }
  return parseColor(raw);
}

/** 六个多色标签底（需求 UX-3.6 追加）。名字与 `tagTone.ts` 的 `TAG_TONES` 一一对应。 */
const TAG_TONES = ['blue', 'teal', 'green', 'purple', 'amber', 'rose'] as const;

describe('标签底色的文字对比度（需求 UX-3.6）', () => {
  const text = token('--text-body');

  it.each([...TAG_TONES, 'bg'])('--color-tag-%s 配 --text-body 达到 4.5:1', (tone) => {
    const background = token(tone === 'bg' ? '--color-tag-bg' : `--color-tag-${tone}`);
    expect(contrast(text, background)).toBeGreaterThanOrEqual(MIN_TEXT_CONTRAST);
  });
});

describe('卡片按钮蓝字的对比度（需求 UX-3.3）', () => {
  const surface = token('--color-surface');

  /*
   * 悬浮/按下时按钮底上是叠出来的一层浅蓝，不是纯白：文字在这两个状态下的对比度
   * 反而更低。所以三个状态都要算——只验白底会把最难看的那一态漏掉。
   */
  const states = [
    ['默认', surface],
    ['悬浮', over(token('--color-hover'), surface)],
    ['按下', over(token('--color-active'), surface)],
  ] as const;

  it.each(states)('%s态达到 4.5:1', (_state, background) => {
    expect(contrast(token('--color-primary-text'), background)).toBeGreaterThanOrEqual(
      MIN_TEXT_CONTRAST,
    );
  });

  it('这条守卫真的在守东西：旧取值 --color-primary 会被判不达标', () => {
    /*
     * 没有这一条的话，将来有人把 `.outline` 改回 `--color-primary`、又顺手把上面那组
     * 断言的期望值调低，测试照样绿。这里把"为什么不能用它"钉死，改回去必然红。
     */
    expect(contrast(token('--color-primary'), surface)).toBeLessThan(MIN_TEXT_CONTRAST);
  });
});

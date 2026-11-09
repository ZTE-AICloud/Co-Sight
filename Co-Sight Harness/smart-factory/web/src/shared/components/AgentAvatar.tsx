import { useState } from 'react';
import './AgentAvatar.css';

interface AgentAvatarProps {
  /**
   * 封面图地址（`Agent.icon`）。**空串表示没有封面** —— 契约 5.01 里这是一个有意义的取值，
   * 不是缺省占位。
   */
  icon: string;
  /** 名称。只在没有封面（或封面取不到）时用到，取它的第一个字 */
  name: string;
  /**
   * 派生配色的种子，一般传 `id`。手边没有 id（比如新建表单里的预览）就传名字。
   *
   * 为什么要有种子：没有封面时那颗色块**得每次都是同一个颜色**，否则同一个专家在不同页面
   * （卡片 / 顶栏 / 弹窗预览）会换色，看着像两个东西。用名字也行，但名字可改，
   * id 不可改 —— 所以优先 id。
   */
  seed?: string;
  /** 边长，默认 34 */
  size?: number;
}

/**
 * 专家头像：有封面就放封面图，没有就放**名称的第一个字 + 一块派生色渐变**。
 *
 * 三处共用（卡片、创建页顶栏、弹窗预览），所以兜底必须一致 —— 同一张卡片点进去，
 * 头像不该变个样子。
 *
 * **封面加载失败也走首字兜底**：后端说「icon 不解析、不校验形态，只管长度」（契约 5.01），
 * 所以一个地址可能是错的、过期的、或者内网取不到的。放任它渲染成裂图，
 * 卡片上就是个坏掉的方块；换成一个字，最多是「没图」，不会像坏了。
 */
export function AgentAvatar({ icon, name, seed, size = 34 }: AgentAvatarProps) {
  /**
   * 记住「哪个地址取不到」，而不是一个 true/false —— 编辑弹窗里用户会一边改地址一边看预览，
   * 前一版地址失败过不能把后一版也判死。地址一变，`broken` 自然就假了，不用 effect 去复位。
   */
  const [brokenSrc, setBrokenSrc] = useState<string | null>(null);
  const src = icon.trim();
  const broken = src !== '' && brokenSrc === src;

  // 圆角随边长走，跟设计稿一致：44px → 12px，64px → 17px
  const radius = Math.round(size * 0.27);
  const style = { width: size, height: size, borderRadius: radius };

  if (src !== '' && !broken) {
    return (
      <span className="agent-avatar" style={style}>
        <img
          src={src}
          // 名字就在旁边，图是装饰：读屏再念一遍图里的东西只是噪音
          alt=""
          loading="lazy"
          onError={() => setBrokenSrc(src)}
        />
      </span>
    );
  }

  const [tint, ink] = avatarPalette(seed ?? name);

  return (
    <span
      className="agent-avatar agent-avatar--letter"
      // 浅底 + 同色系首字（2026-10-20）：底色用 `29` 后缀的同一色做内描边，两色永远成套
      style={{ ...style, background: tint, color: ink, boxShadow: `inset 0 0 0 1px ${ink}29` }}
      aria-hidden="true"
    >
      <span className="agent-avatar__char" style={{ fontSize: Math.round(size * 0.42) }}>
        {initialOf(name)}
      </span>
    </span>
  );
}

/**
 * 名称的第一个字。
 *
 * 用展开而不是 `name[0]`：emoji 与部分汉字在 UTF-16 里占两个码元，`[0]` 会切出半个字符
 * （渲染成一个 �）。名称必填且 trim 后非空，所以只剩「一个字都没有」这一种异常，
 * 那时候给个问号，别让头像变成空白。
 */
export function initialOf(name: string): string {
  const text = name.trim();
  if (text === '') return '?';
  const [first] = [...text];
  // 拉丁字母大写一下（"weather-agent" → "W"），中文原样
  return first.toUpperCase();
}

/**
 * 无封面时的可选配色：`[浅底, 同色系文字]`。
 *
 * 2026-10-20 从「深色渐变 + 白字」换成参考稿的「浅色底 + 同色系首字」：
 * 一屏里十几张卡时，块块饱和的渐变太吵；浅底那块安静得多，字色又把辨识度留住了。
 *
 * 这是**装饰**不是信息：挑哪一对只由 id 决定，不表示任何状态或分类。
 * 所以不必（也不该）往后端要一个颜色字段。
 */
const PALETTE: [string, string][] = [
  ['#e8f3ff', '#1677ff'], // 蓝
  ['#f5e8ff', '#722ed1'], // 紫
  ['#e8ffea', '#00b42a'], // 绿
  ['#fff3e8', '#fa8c16'], // 橙
  ['#ffeff6', '#db2777'], // 粉
  ['#e8faff', '#0891b2'], // 青
];

/** djb2：够稳、够短，只求「同一个 id 永远同一个颜色」，不需要密码学强度。 */
function hash(text: string): number {
  let value = 5381;
  for (let index = 0; index < text.length; index += 1) {
    value = (value * 33 + text.charCodeAt(index)) >>> 0;
  }
  return value;
}

/** 同一个种子派生出的 `[浅底, 文字色]`，同一个专家在卡片 / 详情 / 创建页永远同一套色。 */
function avatarPalette(seed: string): [string, string] {
  return PALETTE[hash(seed) % PALETTE.length];
}

/**
 * 词条的类型层。
 *
 * 三件事在这里定死：
 *
 * 1. `Messages` 的形状 = 中文词条的结构。英文词条用 `: Messages` 标注即可获得
 *    编译期的完整性保障。
 *
 * 2. `MessageKey` 是**点分路径的联合类型**（`'nav.experts' | 'settings.nav.model' | ...`）。
 *    调用点写错一个字母是编译错误，而不是界面上出现 `nav.expertss` 这样的键名。
 *
 * 3. `MessageParams` 与 `{name}` 占位符配合做插值。**不做参数名校验**——
 *    那需要解析模板字符串字面量，代价远超收益；插值缺参时保留 `{name}` 原样显示，
 *    比渲染出 `undefined` 更容易被发现。
 */

import type { zhCN } from './messages/zh-CN';

export type Messages = typeof zhCN;

/**
 * 递归取出所有叶子路径。
 * `{ a: { b: string } }` → `'a.b'`。
 * 非字符串叶子（本项目里不存在）会被排除，避免拼出无意义的键。
 */
export type MessageKey = LeafPaths<Messages>;

type LeafPaths<T> = {
  [K in keyof T & string]: T[K] extends string ? K : `${K}.${LeafPaths<T[K]>}`;
}[keyof T & string];

export type MessageParams = Record<string, string | number>;

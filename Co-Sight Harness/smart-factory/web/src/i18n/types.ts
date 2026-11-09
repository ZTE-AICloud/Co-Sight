/**
 * 词条的类型层。
 *
 * `Messages` 的形状 = 中文词条的结构；英文词条标注 `: Messages` 即可获得
 * 编译期的完整性保障（漏一条翻译是编译错误）。
 *
 * `MessageKey` 是点分路径的联合类型，调用点写错一个字母是编译错误，
 * 而不是界面上出现 `create.expertss` 这样的键名。
 */

import type { zhCN } from './messages/zh-CN';

export type Messages = typeof zhCN;

export type MessageKey = LeafPaths<Messages>;

type LeafPaths<T> = {
  [K in keyof T & string]: T[K] extends string ? K : `${K}.${LeafPaths<T[K]>}`;
}[keyof T & string];

export type MessageParams = Record<string, string | number>;

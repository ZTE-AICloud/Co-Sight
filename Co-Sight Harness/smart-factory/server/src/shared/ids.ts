import { randomUUID } from 'node:crypto';

/** 各实体的 id 前缀，一个 id 空间一种前缀，便于日志与排障。 */
export type IdPrefix = 'agt' | 'inst' | 'sess' | 'run' | 'msg';

export function newId(prefix: IdPrefix): string {
  return `${prefix}_${randomUUID()}`;
}

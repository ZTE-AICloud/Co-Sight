import { randomUUID } from 'node:crypto';

/** 生成实体主键。契约层用 `z.uuid()` 校验，因此必须是标准 UUID 形式。 */
export function newId(): string {
  return randomUUID();
}

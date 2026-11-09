/**
 * 专家仓储（需求 2.2；P4 的数据侧）。
 *
 * 排序规则对应四个页签：
 * - `all`     最近入库在前（默认视图）
 * - `hot`     使用次数倒序（D15 = B：纯使用次数，不加时间衰减）
 * - `new`     创建时间倒序
 * - `preset`  仅预置项，按使用次数倒序（D13 = A）
 *
 * **每种排序都以 `id` 收尾**。这不是装饰：没有唯一列做最后一级排序时，
 * 同分记录在两次查询间的相对顺序是不确定的，分页会出现"第 2 页重复第 1 页的项"
 * 或"某项永远看不到"。加 id 让全序唯一，分页才可靠。
 */

import { and, asc, count, desc, eq, sql, type SQL } from 'drizzle-orm';

import type { CreateExpertInput, Expert, ExpertListQuery } from 'harness-shared';

import type { Database } from '../db/client';
import { experts, type ExpertRow } from '../db/schema';
import { newId } from '../lib/id';

export interface ExpertListResult {
  items: Expert[];
  total: number;
}

function toExpert(row: ExpertRow): Expert {
  return {
    id: row.id,
    name: row.name,
    author: row.author,
    description: row.description,
    avatarUrl: row.avatarUrl,
    tags: row.tags,
    useCount: row.useCount,
    isPreset: row.isPreset,
    createdAt: row.createdAt.toISOString(),
    updatedAt: row.updatedAt.toISOString(),
  };
}

function orderFor(filter: ExpertListQuery['filter']): SQL[] {
  const tieBreak = asc(experts.id);
  switch (filter) {
    case 'hot':
      return [desc(experts.useCount), desc(experts.createdAt), tieBreak];
    case 'new':
      return [desc(experts.createdAt), tieBreak];
    case 'preset':
      return [desc(experts.useCount), desc(experts.createdAt), tieBreak];
    case 'all':
      return [desc(experts.createdAt), tieBreak];
  }
}

function whereFor(query: ExpertListQuery): SQL | undefined {
  const conditions: SQL[] = [];

  if (query.filter === 'preset') {
    conditions.push(eq(experts.isPreset, true));
  }

  if (query.q !== undefined) {
    // 用 instr 而不是 LIKE：LIKE 里的 `%` 和 `_` 是通配符，
    // 用户搜 "a_b" 或 "100%" 时必须转义，而转义又要额外配 ESCAPE 子句。
    // instr 是纯粹的"是否包含"，且参数走绑定，没有通配符语义。
    conditions.push(sql`instr(lower(${experts.name}), lower(${query.q})) > 0`);
  }

  if (conditions.length === 0) {
    return undefined;
  }
  return and(...conditions);
}

export class ExpertRepository {
  readonly #db: Database;

  constructor(db: Database) {
    this.#db = db;
  }

  async list(query: ExpertListQuery): Promise<ExpertListResult> {
    const where = whereFor(query);
    const offset = (query.page - 1) * query.pageSize;

    const rows = await this.#db
      .select()
      .from(experts)
      .where(where)
      .orderBy(...orderFor(query.filter))
      .limit(query.pageSize)
      .offset(offset);

    const [totals] = await this.#db.select({ value: count() }).from(experts).where(where);

    return { items: rows.map(toExpert), total: totals?.value ?? 0 };
  }

  async findById(id: string): Promise<Expert | null> {
    const [row] = await this.#db.select().from(experts).where(eq(experts.id, id)).limit(1);
    return row === undefined ? null : toExpert(row);
  }

  async create(input: CreateExpertInput, now: Date = new Date()): Promise<Expert> {
    const row: ExpertRow = {
      id: newId(),
      name: input.name,
      author: input.author,
      description: input.description,
      avatarUrl: input.avatarUrl,
      tags: [...input.tags],
      useCount: 0,
      isPreset: input.isPreset,
      createdAt: now,
      updatedAt: now,
    };
    await this.#db.insert(experts).values(row);
    return toExpert(row);
  }

  /** 记录一次使用（需求 4.5 `使用`，驱动 D15 = B 的排序）。返回更新后的记录。 */
  async recordUse(id: string, now: Date = new Date()): Promise<Expert | null> {
    await this.#db
      .update(experts)
      .set({ useCount: sql`${experts.useCount} + 1`, updatedAt: now })
      .where(eq(experts.id, id));
    return this.findById(id);
  }

  /**
   * 直接设定使用次数。**仅种子使用**。
   *
   * 与 `recordUse` 的区别是刻意的：这里是"给内置内容一个初始热度"，
   * 而不是"发生过一次使用"。用 `recordUse` 循环 78 次去凑一个初始值，
   * 既慢又把两种语义混成一种，将来给 `recordUse` 加去重/埋点时会连带污染种子。
   */
  async setUseCount(id: string, value: number, now: Date = new Date()): Promise<void> {
    await this.#db
      .update(experts)
      .set({ useCount: Math.max(0, Math.trunc(value)), updatedAt: now })
      .where(eq(experts.id, id));
  }

  async deleteById(id: string): Promise<boolean> {
    const result = await this.#db.delete(experts).where(eq(experts.id, id)).returning({
      id: experts.id,
    });
    return result.length > 0;
  }

  async count(): Promise<number> {
    const [totals] = await this.#db.select({ value: count() }).from(experts);
    return totals?.value ?? 0;
  }
}

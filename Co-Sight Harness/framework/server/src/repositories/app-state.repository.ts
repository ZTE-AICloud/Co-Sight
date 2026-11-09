/**
 * 单例应用状态仓储（kv）。
 *
 * 只暴露 `get/set/delete` 三个动作，键名由调用方以常量给出，而不是把键散落在各处
 * 字符串字面量里——拼错键名不会报错，只会静默读到 undefined。
 */

import { eq } from 'drizzle-orm';

import type { Database } from '../db/client';
import { appState } from '../db/schema';

/** 当前工作区 id（需求 2.1 切换）。 */
export const ACTIVE_WORKSPACE_KEY = 'active_workspace_id';

export class AppStateRepository {
  readonly #db: Database;

  constructor(db: Database) {
    this.#db = db;
  }

  async get(key: string): Promise<string | null> {
    const [row] = await this.#db
      .select({ value: appState.value })
      .from(appState)
      .where(eq(appState.key, key))
      .limit(1);
    return row?.value ?? null;
  }

  async set(key: string, value: string, now: Date = new Date()): Promise<void> {
    await this.#db
      .insert(appState)
      .values({ key, value, updatedAt: now })
      // upsert：调用方不需要先查再决定 insert 还是 update。
      .onConflictDoUpdate({
        target: appState.key,
        set: { value, updatedAt: now },
      });
  }

  async delete(key: string): Promise<void> {
    await this.#db.delete(appState).where(eq(appState.key, key));
  }
}

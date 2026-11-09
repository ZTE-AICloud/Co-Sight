/**
 * 迁移执行（D7：迁移可管）。
 *
 * 迁移 SQL 由 `pnpm db:generate`（drizzle-kit）生成到 `drizzle/`，
 * 启动时按序应用；drizzle 的 migrator 自带 `__drizzle_migrations` 记账表，
 * 重复启动是幂等的。
 */

import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { migrate } from 'drizzle-orm/libsql/migrator';

import type { Database } from './client';

const here = path.dirname(fileURLToPath(import.meta.url));

/** 默认迁移目录：包根下的 `drizzle/`。 */
export const DEFAULT_MIGRATIONS_DIR = path.resolve(here, '..', '..', 'drizzle');

export async function runMigrations(
  db: Database,
  migrationsFolder: string = DEFAULT_MIGRATIONS_DIR,
): Promise<void> {
  await migrate(db, { migrationsFolder });
}

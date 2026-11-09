import { defineConfig } from 'drizzle-kit';

/**
 * 迁移生成配置（D7：SQLite + Drizzle，迁移可管）。
 *
 * 只用于 `pnpm db:generate` 生成 SQL 迁移文件；
 * 运行时由 src/db/migrate.ts 调 drizzle 的 migrator 顺序应用。
 */
export default defineConfig({
  dialect: 'sqlite',
  schema: './src/db/schema.ts',
  out: './drizzle',
  dbCredentials: {
    url: process.env['COSIGHT_DATABASE_URL'] ?? 'file:./.data/dev.sqlite',
  },
});

#!/usr/bin/env node
/**
 * 建库工具：prisma db push 建 schema，再执行 bootstrap.sql 补 schema.prisma 表达不了的手写结构。
 *
 * 用法（与 cwd 无关）：
 *   node scripts/db.mjs sync    建库 / 同步 schema（不重置，已有数据保留）
 *   node scripts/db.mjs reset   重置建库（清空数据后重建）
 *
 * 额外的参数原样透传给 `prisma db push`：删列这类会丢数据的变更需要
 *   node scripts/db.mjs sync --accept-data-loss
 */
import { spawnSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const serverDir = dirname(dirname(fileURLToPath(import.meta.url)));
const prismaCli = join(serverDir, 'node_modules', 'prisma', 'build', 'index.js');
const schemaPath = join(serverDir, 'prisma', 'schema.prisma');
const bootstrapPath = join(serverDir, 'prisma', 'bootstrap.sql');

/** 读 config 推导的 DATABASE_URL（与 scripts/dev.mjs 的 configValue 同法），不在脚本里重算路径规则。 */
function readDatabaseUrl() {
  const probe =
    "const { config } = await import('./src/config/index.js'); process.stdout.write(String(config.databaseUrl));";
  const result = spawnSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e', probe], {
    cwd: serverDir,
    encoding: 'utf8',
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    process.stderr.write(result.stderr ?? '');
    process.exit(result.status ?? 1);
  }
  return result.stdout;
}

/** 跑 Prisma CLI：一律 process.execPath + 解析出的 build/index.js，不用 .bin 垫片、不走 shell。 */
function runPrisma(args, env) {
  const result = spawnSync(process.execPath, [prismaCli, ...args], { cwd: serverDir, env, stdio: 'inherit' });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

const command = process.argv[2];
if (command !== 'sync' && command !== 'reset') {
  process.stderr.write('用法：node scripts/db.mjs sync|reset\n');
  process.exit(1);
}

const env = { ...process.env, DATABASE_URL: readDatabaseUrl() };
const pushArgs = ['db', 'push', '--schema', schemaPath, '--skip-generate'];
if (command === 'reset') pushArgs.push('--force-reset');
// 其余参数透传：删列（--accept-data-loss）这类会丢数据的变更由调用方显式承担
pushArgs.push(...process.argv.slice(3));
runPrisma(pushArgs, env);

// push 不碰手写结构，bootstrap.sql 负责补上（交给 Prisma CLI 执行，不自行切分 SQL）。
runPrisma(['db', 'execute', '--file', bootstrapPath, '--schema', schemaPath], env);

/**
 * 数据库连接。
 *
 * 用 `@libsql/client` 而不是 `better-sqlite3`：后者是原生模块，在本项目的
 * Node 24（ABI 137）上加载会直接 `ERR_DLOPEN_FAILED`，且没有可用预编译产物。
 * libsql 走纯 JS + 预编译绑定，同样读写 SQLite 文件、同样支持 Drizzle 的
 * sqlite-core，且不需要任何编译步骤。
 */

import { createClient, type Client } from '@libsql/client';
import { drizzle, type LibSQLDatabase } from 'drizzle-orm/libsql';

import { schema } from './schema';

export interface DatabaseHandle {
  client: Client;
  db: LibSQLDatabase<typeof schema>;
}

export function createDatabase(url: string): DatabaseHandle {
  const client = createClient({ url });
  const db = drizzle(client, { schema });
  return { client, db };
}

export type Database = DatabaseHandle['db'];

/**
 * libsql 的 `file:` URL 需要绝对路径，否则会相对**进程工作目录**解析，
 * 而不同启动方式（仓库根 / 包目录）的工作目录并不一致。
 */
export function toFileUrl(absolutePath: string): string {
  return `file:${absolutePath}`;
}

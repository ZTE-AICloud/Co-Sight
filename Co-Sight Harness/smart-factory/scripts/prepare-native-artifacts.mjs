#!/usr/bin/env node
/**
 * 在打包机上补齐 smart-factory 的**其他平台**原生运行时件。
 *
 * 当前只剩 Prisma 查询引擎：产物是一份同时覆盖 linux-x64 与 win32-x64 的包
 * （框架侧 D40），`prisma generate` 只按 `binaryTargets` 生成当前平台的引擎，
 * 两个平台都要（`libquery_engine-debian-openssl-1.0.x.so.node` 与
 * `query_engine-windows.dll.node`）。
 *
 * 打包脚本自己**绝不跑 npm install**（D34），所以补齐动作单独成命令，
 * 在 `pnpm package` 之前跑一次。幂等：都在时只打印几行就退出。
 *
 * Claude Code CLI 是用户侧外部前置，**不在产物里**，这里也不再下载任何
 * Anthropic 的 SDK / 平台二进制。
 *
 * 用法：
 *
 * ```bash
 * node smart-factory/scripts/prepare-native-artifacts.mjs
 * ```
 *
 * 前提：`server/node_modules` 已按模块 README 装好（`npm install`）。
 */

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SERVER_DIR = path.join(HERE, '..', 'server');
const NODE_MODULES = path.join(SERVER_DIR, 'node_modules');

/** 产物要覆盖的平台，与 `ARTIFACT_TARGETS` / artifact.json 的 `platforms` 同一份口径。 */
const TARGET_PLATFORMS = ['linux-x64', 'win32-x64'];

/** Prisma 查询引擎：哪个平台缺了都要补。 */
const PRISMA_ENGINES = {
  'linux-x64': 'libquery_engine-debian-openssl-1.0.x.so.node',
  'win32-x64': 'query_engine-windows.dll.node',
};
const PRISMA_CLIENT_DIR = path.join(NODE_MODULES, '.prisma', 'client');

function fail(message) {
  process.stderr.write(`[prepare-native-artifacts] ${message}\n`);
  process.exit(1);
}

/** 只生成、不动别的：Prisma CLI 直接以 JS 入口调用，绕开 `npx` / `.cmd` 的平台差异。 */
function generatePrismaClient() {
  const cli = path.join(NODE_MODULES, 'prisma', 'build', 'index.js');
  if (!fs.existsSync(cli)) {
    fail(`找不到 Prisma CLI：${cli}，请先在 server 目录执行 npm install。`);
  }
  const result = spawnSync(process.execPath, [cli, 'generate'], {
    cwd: SERVER_DIR,
    stdio: 'inherit',
    env: {
      ...process.env,
      // schema 的 datasource 用了 env("DATABASE_URL")；generate 不需要真库，给个占位值即可。
      DATABASE_URL: process.env.DATABASE_URL ?? 'file:./prepare-placeholder.db',
    },
  });
  if (result.error || result.status !== 0) {
    fail(`prisma generate 失败：${result.error?.message ?? `退出码 ${result.status}`}`);
  }
}

function main() {
  if (!fs.existsSync(NODE_MODULES)) {
    fail(`缺少 ${NODE_MODULES}，请先在 smart-factory/server 执行 npm install。`);
  }

  const missingEngines = TARGET_PLATFORMS.filter(
    (platform) => !fs.existsSync(path.join(PRISMA_CLIENT_DIR, PRISMA_ENGINES[platform])),
  );
  if (missingEngines.length === 0) {
    process.stdout.write('  Prisma 双平台引擎已就位\n');
  } else {
    process.stdout.write(`→ 生成 Prisma 引擎（缺 ${missingEngines.join('、')}，schema 里已声明 binaryTargets）…\n`);
    generatePrismaClient();
    const stillMissing = missingEngines.filter(
      (platform) => !fs.existsSync(path.join(PRISMA_CLIENT_DIR, PRISMA_ENGINES[platform])),
    );
    if (stillMissing.length > 0) {
      fail(`prisma generate 之后仍然没有 ${stillMissing.join('、')} 的引擎，请检查 schema.prisma 的 binaryTargets。`);
    }
  }

  process.stdout.write(`两个平台（${TARGET_PLATFORMS.join(' / ')}）的 Prisma 引擎已齐，可以执行 pnpm package。\n`);
}

try {
  main();
} catch (error) {
  fail(error instanceof Error ? error.message : String(error));
}

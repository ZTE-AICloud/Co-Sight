/**
 * 种子 CLI：`pnpm db:seed [-- --force]`。
 *
 * `--force` 是"恢复出厂设置"的意思——把预置专家再写一遍。注意它**不删旧数据**，
 * 只是无条件插入，因此重复执行会得到重复项；要对齐出厂状态请先清空数据目录。
 * 之所以不做成"清空后写入"，是因为这条命令在开发机上跑，一个手滑的删除太贵了。
 */

import { loadConfig } from '../config/env';
import { closeServices, createServices } from '../services/container';
import { seedPresetExperts } from './seed';

async function main(): Promise<void> {
  const force = process.argv.includes('--force');
  const config = loadConfig();
  const services = await createServices({ config });

  try {
    const result = await seedPresetExperts(services, { force });
    const message = result.skipped
      ? '专家表非空，已跳过。需要恢复预置内容请加 --force。'
      : `已写入 ${result.inserted} 条预置专家。`;
    process.stdout.write(`${message}\n`);
  } finally {
    await closeServices(services);
  }
}

main().catch((error: unknown) => {
  const detail = error instanceof Error ? (error.stack ?? error.message) : String(error);
  process.stderr.write(`种子写入失败：${detail}\n`);
  process.exit(1);
});

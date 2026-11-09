import { PrismaClient } from '@prisma/client';

/**
 * PrismaClient 单例。
 *
 * 连接串由 config 在 boot 时写入 `DATABASE_URL`；所有 ORM 调用只出现在 repo 层，
 * service 不直接碰 prisma。
 */
export const prisma = new PrismaClient();

export async function disconnect(): Promise<void> {
  await prisma.$disconnect();
}

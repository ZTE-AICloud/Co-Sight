import { Prisma, type Instance as InstanceModel } from '@prisma/client';
import { config } from '../../config/index.js';
import { BadGatewayError } from '../errors.js';
import { prisma } from '../prisma/client.js';
import { newId } from '../ids.js';
import type { Instance, InstanceStage } from '../types/index.js';

/**
 * `stage='dir'` 是 2026-10-26 之前目录实例的取值，语义已并入 `development`
 * （工坊本来就是开发阶段，阶段不该由「有没有 agentId」决定）。
 * 存量库没跑数据订正时按 development 读，避免 DTO 里漏出一个已废弃的取值。
 */
function toInstanceStage(raw: string): InstanceStage {
  return (raw === 'dir' ? 'development' : raw) as InstanceStage;
}

function toInstance(row: InstanceModel): Instance {
  return {
    id: row.id,
    agentId: row.agentId,
    stage: toInstanceStage(row.stage),
    cwd: row.cwd,
    engine: row.engine,
    createdAt: row.createdAt.toISOString(),
    updatedAt: row.updatedAt.toISOString(),
  };
}

function isUniqueConflict(error: unknown): boolean {
  return error instanceof Prisma.PrismaClientKnownRequestError && error.code === 'P2002';
}

export const instancesRepo = {
  /**
   * 按 `(agentId, stage)` 查不到就建；并发插入由唯一约束兜底，撞了重查返回已有行。
   *
   * `engine` 取值来自 config，在这里一次写定。
   */
  async getOrCreate(agentId: string, stage: InstanceStage): Promise<Instance> {
    const key = { agentId_stage: { agentId, stage } };
    const existing = await prisma.instance.findUnique({ where: key });
    if (existing) return toInstance(existing);

    try {
      const created = await prisma.instance.create({
        data: { id: newId('inst'), agentId, stage, engine: config.engine },
      });
      return toInstance(created);
    } catch (error) {
      if (!isUniqueConflict(error)) throw error;
      const raced = await prisma.instance.findUnique({ where: key });
      if (!raced) throw error;
      return toInstance(raced);
    }
  },

  /**
   * 目录实例入口：按 `(cwd, stage)` 查不到就建，`agentId = null`。
   *
   * `stage` 是「在这个目录里做什么」，与「有没有挂智能体」无关：
   * - 技能工坊在开发技能 → `development`；
   * - 自由对话只是聊天 → `runtime`（默认的「历史运行会话」就能看到它）。
   *
   * 同一目录可以有两种用途，所以身份是 `(cwd, stage)` 而不是 `cwd`：
   * 唯一性由 `uq_instances_cwd_stage` 部分索引兜底（见 bootstrap.sql）。
   *
   * 与 `getOrCreate` 合起来保证不变量 - `agentId` 与 `cwd` 恰有一个非空
   * （本方法不写 agentId，`getOrCreate` 不写 cwd）。
   */
  async getOrCreateByCwd(cwd: string, stage: InstanceStage): Promise<Instance> {
    const where = { cwd, stage };
    // (cwd, stage) 的唯一性来自 bootstrap.sql 的部分索引，Prisma 不感知，只能 findFirst 查
    const existing = await prisma.instance.findFirst({ where });
    if (existing) return toInstance(existing);

    try {
      const created = await prisma.instance.create({
        data: { id: newId('inst'), agentId: null, stage, cwd, engine: config.engine },
      });
      return toInstance(created);
    } catch (error) {
      if (!isUniqueConflict(error)) throw error;
      const raced = await prisma.instance.findFirst({ where });
      if (raced !== null) return toInstance(raced);
      // 旧库还带着只约束 cwd 的 uq_instances_cwd：同一目录的第二种用途建不出来。
      // 给一句能照做的提示，而不是把 "UNIQUE constraint failed" 当成 500 抛出去。
      const legacy = await prisma.instance.findFirst({ where: { cwd } });
      if (legacy !== null) {
        throw new BadGatewayError(
          `目录 ${cwd} 的实例索引未升级（仍只约束 cwd）；请执行 node scripts/db.mjs sync 后重启`,
        );
      }
      throw error;
    }
  },

  /**
   * 只读查询：不建行。
   *
   * 供产物状态 / 起跑门禁判断 development 实例是否有活跃 run；
   * 也用于反向守卫 - development 起跑前检查 runtime 是否正在读取产物树。
   */
  async findByAgentAndStage(agentId: string, stage: InstanceStage): Promise<Instance | null> {
    const row = await prisma.instance.findUnique({ where: { agentId_stage: { agentId, stage } } });
    return row ? toInstance(row) : null;
  },

  /**
   * 批量版：一次取出一页智能体的某阶段实例（列表算产物状态用，避免每行两次往返）。
   * 没有实例的 agentId 不出现在 Map 里，调用方按 null 处理。
   */
  async findByAgentIds(agentIds: string[], stage: InstanceStage): Promise<Map<string, Instance>> {
    if (agentIds.length === 0) return new Map();
    const rows = await prisma.instance.findMany({ where: { agentId: { in: agentIds }, stage } });
    return new Map(rows.map((row) => [row.agentId!, toInstance(row)]));
  },

  async findById(id: string): Promise<Instance | null> {
    const row = await prisma.instance.findUnique({ where: { id } });
    return row ? toInstance(row) : null;
  },

  async findByIds(ids: string[]): Promise<Map<string, Instance>> {
    if (ids.length === 0) return new Map();
    const rows = await prisma.instance.findMany({ where: { id: { in: ids } } });
    return new Map(rows.map((row) => [row.id, toInstance(row)]));
  },
};
